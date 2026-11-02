import copy
import numpy as np
import pytest
from core.config import Scenario
from controllers.distributed import DistributedMPC
from optimisation.dispatch import DispatchProblem, DispatchFailure
from flexibility.analysis import sustained_envelope
from models.network import verify


def test_sharing_admm_matches_central_and_reports_residuals(case):
    c, p, feeder, f, state = case
    c = Scenario(**{**c.serialise(), "admm_tolerance": 0.0001, "admm_iterations": 200})
    central = DispatchProblem(p, c, feeder)
    central.set_inputs(f, state)
    reference = central.solve()
    r = DistributedMPC(p, c, feeder).solve(f, state)
    last = r["admm"][-1]
    assert last["primal"] <= last["epsilon_primal"]
    assert last["dual"] <= last["epsilon_dual"]
    np.testing.assert_allclose(r["net"], reference["net"], atol=0.03)
    for t in range(c.horizon):
        assert verify(feeder, r["net"][t], r["q"][t], c)["feasible"]


def test_distributed_rejects_nonconvex_price_case(case):
    c, p, feeder, f, state = case
    f = copy.deepcopy(f)
    f["buy"][:] = -0.1
    with pytest.raises(DispatchFailure, match="negative"):
        DistributedMPC(p, c, feeder).solve(f, state)


def test_sustained_envelope_accounts_for_duration_and_ac(case):
    from core.simulation import forecast_reference

    c, p, feeder, f, state = case
    reference = forecast_reference(f, p, state)
    short = sustained_envelope(p, c, feeder, f, state, reference, duration=2)
    longer = sustained_envelope(p, c, feeder, f, state, reference, duration=8)
    assert short["upward_reduction_kw"] is not None
    assert longer["upward_reduction_kw"] is not None
    assert longer["upward_reduction_kw"] <= short["upward_reduction_kw"] + 1e-3
    assert "AC verified" in short["upward_reduction_kw_status"]
