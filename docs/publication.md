# Local repository and GitHub publication

The source tree is prepared locally with tests, documentation, citation, MIT software licence and CI. **No remote repository has been created or verified by this task.** The connected GitHub tool can inspect the authenticated account and existing repositories, but does not expose repository creation; the GitHub CLI was not installed. Do not interpret a connected account as a published project.

After reviewing the completed scope and dataset terms, install/authenticate GitHub CLI if needed and run from this project directory:

```powershell
git init
git add .
git commit -m "Add NYC VPP numerical simulator and control centre"
gh auth login
gh repo create nyc-virtual-power-plant-control-centre --public --source . --remote origin --push --description "An open source Python laboratory for network-constrained coordination of urban DERs, predictive control and independent AC verification."
gh repo view --web
git ls-remote --heads origin
```

If a local commit already exists, omit `git init`/`git commit`. Use a private repository instead of `--public` if preferred. The intended branch uses the `codex/` prefix. Run `python -m pytest` before publication and use `python -m data.download` to reacquire public inputs. Result folders, raw acquisition chunks, virtual environments and credentials are ignored.

The included processed source snapshots retain source rights and attribution, separate from MIT software licensing. Review NYISO/source terms for your intended redistribution; remove those cached datasets from the publishable tree and retain acquisition scripts if necessary. There are no credentials or API keys in this project.
