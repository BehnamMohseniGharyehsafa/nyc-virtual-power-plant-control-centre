"""Continuous transport presentation on observed CSCL carriageways.

Horizontal paths and grade codes are observed; vertical metres, tower placement
and architectural detail are presentation estimates. Published DOT main spans
calibrate the two suspension assemblies. This module never enters the VPP model.
"""

from collections import defaultdict

import numpy as np
from shapely import line_merge, set_precision
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union


def bridge_name(name):
    name = name.upper()
    for key in ("BROOKLYN", "MANHATTAN"):
        if name.startswith(key) and ("BRG" in name or "BRIDGE" in name):
            if "PARK" not in name and "GREENWAY" not in name:
                return key.lower()
    return None


def station(bridge, point):
    return float(np.dot(np.asarray(point) - bridge["centre"], bridge["axis"]))


def deck_height(bridge, s):
    """One shared continuous profile; no vertical steps at CSCL segment boundaries."""
    half = bridge["main_span"] / 2
    if abs(s) <= half:
        return 40.5 + 2 * (1 - (s / half) ** 2)
    end = bridge["ends"][0 if s < 0 else 1]
    t = min(1, max(0, (abs(s) - half) / (abs(end) - half)))
    # A monotone approach meets the source's inland ground-level road network.
    return 40.5 * (1 - t) ** 1.12


def transport(road_source, water, project):
    raw = []
    for feature in road_source:
        p = feature["properties"]
        if p["road_type"] in ("4", "11", "12", "14"):
            continue  # tunnels, unknown/nonphysical links and ferries aren't surface roads
        # CSCL grade codes and travel direction describe the WHOLE feature.
        # Its connected MultiLineString parts are storage fragments, not new
        # ramps. Directed merging preserves the original FT/TF digitisation.
        geom = line_merge(project(feature["geometry"]), directed=True)
        for k, line in enumerate(
            geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        ):
            if line.length < 0.5:
                continue
            line = line.simplify(0.15)
            if (
                bridge_name(p["name"])
                or p.get("from_level") != "13"
                or p.get("to_level") != "13"
            ):
                line = line.segmentize(12)
            points = [[round(x, 3), round(-y, 3)] for x, y in line.coords]
            raw.append(
                dict(
                    id=f"{p['id']}-{k}",
                    source_id=p["id"],
                    name=p["name"],
                    points=points,
                    width=p["width_m"],
                    direction=p["direction"],
                    kind=p["road_type"],
                    speed_mph=p["speed_mph"],
                    lanes=p["lanes"],
                    levels=[p.get("from_level"), p.get("to_level")],
                    bridge=bridge_name(p["name"]),
                    walk=p["direction"] == "NV" or p["road_type"] in ("5", "6", "7"),
                )
            )
    # Water is in the same x/z coordinate system as the renderer.
    water_shape = unary_union([Polygon(p[0], p[1:]) for p in water])
    bridges = []
    for key, span, width, tower, side in (
        ("brooklyn", 1595.5 * 0.3048, 26, 84.3, 930 * 0.3048),
        ("manhattan", 1470 * 0.3048, 36, 100, 221),
    ):
        members = [
            r for r in raw if r["name"] == key.upper() + " BRG" and not r["walk"]
        ]
        # Fit the straight crossing to equally spaced samples, rather than
        # overweighting the densely digitised curved approach ramps.
        samples = []
        for r in members:
            line = LineString(r["points"]).intersection(water_shape)
            lines = list(line.geoms) if line.geom_type == "MultiLineString" else [line]
            for piece in lines:
                if piece.geom_type == "LineString" and piece.length > 30:
                    samples.extend(
                        [
                            piece.interpolate(s).coords[0]
                            for s in np.arange(0, piece.length, 15)
                        ]
                    )
        samples = np.asarray(samples)
        centre = samples.mean(axis=0)
        _, _, vectors = np.linalg.svd(samples - centre, full_matrices=False)
        axis = vectors[0]
        if axis[1] > 0:
            axis = -axis  # increasing station points toward Manhattan
        # The river's intersection with the fitted axis defines the crossing
        # centre. Published main spans then determine estimated tower stations.
        crossing = LineString(
            [centre - axis * 2000, centre + axis * 2000]
        ).intersection(water_shape)
        pieces = (
            list(crossing.geoms)
            if crossing.geom_type == "MultiLineString"
            else [crossing]
        )
        crossing = max(
            (p for p in pieces if p.geom_type == "LineString"), key=lambda p: p.length
        )
        centre = np.asarray(crossing.interpolate(0.5, normalized=True).coords[0])
        stations = [
            float(np.dot(np.asarray(p) - centre, axis))
            for r in members
            for p in r["points"]
        ]
        ends = [min(stations), max(stations)]
        bridge = dict(
            id=key,
            name=key.title() + " Bridge",
            centre=centre.tolist(),
            axis=axis.tolist(),
            main_span=round(span, 4),
            width=width,
            tower_height=tower,
            side_span=round(side, 3),
            ends=ends,
            provenance="CSCL alignment; DOT main span; estimated tower stations, vertical profile and structural detail",
        )
        bridges.append(bridge)
    lookup = {b["id"]: b for b in bridges}
    node = lambda p, level: (round(p[0], 2), round(p[1], 2), str(level))
    candidates = defaultdict(list)
    for r in raw:
        if not r["bridge"]:
            continue
        b = lookup[r["bridge"]]
        spine = r["name"] == b["id"].upper() + " BRG" and r["levels"] != ["13", "13"]
        spine_walk = (
            r["walk"]
            and r["kind"] == "3"
            and all(int(level or 13) > 13 for level in r["levels"])
            and LineString(r["points"]).intersects(water_shape)
        )
        if not (spine or spine_walk):
            continue  # named entrance/exit ramps use their actual route length
        r["spine"] = True
        # Manhattan has separate upper carriageways, lower road and rail deck;
        # Brooklyn's central promenade is raised above its vehicle lanes.
        offset = (
            (6.2 if r["width"] < 8 and not r["walk"] else 0)
            if b["id"] == "manhattan"
            else (3.2 if r["walk"] else 0)
        )
        ys = []
        for p in r["points"]:
            s = station(b, p)
            taper = min(1, max(0, min(s - b["ends"][0], b["ends"][1] - s) / 180))
            ys.append(round(deck_height(b, s) + offset * taper, 3))
        r["heights"] = ys
        for end, level in ((0, r["levels"][0]), (-1, r["levels"][1])):
            baseline = (int(level or 13) - 13) * 1.6
            candidates[node(r["points"][end], level)].append(max(ys[end], baseline))
    heights = {
        key: 0 if key[2] == "13" else float(np.median(values))
        for key, values in candidates.items()
    }
    for r in raw:
        if "heights" not in r:
            continue
        lengths = np.r_[
            0, np.cumsum(np.linalg.norm(np.diff(r["points"], axis=0), axis=1))
        ]
        deltas = [
            heights[node(r["points"][end], r["levels"][end])] - r["heights"][end]
            for end in (0, -1)
        ]
        correction = np.interp(lengths, [0, lengths[-1]], deltas)
        r["heights"] = [
            round(max(0, y + float(d)), 3) for y, d in zip(r["heights"], correction)
        ]
    # Reuse bridge endpoint heights on connecting ramps. Grade codes distinguish
    # an overpass from the ground street at the same horizontal position.
    for r in raw:
        if "heights" not in r:
            ends = []
            for p, level in zip((r["points"][0], r["points"][-1]), r["levels"]):
                code = int(level or 13)
                assumed = (code - 13) * 1.6 if 1 <= code <= 26 else 0
                ends.append(heights.get(node(p, level), assumed))
            lengths = np.r_[
                0, np.cumsum(np.linalg.norm(np.diff(r["points"], axis=0), axis=1))
            ]
            r["heights"] = [
                round(float(y), 3) for y in np.interp(lengths, [0, lengths[-1]], ends)
            ]
        r["elevation"] = max(r["heights"])
    roads = raw  # below-grade physical carriageways remain part of the network
    from visualisation.road_mesh import prepare_road_mesh

    road_terrain = prepare_road_mesh(roads)
    # A unified ground network removes internal sidewalk stripes and seams at
    # T-junctions. Separate vertical layers remain separate at real overpasses.
    ground = [r for r in roads if not r["walk"] and max(map(abs, r["heights"])) < 0.01]
    surfaces = {}
    for key, extra in (("curb", 4.4), ("pavement", 3.8), ("asphalt", 0)):
        merged = unary_union(
            [
                LineString(r["points"]).buffer(
                    (r["width"] + extra) / 2, cap_style=2, join_style=2
                )
                for r in ground
            ]
        )
        # Snap topology together before serialising millimetre coordinates.
        # Independently rounding nearly touching rings creates invalid holes.
        merged = set_precision(merged, 0.001)
        polygons = (
            list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
        )
        surfaces[key] = [
            [
                [list(map(lambda v: round(v, 3), p)) for p in list(ring.coords)[:-1]]
                for ring in (poly.exterior, *poly.interiors)
            ]
            for poly in polygons
        ]
    junctions = defaultdict(set)
    for r in ground:
        for p in (r["points"][0], r["points"][-1]):
            junctions[(round(p[0], 1), round(p[1], 1))].add(r["name"])
    for r in roads:
        r["crosswalks"] = [
            len(junctions[(round(p[0], 1), round(p[1], 1))]) > 1
            for p in (r["points"][0], r["points"][-1])
        ]
    return roads, bridges, surfaces, road_terrain
