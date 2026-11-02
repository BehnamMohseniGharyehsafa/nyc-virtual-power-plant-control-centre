"""USD scenario cash flows. Assumptions are illustrative, not tariff quotations."""

import numpy as np
import numpy_financial as npf
import pandas as pd


def operating_cost(
    grid_kw,
    buy_usd_kwh,
    export_usd_kwh,
    charge_kw,
    discharge_kw,
    dt=0.25,
    demand_usd_kw=0.0,
    service_revenue=0.0,
):
    grid = np.asarray(grid_kw)
    imp, exp = np.maximum(grid, 0), np.maximum(-grid, 0)
    energy = float(np.sum(imp * np.asarray(buy_usd_kwh)) * dt)
    export = float(np.sum(exp * np.asarray(export_usd_kwh)) * dt)
    degradation = float(
        0.025 * dt * np.sum(np.asarray(charge_kw) + np.asarray(discharge_kw))
    )
    demand = float(imp.max(initial=0) * demand_usd_kw)
    return dict(
        import_energy_usd=energy,
        export_credit_usd=export,
        demand_usd=demand,
        battery_wear_usd=degradation,
        service_revenue_usd=float(service_revenue),
        total_usd=energy - export + demand + degradation - service_revenue,
    )


def lifecycle(annual_operating_savings, pv_kw, battery_kwh, buildings, assumptions):
    f = assumptions
    parts = dict(
        pv=pv_kw * f.pv_usd_kw,
        battery=battery_kwh * f.battery_usd_kwh,
        controls=buildings * f.controls_usd_building,
    )
    parts["engineering_installation"] = sum(parts.values()) * f.engineering_fraction
    capex = sum(parts.values())
    years = np.arange(f.years + 1)
    cash = np.zeros(f.years + 1)
    cash[0] = -capex
    om = capex * f.om_fraction
    benefits = np.zeros_like(cash)
    maintenance = np.zeros_like(cash)
    replacements = np.zeros_like(cash)
    for y in years[1:]:
        benefits[y] = annual_operating_savings * (
            (1 + f.escalation) * (1 - f.degradation)
        ) ** (y - 1)
        maintenance[y] = om * (1 + f.escalation) ** (y - 1)
        replacements[y] = (
            parts["battery"] * f.replacement_fraction if y == f.replacement_year else 0
        )
        cash[y] = benefits[y] - maintenance[y] - replacements[y]
    cash[-1] += capex * f.residual_fraction
    discounted = cash / (1 + f.discount) ** years
    cumulative = np.cumsum(discounted)
    payback = None
    for y in years[1:]:
        if cumulative[y] >= 0 and cumulative[y - 1] < 0:
            payback = float(y - 1 - cumulative[y - 1] / discounted[y])
            break
    irr = float(npf.irr(cash))
    mirr = float(npf.mirr(cash, f.discount, f.discount))
    return dict(
        npv_usd=float(discounted.sum()),
        irr=irr if np.isfinite(irr) else None,
        mirr=mirr if np.isfinite(mirr) else None,
        discounted_payback_years=payback,
        capex_usd=capex,
        capex_breakdown=parts,
        annual_savings_usd=annual_operating_savings,
        cashflows=pd.DataFrame(
            dict(
                year=years,
                benefit_usd=benefits,
                om_usd=maintenance,
                replacement_usd=replacements,
                cashflow_usd=cash,
                discounted_usd=discounted,
                cumulative_discounted_usd=cumulative,
            )
        ),
    )


def uncertainty(
    annual_savings, pv_kw, battery_kwh, buildings, assumptions, samples=300
):
    rng = np.random.default_rng(assumptions.seed)
    # Declared scenario distributions, not statistically estimated confidence intervals.
    multipliers = rng.lognormal(-0.5 * 0.2**2, 0.2, samples)
    capex = rng.triangular(0.8, 1, 1.3, samples)
    discount = rng.uniform(
        max(0, assumptions.discount - 0.02), assumptions.discount + 0.02, samples
    )
    records = []
    for i in range(samples):
        d = (
            assumptions.model_dump()
            if hasattr(assumptions, "model_dump")
            else assumptions.dict()
        )
        d.update(
            pv_usd_kw=assumptions.pv_usd_kw * capex[i],
            battery_usd_kwh=assumptions.battery_usd_kwh * capex[i],
            discount=float(discount[i]),
        )
        f = type(assumptions)(**d)
        result = lifecycle(
            annual_savings * multipliers[i], pv_kw, battery_kwh, buildings, f
        )
        records.append(
            dict(
                npv_usd=result["npv_usd"],
                savings_multiplier=multipliers[i],
                capex_multiplier=capex[i],
                discount=discount[i],
            )
        )
    return pd.DataFrame(records)
