"""Receding-horizon execution and independent AC checking of stored states."""

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4
import platform
import importlib.metadata
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from core.config import Scenario
from data.inputs import district, time_index, weather_frame, market_frame, provenance
from data.quality import report as quality_report
from models.physics import (
    make_portfolio,
    pv_output,
    base_load,
    thermostat,
    thermal_step,
    battery_step,
    ev_calendar,
)
from models.network import build_feeder, verify
from controllers.forecast import forecast, retail_prices, errors
from controllers.distributed import DistributedMPC
from optimisation.dispatch import DispatchProblem, DispatchFailure
from economics.finance import operating_cost


@dataclass
class Run:
    id: str
    config: Scenario
    portfolio: object
    feeder: object
    index: object
    weather: object
    pv_details: object
    series: object
    assets: dict
    network: list
    diagnostics: list
    metadata: dict
    status: str
    accounting: dict
    baseline: object = None


def prepare(config):
    features = district(config.buildings)
    portfolio = make_portfolio(features, config)
    feeder = build_feeder(portfolio, config)
    index = time_index(config.date, config.steps)
    weather = weather_frame(config.date, index)
    pv, detail = pv_output(index, weather, portfolio.pv_kw)
    base = base_load(index, portfolio, config.load_scale)
    # Multiple days require their own real cached market files.
    prices = pd.Series(index=index, dtype=float)
    da = prices.copy()
    for date in sorted(set(index.tz_convert("America/New_York").strftime("%Y-%m-%d"))):
        ix = index[index.tz_convert("America/New_York").strftime("%Y-%m-%d") == date]
        prices.loc[ix] = market_frame(date, ix, "realtime")
        da.loc[ix] = market_frame(date, ix, "dam")
    return portfolio, feeder, index, weather, pv, detail, base, prices, da


def local_action(state, p, t, weather, base, pv, config, rule=False, price=None):
    heat, cool = thermostat(
        state["temperature"], weather.temperature_2m.iloc[t], base[t] * 0.65, p
    )
    available, arrival, _ = ev_calendar(pd.DatetimeIndex([weather.index[t]]))
    energy_ev = state["ev_energy"] * (not arrival[0])
    ev = (
        np.minimum(
            p.ev_kw, np.maximum(0, p.ev_required_kwh - energy_ev) / (0.95 * 0.25)
        )
        * available[0]
    )
    charge = np.minimum(p.battery_kw, np.maximum(0, pv[t] - base[t] - heat - cool - ev))
    discharge = np.zeros(p.n)
    if rule and price is not None and price > config.retail_usd_kwh * 1.2:
        charge *= 0
        discharge = np.minimum(
            p.battery_kw, np.maximum(0, base[t] + heat + cool + ev - pv[t])
        )
    charge = np.minimum(
        charge, np.maximum(0, 0.9 * p.battery_kwh - state["energy"]) / (0.95 * 0.25)
    )
    discharge = np.minimum(
        discharge, np.maximum(0, state["energy"] - 0.1 * p.battery_kwh) * 0.95 / 0.25
    )
    return dict(
        heat=heat,
        cool=cool,
        ev=ev,
        charge=charge,
        discharge=discharge,
        curtail=np.zeros(p.n),
        q_inverter=np.zeros(p.n),
    )


def forecast_reference(f, p, state):
    """Causal thermostat reference predicted from current counterfactual state."""
    temp = state["temperature"].copy()
    energy = state["energy"].copy()
    evenergy = state["ev_energy"].copy()
    result = []
    for j in range(len(f["buy"])):
        heat, cool = thermostat(temp, f["outdoor"][j], f["gain"][j], p)
        if f["ev_arrival"][j]:
            evenergy *= 0
        ev = (
            np.minimum(
                p.ev_kw, np.maximum(0, p.ev_required_kwh - evenergy) / (0.95 * 0.25)
            )
            * f["ev_available"][j]
        )
        evenergy += ev * 0.95 * 0.25
        ch = np.minimum(
            p.battery_kw, np.maximum(0, f["pv"][j] - f["base"][j] - heat - cool - ev)
        )
        ch = np.minimum(ch, np.maximum(0, 0.9 * p.battery_kwh - energy) / (0.95 * 0.25))
        energy = battery_step(energy, ch, 0)
        result.append(float((f["base"][j] + heat + cool + ev + ch - f["pv"][j]).sum()))
        temp = thermal_step(temp, f["outdoor"][j], heat, cool, f["gain"][j], p)
    return np.array(result)


def simulate(
    config,
    progress=lambda fraction, message: None,
    cancelled=lambda: False,
    baseline=None,
):
    started = perf_counter()
    p, feeder, index, w, pv, pv_details, base, rt, da = prepare(config)
    if config.topology == "meshed" and config.controller in (
        "central",
        "network",
        "distributed",
    ):
        raise ValueError(
            "Meshed networks are supported in snapshot AC OPF and local simulations; MPC requires radial topology"
        )
    if config.event_kw and baseline is None:
        bc = Scenario(**{**config.serialise(), "controller": "baseline", "event_kw": 0})
        progress(0.01, "Computing identical-input counterfactual baseline")
        baseline = simulate(bc, cancelled=cancelled)
    state = dict(
        energy=p.battery_kwh * 0.5,
        temperature=np.full(p.n, 23.0),
        ev_energy=np.zeros(p.n),
    )
    counter_state = {k: v.copy() for k, v in state.items()}
    records = []
    networks = []
    diagnostics = []
    names = (
        "base",
        "pv",
        "charge",
        "discharge",
        "heat",
        "cool",
        "ev",
        "curtail",
        "q_inverter",
        "net",
        "q",
        "energy",
        "temperature",
        "ev_energy",
    )
    assets = {k: [] for k in names}
    lp = None
    binary_lp = None
    distributed = None
    if config.controller == "distributed":
        distributed = DistributedMPC(p, config, feeder)
    predicted_pv = []
    predicted_temp = []
    buy, sell = retail_prices(index, config)
    if config.market == "wholesale":
        buy = rt.to_numpy() / 1000
        sell = buy.copy()
    status = "completed"
    available, arrival, departure = ev_calendar(index)
    for t, stamp in enumerate(index):
        if cancelled():
            status = "cancelled"
            break
        progress(
            t / len(index),
            f"{stamp.tz_convert('America/New_York'):%H:%M} · step {t + 1}/{len(index)}",
        )
        action = None
        diag = dict(
            step=t, solver="local rules", status="applied", seconds=0.0, objective=None
        )
        if config.controller in ("central", "network", "distributed"):
            ix = pd.date_range(stamp, periods=config.horizon, freq="15min")
            f = forecast(stamp, ix, p, config, rt.iloc[:t].to_numpy())
            target = None
            if config.event_kw:
                # Event uses a forecast reference; delivery is assessed against realised baseline later.
                ceiling = np.full(config.horizon, config.import_limit_kw)
                floor = np.full(config.horizon, -config.export_limit_kw)
                mask = (np.arange(t, t + config.horizon) >= config.event_start) & (
                    np.arange(t, t + config.horizon)
                    < config.event_start + config.event_steps
                )
                reference = forecast_reference(f, p, counter_state)
                if config.event_kw > 0:
                    ceiling[mask] = reference[mask] - config.event_kw
                else:
                    floor[mask] = reference[mask] - config.event_kw
                target = dict(ceiling=ceiling, floor=floor)
            try:
                if distributed is not None:
                    solution = distributed.solve(f, state, target, cancelled)
                else:
                    binary = bool(
                        np.min(f["buy"]) < 0 or np.any(f["sell"] > f["buy"] + 1e-10)
                    )
                    network = feeder if config.controller == "network" else None
                    if binary:
                        if binary_lp is None:
                            binary_lp = DispatchProblem(p, config, network, binary=True)
                        problem = binary_lp
                    else:
                        if lp is None:
                            lp = DispatchProblem(p, config, network)
                        problem = lp
                    problem.set_inputs(f, state, target)
                    solution = problem.solve()
                action = {k: v[0] for k, v in solution["actions"].items()}
                diag = {
                    k: v
                    for k, v in solution.items()
                    if k
                    in (
                        "seconds",
                        "objective",
                        "solver",
                        "status",
                        "formulation",
                        "objective_terms",
                        "admm",
                        "fallback",
                    )
                }
                diag["step"] = t
                predicted_pv.append(float(f["pv"][0].sum()))
                predicted_temp.append(float(f["outdoor"][0]))
            except DispatchFailure as exc:
                status = "failed"
                diagnostics.append(
                    dict(
                        step=t,
                        status="failed",
                        error=str(exc),
                        solver="ADMM" if distributed else "HiGHS",
                    )
                )
                break
        else:
            action = local_action(
                state, p, t, w, base, pv, config, config.controller == "rule", buy[t]
            )
        if arrival[t]:
            state["ev_energy"] *= 0
        unmet = (
            np.maximum(0, p.ev_required_kwh - state["ev_energy"])
            if departure[t]
            else np.zeros(p.n)
        )
        next_energy = battery_step(
            state["energy"], action["charge"], action["discharge"]
        )
        next_temp = thermal_step(
            state["temperature"],
            w.temperature_2m.iloc[t],
            action["heat"],
            action["cool"],
            base[t] * 0.65,
            p,
        )
        next_ev = state["ev_energy"] + action["ev"] * 0.95 * 0.25
        net = (
            base[t]
            + action["heat"]
            + action["cool"]
            + action["ev"]
            + action["charge"]
            - action["discharge"]
            - pv[t]
            + action["curtail"]
        )
        q = (
            0.25 * (base[t] + action["heat"] + action["cool"] + action["ev"])
            - action["q_inverter"]
        )
        ac = verify(feeder, net, q, config, initialise=t == 0)
        comfort = np.maximum(0, config.comfort_min - next_temp) + np.maximum(
            0, next_temp - config.comfort_max
        )
        soc_bad = bool(
            np.any(next_energy < 0.1 * p.battery_kwh - 1e-4)
            or np.any(next_energy > 0.9 * p.battery_kwh + 1e-4)
        )
        if soc_bad:
            status = "failed"
            diagnostics.append(
                dict(step=t, status="failed", error="Physical SOC violation")
            )
            break
        violations = (
            len(ac["violations"]) + int(comfort.max() > 1e-4) + int(unmet.max() > 1e-4)
        )
        grid = ac.get("grid_kw", np.nan)
        energycost = (
            (max(grid, 0) * buy[t] - max(-grid, 0) * sell[t]) * 0.25
            if np.isfinite(grid)
            else np.nan
        )
        records.append(
            dict(
                timestamp_utc=stamp,
                timestamp_local=stamp.tz_convert("America/New_York").isoformat(),
                grid_kw=grid,
                net_der_kw=float(net.sum()),
                base_kw=float(base[t].sum()),
                demand_kw=float(
                    (base[t] + action["heat"] + action["cool"] + action["ev"]).sum()
                ),
                pv_kw=float((pv[t] - action["curtail"]).sum()),
                pv_available_kw=float(pv[t].sum()),
                charge_kw=float(action["charge"].sum()),
                discharge_kw=float(action["discharge"].sum()),
                hvac_kw=float((action["heat"] + action["cool"]).sum()),
                ev_kw=float(action["ev"].sum()),
                soc_pct=float(100 * next_energy.sum() / max(p.battery_kwh.sum(), 1e-9)),
                curtail_kw=float(action["curtail"].sum()),
                loss_kw=ac.get("loss_kw", np.nan),
                min_voltage_pu=float(np.min(ac["voltage"]))
                if ac["converged"]
                else np.nan,
                max_line_pct=float(np.max(ac["line_loading"], initial=0))
                if ac["converged"]
                else np.nan,
                max_trafo_pct=float(np.max(ac["trafo_loading"], initial=0))
                if ac["converged"]
                else np.nan,
                voltage_error_pu=ac.get("max_voltage_error_pu", np.nan),
                violations=violations,
                comfort_degree_hours=float(comfort.sum() * 0.25),
                ev_unmet_kwh=float(unmet.sum()),
                temperature_mean_c=float(next_temp.mean()),
                rt_usd_mwh=float(rt.iloc[t]),
                da_usd_mwh=float(da.iloc[t]),
                buy_usd_kwh=buy[t],
                export_usd_kwh=sell[t],
                energy_cost_usd=energycost,
                solver_seconds=diag["seconds"],
                forecast_pv_kw=predicted_pv[-1] if predicted_pv else np.nan,
            )
        )
        assets["base"].append(base[t])
        assets["pv"].append(pv[t])
        assets["net"].append(net)
        assets["q"].append(q)
        for key in action:
            assets[key].append(action[key])
        assets["energy"].append(next_energy)
        assets["temperature"].append(next_temp)
        assets["ev_energy"].append(next_ev)
        networks.append(ac)
        diagnostics.append(diag)
        if config.event_kw:
            ca = local_action(counter_state, p, t, w, base, pv, config)
            if arrival[t]:
                counter_state["ev_energy"] *= 0
            counter_state["temperature"] = thermal_step(
                counter_state["temperature"],
                w.temperature_2m.iloc[t],
                ca["heat"],
                ca["cool"],
                base[t] * 0.65,
                p,
            )
            counter_state["energy"] = battery_step(
                counter_state["energy"], ca["charge"], ca["discharge"]
            )
            counter_state["ev_energy"] += ca["ev"] * 0.95 * 0.25
        state = dict(energy=next_energy, temperature=next_temp, ev_energy=next_ev)
    series = pd.DataFrame(records)
    accounting = {}
    if len(series):
        accounting = operating_cost(
            series.grid_kw,
            series.buy_usd_kwh,
            series.export_usd_kwh,
            series.charge_kw,
            series.discharge_kw,
            demand_usd_kw=config.demand_usd_kw,
        )
        if series.violations.sum() and status == "completed":
            status = "completed with violations"
    assets = {k: np.array(v) for k, v in assets.items()}
    metadata = dict(
        created_utc=datetime.now(timezone.utc).isoformat(),
        python=platform.python_version(),
        packages={
            name: importlib.metadata.version(name)
            for name in (
                "numpy",
                "pandas",
                "cvxpy",
                "pandapower",
                "pvlib",
                "dash",
                "highspy",
            )
        },
        seconds=perf_counter() - started,
        provenance=provenance(),
        forecast=config.forecast,
        forecast_price="completed-interval persistence; cold-start assumption $50/MWh"
        if config.market == "wholesale"
        else "known illustrative retail TOU schedule",
        topology="synthetic, balanced; not the Con Edison network",
        demand="assumed archetypes; not measured 15-minute data",
        initial_state="50% SOC, 23 °C, zero workplace EV energy; assumed",
        financial_basis="illustrative USD scenarios; no market eligibility or official retail tariff claim",
        forecast_pv_errors=errors(predicted_pv, series.pv_available_kw)
        if predicted_pv and len(series) == len(predicted_pv)
        else None,
    )
    root = Path(__file__).resolve().parents[1]
    metadata["input_hashes"] = {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest()
        for f in (root / "data" / "cache").iterdir()
        if f.suffix in (".csv", ".geojson")
    }
    metadata["model_sha256"] = hashlib.sha256(
        b"".join(
            f.read_bytes()
            for folder in (
                "core",
                "models",
                "optimisation",
                "controllers",
                "economics",
                "flexibility",
            )
            for f in sorted((root / folder).glob("*.py"))
        )
    ).hexdigest()
    metadata["data_quality"] = quality_report(p, index, w, rt)
    metadata["weather_mode"] = (
        metadata["provenance"]
        .get("weather_" + config.date, {})
        .get("weather_mode", "historical reanalysis")
    )
    run = Run(
        str(uuid4()),
        config,
        p,
        feeder,
        index,
        w,
        pv_details,
        series,
        assets,
        networks,
        diagnostics,
        metadata,
        status,
        accounting,
        baseline,
    )
    progress(1.0, f"{status} · {len(series)} executed steps")
    return run
