"""Synthetic balanced three-phase feeder and independent pandapower verification."""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
from scipy import sparse
import pandapower as pp


@dataclass
class Feeder:
    net: object
    downstream: object
    voltage_p: object
    voltage_q: object
    ratings_kva: np.ndarray
    building_buses: list
    positions: dict
    resistance: np.ndarray
    reactance: np.ndarray


def build_feeder(portfolio, config):
    n = portfolio.n
    net = pp.create_empty_network(sn_mva=1.0, f_hz=60)
    high = pp.create_bus(net, vn_kv=69, name="External grid · hypothetical connection")
    root = pp.create_bus(net, vn_kv=13.8, name="PCC · synthetic substation")
    pp.create_ext_grid(
        net,
        high,
        vm_pu=1.02,
        min_p_mw=-config.export_limit_kw / 1000,
        max_p_mw=config.import_limit_kw / 1000,
        min_q_mvar=-100,
        max_q_mvar=100,
    )
    # Fixed infrastructure across PV/BESS sizing scenarios; only the explicit rating
    # multiplier changes the feeder, preventing investment comparisons resizing it.
    roof = np.array([f["properties"]["footprint_m2"] for f in portfolio.features])
    design = (
        portfolio.area * 0.052
        + portfolio.ev_kw
        + np.clip(portfolio.area * 0.018, 13.5, 800) / 2
        + roof * 0.09
    )
    sub_kva = max(500, design.sum() * 1.4) * config.network_rating_scale
    pp.create_transformer_from_parameters(
        net,
        high,
        root,
        sn_mva=sub_kva / 1000,
        vn_hv_kv=69,
        vn_lv_kv=13.8,
        vk_percent=6,
        vkr_percent=0.5,
        pfe_kw=0,
        i0_percent=0,
        shift_degree=0,
        max_loading_percent=100,
        name="Synthetic 69/13.8 kV transformer",
    )
    rows, cols, values = [], [], []
    r, x, ratings = (
        [0.005 / (sub_kva)],
        [np.sqrt(0.06**2 - 0.005**2) / (sub_kva)],
        [sub_kva],
    )
    rows.extend([0] * n)
    cols.extend(range(n))
    values.extend([1.0] * n)
    positions = {high: (-500.0, 0.0), root: (-380.0, 0.0)}
    building_buses = []
    groups = (n + 11) // 12
    for g in range(groups):
        ix = list(range(g * 12, min((g + 1) * 12, n)))
        mv = pp.create_bus(net, vn_kv=13.8, name=f"MV feeder {g + 1:02}")
        lon = np.mean([portfolio.features[i]["properties"]["lon"] for i in ix])
        lat = np.mean([portfolio.features[i]["properties"]["lat"] for i in ix])
        positions[mv] = ((lon + 73.989) * 84300, (lat - 40.703) * 111100)
        length = max(0.08, np.hypot(*positions[mv]) / 1000)
        line_kva = max(150, design[ix].sum() * 1.4) * config.network_rating_scale
        pp.create_line_from_parameters(
            net,
            root,
            mv,
            length_km=length,
            r_ohm_per_km=0.16,
            x_ohm_per_km=0.12,
            c_nf_per_km=0,
            max_i_ka=line_kva / (np.sqrt(3) * 13.8 * 1000),
            max_loading_percent=100,
            name=f"Synthetic MV branch {g + 1}",
        )
        e = len(r)
        rows.extend([e] * len(ix))
        cols.extend(ix)
        values.extend([1.0] * len(ix))
        r.append(0.16 * length / (1000 * 13.8**2))
        x.append(0.12 * length / (1000 * 13.8**2))
        ratings.append(line_kva)
        for i in ix:
            lv = pp.create_bus(
                net, vn_kv=0.4, name=f"BIN {portfolio.features[i]['properties']['bin']}"
            )
            size = max(40, design[i] * 1.35) * config.network_rating_scale
            pp.create_transformer_from_parameters(
                net,
                mv,
                lv,
                sn_mva=size / 1000,
                vn_hv_kv=13.8,
                vn_lv_kv=0.4,
                vk_percent=4,
                vkr_percent=1,
                pfe_kw=0,
                i0_percent=0,
                shift_degree=0,
                max_loading_percent=100,
                name=f"Synthetic building transformer {i + 1}",
            )
            e = len(r)
            rows.append(e)
            cols.append(i)
            values.append(1.0)
            r.append(0.01 / size)
            x.append(np.sqrt(0.04**2 - 0.01**2) / size)
            ratings.append(size)
            p = portfolio.features[i]["properties"]
            positions[lv] = ((p["lon"] + 73.989) * 84300, (p["lat"] - 40.703) * 111100)
            building_buses.append(lv)
            pp.create_load(
                net, lv, p_mw=0, q_mvar=0, name=p["address"], controllable=False
            )
            pp.create_sgen(
                net,
                lv,
                p_mw=0,
                q_mvar=0,
                name="PV / BESS converter",
                controllable=False,
            )
    if config.topology == "meshed" and groups > 1:
        mvs = list(net.bus.index[net.bus.name.str.startswith("MV feeder")])
        for a, b in zip(mvs[:-1], mvs[1:]):
            pp.create_line_from_parameters(
                net,
                a,
                b,
                length_km=0.1,
                r_ohm_per_km=0.16,
                x_ohm_per_km=0.12,
                c_nf_per_km=0,
                max_i_ka=0.3,
                max_loading_percent=100,
                name="Synthetic MV tie",
            )
    net.bus["min_vm_pu"] = config.voltage_min
    net.bus["max_vm_pu"] = config.voltage_max
    d = sparse.csr_matrix((values, (rows, cols)), shape=(len(r), n))
    hp = 2 * (d.T @ sparse.diags(r) @ d)
    hq = 2 * (d.T @ sparse.diags(x) @ d)
    return Feeder(
        net,
        d,
        hp,
        hq,
        np.array(ratings),
        building_buses,
        positions,
        np.array(r),
        np.array(x),
    )


def verify(feeder, net_kw, q_kvar, config, initialise=False):
    net = feeder.net
    net.load.loc[:, "p_mw"] = np.maximum(net_kw, 0) / 1000
    net.load.loc[:, "q_mvar"] = q_kvar / 1000
    net.sgen.loc[:, "p_mw"] = np.maximum(-net_kw, 0) / 1000
    net.sgen.loc[:, "q_mvar"] = 0
    try:
        pp.runpp(
            net,
            algorithm="nr",
            numba=False,
            init="flat" if initialise else "auto",
            calculate_voltage_angles=True,
            tolerance_mva=1e-8,
            max_iteration=40,
        )
    except pp.LoadflowNotConverged as exc:
        return {
            "converged": False,
            "feasible": False,
            "error": str(exc),
            "violations": ["AC power flow did not converge"],
        }
    v = net.res_bus.vm_pu.to_numpy().copy()
    line = net.res_line.loading_percent.to_numpy().copy()
    trafo = net.res_trafo.loading_percent.to_numpy().copy()
    loss = (net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()) * 1000
    grid = net.res_ext_grid.p_mw.sum() * 1000
    violations = []
    if v.min() < config.voltage_min - 1e-5 or v.max() > config.voltage_max + 1e-5:
        violations.append("Bus voltage outside limits")
    if len(line) and line.max() > 100.0001:
        violations.append("Line thermal rating exceeded")
    if len(trafo) and trafo.max() > 100.0001:
        violations.append("Transformer thermal rating exceeded")
    if grid > config.import_limit_kw + 0.01 or grid < -config.export_limit_kw - 0.01:
        violations.append("PCC exchange limit exceeded")
    linear = np.sqrt(
        np.maximum(0.1, 1.02**2 - feeder.voltage_p @ net_kw - feeder.voltage_q @ q_kvar)
    )
    return dict(
        converged=True,
        feasible=not violations,
        violations=violations,
        voltage=v,
        angle_deg=net.res_bus.va_degree.to_numpy().copy(),
        line_loading=line,
        trafo_loading=trafo,
        line_p_kw=net.res_line.p_from_mw.to_numpy().copy() * 1000,
        line_q_kvar=net.res_line.q_from_mvar.to_numpy().copy() * 1000,
        grid_kw=float(grid),
        loss_kw=float(loss),
        balance_error_kw=float(grid - net_kw.sum() - loss),
        linear_voltage=linear,
        max_voltage_error_pu=float(np.max(np.abs(v[feeder.building_buses] - linear))),
    )


def ac_opf(feeder, base_kw, q_kvar, available_pv, config, price_usd_kwh=0.22):
    """Snapshot nonconvex AC OPF. BESS injection must be supplied as fixed base_kw.

    Curtailment and inverter reactive power are decisions. No free battery energy.
    Conservative rectangular P/Q limits inscribed in each inverter circle.
    """
    import copy
    from time import perf_counter

    net = copy.deepcopy(feeder.net)
    net.load.loc[:, "p_mw"] = np.asarray(base_kw) / 1000
    net.load.loc[:, "q_mvar"] = np.asarray(q_kvar) / 1000
    net.sgen["controllable"] = True
    net.sgen["min_p_mw"] = 0.0
    net.sgen["max_p_mw"] = np.maximum(available_pv, 1e-5) / 1000
    # P<=PV, Q<=sqrt((1.1*PV)^2-PV^2) respects S limit for every rectangle point.
    qmax = np.maximum(available_pv, 1e-5) * np.sqrt(1.1**2 - 1) / 1000
    net.sgen["min_q_mvar"] = -qmax
    net.sgen["max_q_mvar"] = qmax
    pp.create_poly_cost(net, 0, "ext_grid", cp1_eur_per_mw=price_usd_kwh * 1000)
    # pandapower names monetary columns 'eur'; numerical currency is USD here.
    for i in net.sgen.index:
        pp.create_poly_cost(net, i, "sgen", cp1_eur_per_mw=-1.0)
    started = perf_counter()
    try:
        pp.runopp(
            net, verbose=False, numba=False, init="flat", calculate_voltage_angles=True
        )
    except (pp.OPFNotConverged, ValueError) as exc:
        return dict(
            status="failed",
            feasible=False,
            error=str(exc),
            seconds=perf_counter() - started,
        )
    opf_cost = float(net.res_cost)
    pgen, qgen = (
        net.res_sgen.p_mw.to_numpy().copy() * 1000,
        net.res_sgen.q_mvar.to_numpy().copy() * 1000,
    )
    net.sgen.loc[:, "p_mw"] = pgen / 1000
    net.sgen.loc[:, "q_mvar"] = qgen / 1000
    net.ext_grid.loc[:, "vm_pu"] = net.res_bus.vm_pu.loc[net.ext_grid.bus].to_numpy()
    pp.runpp(net, numba=False, calculate_voltage_angles=True)
    voltages = net.res_bus.vm_pu.to_numpy()
    maxloading = max(
        net.res_line.loading_percent.max() if len(net.line) else 0,
        net.res_trafo.loading_percent.max(),
    )
    grid_kw = float(net.res_ext_grid.p_mw.sum() * 1000)
    feasible = bool(
        voltages.min() >= config.voltage_min - 1e-4
        and voltages.max() <= config.voltage_max + 1e-4
        and maxloading <= 100.01
        and grid_kw <= config.import_limit_kw + 0.1
        and grid_kw >= -config.export_limit_kw - 0.1
    )
    return dict(
        status="locally converged; global optimality not established",
        feasible=feasible,
        objective_usd_per_hour=opf_cost,
        grid_kw=grid_kw,
        voltage=voltages.tolist(),
        angle_deg=net.res_bus.va_degree.tolist(),
        pv_kw=pgen.tolist(),
        q_kvar=qgen.tolist(),
        curtailment_kw=float(np.maximum(0, available_pv - pgen).sum()),
        line=net.res_line.to_dict("records"),
        transformers=net.res_trafo.to_dict("records"),
        loss_kw=float((net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()) * 1000),
        seconds=perf_counter() - started,
    )


def export_network(feeder, folder):
    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    pp.to_json(feeder.net, str(path / "network.pandapower.json"))
    for name in ("bus", "line", "trafo", "load", "sgen", "ext_grid"):
        feeder.net[name].to_csv(path / f"{name}.csv", index_label="index")


def import_network(path):
    """Read documented native pandapower JSON or a directory of indexed element CSVs."""
    path = Path(path)
    if path.is_file():
        return pp.from_json(str(path))
    net = pp.create_empty_network(f_hz=60)
    import pandas as pd

    for name in ("bus", "line", "trafo", "load", "sgen", "ext_grid"):
        frame = pd.read_csv(path / f"{name}.csv", index_col="index")
        for col in ("in_service", "controllable"):
            if col in frame:
                frame[col] = frame[col].map(lambda x: str(x).lower() == "true")
        net[name] = frame
    return net
