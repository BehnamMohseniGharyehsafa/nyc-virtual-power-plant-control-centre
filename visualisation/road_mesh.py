"""Road-edge topology and visible open cuts for observed below-grade roads.

Vertical metres are presentation estimates. Source grade distinctions and all
physical centre-lines are retained; terrain is cut instead of hiding the road.
"""

from collections import defaultdict

import numpy as np
from shapely import constrained_delaunay_triangles, set_precision
from shapely.geometry import LineString, MultiPoint, Point, box
from shapely.ops import substring, unary_union
from shapely.strtree import STRtree


def polygon_rings(poly):
    return [
        [[round(x, 3), round(z, 3)] for x, z in list(r.coords)[:-1]]
        for r in (poly.exterior, *poly.interiors)
    ]


def polygons(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [p for p in geometry.geoms if p.geom_type == "Polygon"]


def chain_lengths(points):
    return np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]


def prepare_road_mesh(roads):
    nodes = defaultdict(list)
    for r in roads:
        r["render_width"] = min(4, r["width"]) if r["walk"] else r["width"]
        r["end_joins"] = [None, None]
        r["junction_clearance"] = [0, 0]
        for end, other in ((0, 1), (-1, -2)):
            p = np.array(r["points"][end])
            direction = np.array(r["points"][other]) - p
            direction /= np.linalg.norm(direction)
            key = (round(p[0], 2), round(p[1], 2), r["levels"][end], r["walk"])
            nodes[key].append((r, end, direction))
    junctions = []
    for key, ports in nodes.items():
        if len(ports) == 2:
            (a, ae, av), (b, be, bv) = ports
            # A shared miter AND width make both edges meet, not just the
            # centre-lines. The digitised directions may oppose one another.
            tangent = av - bv
            if np.linalg.norm(tangent) < 0.2:
                continue
            tangent /= np.linalg.norm(tangent)
            normal = np.array([-tangent[1], tangent[0]])
            width = (a["render_width"] + b["render_width"]) / 2
            for r, end, direction in ports:
                local = direction if end == 0 else -direction
                own_normal = np.array([-local[1], local[0]])
                sign = 1 if np.dot(normal, own_normal) > 0 else -1
                factor = min(3, 1 / max(0.34, abs(np.dot(normal, own_normal))))
                r["end_joins"][0 if end == 0 else 1] = dict(
                    miter=(normal * sign * factor).tolist(), width=width
                )
        elif (
            len(ports) > 2
            and not key[3]
            and any(max(map(abs, r["heights"])) > 0.01 for r, _, _ in ports)
        ):
            # Flat, open merge areas prevent barriers from cutting across exits.
            centre = np.array(key[:2])
            cap_points, stubs = [], []
            height = ports[0][0]["heights"][ports[0][1]]
            for r, end, direction in ports:
                width = r["render_width"]
                length = chain_lengths(r["points"])[-1]
                radius = min(width * 0.8, length / 4, 12)
                r["junction_clearance"][0 if end == 0 else 1] = radius
                normal = np.array([-direction[1], direction[0]])
                cap_points.extend(
                    [centre + normal * width / 2, centre - normal * width / 2]
                )
                stubs.append(
                    LineString(
                        [centre, centre + direction * max(width * 2, radius)]
                    ).buffer(width / 2, cap_style=2)
                )
            gap = MultiPoint(cap_points).convex_hull.difference(unary_union(stubs))
            if not gap.is_empty:
                for poly in polygons(gap):
                    if poly.area > 0.005:
                        junctions.append(dict(rings=polygon_rings(poly), height=height))
    # Loft cross-sections first. Newly inserted height samples must interpolate
    # these sections: recomputing a miter centimetres from a corner folds the
    # inner edge back on itself, even though the centre-line stays continuous.
    for r in roads:
        points = np.asarray(r["points"])
        sections = []
        for i, p in enumerate(points):
            before = p - points[max(0, i - 1)]
            after = points[min(len(points) - 1, i + 1)] - p
            if np.linalg.norm(before) < 1e-8:
                before = after.copy()
            if np.linalg.norm(after) < 1e-8:
                after = before.copy()
            before /= np.linalg.norm(before)
            after /= np.linalg.norm(after)
            n0, n1 = np.array([-before[1], before[0]]), np.array([-after[1], after[0]])
            miter = n0 + n1
            miter /= max(np.linalg.norm(miter), 1e-8)
            miter *= min(3, 1 / max(0.34, np.dot(miter, n1)))
            width = r["render_width"]
            join = (
                r["end_joins"][0 if i == 0 else 1]
                if i in (0, len(points) - 1)
                else None
            )
            if join:
                miter, width = np.array(join["miter"]), join["width"]
            sections.append([*(miter * width / 2), *miter])
        r["sections"] = sections
    # Insert the actual flattening stations, rather than hoping a source vertex
    # happens to fall there. The shared endpoint heights remain unchanged.
    for r in roads:
        if not any(r["junction_clearance"]):
            continue
        line = LineString(r["points"])
        old_s = chain_lengths(r["points"])
        old_y = r["heights"]
        old_sections = np.asarray(r["sections"])
        stations = set(old_s)
        for end, radius in enumerate(r["junction_clearance"]):
            if radius:
                for d in (radius, radius * 2):
                    stations.add(d if end == 0 else line.length - d)
        stations = np.array(sorted(stations))
        ys = np.interp(stations, old_s, old_y)
        for end, radius in enumerate(r["junction_clearance"]):
            if not radius:
                continue
            distance = stations if end == 0 else line.length - stations
            blend = np.clip((distance - radius) / radius, 0, 1)
            blend = blend * blend * (3 - 2 * blend)
            ys = (
                old_y[0 if end == 0 else -1]
                + (ys - old_y[0 if end == 0 else -1]) * blend
            )
        sections = np.array(
            [np.interp(stations, old_s, old_sections[:, i]) for i in range(4)]
        ).T
        points, heights, new_sections = [], [], []
        for s, y, section in zip(stations, ys, sections):
            p = [round(v, 6) for v in line.interpolate(s).coords[0]]
            if points and np.linalg.norm(np.asarray(p) - points[-1]) < 0.001:
                heights[-1] = round(float(y), 3)
                new_sections[-1] = section.tolist()
                continue
            points.append(p)
            heights.append(round(float(y), 3))
            new_sections.append(section.tolist())
        r["points"], r["heights"] = points, heights
        r["sections"] = new_sections
        r["elevation"] = max(r["heights"])

    depressed = [r for r in roads if not r["walk"] and min(r["heights"]) < -0.05]
    cut_parts = []
    for r in depressed:
        line = LineString(r["points"])
        distances = chain_lengths(r["points"])
        intervals = []
        # Clip by height along the complete chain, not at the source's storage
        # fragments. Include the transition mouths of the open cut.
        for i, (a, b) in enumerate(zip(r["heights"][:-1], r["heights"][1:])):
            if min(a, b) >= -0.05:
                continue
            lo, hi = distances[i : i + 2]
            if max(a, b) > -0.05:
                crossing = lo + (-0.05 - a) / (b - a) * (hi - lo)
                if a < -0.05:
                    hi = crossing
                else:
                    lo = crossing
            if hi - lo > 0.001:
                if intervals and abs(intervals[-1][1] - lo) < 0.002:
                    intervals[-1][1] = hi
                else:
                    intervals.append([lo, hi])
        for lo, hi in intervals:
            cut_parts.append(
                substring(line, lo, hi).buffer(
                    r["render_width"] / 2 + 2.2, cap_style=1, join_style=2, quad_segs=4
                )
            )
    cuts = set_precision(unary_union(cut_parts), 0.001)
    cut_polys = polygons(cuts) if not cuts.is_empty else []
    terrain = box(-20000, -20000, 20000, 20000).difference(cuts)
    floors, walls = [], []
    if depressed:
        lines = [LineString(r["points"]) for r in depressed]
        tree = STRtree(lines)
        lengths = [chain_lengths(r["points"]) for r in depressed]

        def floor_height(x, z):
            p = Point(x, z)
            i = int(tree.nearest(p))
            s = lines[i].project(p)
            return round(
                min(
                    -0.2, float(np.interp(s, lengths[i], depressed[i]["heights"])) - 0.3
                ),
                3,
            )

        for poly in cut_polys:
            for ring in (poly.exterior, *poly.interiors):
                walls.append(
                    [
                        [round(x, 3), floor_height(x, z), round(z, 3)]
                        for x, z in ring.coords
                    ]
                )
            for triangle in constrained_delaunay_triangles(poly).geoms:
                coords = list(triangle.exterior.coords)[:3]
                a, b, c = np.asarray(coords)
                if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 0:
                    coords.reverse()  # up-facing in the renderer's x/z plane
                floors.extend(
                    [[round(x, 3), floor_height(x, z), round(z, 3)] for x, z in coords]
                )
    return dict(
        terrain=[polygon_rings(p) for p in polygons(terrain)],
        cutouts=[polygon_rings(p) for p in cut_polys],
        floor_vertices=floors,
        walls=walls,
        junctions=junctions,
    )
