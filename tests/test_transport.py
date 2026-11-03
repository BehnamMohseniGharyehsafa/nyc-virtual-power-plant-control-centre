"""Regression checks for the real mid-river cuts and disconnected grade joins."""

import json
from collections import defaultdict

import networkx as nx
import numpy as np
import pytest
from shapely.geometry import LineString, Polygon
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
