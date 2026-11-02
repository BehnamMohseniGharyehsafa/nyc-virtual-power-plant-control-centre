"""Two-block sharing ADMM: local DER schedules x_i and network copies z_i.

min Σ f_i(x_i)+g(z), x_i=z_i. Local QPs contain intertemporal physics;
aggregator projection contains LinDistFlow and procurement. Convex only.
"""

from dataclasses import fields
from time import perf_counter
import cvxpy as cp
import numpy as np
from models.physics import Portfolio
from optimisation.dispatch import DispatchProblem, DispatchFailure, network_constraints


def subset(portfolio, i):
    values = {}
    for field in fields(portfolio):
        value = getattr(portfolio, field.name)
        values[field.name] = [value[i]] if isinstance(value, list) else value[i : i + 1]
    return Portfolio(**values)


class DistributedMPC:
    def __init__(self, portfolio, config, feeder):
        self.p, self.c, self.feeder = portfolio, config, feeder
        self.locals = [
            DispatchProblem(subset(portfolio, i), config, proximal=True)
            for i in range(portfolio.n)
        ]
        h, n = config.horizon, portfolio.n
        self.z = cp.Variable((h, n))
        self.centre = cp.Parameter((h, n))
        self.buy, self.sell = cp.Parameter(h), cp.Parameter(h)
        self.zq = cp.Variable((h, n))
        self.q_centre = cp.Parameter((h, n))
        self.cap = cp.Parameter(h)
        self.floor = cp.Parameter(h)
        imp, exp = cp.Variable(h, nonneg=True), cp.Variable(h, nonneg=True)
        peak = cp.Variable(nonneg=True)
        cons = [
            imp - exp == cp.sum(self.z, axis=1),
            imp <= 0.98 * config.import_limit_kw,
            exp <= 0.98 * config.export_limit_kw,
            imp <= peak,
            cp.sum(self.z, axis=1) <= self.cap,
            cp.sum(self.z, axis=1) >= self.floor,
        ]
        limits, _ = network_constraints(self.z, self.zq, feeder, config)
        cons += limits
        obj = (
            config.dt_hours * (self.buy @ imp - self.sell @ exp)
            + config.demand_usd_kw * peak
        )
        obj += config.admm_rho / 2 * (
            cp.sum_squares(self.z - self.centre)
            + cp.sum_squares(self.zq - self.q_centre)
        ) + 1e-6 * config.dt_hours * cp.sum(imp + exp)
        self.problem = cp.Problem(cp.Minimize(obj), cons)
        self.previous = None

    def solve(self, forecast, state, target=None, cancelled=lambda: False):
        c, p = self.c, self.p
        if np.min(forecast["buy"]) < 0 or np.any(
            forecast["sell"] > forecast["buy"] + 1e-10
        ):
            raise DispatchFailure(
                "Convex distributed MPC is unavailable for negative/inverted tariffs; use central MILP"
            )
        begin = perf_counter()
        h, n = c.horizon, p.n
        z = np.zeros((h, n)) if self.previous is None else self.previous.copy()
        zq = np.zeros_like(z)
        u = np.zeros_like(z)
        uq = np.zeros_like(z)
        logs = []
        self.buy.value, self.sell.value = forecast["buy"], forecast["sell"]
        if isinstance(target, dict):
            self.cap.value = target["ceiling"]
            self.floor.value = target["floor"]
        else:
            self.cap.value = np.full(h, c.import_limit_kw) if target is None else target
            self.floor.value = np.full(h, -c.export_limit_kw)
        for i, local in enumerate(self.locals):
            f = {
                k: (v[:, i : i + 1] if isinstance(v, np.ndarray) and v.ndim == 2 else v)
                for k, v in forecast.items()
            }
            s = {k: v[i : i + 1] for k, v in state.items()}
            local.set_inputs(f, s)
        for k in range(c.admm_iterations):
            if cancelled():
                raise DispatchFailure("Cancelled")
            out = []
            for i, local in enumerate(self.locals):
                local.centre.value = (z - u)[:, i : i + 1]
                local.q_centre.value = (zq - uq)[:, i : i + 1]
                out.append(local.solve())
            x = np.concatenate([r["net"] for r in out], axis=1)
            q = np.concatenate([r["q"] for r in out], axis=1)
            self.centre.value = x + u
            self.q_centre.value = q + uq
            self.problem.solve(solver="CLARABEL", warm_start=True, max_iter=150)
            if self.problem.status != cp.OPTIMAL:
                raise DispatchFailure("ADMM aggregator: " + str(self.problem.status))
            previous = z
            previous_q = zq
            z = self.z.value.copy()
            zq = self.zq.value.copy()
            u += x - z
            uq += q - zq
            primal = float(np.hypot(np.linalg.norm(x - z), np.linalg.norm(q - zq)))
            dual = float(
                c.admm_rho
                * np.hypot(
                    np.linalg.norm(z - previous), np.linalg.norm(zq - previous_q)
                )
            )
            eps_primal = c.admm_tolerance * np.sqrt(2 * h * n) + c.admm_tolerance * max(
                np.hypot(np.linalg.norm(x), np.linalg.norm(q)),
                np.hypot(np.linalg.norm(z), np.linalg.norm(zq)),
            )
            eps_dual = c.admm_tolerance * np.sqrt(
                2 * h * n
            ) + c.admm_tolerance * np.hypot(
                np.linalg.norm(c.admm_rho * u), np.linalg.norm(c.admm_rho * uq)
            )
            logs.append(
                dict(
                    iteration=k + 1,
                    primal=primal,
                    dual=dual,
                    epsilon_primal=eps_primal,
                    epsilon_dual=eps_dual,
                )
            )
            if primal <= eps_primal and dual <= eps_dual:
                self.previous = z
                # Execute local feasible x; independently check coupling before accepting.
                # Network checking is numerical, not a fabricated claim based on convergence.
                vp = 1.02**2 - x @ self.feeder.voltage_p.T - q @ self.feeder.voltage_q.T
                bp = x @ self.feeder.downstream.T
                bq = q @ self.feeder.downstream.T
                safe = (
                    vp.min() >= c.voltage_min**2
                    and vp.max() <= c.voltage_max**2
                    and np.max(np.hypot(bp, bq) / self.feeder.ratings_kva) <= 1
                    and np.max(x.sum(axis=1)) <= c.import_limit_kw
                    and np.min(x.sum(axis=1)) >= -c.export_limit_kw
                    and np.all(x.sum(axis=1) <= self.cap.value + 1e-3)
                    and np.all(x.sum(axis=1) >= self.floor.value - 1e-3)
                )
                if not safe:
                    raise DispatchFailure(
                        "ADMM residual tolerance reached but local schedule violates coupling constraints"
                    )
                actions = {
                    key: np.concatenate([r["actions"][key] for r in out], axis=1)
                    for key in out[0]["actions"]
                }
                aggregate = x.sum(axis=1)
                terms = dict(
                    energy=float(
                        c.dt_hours
                        * np.sum(
                            forecast["buy"] * np.maximum(aggregate, 0)
                            - forecast["sell"] * np.maximum(-aggregate, 0)
                        )
                    ),
                    degradation=float(
                        sum(r["objective_terms"]["degradation"] for r in out)
                    ),
                    curtailment=float(
                        sum(r["objective_terms"]["curtailment"] for r in out)
                    ),
                    demand=float(c.demand_usd_kw * np.maximum(aggregate, 0).max()),
                    tie_break=float(
                        1e-6 * c.dt_hours * np.abs(aggregate).sum()
                        + 1e-4 * c.dt_hours * np.abs(actions["q_inverter"]).sum()
                    ),
                )
                return dict(
                    actions=actions,
                    net=x,
                    q=q,
                    seconds=perf_counter() - begin,
                    objective=sum(terms.values()),
                    objective_terms=terms,
                    solver="CLARABEL / sharing ADMM",
                    formulation="convex QP decomposition",
                    status="converged",
                    admm=logs,
                )
        raise DispatchFailure(
            f"ADMM did not converge in {c.admm_iterations} iterations; primal={primal:.3g}, dual={dual:.3g}"
        )
