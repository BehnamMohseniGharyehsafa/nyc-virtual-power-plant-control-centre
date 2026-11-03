"""Acquire the observed urban fabric used by the detailed district renderer.

Road geometry, names, widths and traffic directions: NYC OTI CSCL.
Facade/window/roof dressing and the traffic scenario remain explicitly estimated.
"""

import argparse
import io
import json
import posixpath
import re
import tarfile
from pathlib import Path

from shapely.geometry import mapping, shape

from data.download import CACHE, fetch, record

# Visual context includes BOTH East River banks and the inland bridge landings.
# This is deliberately independent of the numerical portfolio's study bounds.
SCENE_BOUNDS = (-74.012, 40.695, -73.979, 40.719)
ROOT = Path(__file__).resolve().parents[1]


def streets():
    west, south, east, north = SCENE_BOUNDS
    polygon = f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    url = "https://data.cityofnewyork.us/resource/inkn-q76z.json"
    response = fetch(
        url, {"$where": f"intersects(the_geom,'{polygon}')", "$limit": 5000}
    )
    (CACHE / "raw").mkdir(exist_ok=True)
    (CACHE / "raw" / "streets.json").write_text(response.text, encoding="utf-8")
    features = []
    for row in response.json():
        if not row.get("the_geom"):
            continue
        # Keep complete source segments: clipping through a crossing leaves a
        # suspended road ending in mid-air at an arbitrary map boundary.
        geom = shape(row["the_geom"])
        if geom.is_empty or geom.geom_type not in ("MultiLineString", "LineString"):
            continue
        source_width = float(row.get("streetwidth", 0) or 0)
        width = source_width * 0.3048 if source_width > 0 else 10.5
        features.append(
            dict(
                type="Feature",
                geometry=mapping(geom),
                properties=dict(
                    id=str(row["objectid"]),
                    physical_id=str(row.get("physicalid", "")),
                    name=row.get("full_street_name")
                    or row.get("street_name")
                    or "Unnamed segment",
                    width_m=max(5, min(width, 38)),
                    width_provenance="observed source feet"
                    if source_width > 0
                    else "assumed 10.5 m",
                    direction=row.get("trafdir", "TW"),
                    road_type=row.get("rw_type"),
                    speed_mph=float(row.get("posted_speed", 20) or 20),
                    lanes=float(row.get("number_travel_lanes", 0) or 0),
                    display_level=row.get("carto_display_level"),
                    from_level=row.get("from_level_code"),
                    to_level=row.get("to_level_code"),
                    geometry_provenance="observed NYC CSCL",
                ),
            )
        )
    if len(features) < 20:
        raise ValueError("Street query returned insufficient observed geometry")
    (CACHE / "streets.geojson").write_text(
        json.dumps(dict(type="FeatureCollection", features=features)), encoding="utf-8"
    )
    record(
        "streets",
        url,
        response.content,
        dataset="NYC OTI Citywide Street Centerline (CSCL)",
        institution="NYC Office of Technology and Innovation",
        bounds=SCENE_BOUNDS,
        count=len(features),
        units="WGS84; source width feet; converted width metres; source speed mph",
        resolution="individual street segments",
        processing="spatial selection, complete source segments retained; object IDs preserve separate carriageways; source grade codes and directions retained; width feet to metres",
        missing="unknown width explicitly assumed; no fabricated centre-line geometry",
        licence="NYC Open Data terms of use",
    )
    print(f"Observed street segments: {len(features)}", flush=True)


def context_buildings():
    """Separate, inexpensive city context; never added to the energy portfolio."""
    west, south, east, north = SCENE_BOUNDS
    url = "https://data.cityofnewyork.us/resource/5zhs-2jue.json"
    response = fetch(
        url,
        {
            "$where": f"within_box(the_geom,{north},{west},{south},{east})",
            "$limit": 5000,
            "$order": "bin",
        },
    )
    fs = []
    for row in response.json():
        if not row.get("the_geom"):
            continue
        geom = shape(row["the_geom"])
        if not geom.is_valid or geom.is_empty:
            continue
        height = float(row.get("height_roof", 0) or 0) * 0.3048
        fs.append(
            dict(
                type="Feature",
                geometry=mapping(geom),
                properties=dict(
                    bin=str(row["bin"]),
                    height_m=height if height > 2 else 12,
                    height_provenance="observed" if height > 2 else "assumed 12 m",
                ),
            )
        )
    if len(fs) < 100:
        raise ValueError("Insufficient observed bridge landing context")
    (CACHE / "context_buildings.geojson").write_text(
        json.dumps(dict(type="FeatureCollection", features=fs)), encoding="utf-8"
    )
    record(
        "context_buildings",
        url,
        response.content,
        dataset="NYC OTI Building Footprints",
        bounds=SCENE_BOUNDS,
        count=len(fs),
        processing="visual context only; observed footprints and roof heights converted feet to metres; missing heights explicitly assumed",
        licence="NYC Open Data terms of use",
    )
    print(f"Observed context buildings: {len(fs)}", flush=True)


def shoreline():
    west, south, east, north = SCENE_BOUNDS
    url = "https://data.cityofnewyork.us/resource/59xk-wagz.json"
    # The shoreline layer can be a map view; inspect its source metadata first.
    meta = fetch("https://data.cityofnewyork.us/api/views/59xk-wagz.json").json()
    source = meta.get("modifyingViewUid", "59xk-wagz")
    if not meta.get("columns"):
        series = (
            meta.get("displayFormat", {})
            .get("visualizationCanvasMetadata", {})
            .get("vifs", [])
        )
        if series:
            source = (
                series[0]
                .get("series", [{}])[0]
                .get("dataSource", {})
                .get("datasetUid", source)
            )
    url = f"https://data.cityofnewyork.us/resource/{source}.json"
    polygon = f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    response = fetch(
        url, {"$where": f"intersects(the_geom,'{polygon}')", "$limit": 2000}
    )
    fs = [
        dict(
            type="Feature",
            geometry=r["the_geom"],
            properties={k: v for k, v in r.items() if k != "the_geom"},
        )
        for r in response.json()
        if r.get("the_geom")
    ]
    if not fs:
        raise ValueError("No shoreline geometry in district")
    (CACHE / "shoreline.geojson").write_text(
        json.dumps(dict(type="FeatureCollection", features=fs)), encoding="utf-8"
    )
    record(
        "shoreline",
        url,
        response.content,
        dataset="NYC Planimetric Shoreline",
        institution="NYC OTI",
        units="WGS84 geometry",
        bounds=SCENE_BOUNDS,
        processing="spatial query; no imputed shoreline",
        missing="fail explicitly",
        licence="NYC Open Data terms of use",
    )
    print(f"Observed shoreline features: {len(fs)}", flush=True)


def vendor():
    version = "0.180.0"
    response = fetch(f"https://registry.npmjs.org/three/-/three-{version}.tgz")
    target = ROOT / "app" / "static" / "vendor"
    target.mkdir(parents=True, exist_ok=True)
    files = {
        "package/build/three.module.js": "three.module.js",
        "package/build/three.core.js": "three.core.js",
        "package/examples/jsm/controls/OrbitControls.js": "OrbitControls.js",
        "package/examples/jsm/utils/BufferGeometryUtils.js": "BufferGeometryUtils.js",
        "package/LICENSE": "THREE-LICENSE.txt",
    }
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
        for member, name in files.items():
            # Extract only explicitly selected files, never arbitrary archive paths.
            content = archive.extractfile(member).read()
            (target / name).write_bytes(content)
        # Preserve the official add-on directory structure and vendor only the
        # selected modules and their relative JS dependencies. No CDN at runtime.
        pending = [
            "postprocessing/EffectComposer.js",
            "postprocessing/RenderPass.js",
            "postprocessing/GTAOPass.js",
            "postprocessing/UnrealBloomPass.js",
            "postprocessing/OutputPass.js",
            "postprocessing/ShaderPass.js",
            "shaders/FXAAShader.js",
            "objects/Sky.js",
            "geometries/RoundedBoxGeometry.js",
        ]
        seen = set()
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            if name.startswith("../") or not name.endswith(".js"):
                raise ValueError("Unsafe Three.js add-on path")
            seen.add(name)
            content = archive.extractfile("package/examples/jsm/" + name).read()
            destination = target / "addons" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            for dependency in re.findall(rb"from\s+['\"]([^'\"]+)['\"]", content):
                specifier = dependency.decode()
                if specifier.startswith("."):
                    pending.append(
                        posixpath.normpath(
                            posixpath.join(posixpath.dirname(name), specifier)
                        )
                    )
    (target / "version.json").write_text(
        json.dumps(
            dict(
                package="three",
                version=version,
                source="https://www.npmjs.com/package/three",
                licence="MIT",
            )
        )
    )
    print("Bundled Three.js", version, flush=True)


def hydrography():
    west, south, east, north = SCENE_BOUNDS
    # Neighbouring named water bodies meet at artificial administrative edges.
    # Include them too, so the East River continues naturally into the harbour.
    west, south, east, north = west - 0.02, south - 0.02, east + 0.02, north + 0.02
    polygon = f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    url = "https://data.cityofnewyork.us/resource/pjs3-c3z5.json"
    response = fetch(
        url, {"$where": f"intersects(the_geom,'{polygon}')", "$limit": 1000}
    )
    fs = []
    for r in response.json():
        # Full water bodies keep an artificial rectangular map edge out of the
        # river when the user zooms out to see both complete crossings.
        geom = shape(r["the_geom"])
        if geom.is_empty:
            continue
        fs.append(
            dict(
                type="Feature",
                geometry=mapping(geom),
                properties={k: v for k, v in r.items() if k != "the_geom"},
            )
        )
    if not fs:
        raise ValueError("No observed hydrography returned")
    (CACHE / "hydrography.geojson").write_text(
        json.dumps(dict(type="FeatureCollection", features=fs)), encoding="utf-8"
    )
    record(
        "hydrography",
        url,
        response.content,
        dataset="NYC Planimetric Hydrography",
        institution="NYC OTI",
        units="WGS84 polygon geometry",
        bounds=SCENE_BOUNDS,
        query_bounds=(west, south, east, north),
        processing="select complete observed water bodies intersecting visual context; no rectangular river clipping",
        missing="reject absent geometry",
        licence="NYC Open Data terms of use",
    )
    print(f"Observed water polygons: {len(fs)}", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vendor-only", action="store_true")
    args = p.parse_args()
    if not args.vendor_only:
        streets()
        shoreline()
        hydrography()
        context_buildings()
    vendor()
