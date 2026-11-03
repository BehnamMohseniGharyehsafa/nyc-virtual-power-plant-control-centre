# Rendering validation

The upgrade was checked on **3 November 2026** in the Codex in-app Chromium browser on Windows with an Intel UHD Graphics GPU. The workflow follows Open 3D Skills' `site-check` guidance using the available browser automation surface. Its external Playwright scripts were not installed or executed.

Checks cover 1440 × 900 desktop, 768 × 1024 tablet and 390 × 844 phone viewports, district/street/plan cameras, lighting controls, building picking, traffic pause/resume and parent timeline coupling. Screenshots and DOM rendering diagnostics are saved in `docs/images/rendering/`. Timing samples are illustrative measurements from this embedded browser, not a guarantee for other devices. The samples include all enabled render passes. Initial shader compilation, window changes, user interactions and background throttling affect frame time.

High quality is intentionally more expensive than automatic quality on this integrated GPU. The scene removes the fixed 30 FPS rendering limit, but a stable 60 FPS claim is not made. Automatic quality lowers post-processing, shadow resolution and, when necessary, drawing resolution to preserve interaction. Static shadow caching, window planes, spatial batching and nearby-only sill detail reduce ongoing cost. Idle rendering stops when traffic is paused and all other animation has settled.

Representative samples from this session: automatic tablet district view **32.7 FPS**, automatic phone viewport **59.5 FPS**, and automatic desktop plan view **38.4 FPS**. Desktop street scenes at explicitly selected High quality measured roughly **11–14 FPS** on this GPU, so Automatic remains the default. These are short embedded-browser samples at different resolutions and settings, not equivalent-workload benchmarks. The authoritative sample settings, drawing resolutions, frame times and triangle counts are recorded in [`qa.json`](images/rendering/qa.json).

No physical phone, WebKit/Safari, Firefox or slow-network test was performed in this environment. Reduced-motion handling is implemented with `prefers-reduced-motion`; OS-level preference switching was not exercised. The numerical simulation equations and stored engineering results are unaffected by presentation settings.

The offline renderer import-graph regression test checks that every executable ES-module import is served locally, including transitive post-processing dependencies. JavaScript syntax checks and the Python test suite accompany browser QA.

Validation completed with **34 tests passed** in 63.39 s. A wheel was built and inspected to confirm inclusion of the renderer, its licence notices and all 17 selected/transitive add-on modules. The standard pip wheel attempt hit Windows' sandbox temporary-path limit; direct setuptools wheel creation completed successfully.

The Intel/ANGLE compiler emitted warnings for the official FXAA shader's varying loop derivatives and a potentially uninitialised value. The shader compiled and rendered; no JavaScript exceptions or blank canvases were observed. The overflowing toolbar's backdrop filter caused a visible driver artefact and was replaced with an opaque surface.
