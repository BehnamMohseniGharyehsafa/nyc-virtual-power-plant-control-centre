# Render deployment and protected main

The Render Blueprint is `render.yaml`. The configured service name is `behnamproject-nyc-virtual-power-plant-control-centre`, in Frankfurt, on the Free compute plan. Its requested address is `https://behnamproject-nyc-virtual-power-plant-control-centre.onrender.com/`; Render must confirm that the subdomain is available when the service is created.

## Runtime

Render installs `requirements-render.txt` with the validated numerical dependency constraints and the hosting extra. Python is pinned to 3.13.15. Gunicorn serves `app.wsgi:server` on Render's assigned `PORT`, using one gthread worker and four HTTP threads. One worker is required because the background job manager holds process-local state. Debug mode and automatic optimisation at startup are disabled. Health checks use `/api/health`.

`data/demo/community/` contains the already calculated 16-building, 96-step result `4c443515-673a-410e-aa8f-10aaadca333f`. It is a model result under the documented asset and tariff assumptions, not live telemetry. Its source provenance, numerical diagnostics and per-file SHA-256 manifest are included. `core.hosting.seed_demo` checks the manifest and registers it on an empty hosted filesystem, leaving existing results intact. It does not run or fabricate a replacement simulation.

Local results default to `results/`. Set `VPP_RESULTS_DIR` to a persistent volume's directory when a paid persistent disk is explicitly provisioned. Free Render services use ephemeral storage: runtime changes disappear on restart, redeploy or idle spin-down. The supplied example is restored from the deployment image; new experiments should be exported before a restart. The Free service has limited CPU and 512 MB memory. Large portfolios, long optimisation horizons and concurrent numerical work may exceed that capacity; use local execution or an appropriately sized service for those workloads.

See [Render's Flask hosting guide](https://render.com/docs/deploy-flask), [Blueprint reference](https://render.com/docs/blueprint-spec) and [Free-instance limits](https://render.com/docs/free).

## Deployment updates

This Blueprint uses the public Git repository URL and manual deployments, so it requires no new GitHub account access. Render does not support automatic deploys for an unconnected public repository. After an approved change is merged to protected `main`, use **Manual Deploy → Deploy latest commit** in Render. If GitHub is connected later, automatic deployment can be configured to wait for passing CI (`autoDeployTrigger: checksPass`).

## Main-branch protections

The requested policy is pull-request changes with one independent approval, stale-approval dismissal, approval of the latest push, resolved conversations, passing GitHub Actions checks for Python 3.12 and 3.13, an up-to-date branch, signed commits and linear history. Force pushes and deletion are disabled, and administrators must follow the protections. The repository owner can still administer the protection settings.

With independent approval required, a PR author cannot approve their own PR. A second authorised reviewer is needed for future changes. Verified commit signatures are also required for newly introduced commits. Do not bypass these requirements for automated updates. Prepare changes on a `codex/` feature branch and open a PR.
