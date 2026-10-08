"""Configuration: a portfolio TOML file, or `.agentic-benchmark.toml` files read from GitHub repos."""
from __future__ import annotations

import base64
import json
import subprocess
import tomllib
from pathlib import Path

REPO_CONFIG = ".agentic-benchmark.toml"

DEFAULTS = {
    "source": "ado",
    "transport": "auto",           # auto: rest if ADO_PAT/ADO_TOKEN is set, else az CLI
    # Covers the Scrum, Agile, CMMI and Basic process templates.
    "work_item_types": ["Product Backlog Item", "User Story", "Requirement", "Issue", "Bug"],
    "estimate": "points",          # points | hours | count
    "points_field": "auto",        # or Microsoft.VSTS.Scheduling.StoryPoints / .Effort / .Size
    "hours_field": "Microsoft.VSTS.Scheduling.OriginalEstimate",
    "unestimated": "exclude",      # exclude | median (fill missing estimates with the team median)
    "done_states": ["Done", "Closed", "Resolved", "Completed"],
    "removed_states": ["Removed", "Cut"],
    "agentic_rule": {"type": "tag", "value": "Agentic"},
    "plan_baseline": "first_assignment",
    "velocity": "auto",            # auto (from history) or a number per sprint
    "velocity_sprints": 3,
    "history_days": 180,
    "run_start": None,
    "as_of": None,
    "plan_clock": "run_start",
    "backfill_minutes": 60,
    "exclude_backfilled": True,
    "include_titles": True,
    "timezone": "Europe/Amsterdam",
    "area_path": None,
    "concurrency": 8,
}


def _products(conf: dict) -> list[dict]:
    p = conf.get("product", [])
    return [p] if isinstance(p, dict) else p  # a repo file may use [product] or [[product]]


def load_file(path: str) -> list[dict]:
    conf = tomllib.loads(Path(path).read_text())
    base = {**DEFAULTS, **conf.get("defaults", {})}
    return [{**base, **p} for p in _products(conf)]


def _gh(args: list[str]):
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout else None


def load_repo(repo: str, defaults: dict | None = None) -> list[dict]:
    """Read .agentic-benchmark.toml from a GitHub repo the caller can access (uses `gh` auth)."""
    meta = _gh([f"repos/{repo}/contents/{REPO_CONFIG}"])
    if not meta:
        return []
    conf = tomllib.loads(base64.b64decode(meta["content"]).decode())
    base = {**DEFAULTS, **(defaults or {}), **conf.get("defaults", {})}
    out = []
    for p in _products(conf):
        p = {**base, **p}
        p.setdefault("name", repo.split("/")[-1])
        p["repo"] = repo
        out.append(p)
    return out


def load_github_org(org: str, defaults: dict | None = None) -> list[dict]:
    """Every repo in the org that carries a .agentic-benchmark.toml."""
    repos = subprocess.run(["gh", "repo", "list", org, "--limit", "1000", "--json", "nameWithOwner",
                            "--jq", ".[].nameWithOwner"], capture_output=True, text=True).stdout.split()
    return [p for r in repos for p in load_repo(r, defaults)]
