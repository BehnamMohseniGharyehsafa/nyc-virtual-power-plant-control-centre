"""Machine-readable quality summaries; no silent repairs."""

import numpy as np


def report(portfolio, index, weather, real_time):
    return dict(
        buildings=portfolio.n,
        unique_bins=len({f["properties"]["bin"] for f in portfolio.features}),
        missing_weather_values=int(weather.isna().sum().sum()),
        duplicate_utc_timestamps=int(index.duplicated().sum()),
        interval_seconds=np.unique(np.diff(index.asi8) / 1e9).tolist(),
        utc_start=index[0].isoformat(),
        utc_end=index[-1].isoformat(),
        temperature_min_c=float(weather.temperature_2m.min()),
        temperature_max_c=float(weather.temperature_2m.max()),
        negative_price_intervals=int((real_time < 0).sum()),
        assumed_heights=sum(
            f["properties"]["height_provenance"] == "assumed"
            for f in portfolio.features
        ),
        missing_benchmark_matches=sum(
            f["properties"]["benchmark_provenance"].startswith("unmatched")
            for f in portfolio.features
        ),
    )
