"""Enumerated PV/BESS sizing using executed dispatch and a no-DER reference.

This is a discrete design-grid comparison, not continuous joint investment OPF.
"""

import argparse
import pandas as pd
from core.config import Scenario, Finance
from core.simulation import simulate
from core.storage import Repository
from economics.finance import lifecycle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--buildings", type=int, default=16)
    parser.add_argument("--steps", type=int, default=96)
    parser.add_argument("--horizon", type=int, default=96)
    args = parser.parse_args()
    repo = Repository()
    base = dict(buildings=args.buildings, steps=args.steps, horizon=args.horizon)
    reference = simulate(
        Scenario(**base, controller="baseline", pv_scale=0, battery_scale=0)
    )
    repo.save(reference)
    if reference.status != "completed":
        raise RuntimeError("No-DER reference is infeasible; sizing stopped")
    records = []
    for pv, battery in ((1, 0), (0, 1), (1, 1), (1, 2), (2, 1)):
        r = simulate(Scenario(**base, pv_scale=pv, battery_scale=battery))
        repo.save(r)
        feasible = r.status == "completed"
        annual = (
            (
                reference.accounting["total_usd"]
                - r.accounting.get("total_usd", float("nan"))
            )
            * 96
            / args.steps
            * 365
        )
        f = (
            lifecycle(
                annual,
                r.portfolio.pv_kw.sum(),
                r.portfolio.battery_kwh.sum(),
                r.portfolio.n,
                Finance(),
            )
            if feasible
            else {}
        )
        records.append(
            dict(
                pv_scale=pv,
                battery_scale=battery,
                status=r.status,
                scenario_annual_savings_usd=annual if feasible else None,
                npv_usd=f.get("npv_usd"),
                run_id=r.id,
            )
        )
        print(records[-1], flush=True)
        pd.DataFrame(records).to_csv(repo.root / "sizing.csv", index=False)


if __name__ == "__main__":
    main()
