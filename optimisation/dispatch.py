"""Multi-period LP/MILP dispatch; optional convex proximal local subproblem.

All monetary terms are USD. LinDistFlow is lossless; AC verification is mandatory.
Negative-price problems use binary battery and grid modes. Positive-price LP
solutions are checked for simultaneous charging/discharging before execution.
"""

from time import perf_counter
import cvxpy as cp
import numpy as np
from models.physics import thermal_coefficients


class DispatchFailure(RuntimeError):
    pass


def network_constraints(net_power, q_power, feeder, config, margin=True):
    """Inscribed octagon thermal limits and squared-voltage bounds."""
    reserve = 0.96 if margin else 1.0
    # Explicit branch-flow variables preserve the sparse tree structure. Eliminating
    # them into dense nodal voltage sensitivities scales quadratically in assets.
    branch_p = cp.Variable((net_power.shape[0], feeder.downstream.shape[0]))
    branch_q = cp.Variable(branch_p.shape)
    limit = reserve * feeder.ratings_kva * np.cos(np.pi / 8)
    cons = [
        branch_p == net_power @ feeder.downstream.T,
        branch_q == q_power @ feeder.downstream.T,
    ]
    for angle in np.arange(8) * np.pi / 4 + np.pi / 8:
        cons.append(np.cos(angle) * branch_p + np.sin(angle) * branch_q <= limit)
    squared_v = (
        1.02**2
        - 2
        * (
            cp.multiply(branch_p, feeder.resistance)
            + cp.multiply(branch_q, feeder.reactance)
        )
        @ feeder.downstream
    )
    buffer = 0.002 if margin else 0
    cons += [
        squared_v >= (config.voltage_min + buffer) ** 2,
        squared_v <= (config.voltage_max - buffer) ** 2,
    ]
    return cons, squared_v


class DispatchProblem:
    def __init__(self, portfolio, config, feeder=None, binary=False, proximal=False):
        self.portfolio, self.config = portfolio, config
        n, h = portfolio.n, config.horizon
        self.n, self.h, self.binary = n, h, binary
        self.base = cp.Parameter((h, n), name="base_kw")
        self.pv = cp.Parameter((h, n), nonneg=True, name="available_pv_kw")
        self.outdoor = cp.Parameter(h)
        self.gain = cp.Parameter((h, n))
        self.cop = cp.Parameter(h, nonneg=True)
        self.buy, self.sell = cp.Parameter(h), cp.Parameter(h)
        self.initial_e = cp.Parameter(n, nonneg=True)
        self.initial_t = cp.Parameter(n)
        self.initial_ev = cp.Parameter(n, nonneg=True)
        self.available = cp.Parameter((h, n), nonneg=True)
        self.carry_ev = cp.Parameter((h, n), nonneg=True)
        self.ev_floor = cp.Parameter((h, n), nonneg=True)
        self.heat_mode = cp.Parameter(nonneg=True)
        self.target_cap = cp.Parameter(h)
        self.target_floor = cp.Parameter(h)
        self.charge, self.discharge = (
            cp.Variable((h, n), nonneg=True),
            cp.Variable((h, n), nonneg=True),
        )
        self.heat, self.cool = (
            cp.Variable((h, n), nonneg=True),
            cp.Variable((h, n), nonneg=True),
        )
        self.ev, self.curtail = (
            cp.Variable((h, n), nonneg=True),
            cp.Variable((h, n), nonneg=True),
        )
        self.energy, self.temp = cp.Variable((h + 1, n)), cp.Variable((h + 1, n))
        self.ev_energy = cp.Variable((h + 1, n))
        self.q_inverter = cp.Variable((h, n))
        self.net = (
            self.base
            + self.heat
            + self.cool
            + self.ev
            + self.charge
            - self.discharge
            - self.pv
            + self.curtail
        )
        self.q = 0.25 * (self.base + self.heat + self.cool + self.ev) - self.q_inverter
        self.imp, self.exp = cp.Variable(h, nonneg=True), cp.Variable(h, nonneg=True)
        self.peak = cp.Variable(nonneg=True)
        dt = config.dt_hours
        p = portfolio
        a, b = thermal_coefficients(p, dt)
        cons = [
            self.energy[0] == self.initial_e,
            self.temp[0] == self.initial_t,
            self.ev_energy[0] == self.initial_ev,
            self.energy[1:]
            == self.energy[:-1] + 0.95 * dt * self.charge - dt * self.discharge / 0.95,
            self.energy >= 0.1 * p.battery_kwh,
            self.energy <= 0.9 * p.battery_kwh,
            self.energy[-1] >= self.initial_e,
            self.charge <= p.battery_kw,
            self.discharge <= p.battery_kw,
            self.curtail <= self.pv,
            self.heat <= self.heat_mode * p.hvac_kw,
            self.cool <= (1 - self.heat_mode) * p.hvac_kw,
            self.temp[1:]
            == cp.multiply(a, self.temp[:-1])
            + cp.multiply((1 - a), self.outdoor[:, None])
            + cp.multiply(
                b, cp.multiply(self.cop[:, None], self.heat - self.cool) + self.gain
            ),
            self.temp[1:] >= config.comfort_min,
            self.temp[1:] <= config.comfort_max,
            self.ev <= cp.multiply(self.available, p.ev_kw),
            self.ev_energy[1:]
            == cp.multiply(self.carry_ev, self.ev_energy[:-1]) + 0.95 * dt * self.ev,
            self.ev_energy >= 0,
            self.ev_energy[1:] >= self.ev_floor,
            self.ev_energy <= p.ev_required_kwh,
            self.imp - self.exp == cp.sum(self.net, axis=1),
            self.imp <= 0.98 * config.import_limit_kw,
            self.exp <= 0.98 * config.export_limit_kw,
            self.imp <= self.peak,
            cp.sum(self.net, axis=1) <= self.target_cap,
            cp.sum(self.net, axis=1) >= self.target_floor,
        ]
        if not config.grid_charging:
            cons += [self.charge <= self.pv - self.curtail]
        # Independent P/Q rectangles lie inside hypothetical PV + BESS inverter ratings.
        qmax = np.sqrt(1.1**2 - 1) * (p.pv_kw + p.battery_kw)
        cons += [self.q_inverter <= qmax, self.q_inverter >= -qmax]
        if binary:
            mode = cp.Variable((h, n), boolean=True)
            grid_mode = cp.Variable(h, boolean=True)
            cons += [
                self.charge <= cp.multiply(p.battery_kw, mode),
                self.discharge <= cp.multiply(p.battery_kw, 1 - mode),
                self.imp <= config.import_limit_kw * grid_mode,
                self.exp <= config.export_limit_kw * (1 - grid_mode),
            ]
        if feeder is not None:
            if config.topology != "radial":
                raise ValueError(
                    "LinDistFlow dispatch only supports radial topology; use snapshot AC OPF for meshed cases"
                )
            limits, self.voltage = network_constraints(self.net, self.q, feeder, config)
            cons += limits
        self.energy_cost = dt * (self.buy @ self.imp - self.sell @ self.exp)
        self.degradation_cost = 0.025 * dt * cp.sum(self.charge + self.discharge)
        self.curtailment_cost = 0.002 * dt * cp.sum(self.curtail)
        self.demand_cost = config.demand_usd_kw * self.peak
        # Tiny tie-break resolves equal buy/export LP degeneracy; separately accounted.
        self.tie_cost = 1e-6 * dt * cp.sum(self.imp + self.exp) + 1e-4 * dt * cp.sum(
            cp.abs(self.q_inverter)
        )
        objective = (
            self.energy_cost
            + self.degradation_cost
            + self.curtailment_cost
            + self.demand_cost
            + self.tie_cost
        )
        if proximal:
            if binary:
                raise ValueError(
                    "Distributed convex subproblems do not support binary modes"
                )
            self.centre = cp.Parameter((h, n))
            self.q_centre = cp.Parameter((h, n))
            objective = (
                self.degradation_cost
                + self.curtailment_cost
                + 1e-4 * dt * cp.sum(cp.abs(self.q_inverter))
                + config.admm_rho
                / 2
                * (
                    cp.sum_squares(self.net - self.centre)
                    + cp.sum_squares(self.q - self.q_centre)
                )
            )
        self.problem = cp.Problem(cp.Minimize(objective), cons)
        self.proximal = proximal

    def set_inputs(self, forecast, state, target=None):
        p, c = self.portfolio, self.config
        self.base.value, self.pv.value = forecast["base"], np.maximum(forecast["pv"], 0)
        self.outdoor.value, self.gain.value = forecast["outdoor"], forecast["gain"]
        self.cop.value = forecast["cop"]
        self.buy.value, self.sell.value = forecast["buy"], forecast["sell"]
        self.initial_e.value, self.initial_t.value = (
            state["energy"],
            state["temperature"],
        )
        self.initial_ev.value = state["ev_energy"]
        self.available.value = np.tile(forecast["ev_available"][:, None], (1, p.n))
        self.carry_ev.value = np.tile(
            (~forecast["ev_arrival"])[:, None], (1, p.n)
        ).astype(float)
        self.ev_floor.value = forecast["ev_floor"]
        self.heat_mode.value = forecast["heat_mode"]
        if isinstance(target, dict):
            self.target_cap.value = target["ceiling"]
            self.target_floor.value = target["floor"]
        else:
            self.target_cap.value = (
                np.full(self.h, c.import_limit_kw) if target is None else target
            )
            self.target_floor.value = np.full(self.h, -c.export_limit_kw)

    def solve(self):
        started = perf_counter()
        fallback = None
        try:
            if self.proximal:
                self.problem.solve(solver="CLARABEL", warm_start=True, max_iter=150)
            else:
                options = {
                    "time_limit": self.config.solver_seconds,
                    "mip_rel_gap": 1e-5,
                    "threads": 1,
                }
                # Reusing a simplex basis was slower in measured rolling-horizon
                # cases. HiGHS IPM without crossover is faster for these sparse LPs.
                if not self.binary:
                    options.update(solver="ipm", run_crossover="off")
                try:
                    self.problem.solve(
                        solver="HIGHS", warm_start=False, highs_options=options
                    )
                except (cp.error.SolverError, ValueError) as exc:
                    if self.binary:
                        raise
                    fallback = f"IPM returned no usable solution ({type(exc).__name__}); retried simplex"
                    remaining = self.config.solver_seconds - (perf_counter() - started)
                    if remaining <= 0:
                        raise DispatchFailure(
                            fallback + "; time budget exhausted"
                        ) from exc
                    self.problem.solve(
                        solver="HIGHS",
                        warm_start=False,
                        highs_options={
                            "time_limit": remaining,
                            "threads": 1,
                            "solver": "simplex",
                        },
                    )
        except (cp.error.SolverError, ValueError) as exc:
            raise DispatchFailure(f"Solver error: {exc}") from exc
        if self.problem.status != cp.OPTIMAL:
            raise DispatchFailure(
                f"Dispatch status: {self.problem.status}; no control action applied"
            )
        overlap = float(np.max(np.minimum(self.charge.value, self.discharge.value)))
        if overlap > 1e-4:
            raise DispatchFailure(
                f"Convex schedule has simultaneous battery charge/discharge ({overlap:.3g} kW)"
            )
        actions = {
            name: np.maximum(0, var.value).copy()
            for name, var in [
                ("charge", self.charge),
                ("discharge", self.discharge),
                ("heat", self.heat),
                ("cool", self.cool),
                ("ev", self.ev),
                ("curtail", self.curtail),
            ]
        }
        actions["q_inverter"] = self.q_inverter.value.copy()
        return dict(
            actions=actions,
            net=self.net.value.copy(),
            q=self.q.value.copy(),
            energy=self.energy.value.copy(),
            temperature=self.temp.value.copy(),
            ev_energy=self.ev_energy.value.copy(),
            status=self.problem.status,
            objective=float(self.problem.value),
            seconds=perf_counter() - started,
            objective_terms={
                "energy": float(self.energy_cost.value),
                "degradation": float(self.degradation_cost.value),
                "curtailment": float(self.curtailment_cost.value),
                "demand": float(self.demand_cost.value),
                "tie_break": float(self.tie_cost.value) if not self.proximal else 0,
            },
            solver="CLARABEL" if self.proximal else "HiGHS",
            fallback=fallback,
            formulation="convex QP"
            if self.proximal
            else ("MILP" if self.binary else "LP"),
        )
