"""Import explicit historical CSV or typical-year EPW without claiming simultaneity.

python -m data.weather_import path/to/NewYork.epw --date 2024-07-17 --mode tmy
EPW uses local standard time, not daylight-saving clock time. PVlib retains that
fixed offset; timestamps are converted to UTC. A TMY/calendar-price pairing is
always labelled a hybrid scenario in provenance, never a historical observation.
"""

import argparse
from pathlib import Path
import pandas as pd
import pvlib
from data.download import CACHE, record


def import_weather(path, date, mode, source_url):
    path = Path(path)
    year = pd.Timestamp(date).year
    if path.suffix.lower() == ".epw":
        df, metadata = pvlib.iotools.read_epw(
            path, coerce_year=year if mode == "tmy" else None
        )
        if not (
            abs(float(metadata["latitude"]) - 40.703) < 1
            and abs(float(metadata["longitude"]) + 73.989) < 1
        ):
            raise ValueError("Weather location is not in the New York study region")
        fields = {
            "temp_air": "temperature_2m",
            "relative_humidity": "relative_humidity_2m",
            "ghi": "shortwave_radiation",
            "dni": "direct_normal_irradiance",
            "dhi": "diffuse_radiation",
            "wind_speed": "wind_speed_10m",
            "atmospheric_pressure": "surface_pressure",
        }
        out = df[list(fields)].rename(columns=fields).copy()
        out["surface_pressure"] /= 100  # Pa → hPa
        out.index = out.index.tz_convert("UTC")
        # Cached weather convention is interval-end radiation. PVlib returns hour-start.
        out.index += pd.Timedelta(hours=1)
        out.index.name = "timestamp_utc"
    else:
        out = pd.read_csv(path, parse_dates=["timestamp_utc"]).set_index(
            "timestamp_utc"
        )
        if out.index.tz is None:
            raise ValueError("CSV timestamps need explicit UTC offsets")
        out.index = out.index.tz_convert("UTC")
    if out.isna().any().any() or out.index.has_duplicates:
        raise ValueError("Missing/duplicate weather observations")
    if (
        (
            out[
                ["shortwave_radiation", "direct_normal_irradiance", "diffuse_radiation"]
            ]
            < 0
        )
        .any()
        .any()
    ):
        raise ValueError("Negative irradiance")
    CACHE.mkdir(parents=True, exist_ok=True)
    out.to_csv(CACHE / f"weather_{date}.csv")
    record(
        f"weather_{date}",
        source_url,
        path.read_bytes(),
        institution="User-specified EPW/CSV provider",
        dataset="Typical meteorological year / hybrid price scenario"
        if mode == "tmy"
        else "Imported historical calendar weather",
        weather_mode=mode,
        units="°C, %, W/m², m/s, hPa",
        resolution="hourly interval-end irradiance",
        processing="EPW fixed standard time → UTC; TMY calendar reassignment explicitly labelled"
        if path.suffix.lower() == ".epw"
        else "strict timestamped CSV",
        missing="reject missing values, duplicates, and negative irradiance",
        licence="User must verify source redistribution rights",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--mode", choices=["historical", "tmy"], required=True)
    parser.add_argument("--source-url", required=True)
    args = parser.parse_args()
    import_weather(args.path, args.date, args.mode, args.source_url)


if __name__ == "__main__":
    main()
