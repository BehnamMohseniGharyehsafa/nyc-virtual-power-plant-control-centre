# Detailed urban visualisation

The command centre now uses a dedicated, locally bundled Three.js renderer rather than Plotly solid extrusions. Numerical power-system models remain in Python. The renderer works offline after data acquisition and uses no paid map service, external map token or remote runtime CDN.

## Urban fabric

* Observed building footprints and source roof heights come from NYC OTI. Geometry is projected to EPSG:32618 and rendered relative to the district origin.
* Streets use NYC OTI Citywide Street Centerline (`inkn-q76z`), retaining source names, geometry, width and traffic direction. Source widths are converted from feet to metres; unknown widths are explicitly flagged assumptions. Ferry routes are excluded from road rendering.
* East River polygons use NYC Planimetric Hydrography (`pjs3-c3z5`); shoreline source (`59xk-wagz`) is separately retained.
* Building façades use reproducible brick, stone and glazing treatments, geometric window frames and mullions, cornices, pilasters and rooftop equipment. Likely party walls are identified with a spatial neighbour test and left without windows. Architectural details are **estimated dressing**, not measured window inventories or photogrammetry.
* Rooftop PV arrays reflect the hypothetical portfolio, within footprint geometry, with visual spacing and access clearances. Roof equipment, water tanks, street furniture, planting, lane markings, crossings and bridge elevations are estimates. Their presence does not assert surveyed installations.

These distinctions appear in the scene's source information and the command-centre legend. The result is a detailed real-geometry reconstruction with estimated architectural detail, not an exact photographic replica of every façade.

## Traffic

`visualisation/urban_scene.py` executes an illustrative traffic scenario in Python: 64 vehicles, seed 1401, 0.25 s timestep, 960 stored frames. Vehicles use directional street edges, assumed desired speeds, acceleration/deceleration bounds, leader headways and alternating illustrative signal phases. The browser interpolates these stored numerical states. Scenario boundary reinsertion is hidden rather than interpolated across the city.

This is not observed/live traffic and is separate from the VPP's EV-charging assets. It does not generate electrical demand or claim real traffic performance. The traffic control pauses/resumes the illustrative trajectories independently of historical energy-state playback.

## Interaction and result coupling

District, street and plan camera presets, orbit, pan, zoom, building selection, daylight/evening lighting, full-screen, traffic playback, a 10-second WebM recording control and an electrical overlay are available. The building inspector obtains PV power, battery SOC and voltage from the selected saved simulation state. The electrical overlay uses calculated branch power: flow direction follows the sign and particle speed/size responds to magnitude. Hypothetical electrical paths remain labelled synthetic.

The Dash-to-scene bridge is restricted to the same origin. A scene is retained across timestep changes; state messages update it without rebuilding all geometry. Static road/roof/furniture meshes are merged by material and windows, PV panels, trees and vehicles use instancing to reduce draw calls. Large portfolios retain individual numerical states with visual level-of-detail limits.

## Acquisition and verification

```bash
python -m data.urban
python -m pytest tests/test_urban_scene.py tests/test_ui.py
python -m app.main
```

Three.js 0.180.0 and its selected utilities are bundled from the official npm package with its MIT licence in `app/static/vendor/THREE-LICENSE.txt`. New scene data are visual inputs and are excluded from numerical weather/price/building input hashes. No numerical controller or DER balance is replaced by a visual estimate.
