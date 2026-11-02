"""Strict cached-input loading and time alignment."""

import json
import numpy as np
import pandas as pd
from data.download import CACHE, NY


def time_index(date, steps):
    start = pd.Timestamp(date, tz=NY).tz_convert("UTC")
    return pd.date_range(start, periods=steps, freq="15min")


def weather_frame(date, index):
    path = CACHE / f"weather_{date}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Run python -m data.download --date {date}. No fallback data are used."
        )
    df = pd.read_csv(path, parse_dates=["timestamp_utc"]).set_index("timestamp_utc")
    df.index = pd.to_datetime(df.index, utc=True)
    if df.index.has_duplicates or df.isna().any().any():
        raise ValueError("Invalid weather timestamps or missing observations")
    out = pd.DataFrame(index=index)
    radiation = {"shortwave_radiation", "direct_normal_irradiance", "diffuse_radiation"}
    for c in df:
        series = df[c].copy()
        if c in radiation:
            series.index = series.index - pd.Timedelta(hours=1)
            out[c] = (
                series.reindex(series.index.union(index))
                .sort_index()
                .ffill()
                .reindex(index)
            )
        else:
            out[c] = (
                series.reindex(series.index.union(index))
                .sort_index()
                .interpolate(method="time")
                .reindex(index)
            )
    if (
        out.isna().any().any()
        or index.min() < df.index.min()
        or index.max() > df.index.max() - pd.Timedelta(hours=1)
    ):
        raise ValueError(
            "Weather cache does not cover the simulation and forecast history"
        )
    if (out[list(radiation)] < 0).any().any():
        raise ValueError("Negative irradiance")
    return out


def market_frame(date, index, market="realtime"):
    path = CACHE / f"{market}_{date}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path.name}; acquire the historical day explicitly"
        )
    raw = pd.read_csv(path, parse_dates=["timestamp_utc"]).set_index("timestamp_utc")[
        "usd_mwh"
    ]
    raw.index = pd.to_datetime(raw.index, utc=True)
    raw = raw.sort_index()
    if raw.index.has_duplicates or raw.isna().any():
        raise ValueError("Invalid market observations")
    # Time-weighted settlement mapping: preserve each native interval's energy price.
    if market == "dam":
        end = raw.index[-1] + pd.Timedelta(hours=1)
    else:
        # NYISO integrated RT timestamps denote interval END, including irregular
        # dispatch intervals. Preserve their actual durations instead of assuming 5 min.
        end = raw.index[-1]
        begin = pd.Timestamp(date, tz=NY).tz_convert("UTC")
        raw.index = pd.DatetimeIndex([begin, *raw.index[:-1]])
    if index.min() < raw.index.min() or index.max() + pd.Timedelta(minutes=15) > end:
        raise ValueError("NYISO price cache does not fully cover requested intervals")
    boundaries = (
        index.union(index + pd.Timedelta(minutes=15))
        .union(raw.index)
        .union(pd.DatetimeIndex([end]))
        .sort_values()
    )
    values = raw.reindex(boundaries, method="ffill").to_numpy()
    seconds = np.diff(boundaries.asi8) / 1e9
    integral = pd.Series(np.r_[0, np.cumsum(values[:-1] * seconds)], index=boundaries)
    return pd.Series(
        (
            integral.reindex(index + pd.Timedelta(minutes=15)).to_numpy()
            - integral.reindex(index).to_numpy()
        )
        / 900,
        index=index,
        name=market + "_usd_mwh",
    )


def district(n):
    path = CACHE / "buildings.geojson"
    if not path.exists():
        raise FileNotFoundError(
            "No real building cache. Run python -m data.download first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if n > len(data["features"]):
        raise ValueError(
            f"Requested {n} buildings, cache contains {len(data['features'])}"
        )
    return data["features"][:n]


def provenance():
    return json.loads((CACHE / "provenance.json").read_text())
