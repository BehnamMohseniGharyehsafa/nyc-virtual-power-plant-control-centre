"""Restore a verified, calculated demonstration on an empty hosted filesystem."""

import hashlib
import json
from pathlib import Path
import shutil
from uuid import UUID

DEMO = Path(__file__).resolve().parents[1] / "data" / "demo" / "community"


def seed_demo(repository, source=DEMO):
    """Register the bundled model result once, preserving existing user results."""
    source = Path(source)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    identifier = str(UUID(manifest["run_id"]))
    if any(row["id"] == identifier for row in repository.list()):
        return identifier
    payload = json.loads((source / "run.json").read_text(encoding="utf-8"))
    if payload["id"] != identifier or payload["status"] != "completed":
        raise ValueError("The hosted demonstration must be a completed calculated run")
    for name, digest in manifest["files"].items():
        if Path(name).name != name or name in (".", ".."):
            raise ValueError("Invalid demonstration filename")
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Demonstration checksum failed: {name}")
    folder = repository.root / identifier
    folder.mkdir(exist_ok=True)
    for name, digest in manifest["files"].items():
        destination = folder / name
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise ValueError(
                    f"Existing result differs from the demonstration: {name}"
                )
        else:
            shutil.copyfile(source / name, destination)
    with repository.lock, repository.connection() as db:
        db.execute(
            "INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?,?,?,?)",
            (
                identifier,
                payload["metadata"]["created_utc"],
                payload["config"]["name"],
                payload["config"]["controller"],
                payload["status"],
                payload["config"]["buildings"],
                payload["metadata"]["seconds"],
                payload["accounting"].get("total_usd"),
            ),
        )
    return identifier
