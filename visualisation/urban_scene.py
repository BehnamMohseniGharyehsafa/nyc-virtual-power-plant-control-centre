"""Detailed observed urban fabric and an explicit illustrative traffic model.

The numerical energy engine remains Python. The browser interpolates these
Python-generated traffic states and renders estimated architectural details.
"""

from functools import lru_cache
import json
import math
import numpy as np
from pyproj import Transformer
from shapely.geometry import shape, box, Point
from shapely.ops import unary_union, polygonize
from shapely import transform
from shapely.geometry.polygon import orient
from shapely.strtree import STRtree
from data.download import CACHE
from data.urban import SCENE_BOUNDS
from data.inputs import district

PROJECTION = Transformer.from_crs(4326, 32618, always_xy=True)
ORIGIN = np.array(PROJECTION.transform(-73.989, 40.703))


def xy(lon, lat):
    x, y = PROJECTION.transform(lon, lat)
    return [round(x - ORIGIN[0], 3), round(-(y - ORIGIN[1]), 3)]


def project(geom):
    return transform(
        geom,
        lambda x, y: (
            np.asarray(PROJECTION.transform(x, y)[0]) - ORIGIN[0],
            np.asarray(PROJECTION.transform(x, y)[1]) - ORIGIN[1],
        ),
        interleaved=False,
    )


def rings(poly):
    return [
        [[round(x, 3), round(-y, 3)] for x, y in list(r.coords)[:-1]]
        for r in (poly.exterior, *poly.interiors)
    ]


@lru_cache(maxsize=2)
def fabric(count=320):
    source = district(min(count, 1000))
    geometries = [
        project(shape(f["geometry"])).simplify(0.12, preserve_topology=True)
        for f in source
    ]
    tree = STRtree(geometries)
    buildings = []
    for i, (f, geom) in enumerate(zip(source, geometries)):
        p = f["properties"]
        polygons = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        parts = []
        for poly in polygons:
            poly = orient(poly, sign=1)
            exposed = []
            coords = list(poly.exterior.coords)
            for a, b in zip(coords[:-1], coords[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                length = math.hypot(dx, dy)
                test = Point(
                    (a[0] + b[0]) / 2 + dy / max(length, 0.01) * 1.5,
                    (a[1] + b[1]) / 2 - dx / max(length, 0.01) * 1.5,
                )
                party = any(
                    j != i and geometries[j].covers(test) for j in tree.query(test)
                )
                exposed.append(not party)
            parts.append(dict(rings=rings(poly), exposed=exposed))
        year = int(float(p.get("construction_year") or 0))
        style = (
            "brick"
            if 1850 < year < 1945
            else ("glass" if p["use"] == "Office" and year >= 1960 else "stone")
        )
        if p["footprint_m2"] < 300 and p["height_m"] < 25:
            style = "brownstone"
        buildings.append(
            dict(
                index=i,
                bin=p["bin"],
                address=p["address"],
                use=p["use"],
                year=year,
                height=round(p["height_m"], 2),
                floors=p["floors"],
                area=round(p["footprint_m2"], 1),
                centre=xy(p["lon"], p["lat"]),
                parts=parts,
                style=style,
            )
        )
    path = CACHE / "streets.geojson"
    if not path.exists():
        raise FileNotFoundError("Acquire real street geometry: python -m data.urban")
    road_source = json.loads(path.read_text(encoding="utf-8"))["features"]
    roads = []
    seen = set()
    for f in road_source:
        p = f["properties"]
        if p["road_type"] == "14" or p["id"] in seen:
            continue  # ferry routes are not roads
        seen.add(p["id"])
        geom = project(shape(f["geometry"]))
        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        for k, line in enumerate(lines):
            if line.distance(Point(0, 0)) > 850 or line.length < 6:
                continue
            coords = [
                [round(x, 3), round(-y, 3)] for x, y in line.simplify(0.25).coords
            ]
            name = p["name"].upper()
            bridge = p["road_type"] == "3" and (
                "BRG" in name or "BRIDGE" in name or "EXPY" in name
            )
            highway = p["road_type"] in ("2", "9")
            # Bridge/deck elevations are dressing assumptions, not measured elevations.
            elevation = (
                24
                if bridge and "MANHATTAN" in name
                else 18
                if bridge
                else 8
                if highway
                else 0
            )
            roads.append(
                dict(
                    id=p["id"] + f"-{k}",
                    name=p["name"],
                    points=coords,
                    width=p["width_m"],
                    direction=p["direction"],
                    kind=p["road_type"],
                    speed_mph=p["speed_mph"],
                    elevation=elevation,
                    walk=p["direction"] == "NV" or p["road_type"] in ("6", "7"),
                )
            )
    # Derive water/land subdivision from the actual clipped NYC shoreline.
    west, south, east, north = SCENE_BOUNDS
    bounds = project(box(west, south, east, north))
    water = []
    hydropath = CACHE / "hydrography.geojson"
    if hydropath.exists():
        for f in json.loads(hydropath.read_text())["features"]:
            geometry = project(shape(f["geometry"]))
            for poly in (
                geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]
            ):
                if poly.geom_type == "Polygon":
                    water.append(rings(poly))
    shorepath = CACHE / "shoreline.geojson"
    if shorepath.exists() and not water:
        lines = [
            project(shape(f["geometry"])).intersection(bounds)
            for f in json.loads(shorepath.read_text())["features"]
        ]
        segments = unary_union([*lines, bounds.boundary])
        pieces = list(polygonize(segments))
        centres = [g.representative_point() for g in geometries]
        for poly in pieces:
            if poly.area > 15000 and not any(poly.covers(c) for c in centres):
                water.append(rings(poly))
    return dict(
        buildings=buildings,
        roads=roads,
        water=water,
        provenance=dict(
            buildings="Observed NYC OTI footprints and source roof heights; missing heights remain flagged",
            roads="Observed NYC CSCL geometry, names, widths/directions where available",
            architecture="Estimated façade/window/cornice/roof details; not a photogrammetric reconstruction",
            traffic="Illustrative Python kinematic scenario on observed streets; not live or observed traffic",
            shoreline="Land/water subdivision derived from observed NYC planimetric shoreline; bridge heights estimated",
        ),
    )


@lru_cache(maxsize=1)
def traffic_model():
    """Quarter-second kinematic updates with directional routing, signals and headways.

    Stored states make the moving cars an executed numerical scenario rather than
    arbitrary animation. Speeds/arrivals are assumptions, independent of VPP EV load.
    """
    roads = fabric()["roads"]
    edges = []
    outgoing = {}
    node = lambda p: (round(p[0] / 3), round(p[1] / 3))
    for road in roads:
        if (
            road["walk"]
            or road["kind"] not in ("1", "10", "12", "13")
            or road["elevation"]
        ):
            continue
        points = np.array(road["points"], float)
        if np.linalg.norm(points.mean(axis=0)) > 520:
            continue
        directions = (
            [points]
            if road["direction"] == "FT"
            else [points[::-1]]
            if road["direction"] == "TF"
            else [points, points[::-1]]
        )
        for pts in directions:
            lengths = np.linalg.norm(np.diff(pts, axis=0), axis=1)
            if lengths.sum() < 12:
                continue
            edge = dict(
                points=pts,
                cumulative=np.r_[0, np.cumsum(lengths)],
                length=lengths.sum(),
                start=node(pts[0]),
                end=node(pts[-1]),
                width=road["width"],
                speed=min(9.5, road["speed_mph"] * 0.44704 * 0.68),
            )
            outgoing.setdefault(edge["start"], []).append(len(edges))
            edges.append(edge)
    if not edges:
        raise ValueError("No drivable observed streets for traffic scenario")
    rng = np.random.default_rng(1401)
    number = 64
    dt = 0.25
    frames = 960
    cars = []
    for i in range(number):
        index = int(rng.integers(len(edges)))
        edge = edges[index]
        position = float((i % 7 + 0.3) / 7.5 * edge["length"])
        cars.append(
            dict(
                edge=index,
                s=position,
                v=0.0,
                desired=float(rng.uniform(0.65, 1)),
                kind="taxi" if i % 7 == 0 else "van" if i % 11 == 0 else "car",
            )
        )
    result = np.zeros((frames, number, 3), dtype=np.float32)
    for frame in range(frames):
        occupied = {}
        for i, car in enumerate(cars):
            occupied.setdefault(car["edge"], []).append((car["s"], i))
        for lane in occupied.values():
            lane.sort()
        for i, car in enumerate(cars):
            edge = edges[car["edge"]]
            wanted = edge["speed"] * car["desired"]
            leader = next(
                (s for s, j in occupied[car["edge"]] if s > car["s"] and j != i), None
            )
            if leader is not None:
                wanted = min(wanted, max(0, (leader - car["s"] - 7) / 1.4))
            remaining = edge["length"] - car["s"]
            phase = (
                frame * dt + abs(edge["end"][0] * 7 + edge["end"][1] * 13) % 48
            ) % 48
            # Approximate alternating intersection controls; no real signal plan claimed.
            vertical = abs(edge["points"][-1, 1] - edge["points"][0, 1]) > abs(
                edge["points"][-1, 0] - edge["points"][0, 0]
            )
            green = phase < 22 if vertical else 24 <= phase < 46
            if not green and remaining < 28:
                wanted = min(wanted, max(0, (remaining - 3) / 1.5))
            car["v"] = float(np.clip(wanted, car["v"] - 3.2 * dt, car["v"] + 1.8 * dt))
            car["s"] += car["v"] * dt
            if car["s"] >= edge["length"]:
                choices = [
                    j
                    for j in outgoing.get(edge["end"], [])
                    if edges[j]["end"] != edge["start"]
                ]
                if choices:
                    car["edge"] = int(rng.choice(choices))
                    car["s"] -= edge["length"]
                else:
                    car["edge"] = int(rng.integers(len(edges)))
                    car["s"] = 0
                    car["v"] = 0
                edge = edges[car["edge"]]
            seg = min(
                np.searchsorted(edge["cumulative"], car["s"], side="right") - 1,
                len(edge["points"]) - 2,
            )
            seg = max(0, seg)
            a, b = edge["points"][seg : seg + 2]
            direction = (b - a) / max(np.linalg.norm(b - a), 0.01)
            position = a + direction * (car["s"] - edge["cumulative"][seg])
            offset = min(edge["width"] * 0.22, 2.6)
            position += np.array([direction[1], -direction[0]]) * offset
            result[frame, i] = [
                position[0],
                position[1],
                -math.atan2(direction[1], direction[0]),
            ]
    return dict(
        dt=dt,
        frames=frames,
        seed=1401,
        cars=[dict(kind=c["kind"], colour=int(i % 8)) for i, c in enumerate(cars)],
        positions=np.round(result, 3).tolist(),
        provenance="Executed illustrative Python traffic scenario; observed street geometry/direction; assumed arrivals, signal phases and speeds",
    )


def scene_config(run):
    count = min(max(run.portfolio.n, 320), 1000)
    scene = fabric(count)
    p = run.portfolio
    assets = [
        dict(
            index=i,
            bin=f["properties"]["bin"],
            centre=xy(f["properties"]["lon"], f["properties"]["lat"]),
            pv_kw=float(p.pv_kw[i]),
            battery_kwh=float(p.battery_kwh[i]),
            height=f["properties"]["height_m"],
        )
        for i, f in enumerate(p.features)
    ]
    buses = {
        int(bus): xy(pos[0] / 84300 - 73.989, pos[1] / 111100 + 40.703)
        for bus, pos in run.feeder.positions.items()
    }
    network = []
    for i, line in run.feeder.net.line.iterrows():
        network.append(
            dict(
                start=buses[int(line.from_bus)],
                end=buses[int(line.to_bus)],
                kind="line",
                index=int(i),
            )
        )
    for i, trafo in run.feeder.net.trafo.iterrows():
        building = next(
            (
                j
                for j, bus in enumerate(run.feeder.building_buses)
                if bus == trafo.lv_bus
            ),
            None,
        )
        network.append(
            dict(
                start=buses[int(trafo.hv_bus)],
                end=buses[int(trafo.lv_bus)],
                kind="transformer",
                index=int(i),
                building=building,
            )
        )
    return dict(**scene, run_id=run.id, assets=assets, network=network)


def scene_state(run, t):
    t = max(0, min(int(t), len(run.series) - 1))
    p = run.portfolio
    r = run.series.iloc[t]
    ac = run.network[t]
    import pvlib

    sun = pvlib.solarposition.get_solarposition([r.timestamp_utc], 40.703, -73.989)
    voltage = np.array(ac.get("voltage", []))
    return dict(
        step=t,
        timestamp=r.timestamp_local,
        solar_elevation=float(sun.apparent_elevation.iloc[0]),
        solar_azimuth=float(sun.azimuth.iloc[0]),
        grid_kw=float(r.grid_kw),
        pv_kw=float(r.pv_kw),
        soc_pct=float(r.soc_pct),
        violations=int(r.violations),
        assets=[
            dict(
                index=i,
                pv_kw=float(run.assets["pv"][t, i] - run.assets["curtail"][t, i]),
                battery_kw=float(
                    run.assets["discharge"][t, i] - run.assets["charge"][t, i]
                ),
                soc=float(run.assets["energy"][t, i] / max(p.battery_kwh[i], 1e-9)),
                net_kw=float(run.assets["net"][t, i]),
                voltage=float(voltage[run.feeder.building_buses[i]])
                if len(voltage)
                else None,
            )
            for i in range(p.n)
        ],
        line_kw=ac.get("line_p_kw", []),
    )
