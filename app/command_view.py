"""Spatial-first command-centre layout using the detailed urban renderer."""

import pandas as pd
from dash import html

from visualisation.figures import COLOURS as C
from visualisation.figures import timeline


def command_view(run, t, asset, layer, *, panel, graph, metric, badge, page_heading):
    r = run.series.iloc[t]
    ac = run.network[t]
    verified = ac["feasible"] and not r.violations
    dispatch = timeline(
        run,
        [
            ("demand_kw", "District demand", C["navy"]),
            ("pv_kw", "Solar PV", C["green"]),
            ("grid_kw", "Grid exchange", C["cyan"]),
        ],
        t,
        240,
    )
    storage = timeline(
        run,
        [
            ("charge_kw", "Charging", C["cyan"]),
            ("discharge_kw", "Discharging", C["violet"]),
        ],
        t,
        240,
    )
    stamp = (
        pd.Timestamp(r.timestamp_utc)
        .tz_convert("America/New_York")
        .strftime("%d %b %Y · %H:%M %Z")
    )
    return [
        html.Div(
            [
                html.Div(
                    [
                        html.Div("NEW YORK / DISTRIBUTED ENERGY", className="eyebrow"),
                        html.H1("Brooklyn district twin"),
                        html.P("A living district. A calculated energy system."),
                    ]
                ),
                html.Div(
                    [
                        badge(
                            "● AC verified" if verified else "● Review constraints",
                            "green" if verified else "red",
                        ),
                        html.Span(stamp, className="spatial-stamp"),
                    ],
                    className="spatial-heading-status",
                ),
            ],
            className="spatial-heading",
        ),
        html.Section(
            [
                html.Iframe(
                    id="district-world",
                    src=f"/district?run={run.id}",
                    title="Detailed interactive Brooklyn district with observed streets and illustrative moving traffic",
                    allow="fullscreen",
                    className="district-world",
                ),
            ],
            className="world-stage",
        ),
        html.Div(
            [
                metric(
                    "PCC exchange",
                    f"{r.grid_kw:,.0f}",
                    "kW",
                    "AC power flow",
                    "cyan",
                ),
                metric(
                    "Solar generation",
                    f"{r.pv_kw:,.0f}",
                    "kW",
                    "Calculated PV output",
                    "green",
                ),
                metric(
                    "Battery SOC",
                    f"{r.soc_pct:.1f}",
                    "%",
                    f"{r.discharge_kw:.0f} kW out · {r.charge_kw:.0f} kW in",
                    "violet",
                ),
            ],
            className="urban-metrics",
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.Span(className="status-dot"),
                        html.Strong(f"{run.portfolio.n} connected buildings"),
                        html.Span(
                            "NYC geometry · estimated façade details · modelled traffic"
                        ),
                    ]
                ),
                html.Div(
                    [
                        html.Span(f"Min voltage {r.min_voltage_pu:.4f} pu"),
                        html.Span(f"Losses {r.loss_kw:.2f} kW"),
                        html.Strong(
                            f"${run.accounting.get('total_usd', 0):,.0f} / {len(run.series) * 0.25:g} h scenario"
                        ),
                    ]
                ),
            ],
            className="spatial-ledger",
        ),
        html.Div(
            [
                panel(
                    "District energy balance",
                    graph(dispatch),
                    "Executed demand, renewable generation and AC-verified grid exchange",
                ),
                panel(
                    "Storage dispatch",
                    graph(storage),
                    "Battery charging and discharging from the selected controller",
                ),
            ],
            className="two-col spatial-analysis",
        ),
    ]
