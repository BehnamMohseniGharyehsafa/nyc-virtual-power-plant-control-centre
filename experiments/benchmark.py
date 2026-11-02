"""Actually execute portfolio scaling cases. No extrapolated speed claims.

python -m experiments.benchmark --sizes 16 64 500 1000 --horizon 4 --steps 4
These short-horizon measurements do not validate 1,000-asset day-long MPC.
"""

import argparse
import pandas as pd
from core.config import Scenario
from core.simulation import simulate
from core.storage import Repository, dumps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[16, 64, 500, 1000])
    parser.add_argument("--horizon", type=int, default=4)
    parser.add_argument("--steps", type=int, default=4)
    args = parser.parse_args()
    rows = []
    repo = Repository()
    for n in args.sizes:
        print(f"Benchmark: {n} buildings", flush=True)
        try:
            r = simulate(
                Scenario(
                    buildings=n,
                    horizon=args.horizon,
                    steps=args.steps,
                    import_limit_kw=200000,
                    export_limit_kw=200000,
                )
            )
            repo.save(r)
            rows.append(
                dict(
                    buildings=n,
                    independent_der_devices=4 * n,
                    horizon=args.horizon,
                    executed_steps=len(r.series),
                    seconds=r.metadata["seconds"],
                    status=r.status,
                    violations=int(r.series.violations.sum())
                    if len(r.series)
                    else None,
                    solver_seconds=float(r.series.solver_seconds.sum())
                    if len(r.series)
                    else None,
                    run_id=r.id,
                )
            )
        except Exception as exc:
            rows.append(dict(buildings=n, status="failed", error=str(exc)))
        print(dumps(rows[-1]), flush=True)
        (repo.root / "benchmarks.json").write_text(dumps(rows))
    pd.DataFrame(rows).to_csv(repo.root / "benchmarks.csv", index=False)


if __name__ == "__main__":
    main()
