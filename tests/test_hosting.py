"""Check first-boot result restoration and production server configuration."""

import runpy
import shutil
from pathlib import Path
import pytest
from core.hosting import DEMO, seed_demo
from core.storage import Repository


def test_calculated_demo_seeds_once_and_loads_without_resimulation(
    tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("A hosted first boot must not launch a simulation")

    monkeypatch.setattr("core.jobs.simulate", forbidden)
    repository = Repository(tmp_path)
    identifier = seed_demo(repository)
    original = (tmp_path / identifier / "run.json").stat().st_mtime_ns
    assert seed_demo(repository) == identifier
    assert len(repository.list()) == 1
    assert (tmp_path / identifier / "run.json").stat().st_mtime_ns == original
    run = repository.load(identifier)
    assert run.status == "completed"
    assert len(run.series) == 96 and run.portfolio.n == 16
    assert run.accounting["total_usd"] == pytest.approx(5936.7145, abs=0.01)


def test_damaged_demo_is_rejected_before_registration(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(DEMO, source)
    (source / "assets.npz").write_bytes(b"damaged")
    repository = Repository(tmp_path / "results")
    with pytest.raises(ValueError, match="checksum failed"):
        seed_demo(repository, source)
    assert repository.list() == []


def test_gunicorn_binds_assigned_port_with_one_shared_worker(monkeypatch):
    monkeypatch.setenv("PORT", "8123")
    settings = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "gunicorn.conf.py")
    )
    assert settings["bind"] == "0.0.0.0:8123"
    assert settings["workers"] == 1 and settings["threads"] >= 2
    assert settings["preload_app"] is False
