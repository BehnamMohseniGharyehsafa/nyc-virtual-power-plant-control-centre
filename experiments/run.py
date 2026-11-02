"""CLI: python -m experiments.run --controller network --buildings 16."""

import argparse
import json
from pathlib import Path
from core.config import Scenario
from core.simulation import simulate
from core.storage import Repository, export_bundle, dumps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--controller",
        choices=["baseline", "rule", "central", "network", "distributed"],
        default="network",
    )
    parser.add_argument("--buildings", type=int, default=16)
    parser.add_argument("--steps", type=int, default=96)
    parser.add_argument("--horizon", type=int, default=96)
    parser.add_argument("--date", default="2024-07-17")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    config = (
        Scenario(**json.loads(args.config.read_text()))
        if args.config
        else Scenario(
            controller=args.controller,
            buildings=args.buildings,
            steps=args.steps,
            horizon=args.horizon,
            date=args.date,
        )
    )
    run = simulate(
        config, progress=lambda f, m: print(f"{100 * f:5.1f}% {m}", flush=True)
    )
    repo = Repository()
    repo.save(run)
    if args.export:
        (repo.root / run.id / "results.zip").write_bytes(export_bundle(run))
    print(
        dumps(
            dict(
                id=run.id,
                status=run.status,
                seconds=run.metadata["seconds"],
                cost=run.accounting,
            )
        )
    )
    if run.status.startswith("failed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
