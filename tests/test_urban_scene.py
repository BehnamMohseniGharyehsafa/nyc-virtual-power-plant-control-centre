"""Check source geometry, traffic trajectories, result coupling and offline assets."""

import gzip
import json
import re
import posixpath
from pathlib import Path
import numpy as np
import pytest
from app.main import create_app
from core.config import Scenario
from core.simulation import simulate
from visualisation.urban_scene import fabric, traffic_model, scene_config, scene_state


def test_observed_streets_water_and_building_coordinates():
    f = fabric()
    assert len(f["buildings"]) >= 300
    assert len(f["roads"]) > 100
    assert f["water"]
    assert all(r["kind"] != "14" for r in f["roads"]), (
        "Ferry routes must not be rendered as streets"
    )
    assert all(b["parts"] and b["height"] > 0 for b in f["buildings"])
    assert len(f["buildings"][0]["parts"][0]["exposed"]) == len(
        f["buildings"][0]["parts"][0]["rings"][0]
    )


def test_traffic_is_executed_finite_moving_and_reproducible():
    a = traffic_model()
    p = np.asarray(a["positions"])
    assert p.shape == (960, 64, 3)
    assert np.isfinite(p).all()
    assert np.max(np.linalg.norm(p[10, :, :2] - p[0, :, :2], axis=1)) > 1
    steps = np.linalg.norm(np.diff(p[:, :, :2], axis=0), axis=2)
    # Reinsertion at network boundaries is explicit and hidden by the renderer;
    # ordinary kinematic steps must respect configured city speed limits.
    regular = steps[steps < 15]
    assert np.quantile(regular, 0.99) / a["dt"] <= 10
    assert a["seed"] == 1401
    assert "illustrative" in a["provenance"]


def test_scene_energy_values_are_the_saved_model_state():
    r = simulate(Scenario(buildings=4, steps=4, horizon=8))
    c = scene_config(r)
    s = scene_state(r, 2)
    assert c["run_id"] == r.id
    assert len(c["assets"]) == r.config.buildings
    assert s["grid_kw"] == pytest.approx(r.series.grid_kw.iloc[2])
    assert sum(a["pv_kw"] for a in s["assets"]) == pytest.approx(r.series.pv_kw.iloc[2])
    assert s["assets"][0]["soc"] == pytest.approx(
        r.assets["energy"][2, 0] / r.portfolio.battery_kwh[0]
    )


def test_offline_renderer_and_compressed_traffic_endpoint():
    a = create_app(False)
    client = a.server.test_client()
    assert client.get("/district").status_code == 200
    for path in (
        "city/world.js",
        "city/scene.css",
        "city/rendering.js",
        "vendor/three.module.js",
        "vendor/three.core.js",
        "vendor/OrbitControls.js",
    ):
        assert client.get("/static/" + path).status_code == 200
    response = client.get("/api/city-traffic")
    assert response.status_code == 200
    assert response.headers["Content-Encoding"] == "gzip"
    payload = json.loads(gzip.decompress(response.data))
    assert len(payload["cars"]) == 64 and payload["frames"] == 960
    assert client.get("/api/city/not-a-run").status_code == 404


def test_renderer_addon_graph_is_complete_and_available_offline():
    """A missing transitive add-on would leave the entire WebGL view blank."""
    client = create_app(False).server.test_client()
    root = Path(__file__).resolve().parents[1] / "app" / "static"
    pending = ["city/world.js", "city/rendering.js"]
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        assert client.get("/static/" + name).status_code == 200, name
        content = (root / name).read_text(encoding="utf-8")
        # Match executable imports, not illustrative import snippets in JSDoc.
        for specifier in re.findall(
            r"(?m)^import\s+[\s\S]*?\bfrom\s+['\"]([^'\"]+)['\"]", content
        ):
            if specifier == "three":
                dependency = "vendor/three.module.js"
            elif specifier == "three/addons/controls/OrbitControls.js":
                dependency = "vendor/OrbitControls.js"
            elif specifier.startswith("three/addons/"):
                dependency = specifier.replace("three/addons/", "vendor/addons/")
            elif specifier.startswith("/static/"):
                dependency = specifier.removeprefix("/static/")
            elif specifier.startswith("."):
                dependency = posixpath.normpath(
                    posixpath.join(posixpath.dirname(name), specifier)
                )
            else:
                raise AssertionError(f"Unexpected external runtime import: {specifier}")
            pending.append(dependency)
