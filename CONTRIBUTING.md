# Contributing

Use Python 3.12 or 3.13 and install `python -m pip install -e ".[dev]"`. Run `python -m pytest` before submitting changes. Acquisition scripts must fail explicitly on missing data and preserve source units, UTC timestamps and provenance.

Keep physical equations outside Dash callbacks. Declare units, signs, assumptions, source references and numerical tolerances. Add independent conservation or benchmark checks for changes to physical models. An optimiser returning a value is not proof of AC feasibility. Record solver errors and constraint violations without replacing them with successful-looking outputs.

New performance claims need executed experiments with size, horizon, solver, input hashes and measured time. New financial benefits need an executed comparable counterfactual and consistent terminal energy treatment. Treat synthetic infrastructure and assumed device data as such in every interface and publication.

Use British English. Do not commit credentials, raw restricted inputs, generated virtual environments or results. Identify incomplete/experimental behaviour in documentation before claiming it as implemented.
