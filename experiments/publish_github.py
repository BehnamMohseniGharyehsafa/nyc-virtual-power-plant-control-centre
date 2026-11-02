"""Publish this project using an existing Git Credential Manager sign-in.

Credentials stay in process memory. No token is printed, stored in the project,
embedded in remote URLs, or passed as a command-line argument.
"""

import argparse
import os
from pathlib import Path
import subprocess
import requests

OWNER = "BehnamMohseniGharyehsafa"
NAME = "nyc-virtual-power-plant-control-centre"
ROOT = Path(__file__).resolve().parents[1]


def session():
    env = dict(os.environ, GCM_INTERACTIVE="Never", GIT_TERMINAL_PROMPT="0")
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=25,
        cwd=ROOT,
    )
    credential = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    if not credential.get("password"):
        raise RuntimeError(
            "No existing GitHub Git credential; sign in using your normal Git tooling"
        )
    client = requests.Session()
    client.headers.update(
        Authorization="Bearer " + credential["password"],
        Accept="application/vnd.github+json",
        **{"X-GitHub-Api-Version": "2022-11-28"},
    )
    user = client.get("https://api.github.com/user", timeout=30)
    user.raise_for_status()
    if user.json().get("login") != OWNER:
        raise RuntimeError(
            "Stored Git sign-in does not match the requested GitHub owner"
        )
    return client, env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    client, env = session()
    url = f"https://api.github.com/repos/{OWNER}/{NAME}"
    response = client.get(url, timeout=30)
    if response.status_code == 404:
        response = client.post(
            "https://api.github.com/user/repos",
            json=dict(
                name=NAME,
                private=False,
                description="A Python urban VPP research simulator with realistic Brooklyn district visualisation, predictive DER control and independent AC power-flow verification.",
                auto_init=False,
                has_issues=True,
            ),
            timeout=30,
        )
        response.raise_for_status()
        print("Created public repository:", response.json()["html_url"], flush=True)
    else:
        response.raise_for_status()
        if response.json()["private"]:
            response = client.patch(url, json={"private": False}, timeout=30)
            response.raise_for_status()
        print("Public repository:", response.json()["html_url"], flush=True)
    remote = f"https://github.com/{OWNER}/{NAME}.git"
    existing = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=ROOT, text=True, capture_output=True
    )
    if existing.returncode:
        subprocess.run(
            ["git", "remote", "add", "origin", remote], cwd=ROOT, env=env, check=True
        )
    elif existing.stdout.strip() != remote:
        raise RuntimeError(
            "Existing origin differs from the requested repository; refusing to overwrite it"
        )
    if args.push:
        subprocess.run(
            ["git", "push", "-u", "origin", "HEAD:main"], cwd=ROOT, env=env, check=True
        )
        client.patch(
            url, json={"default_branch": "main"}, timeout=30
        ).raise_for_status()
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        branch = client.get(url + "/branches/main", timeout=30)
        branch.raise_for_status()
        if branch.json()["commit"]["sha"] != sha:
            raise RuntimeError("Remote HEAD verification failed")
        print("Verified remote commit:", sha, flush=True)
    verify = client.get(url, timeout=30)
    verify.raise_for_status()
    if verify.json()["private"]:
        raise RuntimeError("Repository is still private")
    print("Verified visibility: public", flush=True)


if __name__ == "__main__":
    main()
