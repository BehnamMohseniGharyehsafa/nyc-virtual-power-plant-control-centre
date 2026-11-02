"""Validated, serialisable scenario assumptions. Power: kW; energy: kWh."""

from typing import Literal
from pydantic import BaseModel, Field


class Scenario(BaseModel):
    name: str = "DUMBO · network-aware dispatch"
    date: str = "2024-07-17"
    buildings: int = Field(16, ge=2, le=1000)
    steps: int = Field(96, ge=4, le=672)
    horizon: int = Field(96, ge=4, le=192)
    controller: Literal["baseline", "rule", "central", "network", "distributed"] = (
        "network"
    )
    market: Literal["retail", "wholesale"] = "retail"
    topology: Literal["radial", "meshed"] = "radial"
    pv_scale: float = Field(1.0, ge=0, le=4)
    battery_scale: float = Field(1.0, ge=0, le=4)
    load_scale: float = Field(1.0, gt=0, le=4)
    grid_charging: bool = True
    import_limit_kw: float = Field(15000.0, gt=0)
    export_limit_kw: float = Field(15000.0, ge=0)
    network_rating_scale: float = Field(1.0, gt=0, le=3)
    voltage_min: float = Field(0.95, ge=0.8, lt=1.02)
    voltage_max: float = Field(1.05, gt=1.02, le=1.2)
    comfort_min: float = Field(21.0, ge=16, le=23)
    comfort_max: float = Field(25.0, ge=24, le=30)
    demand_usd_kw: float = Field(0.0, ge=0, le=100)
    retail_usd_kwh: float = Field(0.22, ge=0, le=2)
    export_usd_kwh: float = Field(0.045, ge=0, le=2)
    solver_seconds: float = Field(30.0, ge=1, le=600)
    forecast: Literal["persistence", "seasonal"] = "seasonal"
    seed: int = 42
    event_start: int = Field(64, ge=0, le=671)
    event_steps: int = Field(8, ge=1, le=96)
    event_kw: float = Field(0.0, ge=-20000, le=20000)
    event_payment_usd_kwh: float = Field(0.0, ge=0, le=20)
    event_tolerance_kw: float = Field(5.0, ge=0, le=1000)
    admm_rho: float = Field(0.05, gt=0, le=20)
    admm_iterations: int = Field(100, ge=5, le=1000)
    admm_tolerance: float = Field(0.01, gt=0, le=1)
    battery_outage: bool = False
    dt_hours: float = 0.25

    def serialise(self):
        return self.model_dump() if hasattr(self, "model_dump") else self.dict()


class Finance(BaseModel):
    years: int = Field(20, ge=1, le=50)
    discount: float = Field(0.07, ge=0, le=0.3)
    escalation: float = Field(0.02, ge=-0.1, le=0.2)
    degradation: float = Field(0.005, ge=0, le=0.1)
    pv_usd_kw: float = Field(2100, ge=0)
    battery_usd_kwh: float = Field(450, ge=0)
    controls_usd_building: float = Field(1000, ge=0)
    om_fraction: float = Field(0.015, ge=0, le=0.2)
    engineering_fraction: float = Field(0.1, ge=0, le=0.5)
    replacement_year: int = Field(12, ge=1, le=50)
    replacement_fraction: float = Field(0.6, ge=0, le=2)
    residual_fraction: float = Field(0.05, ge=0, le=1)
    representative_days: float = Field(365, gt=0, le=366)
    seed: int = 42
