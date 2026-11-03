"""Regression checks for the real mid-river cuts and disconnected grade joins."""

import json
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import networkx as nx
import numpy as np
import pytest
from shapely import line_merge
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import unary_union

from data.download import CACHE
from visualisation.transport import bridge_name, station
from visualisation.urban_scene import fabric


def test_complete_source_crossings_connect_both_banks():
    scene = fabric()
    source = json.loads((CACHE / "streets.geojson").read_text(encoding="utf-8"))[
        "features"
    ]
    expected = {
        f["properties"]["id"]
        for f in source
        if f["properties"]["road_type"] == "3" and bridge_name(f["properties"]["name"])
    }
    assert expected <= {r["source_id"] for r in scene["roads"]}
    assert all(r["kind"] not in ("4", "11", "12", "14") for r in scene["roads"])
    for bridge in scene["bridges"]:
        for direction in ("FT", "TF"):
            graph = nx.Graph()
            for road in scene["roads"]:
                if (
                    road["name"] == bridge["name"].upper().replace("BRIDGE", "BRG")
                    and road["direction"] == direction
                    and not road["walk"]
                ):
                    graph.add_edge(
                        *(
                            tuple(round(v, 2) for v in road["points"][end])
                            for end in (0, -1)
                        )
                    )
            # Each travel direction has a connected path across the main span
            # and onto both banks; ramps may legitimately merge inland.
            assert any(
                min(station(bridge, p) for p in c) < -bridge["main_span"] / 2 - 100
                and max(station(bridge, p) for p in c) > bridge["main_span"] / 2 + 100
                for c in nx.connected_components(graph)
            ), (bridge["name"], direction)
        assert bridge["main_span"] == pytest.approx(
            {"brooklyn": 486.3084, "manhattan": 448.056}[bridge["id"]]
        )


def test_shared_source_nodes_have_no_height_steps():
    nodes = defaultdict(list)
    for road in fabric()["roads"]:
        assert len(road["points"]) == len(road["heights"])
        assert np.isfinite(road["heights"]).all()
        for end in (0, -1):
            key = tuple(round(v, 2) for v in road["points"][end]) + (
                road["levels"][end],
            )
            nodes[key].append(road["heights"][end])
    for key, heights in nodes.items():
        assert max(heights) - min(heights) <= 0.003, key
        if key[2] == "13":
            assert max(map(abs, heights)) < 0.003


def test_joined_street_surfaces_cover_ground_carriageways():
    scene = fabric()
    surface = unary_union(
        [Polygon(p[0], p[1:]) for p in scene["street_surfaces"]["asphalt"]]
    )
    assert surface.is_valid
    coverage = surface.buffer(0.002)
    for road in scene["roads"]:
        if not road["walk"] and max(map(abs, road["heights"])) < 0.01:
            # Rounding the transmitted polygons is allowed one millimetre.
            assert coverage.covers(LineString(road["points"])), road["id"]
    assert len(scene["context_buildings"]) > 500
    assert not (
        {b["bin"] for b in scene["buildings"]}
        & {b["bin"] for b in scene["context_buildings"]}
    )


def test_multipart_records_keep_one_directed_grade_transition():
    scene = fabric()
    features = json.loads((CACHE / "streets.geojson").read_text(encoding="utf-8"))[
        "features"
    ]
    for feature in features:
        p = feature["properties"]
        if p["road_type"] in ("4", "11", "12", "14"):
            continue
        source = line_merge(shape(feature["geometry"]), directed=True)
        if source.geom_type != "LineString":
            continue
        rows = [r for r in scene["roads"] if r["source_id"] == p["id"]]
        assert len(rows) == 1, p["id"]
    for sid in ("129911", "128674", "115101", "71806", "81797"):
        road = next(r for r in scene["roads"] if r["source_id"] == sid)
        dy = np.diff(road["heights"])
        assert (dy >= -0.001).all() or (dy <= 0.001).all(), sid
        assert not road.get("spine"), sid
    for road in scene["roads"]:
        if road["levels"] == ["13", "13"]:
            assert max(map(abs, road["heights"])) < 0.003, road["id"]


def test_below_grade_roads_are_retained_and_terrain_is_open():
    scene = fabric()
    omitted = (
        "129657",
        "130177",
        "127773",
        "126550",
        "130121",
        "129057",
        "70310",
        "126555",
        "128064",
    )
    assert set(omitted) <= {r["source_id"] for r in scene["roads"]}
    terrain = scene["road_terrain"]
    cuts = unary_union([Polygon(p[0], p[1:]) for p in terrain["cutouts"]]).buffer(0.002)
    ground = unary_union([Polygon(p[0], p[1:]) for p in terrain["terrain"]])
    assert ground.is_valid and cuts.is_valid
    for r in scene["roads"]:
        if r["walk"]:
            continue
        for p, y in zip(r["points"], r["heights"]):
            if y < -0.2:
                assert cuts.covers(Point(p)), r["id"]
                assert not ground.contains(Point(p)), r["id"]
    assert np.isfinite(terrain["floor_vertices"]).all()
    assert len(terrain["floor_vertices"]) % 3 == 0


def test_actual_threejs_mesh_edges_and_winding():
    node = shutil.which("node")
    if not node:
        pytest.skip(
            "Node is needed for the actual Three.js mesh check; installed in CI"
        )
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "tests/validate_road_mesh.mjs"],
        input=json.dumps(fabric()),
        text=True,
        capture_output=True,
        cwd=root,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
