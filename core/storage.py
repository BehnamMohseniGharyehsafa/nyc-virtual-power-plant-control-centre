"""SQLite run registry and portable numerical result files (no pickle)."""

import io
import json
import os
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
import zipfile
import numpy as np
import pandas as pd
from core.config import Scenario
from core.simulation import Run
from data.inputs import district
from models.physics import make_portfolio
from models.network import build_feeder

ROOT = Path(
    os.environ.get("VPP_RESULTS_DIR", Path(__file__).resolve().parents[1] / "results")
)


def json_safe(value):
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def dumps(value):
    return json.dumps(json_safe(value), indent=2, ensure_ascii=False)


class Repository:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created TEXT, name TEXT, controller TEXT, status TEXT, buildings INTEGER, seconds REAL, cost REAL)"
            )

    def connection(self):
        return sqlite3.connect(self.root / "runs.sqlite")

    def save(self, run):
        folder = self.root / run.id
        folder.mkdir(exist_ok=True)
        run.series.to_parquet(folder / "timeseries.parquet", index=False)
        np.savez_compressed(folder / "assets.npz", **run.assets)
        (folder / "buildings.geojson").write_text(
            dumps(dict(type="FeatureCollection", features=run.portfolio.features)),
            encoding="utf-8",
        )
        run.weather.to_parquet(folder / "weather.parquet")
        run.pv_details.to_parquet(folder / "pv_details.parquet")
        import pandapower as pp

        pp.to_json(run.feeder.net, str(folder / "network.pandapower.json"))
        payload = dict(
            id=run.id,
            config=run.config.serialise(),
            metadata=run.metadata,
            status=run.status,
            accounting=run.accounting,
            network=run.network,
            diagnostics=run.diagnostics,
        )
        (folder / "run.json").write_text(dumps(payload), encoding="utf-8")
        if run.baseline is not None:
            run.baseline.series.to_parquet(folder / "baseline.parquet", index=False)
            (folder / "baseline_accounting.json").write_text(
                dumps(run.baseline.accounting), encoding="utf-8"
            )
        with self.lock, self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?)",
                (
                    run.id,
                    run.metadata["created_utc"],
                    run.config.name,
                    run.config.controller,
                    run.status,
                    run.config.buildings,
                    run.metadata["seconds"],
                    run.accounting.get("total_usd"),
                ),
            )

    def list(self):
        with self.connection() as db:
            db.row_factory = sqlite3.Row
            return [
                dict(r) for r in db.execute("SELECT * FROM runs ORDER BY created DESC")
            ]

    def load(self, identifier):
        # UUID validation prevents path traversal through HTTP inputs.
        from uuid import UUID

        identifier = str(UUID(identifier))
        folder = self.root / identifier
        j = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        config = Scenario(**j["config"])
        features = (
            json.loads((folder / "buildings.geojson").read_text(encoding="utf-8"))[
                "features"
            ]
            if (folder / "buildings.geojson").exists()
            else district(config.buildings)
        )
        p = make_portfolio(features, config)
        feeder = build_feeder(p, config)
        series = pd.read_parquet(folder / "timeseries.parquet")
        with np.load(folder / "assets.npz", allow_pickle=False) as arr:
            assets = {k: arr[k] for k in arr.files}
        baseline = None
        if (folder / "baseline.parquet").exists():
            baseline = SimpleNamespace(
                series=pd.read_parquet(folder / "baseline.parquet"),
                accounting=json.loads(
                    (folder / "baseline_accounting.json").read_text()
                ),
            )
        if (folder / "weather.parquet").exists():
            w = pd.read_parquet(folder / "weather.parquet")
            detail = pd.read_parquet(folder / "pv_details.parquet")
            index = w.index
            import pandapower as pp

            feeder.net = pp.from_json(str(folder / "network.pandapower.json"))
        else:
            from core.simulation import prepare

            _, _, index, w, _, detail, _, _, _ = prepare(config)
        return Run(
            identifier,
            config,
            p,
            feeder,
            index,
            w,
            detail,
            series,
            assets,
            j["network"],
            j["diagnostics"],
            j["metadata"],
            j["status"],
            j["accounting"],
            baseline,
        )


def export_bundle(run):
    """Time series, every asset, every AC bus/branch, configuration and provenance."""
    from visualisation.figures import publication_figure

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("timeseries.csv", run.series.to_csv(index=False))
        archive.writestr("scenario.json", dumps(run.config.serialise()))
        archive.writestr("provenance.json", dumps(run.metadata))
        archive.writestr("solver_diagnostics.json", dumps(run.diagnostics))
        archive.writestr("financial_operating_summary.json", dumps(run.accounting))
        archive.writestr(
            "financial_operating_summary.csv",
            pd.DataFrame([run.accounting]).to_csv(index=False),
        )
        archive.writestr(
            "buildings.csv",
            pd.DataFrame([f["properties"] for f in run.portfolio.features]).to_csv(
                index=False
            ),
        )
        archive.writestr(
            "buildings.geojson",
            dumps(dict(type="FeatureCollection", features=run.portfolio.features)),
        )
        import pandapower as pp

        archive.writestr("network.pandapower.json", pp.to_json(run.feeder.net))
        rows = []
        units = {
            "base": "kw",
            "pv": "kw",
            "charge": "kw",
            "discharge": "kw",
            "heat": "kw",
            "cool": "kw",
            "ev": "kw",
            "curtail": "kw",
            "q_inverter": "kvar",
            "net": "kw",
            "q": "kvar",
            "energy": "kwh",
            "temperature": "c",
            "ev_energy": "kwh",
        }
        for t in range(len(run.series)):
            for i, f in enumerate(run.portfolio.features):
                row = dict(
                    timestamp_utc=run.series.timestamp_utc.iloc[t],
                    bin=f["properties"]["bin"],
                    bus=run.feeder.building_buses[i],
                )
                row.update({k + "_" + units[k]: v[t, i] for k, v in run.assets.items()})
                rows.append(row)
        archive.writestr("der_dispatch.csv", pd.DataFrame(rows).to_csv(index=False))
        buses = []
        lines = []
        transformers = []
        violations = []
        for t, n in enumerate(run.network):
            for violation in n["violations"]:
                violations.append(
                    dict(
                        step=t,
                        timestamp_utc=run.series.timestamp_utc.iloc[t],
                        violation=violation,
                    )
                )
            if not n["converged"]:
                continue
            for bus, (v, a) in enumerate(zip(n["voltage"], n["angle_deg"])):
                buses.append(dict(step=t, bus=bus, voltage_pu=v, angle_deg=a))
            for i, (p, q, l) in enumerate(
                zip(n["line_p_kw"], n["line_q_kvar"], n["line_loading"])
            ):
                lines.append(
                    dict(step=t, line=i, p_from_kw=p, q_from_kvar=q, loading_pct=l)
                )
            for i, l in enumerate(n["trafo_loading"]):
                transformers.append(dict(step=t, transformer=i, loading_pct=l))
        for name, rows in (
            ("bus_results", buses),
            ("line_results", lines),
            ("transformer_results", transformers),
        ):
            archive.writestr(name + ".csv", pd.DataFrame(rows).to_csv(index=False))
        for t, row in run.series.iterrows():
            if row.comfort_degree_hours > 1e-5:
                violations.append(
                    dict(
                        step=t,
                        violation="Thermal comfort deviation",
                        value_degree_hours=row.comfort_degree_hours,
                    )
                )
            if row.ev_unmet_kwh > 1e-5:
                violations.append(
                    dict(
                        step=t,
                        violation="EV departure shortfall",
                        value_kwh=row.ev_unmet_kwh,
                    )
                )
        archive.writestr(
            "constraint_violations.csv",
            pd.DataFrame(
                violations,
                columns=[
                    "step",
                    "timestamp_utc",
                    "violation",
                    "value_degree_hours",
                    "value_kwh",
                ],
            ).to_csv(index=False),
        )
        parquet = io.BytesIO()
        run.series.to_parquet(parquet, index=False)
        archive.writestr("timeseries.parquet", parquet.getvalue())
        for ext in ("png", "svg"):
            archive.writestr(
                "dispatch_and_network." + ext, publication_figure(run, ext)
            )
        archive.writestr(
            "README.txt",
            f"Run {run.id}\nStatus: {run.status}\nEvery output comes from an executed numerical model.\n"
            "Geometry: NYC Open Data; loads and DER installations assumed; feeder synthetic.\n"
            "Electricity prices: NYISO Zone J. Weather: Open-Meteo reanalysis.\n"
            "Retail tariffs and financial assumptions are illustrative. See provenance.json.\n",
        )
    return output.getvalue()
