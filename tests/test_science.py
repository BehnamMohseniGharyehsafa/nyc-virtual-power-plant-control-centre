"""Tolerances: balances 1e-4 kW/kWh; OPF feasibility 1e-4 pu; RC 1e-10 °C.

Tests check conservation, independent AC feasibility and deliberate infeasibility;
they are not claims of empirical building calibration or field validation.
"""

import copy
import io
import zipfile
import numpy as np
import pandas as pd
import pytest
from core.config import Scenario, Finance
from core.simulation import simulate
from core.storage import Repository, export_bundle
from models.physics import (
    battery_step,
    thermal_step,
    heat_pump_cop,
    pv_output,
    wind_output,
    hot_water_step,
)
from models.network import verify, ac_opf, export_network, import_network
from optimisation.dispatch import DispatchProblem, DispatchFailure
from controllers.forecast import forecast
from economics.finance import lifecycle, operating_cost, uncertainty
from data.inputs import time_index, weather_frame, market_frame


def test_battery_energy_and_round_trip():
    e = battery_step(50, 20, 0, dt=1)
    final = battery_step(e, 0, 20 * 0.95**2, dt=1)
    assert e == pytest.approx(69)
    assert final == pytest.approx(50, abs=1e-10)


def test_rc_exact_zero_order_hold(case):
    _, p, *_ = case
    start = np.full(p.n, 23.0)
    outdoor = 30.0
    heat = np.zeros(p.n)
    cool = np.full(p.n, 2.0)
    gain = np.full(p.n, 1.0)
    equilibrium = outdoor + (gain - heat_pump_cop(outdoor) * cool) / p.conductance_kw_k
    expected = equilibrium + (start - equilibrium) * np.exp(
        -p.conductance_kw_k * 0.25 / p.capacitance_kwh_k
    )
    np.testing.assert_allclose(
        thermal_step(start, outdoor, heat, cool, gain, p), expected, atol=1e-10
    )


def test_hot_water_energy_balance():
    assert hot_water_step(20, 4, 1, dt=1) == pytest.approx(20 * 0.99 + 4 * 0.98 - 1)


def test_pv_night_and_inverter_limits(case):
    c, p, *_ = case
    index = time_index(c.date, 96)
    w = weather_frame(c.date, index)
    output, detail = pv_output(index, w, p.pv_kw)
    assert np.all(output >= 0)
    assert np.all(output <= p.pv_kw[None, :] / 1.2 * 0.96 + 1e-8)
    assert np.all(output[:16] == 0)
    assert np.max(output) > 0
    assert np.all(detail.poa_w_m2 >= 0)


def test_wind_cutout():
    p = wind_output([0, 3, 12, 25, 30], 100, hub_height=10)
    np.testing.assert_allclose(p, [0, 0, 100, 0, 0])


def test_dispatch_intertemporal_and_objective(case):
    c, p, feeder, f, state = case
    model = DispatchProblem(p, c, feeder)
    model.set_inputs(f, state)
    r = model.solve()
    e = r["energy"]
    a = r["actions"]
    np.testing.assert_allclose(
        e[1:], battery_step(e[:-1], a["charge"], a["discharge"]), atol=1e-5
    )
    assert np.all(e >= p.battery_kwh * 0.1 - 1e-5)
    assert np.all(e <= p.battery_kwh * 0.9 + 1e-5)
    assert np.all(e[-1] >= state["energy"] - 1e-5)
    assert np.max(np.minimum(a["charge"], a["discharge"])) < 1e-5
    assert r["objective"] == pytest.approx(sum(r["objective_terms"].values()), abs=1e-5)
    for t in range(c.horizon):
        ac = verify(feeder, r["net"][t], r["q"][t], c)
        assert ac["converged"] and ac["feasible"]
        assert abs(ac["balance_error_kw"]) < 1e-4


def test_negative_price_uses_mutually_exclusive_modes(case):
    c, p, feeder, f, state = case
    f = copy.deepcopy(f)
    f["buy"][:] = -0.1
    f["sell"][:] = -0.1
    model = DispatchProblem(p, c, feeder, binary=True)
    model.set_inputs(f, state)
    r = model.solve()
    assert r["formulation"] == "MILP"
    assert np.max(np.minimum(r["actions"]["charge"], r["actions"]["discharge"])) < 1e-5
    assert np.isfinite(r["objective"])


def test_infeasible_pcc_is_reported(case):
    c, p, feeder, f, state = case
    bad = Scenario(**{**c.serialise(), "import_limit_kw": 1})
    model = DispatchProblem(p, bad, feeder)
    model.set_inputs(f, state)
    with pytest.raises(DispatchFailure, match="infeasible"):
        model.solve()


def test_ac_detects_voltage_and_thermal_overload(case):
    c, p, feeder, *_ = case
    overloaded = verify(feeder, np.full(p.n, 3000.0), np.full(p.n, 1000.0), c)
    assert not overloaded["feasible"]
    assert overloaded["violations"]


def test_ev_departure_constraints(case):
    c, p, feeder, _, state = case
    c = Scenario(**{**c.serialise(), "horizon": 48})
    origin = pd.Timestamp(c.date + " 08:00", tz="America/New_York").tz_convert("UTC")
    f = forecast(
        origin, pd.date_range(origin, periods=c.horizon, freq="15min"), p, c, []
    )
    model = DispatchProblem(p, c, feeder)
    model.set_inputs(f, state)
    r = model.solve()
    assert np.all(r["ev_energy"][40] >= p.ev_required_kwh - 1e-5)
    assert np.all(r["actions"]["ev"][40:] < 1e-5)


def test_receding_horizon_state_updates(case):
    c, p, *_ = case
    run = simulate(c)
    assert run.status == "completed"
    previous = np.vstack([p.battery_kwh * 0.5, run.assets["energy"][:-1]])
    np.testing.assert_allclose(
        run.assets["energy"],
        battery_step(previous, run.assets["charge"], run.assets["discharge"]),
        atol=1e-5,
    )
    assert len(run.diagnostics) == c.steps
    assert np.all(run.series.violations == 0)


def test_snapshot_ac_opf_is_independently_verified(case):
    c, p, feeder, *_ = case
    result = ac_opf(feeder, np.full(p.n, 20.0), np.full(p.n, 5.0), p.pv_kw * 0.3, c)
    assert result["feasible"], result
    assert "global optimality not established" in result["status"]
    assert np.min(result["voltage"]) >= c.voltage_min - 1e-4
    assert (
        np.max(
            np.hypot(result["pv_kw"], result["q_kvar"])
            / (np.maximum(p.pv_kw * 0.3, 1e-5) * 1.1)
        )
        <= 1.0001
    )


def test_ieee33_validation_feeder():
    import pandapower as pp
    import pandapower.networks as networks

    net = networks.case33bw()
    pp.runpp(net, numba=False)
    assert net.converged
    assert net.res_bus.vm_pu.min() == pytest.approx(0.91309, abs=2e-4)
    losses = net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()
    assert net.res_ext_grid.p_mw.sum() - net.load.p_mw.sum() == pytest.approx(
        losses, abs=1e-6
    )


def test_dcf_npv_and_discounted_payback():
    f = Finance(
        years=3,
        discount=0.1,
        escalation=0,
        degradation=0,
        pv_usd_kw=100,
        battery_usd_kwh=0,
        controls_usd_building=0,
        om_fraction=0,
        engineering_fraction=0,
        residual_fraction=0,
    )
    r = lifecycle(50, 1, 0, 0, f)
    assert r["npv_usd"] == pytest.approx(-100 + 50 / 1.1 + 50 / 1.1**2 + 50 / 1.1**3)
    assert r["discounted_payback_years"] == pytest.approx(
        2 + (100 - 50 / 1.1 - 50 / 1.1**2) / (50 / 1.1**3)
    )
    assert lifecycle(1, 1, 0, 0, f)["discounted_payback_years"] is None
    assert r["cashflows"].cashflow_usd.iloc[0] == -r["capex_usd"]


def test_settlement_no_double_counting():
    cost = operating_cost(
        [100, -40], [0.2, 0.2], [0.05, 0.05], [0, 0], [0, 0], dt=1, service_revenue=3
    )
    assert cost["total_usd"] == pytest.approx(20 - 2 - 3)


def test_monte_carlo_reproducibility():
    a = uncertainty(100, 2, 3, 1, Finance(), samples=10)
    b = uncertainty(100, 2, 3, 1, Finance(), samples=10)
    pd.testing.assert_frame_equal(a, b)


def test_utc_dst_and_leap_year():
    for date, expected in (("2024-03-10", 92), ("2024-11-03", 100), ("2024-02-29", 96)):
        start = pd.Timestamp(date, tz="America/New_York")
        end = start + pd.DateOffset(days=1)
        index = pd.date_range(start, end, freq="15min", inclusive="left").tz_convert(
            "UTC"
        )
        assert len(index) == expected
        assert index.is_unique
        assert np.all(np.diff(index.asi8) == 15 * 60 * 10**9)


def test_price_mapping_preserves_native_settlement_integral():
    from data.download import CACHE

    raw = pd.read_csv(CACHE / "realtime_2024-07-17.csv")
    ends = pd.to_datetime(raw.timestamp_utc, utc=True)
    start = pd.Timestamp("2024-07-17", tz="America/New_York").tz_convert("UTC")
    previous = pd.DatetimeIndex([start, *ends.iloc[:-1]])
    native = np.sum(
        raw.usd_mwh.to_numpy() * (pd.DatetimeIndex(ends).asi8 - previous.asi8) / 3.6e12
    )
    mapped = market_frame("2024-07-17", time_index("2024-07-17", 96))
    assert mapped.sum() * 0.25 == pytest.approx(native, abs=1e-8)


def test_missing_historical_data_is_not_fabricated():
    with pytest.raises(FileNotFoundError):
        weather_frame("1900-01-01", time_index("1900-01-01", 4))


def test_forecast_information_is_strictly_historical(case, monkeypatch):
    import importlib

    module = importlib.import_module("controllers.forecast")
    c, p, _, _, _ = case
    origin = time_index(c.date, 4)[0]
    original = module.weather_frame
    seen = []

    def check(date, index):
        seen.append(index.max())
        return original(date, index)

    monkeypatch.setattr(module, "weather_frame", check)
    module.forecast(
        origin, pd.date_range(origin, periods=96, freq="15min"), p, c, []
    )
    assert max(seen) < origin


def test_network_json_and_csv_roundtrip(case, tmp_path):
    _, _, feeder, *_ = case
    export_network(feeder, tmp_path)
    for path in (tmp_path, tmp_path / "network.pandapower.json"):
        net = import_network(path)
        assert len(net.bus) == len(feeder.net.bus)
        assert len(net.trafo) == len(feeder.net.trafo)


def test_result_persistence_and_export_completeness(case, tmp_path):
    c, *_ = case
    run = simulate(c)
    repo = Repository(tmp_path)
    repo.save(run)
    loaded = repo.load(run.id)
    pd.testing.assert_frame_equal(run.series, loaded.series)
    blob = export_bundle(loaded)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert {
            "timeseries.csv",
            "timeseries.parquet",
            "der_dispatch.csv",
            "bus_results.csv",
            "line_results.csv",
            "transformer_results.csv",
            "constraint_violations.csv",
            "solver_diagnostics.json",
            "scenario.json",
            "provenance.json",
            "dispatch_and_network.png",
            "dispatch_and_network.svg",
        } <= set(archive.namelist())
        assert (
            len(pd.read_csv(archive.open("der_dispatch.csv"))) == c.buildings * c.steps
        )


def test_mesh_lin_model_is_explicitly_rejected(case):
    c, p, feeder, *_ = case
    c = Scenario(**{**c.serialise(), "topology": "meshed"})
    with pytest.raises(ValueError, match="radial"):
        DispatchProblem(p, c, feeder)
