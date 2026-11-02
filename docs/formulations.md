# Equations, units and solver capabilities

Positive device `net_kw` means consumption/import at a building. Positive PCC power means import from the external grid. PV and battery discharge reduce net consumption. Reactive demand is positive inductive consumption; inverter reactive injection reduces it. Active power is kW, reactive power kvar, apparent power kVA, energy kWh, time hours, currency USD, temperature °C, voltage per unit.

## DER balances

Battery: `E[t+1] = E[t] + ηc Pc[t] Δt − Pd[t] Δt / ηd`. Both efficiencies are 0.95; SOC is bounded at 10–90%, power at capacity/2, initial SOC at 50%, and the prediction horizon terminates with energy at least equal to its initial value. A $0.025/kWh AC-side throughput proxy prices wear; it is not a validated lifetime model. This is the first-law energy balance, implemented in `models/physics.py` and independently checked in `test_battery_energy_and_round_trip` and `test_dispatch_intertemporal_and_objective`.

Binary charge/discharge and grid import/export modes are mandatory for negative-price/inverted-tariff MILPs and for maximum-flexibility envelopes. The positive-price cost-minimising LP is relaxed but its charge/discharge overlap is checked before applying any action. A relaxed solution with overlap >1e−4 kW is rejected. Disabling grid charging limits battery charging to contemporaneous PV; surplus-only source tracing within a shared AC bus is not modelled.

Building heat balance: `C dT/dt = U(Tout − T) + COP(Ph − Pc) + Qint`, with `U = 0.0008 A` kW/K, `C = 0.045 A` kWh/K, assumed floor area A in m², and `Qint = 0.65 Pbase`. Exact zero-order-hold discretisation gives `a = exp(−U Δt/C)`, `b = (1−a)/U`, and `Tnext = a T + (1−a) Tout + b[COP(Ph−Pc)+Qint]`. This is a lumped first-law RC model, not a calibrated high-fidelity building simulation. COP is an explicitly assumed clipped temperature curve, not a manufacturer performance fit. Predictive heating/cooling mode is fixed by season to avoid simultaneous operation; the baseline thermostat targets 23 °C. The optimiser imposes hard 21–25 °C default bounds on predicted states. Actual forecast errors may cause deviations, which are retained as degree hours. `test_rc_exact_zero_order_hold` checks the analytic equilibrium solution to 1e−10 °C.

EV: `Eev[t+1] = carry[t] Eev[t] + 0.95 Pev[t] Δt`; `carry=0` on arrival, otherwise 1. Workplace arrival is 08:00, departure 18:00, 16 kWh required per assumed vehicle, charger 7.2 kW. A backward reachable energy floor ensures the requirement remains attainable even when departure lies beyond a short horizon. There is no V2G or stochastic arrival model. See `test_ev_departure_constraints`.

PV follows the checked pvlib PVWatts/Faiman documentation: solar position at interval midpoint; isotropic plane-of-array transposition; Faiman module temperature; `Pdc = PSTC Gpoa/1000 [1+γ(Tcell−25)]`, γ = −0.0035/K; 4% assumed balance-of-system loss; PVWatts inverter efficiency/clipping. Usable roof area fraction 45%, module STC area efficiency 20%, tilt 15°, azimuth 180°, DC/AC ratio 1.2. These are assumed potential installations, not roof survey results. Night-time irradiance and AC power are nonnegative, with inverter limits checked by tests. [pvlib sources](references.md) document the conversion implementation.

## Electrical model

The synthetic balanced network has a 69 kV external bus, 69/13.8 kV substation, radial 13.8 kV branches and separate 13.8/0.4 kV building transformers. Line assumptions: r = 0.16 Ω/km, x = 0.12 Ω/km, shunt capacitance zero. Substation impedance: 6%, resistive part 0.5%; building transformers: 4%, resistive part 1%; fixed ratio, zero phase shift. Thermal ratings are stated design assumptions with an adjustable multiplier, held fixed across PV/BESS sizing cases. These parameters are not inferred utility equipment.

Orient all branches from root towards buildings. Sparse matrix D maps building demands to downstream branches. Active/reactive nodal balance is `Pbranch = D Pbuilding`, `Qbranch = D Qbuilding`. Squared voltage is `vbuilding ≈ 1.02² − 2 Dᵀ (r̄ Pbranch + x̄ Qbranch)`, where line coefficients r̄ = R/(1000 VLL,kV²) per kW, and transformer coefficients use impedance per unit divided by kVA rating. Explicit branch-flow variables keep the optimisation matrix sparse. The model neglects second-order current/loss terms and is not exact AC OPF. The derivation is the lossless radial branch-flow approximation associated with Baran–Wu and Farivar–Low; see the checked references.

Eight tangent-normal inequalities form an **inscribed** octagon inside each branch's apparent-power circle: `P cos φk + Q sin φk ≤ 0.96 Srated cos(π/8)`, φk = π/8 + kπ/4. The 4% rating reserve and 0.002 pu voltage margin are declared approximation reserves. Net PCC limits receive a 2% loss reserve. Inverter P/Q rectangular limits lie inside a shared `1.1 × (PV + BESS power)` apparent-power rating. Inverter independent source/thermal derating is not modelled. PV-only snapshot AC OPF uses its own conservative inverter rectangle.

Independent AC verification uses pandapower Newton–Raphson. It solves conventional `S = V · conjugate(Ybus V)` balances including calculated losses, signed injections and voltage angles. It checks bus voltage, line current loading, transformer loading and PCC limits. `grid − Σ building net − losses` is exported as a conservation residual. `max |Vlinear − VAC|` is exported at each step. An AC-invalid schedule is explicitly labelled with violations and excluded from investment results. There is no automatic feasibility-restoration policy; this is an outstanding operational capability.

Snapshot nonlinear AC OPF uses pandapower/PYPOWER `runopp` with PV curtailment/reactive dispatch and fixed BESS/HVAC/EV powers. Battery energy is never a free snapshot decision. The resulting generator P/Q and slack voltage are copied into an independent `runpp` verification. Its USD/h objective includes a small renewable preference. pandapower's monetary column names contain `eur`; the configured numerical currency is USD. Local convergence is not proof of global optimality. The snapshot objective and multi-period objective differ and must not be directly ranked as identical optimisation problems.

## MPC and accounting

At every quarter hour: observe stored physical state, generate causal forecasts, solve the horizon, apply only the first action, simulate actual physical response, AC-verify, then advance. Forecast and executed horizons are distinct. Terminal energy limits reduce horizon depletion but do not enforce a final realised-day cyclic SOC; any terminal energy differences must be considered in cross-controller comparisons.

Multi-period objective, in USD: `Σ Δt(πbuy Pimport − πexport Pexport + 0.025(Pc+Pd) + 0.002 Pcurtail) + demand_rate × peak`. Tiny tie-break costs of 1e−6 USD/kWh grid throughput and 1e−4 USD/kvarh inverter effort prevent arbitrary LP degeneracy. Physical constraints are hard, not bought off by penalties. Horizon objectives are reported separately from realised operating accounts; summing repeated full-horizon objectives would double-count overlapping forecasts.

Actual settlement includes AC losses and charges import/export separately. Retail rates are illustrative (base $0.22/kWh, peak multiplier 1.4 at 16:00–21:00, export $0.045/kWh). Wholesale exposure uses observed RT LBMP / 1000 and hypothetical access. Demand charges are assessed once per simulated window; this is not an automatically reconstructed monthly customer bill.

## Sharing ADMM

The convex problem is `min Σ fi(xi) + g(z)`, with each local physical feasible set and `(Pi,Qi) = (zPi,zQi)`. Local QPs minimise wear/curtailment/reactive effort plus `ρ/2 ||xi − zi + ui||²`. The aggregator minimises energy/demand cost plus `ρ/2 ||x + u − z||²` over the network and PCC set. Scaled duals update `u ← u+x−z`. Primal residual is `||x−z||`; dual residual is `ρ ||z−zprevious||`; absolute-plus-relative stopping thresholds are recorded. P and Q both participate in consensus. The algorithm is sequentially executed local agents in one process, not distributed hardware. Converged local schedules are numerically checked against coupling and independently AC-verified before any success claim. Max-iteration failure is surfaced. Negative-price/nonconvex cases are explicitly rejected. See Boyd et al. and `tests/test_control.py`.

## Flexibility and finance

Positive delivered flexibility is `Pbaseline,AC − Pcontrolled,AC`. Baseline is an independently executed identical-input conventional local counterfactual. Event planning uses a causal forecast reference; ex-post evaluation uses the realised counterfactual, so scheduled and delivered quantities can differ. Positive requests impose an import ceiling, negative requests an import floor. Hypothetical settlement requires every completed event interval within tolerance and no network/comfort/EV flags. Recovery energy is additional consumption within a declared four-hour window. Service payment is reported separately, without double-counting avoided energy costs.

Sustained envelopes optimise one constant reduction/increase over all event timesteps with battery, thermal, EV, network and terminal/recovery constraints. Both use binary exclusivity and receive full-horizon AC checks. They are forecast-conditional estimates, not guaranteed field availability.

Finance uses `NPV = −CAPEX + Σ CFy/(1+r)^y`. Annual benefit is explicitly extrapolated from the executed comparison using configurable representative days. Cash flows include illustrative installation/engineering, O&M, degradation, escalation, battery replacement and residual value. IRR/MIRR use numpy-financial. Discounted payback interpolates the first positive cumulative discounted cash-flow crossing, or returns None. Multiple-sign-change IRRs are not uniqueness-certified. Tax, incentives, fuel and eligibility-based market revenues are not included. Monte Carlo uses declared assumed distributions, a fixed seed and scenario percentiles—not estimated confidence intervals. See independent cash-flow tests.

## Solver capability matrix

| Solver | LP | Convex QP | MILP | Convex SOCP | Nonlinear AC OPF |
|---|---|---|---|---|---|
| HiGHS | Yes | Yes (solver capability) | Yes | No | No |
| Clarabel | Yes | Yes | No | Yes (solver capability) | No |
| OSQP (optional) | Via QP | Yes | No | No | No |
| pandapower/PYPOWER interior-point | No general LP interface here | Not used for dispatch | No | No | Local nonconvex solve |

Implemented formulations: LP/MILP dispatch and convex-QP ADMM, plus snapshot nonlinear AC OPF. No SOCP branch-flow implementation or exact multiperiod AC OPF is claimed. Solver availability can be inspected with `python -c "import cvxpy; print(cvxpy.installed_solvers())"`. A solver error, unrecognised status, timeout or physical exclusivity failure cannot produce a successful dispatch. IPM failures may retry simplex within the remaining configured time and are recorded in diagnostics.
