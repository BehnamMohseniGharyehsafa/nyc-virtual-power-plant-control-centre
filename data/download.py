"""Explicit, failure-visible acquisition of public data; no synthetic fallback.

Run: python -m data.download --date 2024-07-17 --buildings 1000
"""

import argparse
import hashlib
import io
import json
import zipfile
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CACHE = Path(__file__).parent / "cache"
NY = "America/New_York"
# Downtown Brooklyn including DUMBO. WGS84 west, south, east, north.
BOUNDS = (-74.001, 40.688, -73.977, 40.709)


def canonical_bbl(value):
    try:
        return str(int(Decimal(str(value))))
    except (ValueError, TypeError, ArithmeticError):
        return ""


def fetch(url, params=None):
    session = requests.Session()
    session.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(
                total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
            )
        ),
    )
    response = session.get(url, params=params, timeout=90)
    response.raise_for_status()
    return response


def record(key, url, payload, **details):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "provenance.json"
    manifest = json.loads(path.read_text()) if path.exists() else {}
    manifest[key] = dict(
        url=url,
        institution=details.pop("institution", "NYC Open Data"),
        downloaded_utc=datetime.now(timezone.utc).isoformat(),
        sha256=hashlib.sha256(payload).hexdigest(),
        **details,
    )
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def buildings(limit=1000):
    from shapely.geometry import shape, mapping
    from shapely.ops import transform
    from pyproj import Transformer

    west, south, east, north = BOUNDS
    url = "https://data.cityofnewyork.us/resource/5zhs-2jue.json"
    response = fetch(
        url,
        {
            "$where": f"within_box(the_geom,{north},{west},{south},{east})",
            "$limit": 5000,
            "$order": "bin",
        },
    )
    raw = response.json()
    if len(raw) < 16:
        raise ValueError("NYC footprint query returned too few buildings")
    project = Transformer.from_crs(4326, 32618, always_xy=True).transform
    rows = []
    for item in raw:
        geom = shape(item["the_geom"])
        area = transform(project, geom).area
        if area < 60 or not geom.is_valid:
            continue
        c = geom.centroid
        h = float(item.get("height_roof", 0) or 0) * 0.3048
        rows.append(
            dict(
                id=str(item["bin"]),
                bin=str(item["bin"]),
                bbl=canonical_bbl(item.get("mappluto_bbl") or item.get("base_bbl")),
                geometry=mapping(geom),
                lon=c.x,
                lat=c.y,
                footprint_m2=area,
                height_m=h if h > 2 else 12.0,
                height_provenance="observed" if h > 2 else "assumed",
                construction_year=item.get("construction_year"),
                geometry_provenance="observed",
                use="Mixed residential",
                use_provenance="assumed",
                floors=max(1, round(h / 3.3)) if h > 2 else 4,
                floors_provenance="derived",
                address="BIN " + str(item["bin"]),
            )
        )
    # Keep the smallest portfolio centred on DUMBO, independent of query ordering.
    rows.sort(key=lambda r: (r["lon"] + 73.989) ** 2 + (r["lat"] - 40.703) ** 2)
    rows = rows[:limit]
    bbls = sorted({r["bbl"] for r in rows if r["bbl"].isdigit()})
    pluto_url = "https://data.cityofnewyork.us/resource/64uk-42ks.json"
    lots = {}
    rawdir = CACHE / "raw"
    rawdir.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(bbls), 80):
        selection = ",".join("'" + b + "'" for b in bbls[i : i + 80])
        key = hashlib.sha256(selection.encode()).hexdigest()[:16]
        chunk = rawdir / f"pluto_{key}.json"
        if chunk.exists():
            records = json.loads(chunk.read_text())
        else:
            response_pluto = fetch(
                pluto_url,
                {
                    "$where": f"bbl in ({selection})",
                    "$limit": 5000,
                    "$select": "bbl,address,landuse,numfloors,bldgarea,yearbuilt,numbldgs,bldgclass",
                },
            )
            records = response_pluto.json()
            chunk.write_text(json.dumps(records))
        lots.update({canonical_bbl(x["bbl"]): x for x in records})
    use_map = {
        "01": "Residential",
        "02": "Multifamily",
        "03": "Multifamily",
        "04": "Mixed use",
        "05": "Office",
        "06": "Retail",
        "07": "Warehouse",
        "08": "Institutional",
        "1": "Residential",
        "2": "Multifamily",
        "3": "Multifamily",
        "4": "Mixed use",
        "5": "Office",
        "6": "Retail",
        "7": "Warehouse",
        "8": "Institutional",
    }
    for r in rows:
        lot = lots.get(r["bbl"], {})
        if lot:
            r["address"] = lot.get("address", r["address"])
            r["use"] = use_map.get(lot.get("landuse"), "Other commercial")
            r["use_provenance"] = "derived from observed tax-lot land use"
            r["lot_building_count"] = float(lot.get("numbldgs", 1) or 1)
            r["lot_floor_area_ft2"] = float(lot.get("bldgarea", 0) or 0)
            # Tax-lot totals are never assigned to every footprint.
            r["construction_year"] = lot.get("yearbuilt") or r["construction_year"]
        r["floor_area_m2"] = r["footprint_m2"] * r["floors"]
        r["floor_area_provenance"] = (
            "derived footprint × estimated floors; not lot floor area"
        )
        r["benchmark_provenance"] = "unmatched; no LL84 calibration claimed"
    if len({r["bin"] for r in rows}) != len(rows):
        raise ValueError(
            "Duplicate building BINs require an explicit geometry-dissolve decision"
        )
    (CACHE / "buildings.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": r.pop("geometry"), "properties": r}
                    for r in rows
                ],
            }
        ),
        encoding="utf-8",
    )
    record(
        "buildings",
        url,
        response.content,
        dataset="NYC OTI Building Footprints",
        bounds=BOUNDS,
        original_map="https://data.cityofnewyork.us/d/3g6p-4u5s",
        crs="EPSG:4326; area EPSG:32618",
        units="source height feet; geometry degrees; processed height/area m/m²",
        count=len(rows),
        licence="NYC Open Data terms of use; see docs/data.md",
        missing="height: flagged 12 m assumption",
        processing="filter area >=60 m²; centroid distance ordering; roof heights ft→m",
    )
    record(
        "pluto",
        pluto_url,
        json.dumps(lots).encode(),
        dataset="NYC DCP PLUTO",
        units="feet and ft²",
        matched_lots=len(lots),
        missing="unmatched use remains assumed",
        resolution="tax lot",
        processing="exact BBL join; use classified at lot level; no one-lot/one-building assumption",
        licence="NYC Open Data terms of use",
    )
    return len(rows)


def prices(date, market="dam"):
    token = pd.Timestamp(date).strftime("%Y%m%d")
    source = "damlbmp" if market == "dam" else "realtime"
    url = f"https://mis.nyiso.com/public/csv/{source}/{token}{source}_zone.csv"
    response = requests.get(url, timeout=90)
    if response.status_code == 404:
        month = pd.Timestamp(date).strftime("%Y%m01")
        url = f"https://mis.nyiso.com/public/csv/{source}/{month}{source}_zone_csv.zip"
        response = fetch(url)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            content = archive.read(f"{token}{source}_zone.csv").decode("utf-8-sig")
    else:
        response.raise_for_status()
        content = response.text
    df = pd.read_csv(io.StringIO(content))
    df.columns = df.columns.str.strip()
    df = df[df["Name"].str.strip() == "N.Y.C."].copy()
    if df.empty or set(df["PTID"].astype(int)) != {61761}:
        raise ValueError("Zone J name/PTID verification failed")
    naive = pd.to_datetime(df["Time Stamp"])
    # RT files supply explicit EDT/EST, avoiding ambiguity at the autumn transition.
    if "Time Zone" in df:
        offsets = df["Time Zone"].str.strip().map({"EDT": "-04:00", "EST": "-05:00"})
        if offsets.isna().any():
            raise ValueError("Unknown NYISO time-zone label")
        index = pd.to_datetime(
            naive.dt.strftime("%Y-%m-%d %H:%M:%S") + offsets, utc=True
        )
    else:
        index = naive.dt.tz_localize(
            NY, ambiguous="infer", nonexistent="raise"
        ).dt.tz_convert("UTC")
    out = pd.DataFrame(
        {"timestamp_utc": index, "usd_mwh": pd.to_numeric(df["LBMP ($/MWHr)"])}
    )
    if out.timestamp_utc.duplicated().any():
        raise ValueError("Duplicate NYISO settlement timestamps")
    out.to_csv(CACHE / f"{market}_{date}.csv", index=False)
    record(
        f"{market}_{date}",
        url,
        response.content,
        institution="NYISO",
        dataset="Zone J LBMP",
        units="USD/MWh",
        resolution="hourly interval-start DA"
        if market == "dam"
        else "native irregular interval-end integrated RT",
        coverage="Zone J, N.Y.C., PTID 61761",
        licence="NYISO public market data; no software licence asserted",
        missing="fail on missing coverage",
        processing="UTC conversion using source time-zone labels; RT values apply to preceding native intervals; time-weighted settlement; no price interpolation",
    )
    return len(out)


def weather(date, days=4):
    start = pd.Timestamp(date) - pd.Timedelta(days=1)
    end = pd.Timestamp(date) + pd.Timedelta(days=days)
    url = "https://archive-api.open-meteo.com/v1/archive"
    fields = [
        "temperature_2m",
        "relative_humidity_2m",
        "shortwave_radiation",
        "direct_normal_irradiance",
        "diffuse_radiation",
        "wind_speed_10m",
        "surface_pressure",
    ]
    response = fetch(
        url,
        dict(
            latitude=40.703,
            longitude=-73.989,
            start_date=str(start.date()),
            end_date=str(end.date()),
            hourly=",".join(fields),
            timezone="UTC",
            wind_speed_unit="ms",
        ),
    )
    j = response.json()
    df = pd.DataFrame(j["hourly"]).rename(columns={"time": "timestamp_utc"})
    df["timestamp_utc"] = pd.to_datetime(df.timestamp_utc, utc=True)
    if df.isna().any().any():
        raise ValueError("Weather contains missing values")
    df.to_csv(CACHE / f"weather_{date}.csv", index=False)
    record(
        f"weather_{date}",
        response.url,
        response.content,
        institution="Open-Meteo / ECMWF",
        dataset="Historical gridded reanalysis (not a measured roof station)",
        units=j["hourly_units"],
        resolution="hourly; radiation is preceding-hour mean",
        coverage=[j["latitude"], j["longitude"]],
        licence="CC BY 4.0; attribution required",
        missing="fail; no synthetic fallback",
        processing="radiation shifted to interval start; piecewise constant 15 min preserves hourly energy; temperature interpolated",
    )
    return len(df)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2024-07-17")
    parser.add_argument("--buildings", type=int, default=1000)
    parser.add_argument("--skip-buildings", action="store_true")
    args = parser.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    if not args.skip_buildings:
        print("Buildings:", buildings(args.buildings))
    print("DA prices:", prices(args.date))
    print("RT prices:", prices(args.date, "realtime"))
    print("Weather:", weather(args.date))


if __name__ == "__main__":
    main()
