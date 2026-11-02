import numpy as np
import cvxpy as cp
import copy
from models.network import verify
from optimisation.dispatch import DispatchProblem


def event_metrics(run):
    if run.baseline is None or run.config.event_kw == 0:
        return None
    c = run.config
    df = run.series
    baseline = run.baseline.series
    count = min(len(df), len(baseline))
    delivered = baseline.grid_kw.to_numpy()[:count] - df.grid_kw.to_numpy()[:count]
    requested = np.zeros(count)
    mask = (np.arange(count) >= c.event_start) & (
        np.arange(count) < c.event_start + c.event_steps
    )
    requested[mask] = c.event_kw
    recovery = (np.arange(count) >= c.event_start + c.event_steps) & (
        np.arange(count) < c.event_start + c.event_steps + 16
    )
    err = delivered[mask] - requested[mask]
    complete = bool(mask.sum() == c.event_steps)
    verified = (
        complete
        and bool(np.all(np.abs(err) <= c.event_tolerance_kw))
        and bool(df.loc[mask, "violations"].sum() == 0)
    )
    signed = np.sign(c.event_kw)
    eligible = np.minimum(np.maximum(signed * delivered[mask], 0), abs(c.event_kw))
    payment = (
        float(eligible.sum() * 0.25 * c.event_payment_usd_kwh) if verified else 0.0
    )
    return dict(
        delivered_kw=delivered,
        requested_kw=requested,
        baseline_kw=baseline.grid_kw.to_numpy()[:count],
        rmse_kw=float(np.sqrt(np.mean(err**2))) if len(err) else None,
        delivered_kwh=float(delivered[mask].sum() * 0.25),
        requested_kwh=float(c.event_kw * c.event_steps * 0.25),
        recovery_kwh=float(np.maximum(-delivered[recovery], 0).sum() * 0.25),
        rebound_peak_kw=float(np.max(np.maximum(-delivered[recovery], 0), initial=0)),
        verified=verified,
        complete=complete,
        hypothetical_payment_usd=payment,
        settlement="All-or-nothing eligibility: every event interval within tolerance and no physical violation; hypothetical contract",
    )


def sustained_envelope(
    portfolio, config, feeder, forecast, state, reference, event_start=0, duration=4
):
    """Optimise a constant service across all event intervals, including recovery.

    This is a forecast-conditional feasible envelope, not a guaranteed AC envelope.
    The shared terminal SOC and EV/thermal constraints remain in both LPs.
    """
    if event_start + duration > config.horizon:
        raise ValueError("Event exceeds forecast horizon")
    result = {}
    for direction, name in ((1, "upward_reduction_kw"), (-1, "downward_increase_kw")):
        # A maximum-consumption objective can exploit simultaneous cycling even
        # at positive prices; explicit modes are therefore mandatory for envelopes.
        model = DispatchProblem(portfolio, config, feeder, binary=True)
        model.set_inputs(forecast, state)
        service = cp.Variable(nonneg=True)
        ix = slice(event_start, event_start + duration)
        cons = model.problem.constraints + [
            direction * (reference[ix] - cp.sum(model.net[ix], axis=1)) >= service
        ]
        problem = cp.Problem(cp.Maximize(service), cons)
        problem.solve(
            solver="HIGHS",
            highs_options={"time_limit": config.solver_seconds, "threads": 1},
        )
        if problem.status != cp.OPTIMAL:
            result[name] = None
            result[name + "_status"] = problem.status
        else:
            independent = copy.deepcopy(feeder)
            checks = [
                verify(independent, model.net.value[t], model.q.value[t], config)
                for t in range(config.horizon)
            ]
            safe = all(r["feasible"] for r in checks)
            result[name] = float(service.value) if safe else None
            result[name + "_linear_kw"] = float(service.value)
            result[name + "_status"] = (
                "forecast schedule AC verified"
                if safe
                else "rejected by AC verification"
            )
    return result
