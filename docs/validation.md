# Validation and measured performance

Validation date: 2 November 2026. Development host: Windows, Python 3.13.15. Exact installed package versions and input/model hashes accompany numerical result folders. Results below are **executed measurements**, not expected performance.

## Automated checks

The suite covers battery energy/round-trip efficiency, RC analytic thermal response, tank first-law balance, PV night/clipping limits, wind cut-out, intertemporal dispatch and terminal SOC, negative-price exclusivity, infeasible PCC reporting, overloaded AC network detection, EV departure service, receding-horizon updates, independent snapshot AC OPF verification, IEEE 33-bus reference power flow, cash-flow arithmetic/payback, separate import/export accounting, seeded uncertainty, DST/leap-year timestamps, native-to-15-minute settlement integrals, missing-data rejection, causal forecast history, JSON/CSV network import, persisted numerical results and export completeness, explicit rejection of mesh LinDistFlow, P/Q sharing ADMM residuals/reference agreement, signed counterfactual events, sustained-duration envelopes, all page renderers and HTTP routes.

Numerical foundation: **29 tests passed in a clean virtual environment**, with `pip check` reporting no broken requirements. The fresh installation resolved NumPy 2.4.6, SciPy 1.17.1, CVXPY 1.9.3 and Pydantic 2.14.2, separately from the preinstalled development packages. Exact clean-environment pins are in `requirements-validated.txt`. The clean suite took 31.19 s. Run `python -m pytest` to reproduce. Numerical tolerances are defined in `tests/test_science.py`: typical conservation 1eâˆ’4 kW/kWh, reference voltage comparison 2eâˆ’4 pu, analytic RC comparison 1eâˆ’10 Â°C. The IEEE case is a separate reference feeder and is never called the Brooklyn utility network.

The subsequent rendering upgrade adds an offline ES-module dependency-graph check. The complete suite now passes **34 tests** (63.39 s in the validated environment). Browser verification and its platform limits are documented in [rendering validation](rendering-validation.md).

## Full community experiment

The 16-building network-aware run on 17 July 2024 executed **96 quarter-hour steps**, solving a **96-step prediction horizon at each decision**, then independently AC-checking each applied action. The clean-environment run `4c443515-673a-410e-aa8f-10aaadca333f` completed in **132.72 s**, with no reported network, SOC, EV or comfort flags. Realised scenario operating cost was **$5,936.71**, identical to development-environment run `59097493-25de-412f-9739-0042721f6702` (198.68 s under concurrent validation load). That is a model result under illustrative tariff/asset assumptions, not an observed customer bill. Run folders contain the authoritative diagnostics, input hashes, package versions and data-quality report.

Baseline runs using the same corrected public-source inputs: conventional local control with the same assumed DERs **$8,060.97**; no PV/BESS local reference **$9,925.57**. The financial UI derives comparison benefits from stored matching inputs, rather than embedding these numbers in application code. End-of-day stored energy can differ between controllers; the predictive terminal condition applies to each rolling horizon, not an enforced common realised-day terminal SOC. Interpret operating comparisons accordingly.

## Short-horizon scaling

All cases below have **4 forecast steps and 4 executed steps**. They use identical acquisition snapshots and modelling rules, with size-dependent buildings and a 200 MW PCC cap to isolate numerical scaling. Four device categories per building means PV, BESS, HVAC and workplace EV; it does not claim four measured installations per building.

| Buildings | Independently represented device categories | Wall time (s) | Sum of solve times (s) | Executed steps | Violations |
|---:|---:|---:|---:|---:|---:|
| 16 | 64 | 4.65 | 0.55 | 4 | 0 |
| 64 | 256 | 6.94 | 1.01 | 4 | 0 |
| 500 | 2,000 | 20.01 | 3.41 | 4 | 0 |
| 1,000 | 4,000 | 43.77 | 8.21 | 4 | 0 |

Wall times include portfolio/network construction, input processing, forecasting and all AC verifications. They were measured while other validation tasks were running and are not isolated-hardware speed records. Detailed machine-readable results are generated at `results/benchmarks.json` and `results/benchmarks.csv`. Sparse explicit branch variables replaced dense nodal voltage matrices after profiling. These measurements do **not** establish 96-step large-portfolio rolling-MPC performance.

## Interpretation of failures

Optimisation failure: status/error recorded, no action applied and execution stops. AC/comfort/EV violation: actual trajectory is retained and the run is labelled with violations, not physically feasible. Negative/inverted-price distributed cases: explicitly rejected as outside the convex controller. ADMM max iterations: explicit nonconvergence, not a claimed successful dispatch. Infeasible cases are tested deliberately.

This is mathematical/software validation of declared reduced-order models. It is not empirical field validation, tariff certification, battery lifetime validation or a guarantee of safe real-grid operation.

## Detailed urban scene checks

The expanded suite includes four urban checks: observed street/building/water geometry, rejection of ferry routes as roads, finite moving Python traffic trajectories with ordinary speed bounds, saved numerical energy-state coupling, and offline renderer/compressed endpoint availability. These brought the suite to **33 passing tests**. The scene uses about 60,000 geometric windows for the default 320-building visual context. Static city meshes are merged by material; windows, glazing, PV, trees and cars use GPU instancing. Browser checks include district/street/plan views, traffic pause/resume, lighting, building selection and numerical timeline updates. Façade and traffic details are estimates, not observed asset data.
