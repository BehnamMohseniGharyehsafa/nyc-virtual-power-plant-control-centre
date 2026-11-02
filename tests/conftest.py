import pytest
import numpy as np
import pandas as pd
from core.config import Scenario
from data.inputs import district
from models.physics import make_portfolio
from models.network import build_feeder
from controllers.forecast import forecast


@pytest.fixture
def case():
    c = Scenario(buildings=4, horizon=8, steps=4)
    p = make_portfolio(district(c.buildings), c)
    feeder = build_feeder(p, c)
    origin = pd.Timestamp(c.date, tz="America/New_York").tz_convert("UTC")
    f = forecast(
        origin, pd.date_range(origin, periods=c.horizon, freq="15min"), p, c, []
    )
    state = dict(
        energy=p.battery_kwh * 0.5,
        temperature=np.full(p.n, 23.0),
        ev_energy=np.zeros(p.n),
    )
    return c, p, feeder, f, state
