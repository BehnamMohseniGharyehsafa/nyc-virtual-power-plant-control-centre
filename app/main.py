"""Local engineering application; numerical models live outside Dash callbacks."""

import argparse
import json
import io
from pathlib import Path
import numpy as np
import pandas as pd
from dash import Dash, html, dcc, dash_table, Input, Output, State, ctx, no_update
from flask import jsonify, send_file
import plotly.graph_objects as go
from core.config import Scenario, Finance
from core.jobs import Jobs
from core.storage import export_bundle, json_safe
from models.network import ac_opf
from economics.finance import lifecycle, uncertainty
from flexibility.analysis import event_metrics, sustained_envelope
from visualisation.figures import (
    COLOURS as C,
    style,
    timeline,
    network_graph,
    voltage_plot,
)

NAV = [
    ("/", "Command centre", "01"),
    ("/assets", "DER asset explorer", "02"),
    ("/network", "Power flow laboratory", "03"),
    ("/controllers", "Control strategies", "04"),
    ("/market", "Electricity markets", "05"),
    ("/flexibility", "Flexibility dispatch", "06"),
    ("/economics", "Investment analysis", "07"),
    ("/compare", "Scenario comparison", "08"),
    ("/export", "Results & provenance", "09"),
]


def badge(text, colour="green"):
    return html.Span(text, className="badge " + colour)


def graph(fig, id=None):
    kwargs = dict(
        figure=fig,
        config=dict(
            displayModeBar="hover",
            displaylogo=False,
            modeBarButtonsToRemove=["select2d", "lasso2d"],
            toImageButtonOptions=dict(format="svg"),
        ),
        className="chart",
    )
    if id:
        kwargs["id"] = id
    return dcc.Graph(**kwargs)


def panel(title, children, subtitle=None, extra=None, className=""):
    return html.Section(
        [
            html.Div(
                [
                    html.Div([html.H3(title), html.P(subtitle) if subtitle else None]),
                    extra,
                ],
                className="panel-heading",
            ),
            html.Div(children, className="panel-body"),
        ],
        className="panel " + className,
    )


def metric(label, value, unit="", note="", colour="cyan"):
    return html.Div(
        [
            html.Div(
                [html.Span(label), html.Span("↗", className="metric-icon " + colour)],
                className="metric-label",
            ),
            html.Div([html.Strong(value), html.Span(unit)], className="metric-value"),
            html.Div(note, className="metric-note"),
        ],
        className="metric",
    )


def table(records, columns=None, page_size=12, id=None):
    frame = pd.DataFrame(records)
    if columns:
        frame = frame[columns]
    data = json_safe(frame.to_dict("records"))
    cols = [{"name": str(c).replace("_", " "), "id": c} for c in frame.columns]
    kwargs = dict(
        data=data,
        columns=cols,
        page_size=page_size,
        sort_action="native",
        filter_action="native",
        style_table={"overflowX": "auto"},
        style_header={
            "backgroundColor": "#f5f8fb",
            "color": "#64748b",
            "fontWeight": 600,
            "border": "none",
            "fontSize": 11,
            "padding": "12px",
        },
        style_cell={
            "fontFamily": "Inter, Segoe UI, sans-serif",
            "fontSize": 12,
            "textAlign": "left",
            "padding": "12px",
            "border": "none",
            "borderBottom": "1px solid #edf1f6",
            "color": "#344963",
            "maxWidth": "250px",
            "overflow": "hidden",
            "textOverflow": "ellipsis",
        },
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#fcfdfe"}
        ],
        style_filter={"backgroundColor": "#fff"},
    )
    if id:
        kwargs["id"] = id
    return dash_table.DataTable(**kwargs)


def field(label, id, value, min=None, max=None, step=None):
    return html.Label(
        [
            html.Span(label),
            dcc.Input(
                id=id,
                type="number",
                value=value,
                min=min,
                max=max,
                step=step,
                debounce=True,
            ),
        ],
        className="field",
    )


def page_heading(kicker, title, description, extra=None):
    return html.Div(
        [
            html.Div(
                [
                    html.Div(kicker, className="eyebrow"),
                    html.H1(title),
                    html.P(description),
                ]
            ),
            extra,
        ],
        className="page-heading",
    )


def command(run, t, asset, layer):
    from app.command_view import command_view

    return command_view(
        run,
        t,
        asset,
        layer,
        panel=panel,
        graph=graph,
        metric=metric,
        badge=badge,
        page_heading=page_heading,
    )


def asset_page(run, t, asset):
    p = run.portfolio
    props = p.features[asset]["properties"]
    x = run.series.timestamp_local.str.slice(11, 16)
    records = []
    for i, f in enumerate(p.features):
        r = f["properties"]
        records.append(
            dict(
                BIN=r["bin"],
                address=r["address"],
                use=r["use"],
                floor_area_m2=round(p.area[i]),
                PV_kWp=round(p.pv_kw[i], 1),
                BESS_kWh=round(p.battery_kwh[i], 1),
                bus=run.feeder.building_buses[i],
                SOC_pct=round(
                    run.assets["energy"][t, i] / max(p.battery_kwh[i], 1e-9) * 100, 1
                ),
                source="Observed geometry / assumed DER",
            )
        )
    battery = go.Figure()
    for key, label, c in (
        ("charge", "Charge", C["cyan"]),
        ("discharge", "Discharge", C["violet"]),
        ("ev", "EV charging", C["orange"]),
    ):
        battery.add_trace(
            go.Scatter(x=x, y=run.assets[key][:, asset], name=label, line=dict(color=c))
        )
    style(battery)
    battery.update_yaxes(title="Electrical power (kW)")
    temp = go.Figure(
        go.Scatter(
            x=x,
            y=run.assets["temperature"][:, asset],
            name="Indoor temperature",
            line=dict(color=C["orange"]),
        )
    )
    temp.add_hrect(
        y0=run.config.comfort_min,
        y1=run.config.comfort_max,
        fillcolor="rgba(23,164,119,.08)",
        line_width=0,
    )
    style(temp)
    temp.update_yaxes(title="Indoor temperature (°C)")
    pvfig = go.Figure(
        go.Scatter(
            x=x,
            y=run.assets["pv"][:, asset],
            name="Available AC PV",
            line=dict(color=C["green"]),
        )
    )
    style(pvfig)
    pvfig.update_yaxes(title="PV power (kW)")
    energy = go.Figure(
        go.Scatter(
            x=x,
            y=run.assets["energy"][:, asset],
            name="Stored energy",
            line=dict(color=C["violet"]),
        )
    )
    style(energy)
    energy.update_yaxes(title="Battery energy (kWh)")
    return [
        page_heading(
            "PORTFOLIO / PHYSICAL ASSETS",
            "DER asset explorer",
            "Search the portfolio and use the building selector above to inspect individual physical trajectories.",
        ),
        panel(
            "Portfolio register",
            table(records, page_size=8),
            "All installations in this study are hypothetical; building identifiers are real.",
        ),
        html.Div(
            [
                panel(props["address"] + " · conversion & charging", graph(battery)),
                panel("Thermal comfort", graph(temp)),
            ],
            className="two-col",
        ),
        html.Div(
            [
                panel(
                    "Photovoltaic generation",
                    graph(pvfig),
                    "PVWatts AC conversion with POA irradiance and Faiman temperature",
                ),
                panel(
                    "Battery energy state",
                    graph(energy),
                    "95% charge and discharge efficiency · 10–90% SOC bounds",
                ),
            ],
            className="two-col",
        ),
        panel(
            "Attribute provenance",
            table(
                [{"attribute": k, "value": str(v)} for k, v in props.items()],
                page_size=10,
            ),
        ),
    ]


def network_page(run, t):
    d = run.series.iloc[t]
    net = run.network[t]
    return [
        page_heading(
            "ENGINEERING / INDEPENDENT VERIFICATION",
            "Power flow laboratory",
            "Inspect the synthetic network, compare LinDistFlow with AC power flow, or solve a snapshot nonlinear AC OPF.",
        ),
        html.Div(
            [
                metric(
                    "Minimum voltage",
                    f"{d.min_voltage_pu:.4f}",
                    "pu",
                    "Calculated by pandapower",
                ),
                metric(
                    "Peak transformer loading",
                    f"{d.max_trafo_pct:.2f}",
                    "%",
                    "Independent AC verification",
                    "violet",
                ),
                metric(
                    "Approximation discrepancy",
                    f"{d.voltage_error_pu:.5f}",
                    "pu",
                    "Maximum |V AC − V linear|",
                    "orange",
                ),
                metric(
                    "Power conservation residual",
                    f"{net.get('balance_error_kw', np.nan):.2e}",
                    "kW",
                    "Grid − demand − losses",
                    "green",
                ),
            ],
            className="metrics four",
        ),
        html.Div(
            [
                panel(
                    "Electrical topology",
                    graph(network_graph(run, t)),
                    "69 kV / 13.8 kV / 0.4 kV · hypothetical radial or meshed connections",
                ),
                panel(
                    "Voltage verification",
                    graph(voltage_plot(run, t)),
                    "Linearised voltage estimates are independently checked with nonlinear AC power flow.",
                ),
            ],
            className="two-col",
        ),
        panel(
            "Nonlinear AC optimal power flow",
            [
                html.P(
                    "Optimises PV curtailment and inverter reactive power at the selected snapshot. Battery and thermal dispatch remain fixed to the stored schedule. Local convergence does not establish global optimality."
                ),
                html.Button(
                    "Solve snapshot AC OPF", id="solve-ac", className="button primary"
                ),
                dcc.Loading(html.Div(id="ac-result", className="diagnostic")),
            ],
        ),
        panel(
            "AC verification history",
            table(
                run.series[
                    [
                        "timestamp_local",
                        "min_voltage_pu",
                        "max_line_pct",
                        "max_trafo_pct",
                        "loss_kw",
                        "voltage_error_pu",
                        "violations",
                    ]
                ]
                .round(5)
                .to_dict("records")
            ),
            "Mandatory operating limits are checked independently; violations remain visible.",
        ),
    ]


def controls_page(run, t):
    diag = run.diagnostics
    records = [
        {
            k: r.get(k)
            for k in (
                "step",
                "status",
                "solver",
                "formulation",
                "seconds",
                "objective",
                "error",
            )
        }
        for r in diag
    ]
    convergence = []
    if t < len(diag):
        convergence = diag[t].get("admm", [])
    fig = go.Figure()
    for key, c in (("primal", C["cyan"]), ("dual", C["violet"])):
        if convergence:
            fig.add_trace(
                go.Scatter(
                    x=[r["iteration"] for r in convergence],
                    y=[r[key] for r in convergence],
                    name=key.title() + " residual",
                    line=dict(color=c),
                )
            )
    style(fig)
    fig.update_yaxes(type="log", title="Residual norm")
    fig.update_xaxes(title="ADMM iteration")
    definitions = [
        dict(
            controller="Conventional local",
            formulation="Thermostat + PV-surplus battery charging + immediate workplace EV charging",
        ),
        dict(
            controller="Rule based",
            formulation="Local control plus battery discharge at configured high retail price threshold",
        ),
        dict(
            controller="Central economic MPC",
            formulation="Receding-horizon LP/MILP with thermal, EV, battery and PCC constraints",
        ),
        dict(
            controller="Network aware MPC",
            formulation="Central MPC plus radial LinDistFlow and conservative thermal polygons; AC verification",
        ),
        dict(
            controller="Hierarchical distributed MPC",
            formulation="Sharing ADMM: local P/Q consensus, DER QPs, aggregator network/procurement projection; convex positive-price cases",
        ),
    ]
    return [
        page_heading(
            "CONTROL / OPTIMISATION",
            "Control strategy laboratory",
            "Select a controller and horizon above, execute the simulation, then compare saved runs under identical inputs.",
        ),
        html.Div(
            [
                metric(
                    "Executed steps",
                    str(len(run.series)),
                    "",
                    f"{run.config.steps} requested · {run.config.horizon} forecast horizon",
                ),
                metric(
                    "Computation time",
                    f"{run.metadata['seconds']:.2f}",
                    "s",
                    "Measured wall-clock time",
                    "violet",
                ),
                metric(
                    "Comfort deviation",
                    f"{run.series.comfort_degree_hours.sum():.3f}",
                    "°C·h",
                    "Sum across all buildings",
                    "orange",
                ),
                metric(
                    "EV unmet departure energy",
                    f"{run.series.ev_unmet_kwh.sum():.3f}",
                    "kWh",
                    "Physical service constraint",
                    "green",
                ),
            ],
            className="metrics four",
        ),
        panel("Implemented architectures", table(definitions, page_size=5)),
        html.Div(
            [
                panel(
                    "Solver execution time",
                    graph(
                        timeline(
                            run,
                            [("solver_seconds", "Solve time", C["violet"])],
                            t,
                            ytitle="Wall-clock time (s)",
                        )
                    ),
                ),
                panel(
                    "Distributed convergence",
                    graph(fig),
                    "Residuals are shown only for an executed ADMM solve."
                    if convergence
                    else "No ADMM iterations in this run. Select hierarchical distributed MPC to execute them.",
                ),
            ],
            className="two-col",
        ),
        panel("Solver diagnostics", table(records)),
        panel(
            "Forecast information set",
            [
                html.P(run.metadata["forecast_price"]),
                html.P(
                    "Weather: "
                    + run.config.forecast
                    + " from data strictly before each forecast origin. Loads and EV schedules are declared archetype assumptions."
                ),
                html.Pre(
                    json.dumps(run.metadata.get("forecast_pv_errors"), indent=2),
                    className="code-block",
                ),
            ],
        ),
    ]


def market_page(run, t):
    d = run.series
    prices = timeline(
        run,
        [
            ("da_usd_mwh", "Day ahead · observed", C["cyan"]),
            ("rt_usd_mwh", "Real time · observed", C["violet"]),
        ],
        t,
        ytitle="Wholesale LBMP (USD/MWh)",
    )
    hist = go.Figure()
    for col, label, c in (
        ("da_usd_mwh", "Day ahead", C["cyan"]),
        ("rt_usd_mwh", "Real time", C["violet"]),
    ):
        hist.add_trace(
            go.Histogram(x=d[col], name=label, opacity=0.65, marker_color=c, nbinsx=24)
        )
    style(hist)
    hist.update_layout(barmode="overlay")
    hist.update_xaxes(title="USD/MWh")
    hist.update_yaxes(title="15-minute mapped intervals")
    return [
        page_heading(
            "MARKETS / NYISO ZONE J",
            "Electricity market analysis",
            "Historical New York City wholesale prices. Retail customer billing and hypothetical market exposure remain separate accounting scenarios.",
        ),
        html.Div(
            [
                metric(
                    "Mean real-time price",
                    f"${d.rt_usd_mwh.mean():.2f}",
                    "/MWh",
                    "Duration-weighted interval mapping",
                ),
                metric(
                    "Maximum price",
                    f"${d.rt_usd_mwh.max():.2f}",
                    "/MWh",
                    "Observed, not a forecast",
                    "violet",
                ),
                metric(
                    "Negative-price intervals",
                    str(int((d.rt_usd_mwh < 0).sum())),
                    "",
                    "Within the executed period",
                    "orange",
                ),
                metric(
                    "Accounting mode",
                    run.config.market.title(),
                    "",
                    "Illustrative retail rates / hypothetical wholesale access",
                    "green",
                ),
            ],
            className="metrics four",
        ),
        panel(
            "Day-ahead and real-time LBMP",
            graph(prices),
            "NYISO N.Y.C. · PTID 61761 · source USD/MWh converted to USD/kWh only for settlement",
        ),
        html.Div(
            [
                panel("Price distribution", graph(hist)),
                panel(
                    "Billing assumptions",
                    [
                        html.P(
                            "Retail: illustrative flat supply/delivery rate with a 1.4× peak multiplier from 16:00–21:00. Export compensation is a separate assumption. No claim of a quoted Con Edison tariff."
                        ),
                        html.P(
                            "Wholesale: realised real-time LBMP settles net PCC exchange. Predictive decisions use only completed-interval price persistence. The first price forecast is a declared $50/MWh cold-start assumption."
                        ),
                        html.P(
                            "Demand charges apply once to the simulated billing window. A partial-day demand charge is not presented as an observed monthly bill."
                        ),
                        html.A(
                            "Official Con Edison rates and tariff sources ↗",
                            href="https://www.coned.com/en/rates-tariffs/rates",
                            target="_blank",
                        ),
                    ],
                ),
            ],
            className="two-col",
        ),
        panel(
            "Energy transaction ledger",
            table(
                d[
                    [
                        "timestamp_local",
                        "grid_kw",
                        "buy_usd_kwh",
                        "export_usd_kwh",
                        "energy_cost_usd",
                    ]
                ]
                .round(4)
                .to_dict("records")
            ),
        ),
    ]


def flexibility_page(run, t):
    result = event_metrics(run)
    intro = page_heading(
        "FLEXIBILITY / COUNTERFACTUAL VERIFICATION",
        "Flexibility dispatch centre",
        "Configure a signed reduction request in scenario settings and run the model. Positive flexibility means reduced grid import against conventional local control.",
    )
    envelope = panel(
        "Sustained flexibility at the selected state",
        [
            html.P(
                "Solve upward and downward constant-power envelopes over the configured event duration, with terminal SOC, EV service, comfort, network constraints and recovery inside the prediction horizon. Every candidate schedule receives an independent AC check."
            ),
            html.Button(
                "Calculate sustained flexibility",
                id="solve-envelope",
                className="button primary",
            ),
            dcc.Loading(html.Div(id="envelope-result", className="diagnostic")),
        ],
        "Forecast-conditional capability; this is not an offered or delivered service.",
    )
    if result is None:
        return [
            intro,
            envelope,
            panel(
                "Create a dispatch event",
                [
                    html.Div("↯", className="empty-icon"),
                    html.H2("Quantify a response, then verify it."),
                    html.P(
                        "Open Scenario settings above. Set a nonzero event request in kW, start step and duration. The model will execute an identical-input baseline, solve the event schedule and check delivered response against AC and comfort constraints."
                    ),
                    html.P(
                        "Requests beyond physical capability are rejected through optimisation infeasibility. Payments are hypothetical and require every event interval to pass the configured tolerance."
                    ),
                    html.P(
                        "Battery SOC, thermal dynamics, EV departures and recovery are included in the predictive horizon. No sustained capability is inferred from a single-step power rating."
                    ),
                ],
                className="empty-panel",
            ),
        ]
    fig = go.Figure()
    x = run.series.timestamp_local.str.slice(11, 16)
    for key, label, c in (
        ("requested_kw", "Requested reduction", C["orange"]),
        ("delivered_kw", "Delivered against baseline", C["cyan"]),
    ):
        fig.add_trace(
            go.Scatter(x=x, y=result[key], name=label, line=dict(color=c, width=2))
        )
    style(fig, 330)
    fig.update_yaxes(title="Import reduction (kW)")
    return [
        intro,
        html.Div(
            [
                metric(
                    "Delivered flexibility",
                    f"{result['delivered_kwh']:.1f}",
                    "kWh",
                    "Against identical-input local-control baseline",
                ),
                metric(
                    "Tracking error",
                    f"{result['rmse_kw'] or 0:.2f}",
                    "kW RMSE",
                    "Requested versus delivered",
                    "orange",
                ),
                metric(
                    "Recovery energy",
                    f"{result['recovery_kwh']:.2f}",
                    "kWh",
                    "Four-hour post-event window",
                    "violet",
                ),
                metric(
                    "Verification",
                    "Accepted" if result["verified"] else "Rejected",
                    "",
                    "All event intervals must pass",
                    "green" if result["verified"] else "red",
                ),
            ],
            className="metrics four",
        ),
        envelope,
        panel(
            "Requested and delivered flexibility",
            graph(fig),
            "Delivered response uses calculated AC PCC power. Positive = import reduction; negative = import increase.",
        ),
        panel(
            "Hypothetical settlement",
            [
                html.P(result["settlement"]),
                html.Strong(
                    f"Eligible payment: ${result['hypothetical_payment_usd']:.2f}"
                ),
                html.P(
                    "Payment is reported separately and is not added again to avoided energy costs. No real programme eligibility is assumed."
                ),
            ],
        ),
    ]


def economics_page(run, assumptions):
    # Financial extrapolation is explicit; no annual benefit is fabricated from installed size.
    if run.status != "completed":
        return [
            page_heading(
                "ECONOMICS / FEASIBILITY REQUIRED",
                "Investment analysis",
                "A complete physically feasible simulation is required before calculating investment benefits.",
            ),
            panel("Run status", html.P(run.status)),
        ]
    baseline = getattr(run, "investment_baseline", None) or run.baseline
    if baseline is None:
        return [
            page_heading(
                "ECONOMICS / LIFECYCLE CASH FLOW",
                "Investment analysis",
                "A financial model needs a counterfactual. Execute a baseline under the same inputs to calculate an operating benefit.",
            ),
            panel(
                "Establish the reference case",
                [
                    html.H2("Run an identical-input baseline"),
                    html.P(
                        "Use ‘Run baseline’ in the toolbar. Once a matching local-control run is stored, this page derives savings from the two executed simulations. Installed PV and batteries are shared by that reference; this comparison values control, not the full DER investment."
                    ),
                    html.P(
                        "A full project NPV requires a separately executed no-DER counterfactual and representative annual inputs. The tool will label short-period extrapolation as a scenario."
                    ),
                ],
            ),
        ]
    no_der = (
        baseline.config.pv_scale == 0 and baseline.config.battery_scale == 0
        if hasattr(baseline, "config")
        else False
    )
    daily = baseline.accounting["total_usd"] - run.accounting["total_usd"]
    hours = len(run.series) * 0.25
    annual = daily * 24 / max(hours, 1) * assumptions.representative_days
    p = run.portfolio
    finance = lifecycle(annual, p.pv_kw.sum(), p.battery_kwh.sum(), p.n, assumptions)
    cash = finance["cashflows"]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=cash.year,
            y=cash.cashflow_usd,
            name="Net cash flow",
            marker_color=C["cyan"],
        )
    )
    fig.add_trace(
        go.Scatter(
            x=cash.year,
            y=cash.cumulative_discounted_usd,
            name="Cumulative discounted",
            line=dict(color=C["violet"]),
        )
    )
    style(fig, 330)
    fig.update_yaxes(title="Cash flow (USD)")
    fig.update_xaxes(title="Project year")
    mc = uncertainty(annual, p.pv_kw.sum(), p.battery_kwh.sum(), p.n, assumptions)
    hist = go.Figure(
        go.Histogram(
            x=mc.npv_usd, name="Scenario samples", nbinsx=25, marker_color=C["violet"]
        )
    )
    style(hist)
    hist.update_xaxes(title="NPV (USD)")
    hist.update_yaxes(title="Samples")
    sens = []
    for discount in (0.03, 0.05, 0.07, 0.09, 0.11):
        a = Finance(
            **{
                **(
                    assumptions.model_dump()
                    if hasattr(assumptions, "model_dump")
                    else assumptions.dict()
                ),
                "discount": discount,
            }
        )
        sens.append(
            {
                "discount_rate_pct": discount * 100,
                "npv_usd": round(
                    lifecycle(annual, p.pv_kw.sum(), p.battery_kwh.sum(), p.n, a)[
                        "npv_usd"
                    ],
                    2,
                ),
            }
        )
    irr = "Undefined" if finance["irr"] is None else f"{100 * finance['irr']:.1f}%"
    payback = (
        "Not achieved"
        if finance["discounted_payback_years"] is None
        else f"{finance['discounted_payback_years']:.1f} y"
    )
    return [
        page_heading(
            "ECONOMICS / ASSUMPTION-DRIVEN SCENARIOS",
            "Investment analysis",
            "All results recalculate from the executed operating comparison and the financial assumptions above.",
        ),
        html.Div(
            [
                metric(
                    "Net present value",
                    f"${finance['npv_usd']:,.0f}",
                    "",
                    f"{assumptions.years}-year horizon · {assumptions.discount:.0%} discount",
                ),
                metric(
                    "Internal rate of return",
                    irr,
                    "",
                    "Multiple sign changes may yield ambiguous IRR",
                    "violet",
                ),
                metric(
                    "Discounted payback",
                    payback,
                    "",
                    "Cumulative discounted cash flows",
                    "orange",
                ),
                metric(
                    "Extrapolated annual benefit",
                    f"${annual:,.0f}",
                    "/yr",
                    f"{hours:g}-hour case × {assumptions.representative_days:g} representative days",
                    "green",
                ),
            ],
            className="metrics four",
        ),
        html.Div(
            "SCENARIO BASIS · This extrapolates a short operating comparison, not an observed annual saving. "
            + (
                "The counterfactual has no PV or BESS and uses conventional local control. Existing building/HVAC/EV equipment is outside incremental CAPEX."
                if no_der
                else "The baseline has the same DER installations; this case compares full CAPEX with control-only benefits. Run a no-DER reference in Scenario settings for an incremental investment comparison."
            ),
            className="notice",
        ),
        panel(
            "Lifecycle cash flows",
            graph(fig),
            "Nominal USD cash flows and nominal discount rate; explicit O&M, degradation, escalation, replacement and residual value",
        ),
        html.Div(
            [
                panel(
                    "Monte Carlo scenario distribution",
                    graph(hist),
                    f"300 reproducible samples · seed {assumptions.seed} · assumed distributions, not confidence intervals",
                ),
                panel("Discount-rate sensitivity", table(sens, page_size=5)),
            ],
            className="two-col",
        ),
        panel(
            "Capital expenditure assumptions",
            table(
                [
                    {"component": k, "usd": round(v, 2)}
                    for k, v in finance["capex_breakdown"].items()
                ]
            ),
        ),
        panel("Cash-flow audit", table(cash.round(2).to_dict("records"))),
    ]


def compare_page(run, jobs):
    candidates = jobs.repository.list()[:12]
    rows = []
    fig = go.Figure()

    def signature(c):
        return {
            k: v
            for k, v in c.serialise().items()
            if k not in ("name", "controller", "event_kw", "event_payment_usd_kwh")
        }

    for item in candidates:
        other = jobs.result(item["id"])
        if other.series.empty:
            continue
        identical = signature(other.config) == signature(
            run.config
        ) and other.metadata.get("input_hashes") == run.metadata.get("input_hashes")
        rows.append(
            dict(
                run_id=other.id[:8],
                controller=other.config.controller,
                buildings=other.config.buildings,
                identical_inputs=identical,
                status=other.status,
                cost_usd=round(other.accounting.get("total_usd", np.nan), 2),
                peak_kw=round(other.series.grid_kw.max(), 2),
                comfort_degree_hours=round(other.series.comfort_degree_hours.sum(), 3),
                violations=int(other.series.violations.sum()),
                seconds=round(other.metadata["seconds"], 2),
            )
        )
        if identical:
            fig.add_trace(
                go.Scatter(
                    x=other.series.timestamp_local.str.slice(11, 16),
                    y=other.series.grid_kw,
                    name=other.config.controller + " · " + other.id[:6],
                )
            )
    style(fig, 350)
    fig.update_yaxes(title="AC PCC exchange (kW)")
    return [
        page_heading(
            "EXPERIMENTS / REPRODUCIBLE COMPARISONS",
            "Scenario comparison",
            "Saved runs retain the configuration, controller, input provenance, solver diagnostics and measured execution time.",
        ),
        panel(
            "Identical-input dispatch comparison",
            graph(fig),
            "Only runs with matching physical, market, forecast and solver settings appear in the chart.",
        ),
        panel(
            "Run registry",
            table(rows),
            "Compare numerical results and feasibility together; a low-cost infeasible run is not a successful control policy.",
        ),
    ]


def export_page(run):
    return [
        page_heading(
            "RESEARCH / AUDIT TRAIL",
            "Scientific results & export",
            "Download calculated states, electrical verification, source metadata and publication figures in a reproducible result bundle.",
        ),
        panel(
            "Reproducibility bundle",
            [
                html.H2(run.id),
                html.P(
                    f"Status: {run.status} · {len(run.series)} executed steps · {run.metadata['seconds']:.2f} seconds"
                ),
                html.A(
                    "↓ Download complete results (.zip)",
                    href=f"/api/export/{run.id}",
                    className="button primary",
                    target="_blank",
                ),
                html.P(
                    "Includes CSV and Parquet time series, all DER states, building GeoJSON, AC bus/branch/transformer results, constraint logs, solver diagnostics, scenario JSON and PNG/SVG figures.",
                    className="muted",
                ),
            ],
        ),
        panel(
            "Data sources and processing",
            table(
                [
                    {
                        "source": k,
                        **{
                            x: str(v.get(x, ""))
                            for x in (
                                "institution",
                                "dataset",
                                "downloaded_utc",
                                "units",
                                "processing",
                                "missing",
                                "licence",
                            )
                        },
                    }
                    for k, v in run.metadata["provenance"].items()
                ],
                page_size=8,
            ),
        ),
        panel(
            "Run configuration",
            html.Pre(
                json.dumps(run.config.serialise(), indent=2), className="code-block"
            ),
        ),
        panel(
            "Computational environment",
            html.Pre(
                json.dumps(
                    {
                        k: run.metadata[k]
                        for k in (
                            "python",
                            "packages",
                            "forecast",
                            "forecast_price",
                            "topology",
                            "demand",
                        )
                    },
                    indent=2,
                ),
                className="code-block",
            ),
        ),
    ]


def create_app(auto_run=True):
    jobs = Jobs()
    app = Dash(
        __name__,
        title="New York VPP · Control centre",
        suppress_callback_exceptions=True,
        assets_folder=str(Path(__file__).parent / "assets"),
        update_title=None,
    )
    saved = jobs.repository.list()
    initial = next(
        (
            r["id"]
            for r in saved
            if r["controller"] == "network"
            and r["buildings"] == 16
            and r["status"] == "completed"
        ),
        saved[0]["id"] if saved else None,
    )
    job = jobs.submit(Scenario()) if auto_run and not initial else None
    app.layout = html.Div(
        [
            dcc.Location(id="url"),
            dcc.Store(id="job-id", data=job),
            dcc.Store(id="run-id", data=initial),
            dcc.Store(id="city-state"),
            dcc.Interval(id="job-poll", interval=1200),
            dcc.Interval(id="play-tick", interval=1000, disabled=True),
            html.Aside(
                [
                    html.Div(
                        [
                            html.Img(src="/assets/mark.svg"),
                            html.Div(
                                [
                                    html.Strong("NEW YORK"),
                                    html.Span("VIRTUAL POWER PLANT"),
                                ]
                            ),
                        ],
                        className="brand",
                    ),
                    html.Div(
                        [html.Span("RESEARCH PLATFORM"), badge("v0.1", "grey")],
                        className="sidebar-caption",
                    ),
                    html.Nav(
                        [
                            dcc.Link(
                                [
                                    html.Span(num, className="nav-number"),
                                    html.Span(label),
                                ],
                                href=path,
                                id="nav-" + num,
                                className="nav-link"
                                + (" active" if path == "/" else ""),
                            )
                            for path, label, num in NAV
                        ]
                    ),
                    html.Div(
                        [
                            html.Div("STUDY DISTRICT", className="eyebrow"),
                            html.Strong("Brooklyn, New York"),
                            html.P("40.703° N · 73.989° W"),
                            html.Div(
                                [
                                    html.Span(className="status-dot"),
                                    " Local research environment",
                                ],
                                className="local-status",
                            ),
                            html.P(
                                "Observed geometry\nSynthetic electrical network",
                                className="sidebar-footnote",
                            ),
                        ],
                        className="sidebar-bottom",
                    ),
                ],
                className="sidebar",
            ),
            html.Main(
                [
                    html.Header(
                        [
                            html.Div(
                                [
                                    html.Span("⌘", className="header-symbol"),
                                    html.Strong("VPP Control Centre"),
                                    html.Span("/", className="muted"),
                                    html.Span(
                                        "Brooklyn research district", className="muted"
                                    ),
                                ],
                                className="header-title",
                            ),
                            html.Div(
                                [
                                    html.Strong(
                                        "Developer: Behnam Mohseni Gharyehsafa"
                                    ),
                                    html.Span("PhD in Electronic Engineering"),
                                    html.A(
                                        "Mohseni.Gharyehsafa.Behnam@gmail.com",
                                        href="mailto:Mohseni.Gharyehsafa.Behnam@gmail.com",
                                    ),
                                ],
                                id="developer-credit",
                                className="developer-credit",
                            ),
                            html.Div(
                                [
                                    badge("RESEARCH ENVIRONMENT", "blue"),
                                    html.Span("NY", className="avatar"),
                                ],
                                className="header-right",
                            ),
                        ],
                        className="topbar",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Span(
                                                "SIMULATION WORKSPACE",
                                                className="eyebrow",
                                            ),
                                            html.Div(
                                                id="job-message",
                                                children="Ready",
                                                className="job-message",
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        [
                                            html.Button(
                                                "Run baseline",
                                                id="run-baseline",
                                                className="button secondary",
                                            ),
                                            html.Button(
                                                "▶ Run simulation",
                                                id="run",
                                                className="button primary",
                                            ),
                                            html.Button(
                                                "Cancel",
                                                id="cancel",
                                                className="button ghost",
                                            ),
                                        ],
                                        className="toolbar-buttons",
                                    ),
                                ],
                                className="simulation-toolbar",
                            ),
                            html.Div(
                                html.Div(id="job-progress", style={"width": "0%"}),
                                className="progress-track",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        [
                                            html.Span("PORTFOLIO"),
                                            dcc.Dropdown(
                                                id="scale",
                                                options=[
                                                    {
                                                        "label": "A · Community / 16 buildings",
                                                        "value": 16,
                                                    },
                                                    {
                                                        "label": "B · District / 64 buildings",
                                                        "value": 64,
                                                    },
                                                    {
                                                        "label": "C · Aggregation / 500 buildings",
                                                        "value": 500,
                                                    },
                                                    {
                                                        "label": "C+ · 1,000 buildings",
                                                        "value": 1000,
                                                    },
                                                ],
                                                value=16,
                                                clearable=False,
                                            ),
                                        ],
                                        className="control wide",
                                    ),
                                    html.Label(
                                        [
                                            html.Span("CONTROL ARCHITECTURE"),
                                            dcc.Dropdown(
                                                id="controller",
                                                options=[
                                                    {"label": label, "value": v}
                                                    for v, label in [
                                                        (
                                                            "network",
                                                            "Network aware MPC",
                                                        ),
                                                        (
                                                            "central",
                                                            "Central economic MPC",
                                                        ),
                                                        (
                                                            "distributed",
                                                            "Hierarchical distributed MPC",
                                                        ),
                                                        ("rule", "Rule based VPP"),
                                                        (
                                                            "baseline",
                                                            "Conventional local control",
                                                        ),
                                                    ]
                                                ],
                                                value="network",
                                                clearable=False,
                                            ),
                                        ],
                                        className="control wide",
                                    ),
                                    html.Label(
                                        [
                                            html.Span("BUILDING TO INSPECT"),
                                            dcc.Dropdown(
                                                id="asset",
                                                options=[
                                                    {"label": "Building 1", "value": 0}
                                                ],
                                                value=0,
                                                clearable=False,
                                            ),
                                        ],
                                        className="control wide",
                                    ),
                                    html.Label(
                                        [
                                            html.Span("MAP OVERLAY"),
                                            dcc.Dropdown(
                                                id="layer",
                                                options=[
                                                    {
                                                        "label": "Resource dispatch",
                                                        "value": "assets",
                                                    },
                                                    {
                                                        "label": "Voltage compliance",
                                                        "value": "voltage",
                                                    },
                                                    {
                                                        "label": "Battery SOC",
                                                        "value": "soc",
                                                    },
                                                ],
                                                value="assets",
                                                clearable=False,
                                            ),
                                        ],
                                        className="control",
                                    ),
                                ],
                                className="controls-row",
                            ),
                            html.Details(
                                [
                                    html.Summary(
                                        "Scenario settings & financial assumptions"
                                    ),
                                    html.Div(
                                        [
                                            html.Label(
                                                [
                                                    html.Span(
                                                        "Historical date (YYYY-MM-DD)"
                                                    ),
                                                    dcc.Input(
                                                        id="date",
                                                        type="text",
                                                        value="2024-07-17",
                                                        debounce=True,
                                                    ),
                                                ],
                                                className="field",
                                            ),
                                            field(
                                                "Executed steps (15 min)",
                                                "steps",
                                                96,
                                                4,
                                                672,
                                                4,
                                            ),
                                            field(
                                                "Prediction horizon (steps)",
                                                "horizon",
                                                96,
                                                4,
                                                192,
                                                4,
                                            ),
                                            field(
                                                "PV capacity multiplier",
                                                "pv-scale",
                                                1,
                                                0,
                                                4,
                                                0.1,
                                            ),
                                            field(
                                                "Battery size multiplier",
                                                "battery-scale",
                                                1,
                                                0,
                                                4,
                                                0.1,
                                            ),
                                            field(
                                                "Load multiplier",
                                                "load-scale",
                                                1,
                                                0.1,
                                                4,
                                                0.1,
                                            ),
                                            field(
                                                "Import limit (kW)",
                                                "import-limit",
                                                15000,
                                                1,
                                                100000,
                                                100,
                                            ),
                                            field(
                                                "Export limit (kW)",
                                                "export-limit",
                                                15000,
                                                0,
                                                100000,
                                                100,
                                            ),
                                            field(
                                                "Network rating multiplier",
                                                "rating",
                                                1,
                                                0.1,
                                                3,
                                                0.1,
                                            ),
                                            field(
                                                "Minimum voltage (pu)",
                                                "voltage-min",
                                                0.95,
                                                0.8,
                                                1.01,
                                                0.005,
                                            ),
                                            field(
                                                "Maximum voltage (pu)",
                                                "voltage-max",
                                                1.05,
                                                1.025,
                                                1.2,
                                                0.005,
                                            ),
                                            field(
                                                "Retail base (USD/kWh)",
                                                "retail",
                                                0.22,
                                                0,
                                                2,
                                                0.01,
                                            ),
                                            field(
                                                "Export (USD/kWh)",
                                                "export-rate",
                                                0.045,
                                                0,
                                                2,
                                                0.005,
                                            ),
                                            field(
                                                "Window demand charge (USD/kW)",
                                                "demand-rate",
                                                0,
                                                0,
                                                100,
                                                1,
                                            ),
                                            html.Label(
                                                [
                                                    html.Span("Accounting scenario"),
                                                    dcc.Dropdown(
                                                        id="market",
                                                        options=[
                                                            {
                                                                "label": "Illustrative retail customer",
                                                                "value": "retail",
                                                            },
                                                            {
                                                                "label": "Hypothetical wholesale exposure",
                                                                "value": "wholesale",
                                                            },
                                                        ],
                                                        value="retail",
                                                        clearable=False,
                                                    ),
                                                ],
                                                className="field",
                                            ),
                                            html.Label(
                                                [
                                                    html.Span("Network topology"),
                                                    dcc.Dropdown(
                                                        id="topology",
                                                        options=[
                                                            {
                                                                "label": "Radial · MPC + AC",
                                                                "value": "radial",
                                                            },
                                                            {
                                                                "label": "Meshed · local control + AC OPF",
                                                                "value": "meshed",
                                                            },
                                                        ],
                                                        value="radial",
                                                        clearable=False,
                                                    ),
                                                ],
                                                className="field",
                                            ),
                                            field(
                                                "Comfort lower bound (°C)",
                                                "comfort-min",
                                                21,
                                                16,
                                                23,
                                                0.5,
                                            ),
                                            field(
                                                "Comfort upper bound (°C)",
                                                "comfort-max",
                                                25,
                                                24,
                                                30,
                                                0.5,
                                            ),
                                            field(
                                                "Event start step",
                                                "event-start",
                                                64,
                                                0,
                                                671,
                                                1,
                                            ),
                                            field(
                                                "Event duration (steps)",
                                                "event-steps",
                                                8,
                                                1,
                                                96,
                                                1,
                                            ),
                                            field(
                                                "Event request (kW; + reduction)",
                                                "event-kw",
                                                0,
                                                -20000,
                                                20000,
                                                10,
                                            ),
                                            field(
                                                "Event payment (USD/kWh)",
                                                "event-payment",
                                                0,
                                                0,
                                                20,
                                                0.1,
                                            ),
                                            field(
                                                "ADMM penalty ρ",
                                                "rho",
                                                0.05,
                                                0.001,
                                                20,
                                                0.01,
                                            ),
                                            field(
                                                "ADMM max iterations",
                                                "admm-iterations",
                                                100,
                                                5,
                                                1000,
                                                5,
                                            ),
                                            dcc.Checklist(
                                                id="battery-outage",
                                                options=[
                                                    {
                                                        "label": "Battery unavailable",
                                                        "value": "outage",
                                                    }
                                                ],
                                                value=[],
                                            ),
                                            dcc.Checklist(
                                                id="grid-charging",
                                                options=[
                                                    {
                                                        "label": "Permit grid charging",
                                                        "value": "yes",
                                                    }
                                                ],
                                                value=["yes"],
                                            ),
                                            field(
                                                "Financial horizon (years)",
                                                "fin-years",
                                                20,
                                                1,
                                                50,
                                                1,
                                            ),
                                            field(
                                                "Discount rate (%)",
                                                "fin-discount",
                                                7,
                                                0,
                                                30,
                                                0.5,
                                            ),
                                            field(
                                                "PV CAPEX (USD/kW)",
                                                "fin-pv",
                                                2100,
                                                0,
                                                10000,
                                                100,
                                            ),
                                            field(
                                                "Battery CAPEX (USD/kWh)",
                                                "fin-battery",
                                                450,
                                                0,
                                                3000,
                                                25,
                                            ),
                                            field(
                                                "Representative days / year",
                                                "fin-days",
                                                365,
                                                1,
                                                366,
                                                1,
                                            ),
                                            field(
                                                "Annual escalation (%)",
                                                "fin-escalation",
                                                2,
                                                -10,
                                                20,
                                                0.5,
                                            ),
                                            field(
                                                "Annual degradation (%)",
                                                "fin-degradation",
                                                0.5,
                                                0,
                                                10,
                                                0.1,
                                            ),
                                            field(
                                                "O&M (% CAPEX/year)",
                                                "fin-om",
                                                1.5,
                                                0,
                                                20,
                                                0.1,
                                            ),
                                            html.Label(
                                                [
                                                    html.Span("Load saved run"),
                                                    dcc.Dropdown(
                                                        id="saved-run",
                                                        options=[
                                                            {
                                                                "label": r["controller"]
                                                                + " · "
                                                                + r["id"][:8],
                                                                "value": r["id"],
                                                            }
                                                            for r in saved
                                                        ],
                                                        placeholder="Select a run",
                                                    ),
                                                ],
                                                className="field",
                                            ),
                                            html.Button(
                                                "Run no-DER investment reference",
                                                id="run-no-der",
                                                className="button secondary",
                                            ),
                                        ],
                                        className="settings-grid",
                                    ),
                                ],
                                className="settings",
                            ),
                            html.Div(id="action-message", className="action-message"),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Button(
                                                "▶",
                                                id="play",
                                                className="play-button",
                                                title="Play / pause stored results",
                                            ),
                                            html.Div(
                                                [
                                                    html.Strong("Simulation playback"),
                                                    html.Span(
                                                        id="playback-time",
                                                        children="Historical states · New York time",
                                                    ),
                                                ]
                                            ),
                                        ],
                                        className="playback-label",
                                    ),
                                    dcc.Slider(
                                        id="timeline",
                                        min=0,
                                        max=95,
                                        step=1,
                                        value=48,
                                        marks={
                                            0: "00:00",
                                            24: "06:00",
                                            48: "12:00",
                                            72: "18:00",
                                            95: "23:45",
                                        },
                                        tooltip={
                                            "placement": "bottom",
                                            "always_visible": False,
                                        },
                                    ),
                                    dcc.Dropdown(
                                        id="speed",
                                        options=[
                                            {"label": f"{i}×", "value": i}
                                            for i in (1, 2, 4, 8)
                                        ],
                                        value=1,
                                        clearable=False,
                                    ),
                                ],
                                className="playback",
                            ),
                            dcc.Loading(
                                html.Div(id="page-content"),
                                type="circle",
                                delay_show=500,
                            ),
                            html.Footer(
                                [
                                    html.Span(
                                        "NEW YORK VIRTUAL POWER PLANT CONTROL CENTRE"
                                    ),
                                    html.Span(
                                        "Open engineering · Reproducible experiments · v0.1"
                                    ),
                                ]
                            ),
                        ],
                        className="workspace",
                    ),
                ],
                className="main",
            ),
        ],
        className="shell",
    )

    controls = [
        ("scale", "buildings"),
        ("date", "date"),
        ("controller", "controller"),
        ("steps", "steps"),
        ("horizon", "horizon"),
        ("pv-scale", "pv_scale"),
        ("battery-scale", "battery_scale"),
        ("load-scale", "load_scale"),
        ("import-limit", "import_limit_kw"),
        ("export-limit", "export_limit_kw"),
        ("rating", "network_rating_scale"),
        ("voltage-min", "voltage_min"),
        ("voltage-max", "voltage_max"),
        ("retail", "retail_usd_kwh"),
        ("export-rate", "export_usd_kwh"),
        ("demand-rate", "demand_usd_kw"),
        ("market", "market"),
        ("topology", "topology"),
        ("comfort-min", "comfort_min"),
        ("comfort-max", "comfort_max"),
        ("event-start", "event_start"),
        ("event-steps", "event_steps"),
        ("event-kw", "event_kw"),
        ("event-payment", "event_payment_usd_kwh"),
        ("rho", "admm_rho"),
        ("admm-iterations", "admm_iterations"),
    ]

    @app.callback(
        Output("job-id", "data"),
        Output("action-message", "children"),
        Input("run", "n_clicks"),
        Input("run-baseline", "n_clicks"),
        Input("run-no-der", "n_clicks"),
        [State(k, "value") for k, _ in controls],
        State("battery-outage", "value"),
        State("grid-charging", "value"),
        prevent_initial_call=True,
    )
    def start(_run, _baseline, _noder, *values):
        try:
            args = {name: value for (_, name), value in zip(controls, values)}
            args.update(
                battery_outage="outage" in values[-2], grid_charging="yes" in values[-1]
            )
            if ctx.triggered_id == "run-baseline":
                args.update(controller="baseline", event_kw=0)
            if ctx.triggered_id == "run-no-der":
                args.update(
                    controller="baseline", event_kw=0, pv_scale=0, battery_scale=0
                )
            config = Scenario(**args)
            return jobs.submit(
                config
            ), "Simulation queued. Completed results remain available during execution."
        except Exception as exc:
            return no_update, str(exc)

    @app.callback(
        Output("action-message", "children", allow_duplicate=True),
        Input("cancel", "n_clicks"),
        State("job-id", "data"),
        prevent_initial_call=True,
    )
    def cancel(_, job):
        if job:
            jobs.cancel(job)
        return "Cancellation requested; the current solver call may finish before the worker stops."

    @app.callback(
        Output("run-id", "data"),
        Output("job-message", "children"),
        Output("job-progress", "style"),
        Input("job-poll", "n_intervals"),
        Input("job-id", "data"),
        State("run-id", "data"),
    )
    def poll(_, job_id, current):
        j = jobs.get(job_id) if job_id else None
        if j is None:
            return (
                no_update,
                "Ready · cached results" if current else "Ready",
                {"width": "0%"},
            )
        new = (
            j["run_id"]
            if j["status"] == "done" and current != j["run_id"]
            else no_update
        )
        return (
            new,
            j["message"],
            {
                "width": f"{100 * j['progress']:.1f}%",
                "backgroundColor": C["red"] if j["status"] == "failed" else C["cyan"],
            },
        )

    @app.callback(
        Output("run-id", "data", allow_duplicate=True),
        Input("saved-run", "value"),
        prevent_initial_call=True,
    )
    def load_saved(identifier):
        return identifier or no_update

    @app.callback(
        Output("asset", "options"),
        Output("asset", "value"),
        Output("timeline", "max"),
        Output("timeline", "marks"),
        Output("saved-run", "options"),
        Input("run-id", "data"),
    )
    def run_controls(identifier):
        if not identifier:
            return (
                [{"label": "Waiting for calculated results", "value": 0}],
                0,
                95,
                {0: "00:00", 48: "12:00", 95: "23:45"},
                [],
            )
        r = jobs.result(identifier)
        last = max(len(r.series) - 1, 0)
        opts = [
            {
                "label": f["properties"]["address"] + " · " + f["properties"]["bin"],
                "value": i,
            }
            for i, f in enumerate(r.portfolio.features)
        ]
        marks = (
            {
                i: r.series.timestamp_local.iloc[i][11:16]
                for i in sorted(set([0, last // 4, last // 2, 3 * last // 4, last]))
            }
            if len(r.series)
            else {0: "No states"}
        )
        return (
            opts,
            0,
            last,
            marks,
            [
                {
                    "label": x["controller"]
                    + " · "
                    + x["id"][:8]
                    + " · "
                    + x["status"],
                    "value": x["id"],
                }
                for x in jobs.repository.list()
            ],
        )

    @app.callback(
        Output("play-tick", "disabled"),
        Output("play", "children"),
        Input("play", "n_clicks"),
        State("play-tick", "disabled"),
        prevent_initial_call=True,
    )
    def play(_, disabled):
        return not disabled, "❚❚" if disabled else "▶"

    @app.callback(
        Output("timeline", "value"),
        Input("play-tick", "n_intervals"),
        State("timeline", "value"),
        State("timeline", "max"),
        prevent_initial_call=True,
    )
    def tick(_, value, last):
        return value + 1 if value < last else 0

    @app.callback(Output("play-tick", "interval"), Input("speed", "value"))
    def speed(value):
        return int(1000 / value)

    @app.callback(
        [Output("nav-" + n, "className") for _, _, n in NAV], Input("url", "pathname")
    )
    def active_nav(path):
        return ["nav-link" + (" active" if p == path else "") for p, _, _ in NAV]

    finids = [
        "fin-years",
        "fin-discount",
        "fin-pv",
        "fin-battery",
        "fin-days",
        "fin-escalation",
        "fin-degradation",
        "fin-om",
    ]

    @app.callback(
        Output("page-content", "children"),
        Output("playback-time", "children"),
        Input("url", "pathname"),
        Input("run-id", "data"),
        Input("timeline", "value"),
        Input("asset", "value"),
        Input("layer", "value"),
        [Input(k, "value") for k in finids],
    )
    def render(path, identifier, t, asset, layer, *fin):
        if not identifier:
            return [
                page_heading(
                    "INITIALISING / NUMERICAL MODELS",
                    "Preparing your district" if auto_run else "Choose a scenario",
                    "The first simulation is running in the background. Results will appear as soon as the full run has been calculated."
                    if auto_run
                    else "Select a portfolio and controller, then run the simulation to calculate physical trajectories.",
                ),
                panel(
                    "Real geography. Real calculations.",
                    [
                        html.H2("Brooklyn, connected."),
                        html.P(
                            "Loading NYC building footprints and executing physical DER models, multi-period optimisation and independent AC power flow. Follow progress above."
                        ),
                    ],
                ),
            ], "Waiting for executed states"
        try:
            run = jobs.result(identifier)
            if run.series.empty:
                return [
                    page_heading(
                        "SIMULATION / " + run.status.upper(),
                        "No control actions executed",
                        f"Run status: {run.status}. Inspect the recorded diagnostics below.",
                    ),
                    panel(
                        "Execution diagnostics",
                        html.Pre(
                            json.dumps(run.diagnostics, indent=2),
                            className="code-block",
                        ),
                    ),
                ], "No completed states"
            t = min(max(int(t or 0), 0), len(run.series) - 1)
            asset = min(max(int(asset or 0), 0), run.portfolio.n - 1)
            # Attach a matching stored baseline for genuine operating comparisons.
            if run.baseline is None:
                for item in jobs.repository.list():
                    if item["controller"] != "baseline":
                        continue
                    other = jobs.result(item["id"])
                    a = run.config.serialise()
                    b = other.config.serialise()
                    exclude = (
                        "name",
                        "controller",
                        "event_kw",
                        "event_payment_usd_kwh",
                    )
                    if (
                        all(a[k] == b[k] for k in a if k not in exclude)
                        and len(other.series) == len(run.series)
                        and other.metadata.get("input_hashes")
                        == run.metadata.get("input_hashes")
                    ):
                        run.baseline = other
                        break
            for item in jobs.repository.list():
                if item["controller"] != "baseline":
                    continue
                other = jobs.result(item["id"])
                if other.config.pv_scale != 0 or other.config.battery_scale != 0:
                    continue
                a = run.config.serialise()
                b = other.config.serialise()
                exclude = (
                    "name",
                    "controller",
                    "event_kw",
                    "event_payment_usd_kwh",
                    "pv_scale",
                    "battery_scale",
                )
                if (
                    all(a[k] == b[k] for k in a if k not in exclude)
                    and len(other.series) == len(run.series)
                    and other.metadata.get("input_hashes")
                    == run.metadata.get("input_hashes")
                ):
                    run.investment_baseline = other
                    break
            if path == "/assets":
                content = asset_page(run, t, asset)
            elif path == "/network":
                content = network_page(run, t)
            elif path == "/controllers":
                content = controls_page(run, t)
            elif path == "/market":
                content = market_page(run, t)
            elif path == "/flexibility":
                content = flexibility_page(run, t)
            elif path == "/economics":
                f = Finance(
                    years=int(fin[0]),
                    discount=fin[1] / 100,
                    pv_usd_kw=fin[2],
                    battery_usd_kwh=fin[3],
                    representative_days=fin[4],
                    escalation=fin[5] / 100,
                    degradation=fin[6] / 100,
                    om_fraction=fin[7] / 100,
                )
                content = economics_page(run, f)
            elif path == "/compare":
                content = compare_page(run, jobs)
            elif path == "/export":
                content = export_page(run)
            else:
                content = command(run, t, asset, layer)
            if run.status != "completed":
                content.insert(
                    1,
                    html.Div(
                        f"RUN STATUS: {run.status}. {len(run.series)} completed timesteps. Review diagnostics and constraint logs.",
                        className="notice",
                    ),
                )
            return content, run.series.timestamp_local.iloc[t][:16].replace(
                "T", " · "
            ) + " New York"
        except Exception as exc:
            return [
                panel(
                    "Input or result error",
                    [
                        html.H2(type(exc).__name__),
                        html.Pre(str(exc), className="code-block"),
                    ],
                )
            ], "Unavailable"

    @app.callback(
        Output("ac-result", "children"),
        Input("solve-ac", "n_clicks"),
        State("run-id", "data"),
        State("timeline", "value"),
        prevent_initial_call=True,
    )
    def solve_ac(_, identifier, t):
        run = jobs.result(identifier)
        t = min(int(t), len(run.series) - 1)
        base = run.assets["net"][t] + run.assets["pv"][t] - run.assets["curtail"][t]
        result = ac_opf(
            run.feeder,
            base,
            0.25
            * (
                run.assets["base"][t]
                + run.assets["heat"][t]
                + run.assets["cool"][t]
                + run.assets["ev"][t]
            ),
            run.assets["pv"][t],
            run.config,
            run.series.buy_usd_kwh.iloc[t],
        )
        (jobs.repository.root / run.id / f"ac_opf_{t}.json").write_text(
            json.dumps(json_safe(result), indent=2)
        )
        return html.Pre(json.dumps(json_safe(result), indent=2), className="code-block")

    @app.server.get("/api/health")
    def health():
        return jsonify(status="ok", engine="Python / CVXPY / HiGHS / pandapower")

    @app.callback(
        Output("envelope-result", "children"),
        Input("solve-envelope", "n_clicks"),
        State("run-id", "data"),
        State("timeline", "value"),
        prevent_initial_call=True,
    )
    def solve_envelope(_, identifier, t):
        from controllers.forecast import forecast
        from core.simulation import forecast_reference

        r = jobs.result(identifier)
        t = min(int(t), len(r.series) - 1)
        p = r.portfolio
        origin = r.series.timestamp_utc.iloc[t]
        state = dict(
            energy=r.assets["energy"][t - 1].copy() if t else p.battery_kwh * 0.5,
            temperature=r.assets["temperature"][t - 1].copy()
            if t
            else np.full(p.n, 23.0),
            ev_energy=r.assets["ev_energy"][t - 1].copy() if t else np.zeros(p.n),
        )
        ix = pd.date_range(origin, periods=r.config.horizon, freq="15min")
        f = forecast(origin, ix, p, r.config, r.series.rt_usd_mwh.iloc[:t].to_numpy())
        try:
            result = sustained_envelope(
                p,
                r.config,
                r.feeder,
                f,
                state,
                forecast_reference(f, p, state),
                duration=r.config.event_steps,
            )
            return html.Pre(
                json.dumps(json_safe(result), indent=2), className="code-block"
            )
        except Exception as exc:
            return html.Pre(str(exc), className="code-block")

    @app.server.get("/api/runs")
    def runs_api():
        return jsonify(jobs.repository.list())

    @app.server.get("/api/jobs/<identifier>")
    def job_api(identifier):
        return jsonify(jobs.get(identifier) or {"error": "Unknown job"})

    @app.server.get("/api/export/<identifier>")
    def export_api(identifier):
        try:
            run = jobs.result(identifier)
        except (FileNotFoundError, ValueError):
            return jsonify(error="Unknown run"), 404
        return send_file(
            io.BytesIO(export_bundle(run)),
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"nyc-vpp-{run.id[:8]}.zip",
        )

    from dash import ClientsideFunction
    from app.city_api import register_city

    register_city(app, jobs)
    app.clientside_callback(
        ClientsideFunction(namespace="vppCity", function_name="sync"),
        Output("city-state", "data"),
        Input("run-id", "data"),
        Input("timeline", "value"),
        Input("asset", "value"),
        Input("layer", "value"),
    )
    workspace = app.layout.children[-1].children[-1]
    selectors = next(
        c for c in workspace.children if getattr(c, "className", None) == "controls-row"
    )
    settings = next(
        c for c in workspace.children if getattr(c, "className", None) == "settings"
    )
    configuration = html.Details(
        [
            html.Summary(
                [
                    html.Span("⚙", className="configuration-icon"),
                    "Scenario configuration",
                    html.Span(
                        "Portfolio · controller · financial assumptions",
                        className="configuration-caption",
                    ),
                ]
            ),
            selectors,
            settings,
        ],
        className="configuration-drawer",
    )
    workspace.children = [
        configuration if c is selectors else c
        for c in workspace.children
        if c is not settings
    ]
    sidebar = app.layout.children[-2]
    for path, label, number in NAV:
        for component in sidebar.children:
            if isinstance(component, html.Nav):
                for link in component.children:
                    if link.id == "nav-" + number:
                        link.title = label
                        setattr(link, "aria-label", label)
    app.vpp_jobs = jobs
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-auto-run", action="store_true")
    args = parser.parse_args()
    create_app(not args.no_auto_run).run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
