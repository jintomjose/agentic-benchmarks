"""Read-only Azure DevOps access: WIQL, revision history, field batches, iteration tree.

Two transports with the same interface:
  az    existing `az login` session (corporate SSO, no PAT)
  rest  ADO_PAT (Work Items: Read) or ADO_TOKEN (Entra bearer) from the environment
Nothing in this module writes to Azure DevOps.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API_VERSION = "7.1"


class AzCliTransport:
    def __init__(self, org: str, project: str):
        self.org, self.project = org, project

    def _run(self, args: list[str]):
        r = subprocess.run(["az", *args, "--org", self.org, "-o", "json"], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"az {' '.join(args[:3])} failed: {r.stderr.strip()[:400]}")
        return json.loads(r.stdout or "null")

    def _invoke(self, resource: str, route: list[str], query: list[str] | None = None, body: dict | None = None):
        args = ["devops", "invoke", "--area", "wit", "--resource", resource,
                "--route-parameters", f"project={self.project}", *route, "--api-version", API_VERSION]
        if query:
            args += ["--query-parameters", *query]
        if body is None:
            return self._run(args)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(body, fh)
        try:
            return self._run(args + ["--http-method", "POST", "--in-file", fh.name])
        finally:
            os.unlink(fh.name)

    def wiql_ids(self, wiql: str) -> list[int]:
        rows = self._run(["boards", "query", "--project", self.project, "--wiql", wiql])
        return [w["id"] for w in rows or []]

    def revisions(self, wid: int) -> list[dict]:
        out, skip = [], 0
        while True:
            page = self._invoke("revisions", [f"id={wid}"], ["$top=200", f"$skip={skip}"])["value"]
            out += page
            if len(page) < 200:
                return out
            skip += 200

    def fields_batch(self, ids: list[int], fields: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(ids), 200):
            out += self._invoke("workitemsbatch", [], body={"ids": ids[i:i + 200], "fields": fields})["value"]
        return out

    def iteration_tree(self) -> dict:
        return self._invoke("classificationNodes", ["structureGroup=iterations"], ["$depth=20"])


class RestTransport:
    def __init__(self, org: str, project: str):
        self.base = f"{org.rstrip('/')}/{urllib.parse.quote(project)}/_apis"
        if os.environ.get("ADO_TOKEN"):
            self.auth = "Bearer " + os.environ["ADO_TOKEN"]
        elif os.environ.get("ADO_PAT"):
            self.auth = "Basic " + base64.b64encode(f":{os.environ['ADO_PAT']}".encode()).decode()
        else:
            raise SystemExit("transport = 'rest' needs ADO_PAT or ADO_TOKEN in the environment")

    def _call(self, path: str, params: dict | None = None, body: dict | None = None):
        q = urllib.parse.urlencode({"api-version": API_VERSION, **(params or {})})
        req = urllib.request.Request(f"{self.base}/{path}?{q}",
                                     data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": self.auth, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

    def wiql_ids(self, wiql: str) -> list[int]:
        return [w["id"] for w in self._call("wit/wiql", body={"query": wiql})["workItems"]]

    def revisions(self, wid: int) -> list[dict]:
        out, skip = [], 0
        while True:
            page = self._call(f"wit/workitems/{wid}/revisions", {"$top": 200, "$skip": skip})["value"]
            out += page
            if len(page) < 200:
                return out
            skip += 200

    def fields_batch(self, ids: list[int], fields: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(ids), 200):
            out += self._call("wit/workitemsbatch", body={"ids": ids[i:i + 200], "fields": fields})["value"]
        return out

    def iteration_tree(self) -> dict:
        return self._call("wit/classificationnodes/Iterations", {"$depth": 20})


def transport_for(cfg: dict):
    kind = cfg["transport"]
    if kind == "auto":
        kind = "rest" if os.environ.get("ADO_PAT") or os.environ.get("ADO_TOKEN") else "az"
    cls = AzCliTransport if kind == "az" else RestTransport
    return cls(cfg["org"], cfg["project"])


def scope_wiql(cfg: dict, since: str | None = None) -> str:
    """Items of the configured types; closed items only if they changed recently (for velocity)."""
    project = cfg["project"].replace("'", "''")
    types = ", ".join(f"'{t}'" for t in cfg["work_item_types"])
    q = f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{project}' AND [System.WorkItemType] IN ({types})"
    if cfg.get("area_path"):
        q += f" AND [System.AreaPath] UNDER '{cfg['area_path'].replace(chr(39), chr(39) * 2)}'"
    if since:
        done = ", ".join(f"'{s}'" for s in cfg["done_states"] + cfg["removed_states"])
        q += f" AND ([System.State] NOT IN ({done}) OR [System.ChangedDate] >= '{since}')"
    return q


def load_histories(cfg: dict, cache_dir: Path, offline: bool, since: str | None = None):
    """Return (revision histories by id, iteration tree). Revisions are cached on disk."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    tree_file, ids_file = cache_dir / "iterations.json", cache_dir / "ids.json"
    if offline:
        tree, ids = json.loads(tree_file.read_text()), json.loads(ids_file.read_text())
        t = None
    else:
        t = transport_for(cfg)
        ids, tree = t.wiql_ids(scope_wiql(cfg, since)), t.iteration_tree()
        tree_file.write_text(json.dumps(tree))
        ids_file.write_text(json.dumps(ids))

    def fetch(wid):
        p = cache_dir / f"rev_{wid}.json"
        if offline:
            return wid, json.loads(p.read_text())
        revs = t.revisions(wid)
        p.write_text(json.dumps(revs))
        return wid, revs

    with ThreadPoolExecutor(cfg["concurrency"]) as ex:
        return dict(ex.map(fetch, ids)), tree
