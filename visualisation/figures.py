"""Scientific Plotly views and publication exports."""

import io
import numpy as np
import plotly.graph_objects as go
from shapely.geometry import shape
from shapely.ops import triangulate
from data.inputs import district

COLOURS = dict(
    navy="#172b4d",
    cyan="#06a7c6",
    green="#17a477",
    violet="#8b6ce0",
    orange="#ec9b47",
    red="#dc5666",
    muted="#8c9bb1",
)


def style(fig, height=280):
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=48, r=18, t=16, b=38),
        font=dict(family="Inter, Segoe UI, sans-serif", size=11, color="#64748b"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.12, x=0, font=dict(size=10)),
        hovermode="x unified",
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(gridcolor="#edf1f6", zeroline=False),
        uirevision="vpp",
    )
    return fig


def timeline(run, columns, cursor=None, height=280, ytitle="Power (kW)"):
    fig = go.Figure()
    x = run.series.timestamp_local.str.slice(11, 16)
    for col, label, colour in columns:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=run.series[col],
                name=label,
                mode="lines",
                line=dict(color=colour, width=2),
                fill="tozeroy" if col == "pv_kw" else None,
                fillcolor="rgba(23,164,119,.08)",
            )
        )
    if cursor is not None and len(x):
        fig.add_vline(
            x=x.iloc[min(cursor, len(x) - 1)], line_color="#cad5e2", line_dash="dot"
        )
    style(fig, height)
    fig.update_yaxes(title=ytitle)
    return fig


def _mesh(geometry, height, colour):
    """Extrude observed polygon geometry. Roof triangles respect concavities/holes."""
    vertices = []
    faces = []
    polygons = (
        list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
    )
    project = lambda xy: ((xy[0] + 73.989) * 84300, (xy[1] - 40.703) * 111100)
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            coords = list(ring.coords)
            for a, b in zip(coords[:-1], coords[1:]):
                ax, ay = project(a)
                bx, by = project(b)
                start = len(vertices)
                vertices.extend(
                    [(ax, ay, 0), (bx, by, 0), (bx, by, height), (ax, ay, height)]
                )
                faces.extend(
                    [(start, start + 1, start + 2), (start, start + 2, start + 3)]
                )
        for triangle in triangulate(polygon):
            if not polygon.covers(triangle.representative_point()):
                continue
            start = len(vertices)
            vertices.extend(
                [(*project(c), height) for c in list(triangle.exterior.coords)[:3]]
            )
            faces.append((start, start + 1, start + 2))
    return vertices, faces


def district_3d(run, t=0, selected=0, layer="assets"):
    p = run.portfolio
    n = p.n
    fig = go.Figure()
    # Context is also observed NYC footprint geometry; cap geometry sent to browser.
    context = district(max(n, min(150, 1000)))
    vertices = []
    faces = []
    for f in context[n:]:
        v, fs = _mesh(shape(f["geometry"]), f["properties"]["height_m"], "#dce3ec")
        offset = len(vertices)
        vertices.extend(v)
        faces.extend([(a + offset, b + offset, c + offset) for a, b, c in fs])
    if vertices:
        vx = np.array(vertices)
        fx = np.array(faces)
        fig.add_trace(
            go.Mesh3d(
                x=vx[:, 0],
                y=vx[:, 1],
                z=vx[:, 2],
                i=fx[:, 0],
                j=fx[:, 1],
                k=fx[:, 2],
                color="#dce4ed",
                opacity=0.8,
                flatshading=True,
                hoverinfo="skip",
                lighting=dict(ambient=0.7, diffuse=0.6),
                name="Observed context buildings",
            )
        )
    render_indices = (
        list(range(n)) if n <= 100 else np.linspace(0, n - 1, 100, dtype=int).tolist()
    )
    if selected not in render_indices:
        render_indices.append(selected)
    for i in render_indices:
        f = p.features[i]
        r = f["properties"]
        v, faces = _mesh(shape(f["geometry"]), r["height_m"], "")
        v = np.array(v)
        faces = np.array(faces)
        colour = COLOURS["cyan"]
        if run.assets["charge"][t, i] + run.assets["discharge"][t, i] > 0.01:
            colour = COLOURS["violet"]
        elif run.assets["pv"][t, i] > 0.01:
            colour = COLOURS["green"]
        elif run.assets["heat"][t, i] + run.assets["cool"][t, i] > 0.01:
            colour = COLOURS["orange"]
        if layer == "voltage" and len(run.network) > t and run.network[t]["converged"]:
            voltage = run.network[t]["voltage"][run.feeder.building_buses[i]]
            colour = (
                COLOURS["red"]
                if voltage < run.config.voltage_min or voltage > run.config.voltage_max
                else COLOURS["cyan"]
            )
        elif layer == "soc":
            soc = run.assets["energy"][t, i] / max(p.battery_kwh[i], 1e-9)
            colour = f"rgb({int(190 - 90 * soc)},{int(155 - 50 * soc)},225)"
        if i == selected:
            colour = "#f0ae59"
        fig.add_trace(
            go.Mesh3d(
                x=v[:, 0],
                y=v[:, 1],
                z=v[:, 2],
                i=faces[:, 0],
                j=faces[:, 1],
                k=faces[:, 2],
                color=colour,
                opacity=0.92,
                flatshading=True,
                customdata=[i] * len(v),
                name=r["address"],
                hovertemplate=f"<b>{r['address']}</b><br>BIN {r['bin']}<br>{r['height_m']:.1f} m · {r['height_provenance']}<br>PV potential {p.pv_kw[i]:.1f} kW<extra></extra>",
                lighting=dict(ambient=0.75, diffuse=0.6, specular=0.1),
            )
        )
    # Only synthetic electrical connections are drawn; no invented street network.
    xs = []
    ys = []
    zs = []
    for _, line in run.feeder.net.line.iterrows():
        a = run.feeder.positions[int(line.from_bus)]
        b = run.feeder.positions[int(line.to_bus)]
        xs.extend([a[0], b[0], None])
        ys.extend([a[1], b[1], None])
        zs.extend([1, 1, None])
    for _, trafo in run.feeder.net.trafo.iloc[1:].iterrows():
        a = run.feeder.positions[int(trafo.hv_bus)]
        b = run.feeder.positions[int(trafo.lv_bus)]
        xs.extend([a[0], b[0], None])
        ys.extend([a[1], b[1], None])
        zs.extend([1, 1, None])
    fig.add_trace(
        go.Scatter3d(
            x=xs,
            y=ys,
            z=zs,
            mode="lines",
            line=dict(color="#42bad0", width=3),
            hoverinfo="skip",
            name="Synthetic feeder",
        )
    )
    props = [f["properties"] for f in p.features]
    fig.add_trace(
        go.Scatter3d(
            x=[(r["lon"] + 73.989) * 84300 for r in props],
            y=[(r["lat"] - 40.703) * 111100 for r in props],
            z=[r["height_m"] + 4 for r in props],
            mode="markers",
            marker=dict(size=3, color="#ffffff", line=dict(width=1, color="#08a6c0")),
            customdata=list(range(n)),
            text=[r["address"] for r in props],
            hovertemplate="%{text}<extra></extra>",
            name="Connection buses",
        )
    )
    fig.update_layout(
        height=470,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="#f4f8fb",
        showlegend=False,
        scene=dict(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            bgcolor="#f4f8fb",
            aspectmode="data",
            camera=dict(eye=dict(x=1.45, y=-1.6, z=1.05), up=dict(x=0, y=0, z=1)),
        ),
        uirevision="district-camera",
        clickmode="event+select",
    )
    return fig


def network_graph(run, t):
    fig = go.Figure()
    net = run.feeder.net
    for table, fromcol, tocol, colour in (
        (net.line, "from_bus", "to_bus", COLOURS["cyan"]),
        (net.trafo, "hv_bus", "lv_bus", COLOURS["violet"]),
    ):
        x = []
        y = []
        for _, row in table.iterrows():
            a = run.feeder.positions[int(row[fromcol])]
            b = run.feeder.positions[int(row[tocol])]
            x.extend([a[0], b[0], None])
            y.extend([a[1], b[1], None])
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines",
                line=dict(color=colour, width=1.5),
                hoverinfo="skip",
                showlegend=False,
            )
        )
    voltage = run.network[t].get("voltage", np.full(len(net.bus), np.nan))
    pos = [run.feeder.positions[i] for i in net.bus.index]
    fig.add_trace(
        go.Scatter(
            x=[a[0] for a in pos],
            y=[a[1] for a in pos],
            mode="markers",
            marker=dict(
                size=9,
                color=voltage,
                colorscale=[[0, "#ef7180"], [0.3, "#1cacc2"], [1, "#7e6dd8"]],
                cmin=0.94,
                cmax=1.06,
                colorbar=dict(title="V (pu)", thickness=10),
            ),
            text=[f"{name}<br>{v:.4f} pu" for name, v in zip(net.bus.name, voltage)],
            hovertemplate="%{text}<extra></extra>",
        )
    )
    style(fig, 370)
    fig.update_layout(
        hovermode="closest",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, scaleanchor="x"),
    )
    return fig


def voltage_plot(run, t):
    ac = run.network[t]
    fig = go.Figure()
    if ac["converged"]:
        buses = run.feeder.building_buses
        fig.add_trace(
            go.Scatter(
                x=list(range(len(buses))),
                y=np.array(ac["voltage"])[buses],
                name="AC verified",
                line=dict(color=COLOURS["cyan"]),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=list(range(len(buses))),
                y=ac["linear_voltage"],
                name="LinDistFlow",
                line=dict(color=COLOURS["violet"], dash="dot"),
            )
        )
        fig.add_hline(
            y=run.config.voltage_min, line_dash="dash", line_color=COLOURS["red"]
        )
        fig.add_hline(
            y=run.config.voltage_max, line_dash="dash", line_color=COLOURS["red"]
        )
    style(fig, 280)
    fig.update_xaxes(title="Building bus index")
    fig.update_yaxes(title="Voltage (pu)")
    return fig


def publication_figure(run, fmt="png"):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    fig = Figure(figsize=(10, 8), layout="constrained")
    axs = fig.subplots(3, 1, sharex=True)
    d = run.series
    x = np.arange(len(d)) * 0.25
    for col, label, c in (
        ("grid_kw", "Grid exchange", COLOURS["cyan"]),
        ("pv_kw", "PV", COLOURS["green"]),
        ("demand_kw", "Demand", COLOURS["navy"]),
    ):
        axs[0].plot(x, d[col], label=label, color=c)
    axs[0].set_ylabel("Active power (kW)")
    axs[0].legend(ncol=3, frameon=False)
    axs[1].plot(x, d.soc_pct, color=COLOURS["violet"])
    axs[1].set_ylabel("Portfolio SOC (%)")
    axs[2].plot(x, d.min_voltage_pu, color=COLOURS["cyan"])
    axs[2].axhline(run.config.voltage_min, color=COLOURS["red"], ls="--")
    axs[2].set_ylabel("Minimum voltage (pu)")
    axs[2].set_xlabel("Hours since simulation start")
    for ax in axs:
        ax.grid(alpha=0.15)
        ax.spines[["right", "top"]].set_visible(False)
    fig.suptitle(
        f"New York VPP · {run.config.controller} · {run.config.buildings} buildings\n{run.config.date} | synthetic feeder | {run.status}",
        fontsize=12,
    )
    output = io.BytesIO()
    fig.savefig(output, format=fmt, dpi=200)
    return output.getvalue()
