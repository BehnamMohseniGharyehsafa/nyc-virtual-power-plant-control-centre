"""Transparent forecasting. Never accepts future realised prices as input."""

import numpy as np
import pandas as pd
from data.inputs import weather_frame
from models.physics import base_load, pv_output, heat_pump_cop, ev_calendar


def retail_prices(index, config):
    h = index.tz_convert("America/New_York").hour.to_numpy()
    buy = np.full(len(index), config.retail_usd_kwh)
    buy[(h >= 16) & (h < 21)] *= 1.4
    return buy, np.minimum(buy, config.export_usd_kwh)


def forecast(origin, index, portfolio, config, past_prices):
    """Day-lag weather or persistence; tariffs and hypothetical EV schedules known.

    Seasonal meteorology is taken strictly before origin. For horizons >24 h,
    repeat the last available previous-day profile; never access future weather.
    """
    if config.forecast == "seasonal":
        history = pd.DatetimeIndex(
            [
                origin - pd.Timedelta(hours=24) + pd.Timedelta(minutes=15 * (i % 96))
                for i in range(len(index))
            ]
        )
    else:
        history = pd.DatetimeIndex([origin - pd.Timedelta(minutes=15)] * len(index))
    historical = weather_frame(config.date, history)
    w = historical.copy()
    w.index = index
    pv, _ = pv_output(index, w, portfolio.pv_kw)
    base = base_load(index, portfolio, config.load_scale)
    buy, sell = retail_prices(index, config)
    if config.market == "wholesale":
        # Only COMPLETED settlement intervals may inform a real-time decision.
        observed = np.asarray(past_prices)
        price = float(observed[-1]) if len(observed) else 50.0
        buy = np.full(len(index), price / 1000)
        sell = buy.copy()
    available, arrival, departure = ev_calendar(index)
    h = (
        index.tz_convert("America/New_York").hour.to_numpy()
        + index.tz_convert("America/New_York").minute.to_numpy() / 60
    )
    hours_left = np.maximum(0, 18 - (h + 0.25))
    floor = np.maximum(
        0,
        portfolio.ev_required_kwh[None, :]
        - 0.95 * hours_left[:, None] * portfolio.ev_kw[None, :],
    )
    floor[~available] = 0
    return dict(
        base=base,
        pv=pv,
        outdoor=w.temperature_2m.to_numpy(),
        gain=base * 0.65,
        cop=heat_pump_cop(w.temperature_2m.to_numpy()),
        buy=buy,
        sell=sell,
        ev_available=available,
        ev_arrival=arrival,
        ev_floor=floor,
        heat_mode=float(pd.Timestamp(origin).month in (11, 12, 1, 2, 3)),
        method=config.forecast,
        wholesale_cold_start_usd_mwh=50.0 if len(past_prices) == 0 else None,
    )


def errors(predicted, realised):
    e = np.asarray(predicted) - np.asarray(realised)
    return {"mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e**2)))}
