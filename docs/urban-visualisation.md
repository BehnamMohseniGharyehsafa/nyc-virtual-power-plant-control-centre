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

## Rendering and presentation upgrade

The lighting, shader, camera and quality workflow adapts the MIT-licensed [Open 3D Skills](https://github.com/Moh4696/open-3d-skills), specifically `threejs-scene` and the `site-check` verification approach. The implementation is adapted to this district and the pinned Three.js **0.180.0**; the source starter's older Three.js version is not substituted. Attribution is retained in `app/static/city/OPEN-3D-SKILLS-LICENSE.txt`.

* A physical sky and sky-derived PMREM reflections are refreshed together with sunlight, atmospheric haze and exposure. Simulation lighting uses the saved state's solar position. Daylight, golden hour, blue hour and night are explicitly presentation overrides; they do not alter PV or other numerical results.
* A half-float post-processing pipeline uses multisampling and an output colour transform. High quality adds half-resolution GTAO contact shading in close views; evening lighting adds restrained bloom. FXAA is the fallback on devices without multisampling. Glass, window dressing, sky, water and electrical lines are excluded from the AO depth pass.
* Camera-fitted sunlight shadows snap in the light's plane to reduce shimmer. Static shadow maps are refreshed for camera/light changes, rather than redundantly for each colour and normal pass. Animated cars use lightweight estimated contact shadows.
* Procedural 512-pixel masonry colour and mortar bump maps, tiled pavement, window blinds and stable room-by-room evening illumination add surface depth. Doors, handles, awnings, projecting sills, clustered foliage with matching wind/depth shaders, rounded car bodywork and estimated warm street-lamp pools improve street views. Lamp pools are lightweight visual overlays, not calculated illuminance. These are estimated architectural dressing.
* Repeated windows use instanced planes, with projecting sill geometry limited to nearby tiles. Building envelopes are batched by spatial tile and material while original geometry remains available for picking. Material textures are shared and shader compilation stays behind the loader.
* Camera changes follow eased elevated paths; users can interrupt a flight. Portrait screens adapt their field of view. Reduced-motion preferences stop automatic traffic and remove camera-flight transitions. When traffic is paused, the camera has settled and no overlay/transition is active, idle rendering stops.

Open **Look** for lighting and quality controls. `Automatic` starts at Balanced and lowers expensive effects after sustained slow frame-time samples. It restores Balanced after sustained spare frame-time capacity, with a cooldown to avoid frequent switches. Resize and compilation warmup samples are excluded. It keeps at least one drawing pixel per CSS pixel rather than making the entire district blurry. `High`, `Balanced` and `Eco` are explicit choices. Automatic quality never changes during a recording. The historical simulation timeline and traffic controls remain independent. Keys **1**, **2**, **3** select district, street and plan; **Escape** closes presentation settings.

### Clear district views

The exposed walls carry floor/bay coordinates matching the estimated close-up windows. A shader integrates periodic window coverage across each pixel using screen-space derivatives, so distant rows average smoothly instead of turning into a flickering checkerboard. Party walls and courtyard holes keep their existing exposure rules. This filtered treatment remains on the original envelopes, adding no façade draw calls. Projecting frames, glass and sills render only within 160 metres, in spatial tiles; masonry bump relief also fades with distance. Original envelopes remain available for building picking.

High uses four multisamples where supported; Balanced and Eco retain two. Devices without multisample support use FXAA. Lower daytime haze, quieter glazing variation and varied roof tones separate building forms and streets. High-quality contact shading is limited to close camera views. Sky reflections refresh once at the end of a lighting transition to avoid repeatedly interrupting the transition with environment-map generation.

The camera near plane and explicit depth bias on map layers prevent nearly coplanar water, pavement and road markings from producing stripes at grazing angles. Distant rooftop panels retain their existing cell texture, placement and tilt on two-triangle surfaces; nearby views retain their thickness.

The energy cards sit below an uninterrupted district canvas. The building inspector opens when requested or when a building is selected. Zoom-in, zoom-out and reset controls use short eased camera moves and honour reduced motion. The scale bar is approximate at the camera target, as labelled. See [district clarity validation](district-clarity-validation.md) for screenshots, measured settings and limitations.

Deep links use `/district?run=<UUID>&view=street&light=golden&quality=high`; valid views are `district`, `street`, `top`, valid lighting modes are `simulation`, `daylight`, `golden`, `blue`, `night`, and valid quality modes are `auto`, `high`, `balanced`, `eco`.

Performance is device- and viewport-dependent. A high-quality image or a smooth exported recording is not evidence of a live 60 FPS interface. Browser frame-time and pass-inclusive draw/triangle diagnostics are exposed as `body` data attributes for reproducible checks; the appearance panel shows measured frame rate and rendering dimensions. See [rendering validation](rendering-validation.md) for the actual checks and limits.

## Acquisition and verification

```bash
python -m data.urban
python -m pytest tests/test_urban_scene.py tests/test_ui.py
python -m app.main
```

Three.js 0.180.0 and its selected utilities are bundled from the official npm package with its MIT licence in `app/static/vendor/THREE-LICENSE.txt`. New scene data are visual inputs and are excluded from numerical weather/price/building input hashes. No numerical controller or DER balance is replaced by a visual estimate.
