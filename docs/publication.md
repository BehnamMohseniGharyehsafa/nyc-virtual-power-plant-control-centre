# Public GitHub repository

The project is published publicly at:

https://github.com/BehnamMohseniGharyehsafa/nyc-virtual-power-plant-control-centre

The repository was created using the existing Git Credential Manager sign-in, with the authenticated account verified before creation. No credential is stored in source files, command arguments or remote URLs. The numerical and UI source, reproducibility metadata, constrained dependencies and MIT software licence are included. Source datasets and Three.js retain their own terms and attribution.

To update the public main branch from this checkout after reviewing and testing changes:

```powershell
git add .
git commit -m "Describe the tested change"
git push origin HEAD:main
```

The local working branch uses the `codex/` prefix. Verify a published commit with `git ls-remote --heads origin`. The publication helper `python -m experiments.publish_github --push` can also verify the public visibility and remote commit using an existing authorised sign-in.

Virtual environments, numerical result folders, raw acquisition chunks and credentials are excluded from Git. Software licensing does not relicense third-party source data. See `data.md` and `urban-visualisation.md` for source attribution and explicit model assumptions.
