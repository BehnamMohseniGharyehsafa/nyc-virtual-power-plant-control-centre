"""Check every page is generated from an executed run and HTTP exports are usable."""

import json
import pytest
from plotly.utils import PlotlyJSONEncoder
from core.config import Scenario, Finance
from core.simulation import simulate
from app.main import (
    create_app,
    command,
    asset_page,
    network_page,
    controls_page,
    market_page,
    flexibility_page,
    economics_page,
    export_page,
)


def test_pages_render_numerical_results():
    run = simulate(Scenario(buildings=4, steps=4, horizon=8))
    pages = [
        command(run, 1, 0, "assets"),
        asset_page(run, 1, 0),
        network_page(run, 1),
        controls_page(run, 1),
        market_page(run, 1),
        flexibility_page(run, 1),
        economics_page(run, Finance()),
        export_page(run),
    ]
    for page in pages:
        rendered = json.dumps(page, cls=PlotlyJSONEncoder)
        assert len(rendered) > 300
        assert "placeholder backend" not in rendered


def test_http_layout_callbacks_and_health():
    app = create_app(auto_run=False)
    client = app.server.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json["status"] == "ok"
    assert client.get("/_dash-layout").status_code == 200
    assert client.get("/_dash-dependencies").status_code == 200
    assert client.get("/api/export/not-a-uuid").status_code == 404


def test_signed_flexibility_event_has_real_counterfactual():
    from flexibility.analysis import event_metrics

    for request in (10, -10):
        run = simulate(
            Scenario(
                buildings=4,
                steps=4,
                horizon=8,
                event_start=0,
                event_steps=2,
                event_kw=request,
            )
        )
        assert run.baseline is not None
        if len(run.series):
            result = event_metrics(run)
            actual = (
                run.baseline.series.grid_kw.to_numpy()[: len(run.series)]
                - run.series.grid_kw.to_numpy()
            )
            assert result["delivered_kw"].tolist() == pytest.approx(actual.tolist())
            assert result["requested_kwh"] == pytest.approx(request * 0.5)
