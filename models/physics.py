"""Reduced-order equipment models with declared assumptions and SI-derived units."""

from dataclasses import dataclass
import numpy as np
import pandas as pd
import pvlib


@dataclass
class Portfolio:
    features: list
    area: np.ndarray
    pv_kw: np.ndarray
    battery_kwh: np.ndarray
    battery_kw: np.ndarray
    hvac_kw: np.ndarray
    conductance_kw_k: np.ndarray
    capacitance_kwh_k: np.ndarray
    ev_kw: np.ndarray
    ev_required_kwh: np.ndarray
    use: list

    @property
    def n(self):
        return len(self.features)


def make_portfolio(features, config):
    props = [f["properties"] for f in features]
    area = np.array([p["floor_area_m2"] for p in props])
    roof = np.array([p["footprint_m2"] for p in props])
    # Hypothetical installations, not records of existing DER equipment.
    pv = roof * 0.45 * 0.20 * config.pv_scale
    battery = np.clip(area * 0.018, 13.5, 800) * config.battery_scale
    if config.battery_outage:
        battery *= 0
    vehicles = np.maximum(1, np.ceil(area / 5000))
    return Portfolio(
        features,
        area,
        pv,
        battery,
        battery / 2,
        area * 0.035,
        area * 0.0008,
        area * 0.045,
        vehicles * 7.2,
        vehicles * 16,
        [p["use"] for p in props],
    )


def pv_output(index, weather, capacities, tilt=15.0, azimuth=180.0, dc_ac=1.2):
    """NREL SPA solar position, isotropic POA, Faiman module T, PVWatts DC/AC.

    Weather irradiance represents interval averages; solar geometry sampled at midpoint.
    No unobserved shading geometry is inferred. Fixed 4% balance-of-system loss.
    """
    mid = index + pd.Timedelta(minutes=7.5)
    sun = pvlib.solarposition.get_solarposition(mid, 40.703, -73.989)
    poa = pvlib.irradiance.get_total_irradiance(
        tilt,
        azimuth,
        sun.apparent_zenith.to_numpy(),
        sun.azimuth.to_numpy(),
        weather.direct_normal_irradiance.to_numpy(),
        weather.shortwave_radiation.to_numpy(),
        weather.diffuse_radiation.to_numpy(),
    )["poa_global"]
    poa = np.maximum(0, np.nan_to_num(poa))
    poa[sun.apparent_zenith.to_numpy() >= 90] = 0
    temp = pvlib.temperature.faiman(
        poa, weather.temperature_2m.to_numpy(), weather.wind_speed_10m.to_numpy()
    )
    per_kw_dc = pvlib.pvsystem.pvwatts_dc(poa, temp, 1.0, -0.0035) * 0.96
    ac = np.maximum(0, pvlib.inverter.pvwatts(per_kw_dc, 1 / dc_ac, eta_inv_nom=0.96))
    return ac[:, None] * capacities[None, :], pd.DataFrame(
        {"poa_w_m2": poa, "cell_temperature_c": temp}, index=index
    )


def base_load(index, portfolio, scale=1.0):
    """Assumed archetype schedules, no claimed subhourly metering or LL84 fit."""
    local = index.tz_convert("America/New_York")
    h = local.hour.to_numpy() + local.minute.to_numpy() / 60
    residential = (
        0.38
        + 0.25 * np.exp(-(((h - 8) / 2.2) ** 2))
        + 0.55 * np.exp(-(((h - 20) / 3) ** 2))
    )
    commercial = 0.26 + 0.74 * ((h >= 8) & (h < 19))
    weekend = np.where(local.dayofweek.to_numpy() >= 5, 0.55, 1.0)
    is_commercial = np.array(
        [
            u in ("Office", "Retail", "Warehouse", "Institutional", "Other commercial")
            for u in portfolio.use
        ]
    )
    shape = np.where(
        is_commercial[None, :], (commercial * weekend)[:, None], residential[:, None]
    )
    return shape * portfolio.area[None, :] * 0.010 * scale


def heat_pump_cop(outdoor):
    return np.clip(3.6 - 0.055 * np.abs(np.asarray(outdoor) - 18), 2.0, 4.2)


def thermal_coefficients(portfolio, dt=0.25):
    a = np.exp(-portfolio.conductance_kw_k * dt / portfolio.capacitance_kwh_k)
    b = (1 - a) / portfolio.conductance_kw_k
    return a, b


def thermal_step(indoor, outdoor, heating, cooling, internal, portfolio, dt=0.25):
    a, b = thermal_coefficients(portfolio, dt)
    cop = heat_pump_cop(outdoor)
    return a * indoor + (1 - a) * outdoor + b * (cop * (heating - cooling) + internal)


def thermostat(indoor, outdoor, internal, portfolio, target=23.0):
    a, b = thermal_coefficients(portfolio)
    passive = a * indoor + (1 - a) * outdoor + b * internal
    thermal = (target - passive) / b / heat_pump_cop(outdoor)
    return np.minimum(np.maximum(thermal, 0), portfolio.hvac_kw), np.minimum(
        np.maximum(-thermal, 0), portfolio.hvac_kw
    )


def battery_step(energy, charge, discharge, dt=0.25, efficiency=0.95):
    return (
        np.asarray(energy)
        + efficiency * np.asarray(charge) * dt
        - np.asarray(discharge) * dt / efficiency
    )


def ev_calendar(index):
    local = index.tz_convert("America/New_York")
    h = local.hour.to_numpy() + local.minute.to_numpy() / 60
    return (h >= 8) & (h < 18), h == 8, h == 18


def wind_output(speed_10m, capacity_kw, hub_height=100, density_kg_m3=1.225):
    """Optional hypothetical external resource; generic assumed power curve, not a manufacturer fit."""
    wind = (
        np.asarray(speed_10m)
        * (hub_height / 10) ** 0.14
        * (density_kg_m3 / 1.225) ** (1 / 3)
    )
    return np.where(
        (wind >= 3) & (wind < 25),
        capacity_kw * np.clip((wind**3 - 3**3) / (12**3 - 3**3), 0, 1),
        0,
    )


def hot_water_step(
    energy_kwh, electrical_kw, draw_kw, dt=0.25, loss_per_hour=0.01, efficiency=0.98
):
    """Lumped tank energy balance; standalone model, not yet coupled to dispatch."""
    return (
        np.asarray(energy_kwh) * (1 - loss_per_hour * dt)
        + (efficiency * np.asarray(electrical_kw) - np.asarray(draw_kw)) * dt
    )
