"""agentic-benchmark: plan vs agentic delivery for any ADO-backed product.

  discover  inspect an ADO project and suggest a config (types, states, estimate field, agentic marker)
  baseline  freeze today's plan (current estimates, sprints, velocity forecast) into baselines/
  compare   later: baseline scope delivered since then vs when the baseline planned it -> ×-speed
  retro     no baseline taken? reconstruct the original plan from revision history
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import ado, backlog, config, htmlreport, metrics, report
from .config import slug


def products(args) -> list[dict]:
    out = []
    if args.config:
        out += config.load_file(args.config)
    for repo in args.repo or []:
        found = config.load_repo(repo)
        if not found:
            print(f"! {repo}: no {config.REPO_CONFIG} found (or no access)", file=sys.stderr)
        out += found
    if args.github_org:
        out += config.load_github_org(args.github_org)
    if args.product:
        out = [p for p in out if p["name"] in args.product]
    if not out:
        sys.exit("no products: pass --config, --repo owner/name or --github-org ORG")
    return out


def moment(cfg: dict, cli_as_of: str | None) -> datetime:
    tz = ZoneInfo(cfg["timezone"])
    d = cli_as_of or cfg.get("as_of")
    return backlog.end_of_day(d, tz) if d else datetime.now(timezone.utc)


UNITS = {"points": "points", "hours": "hours", "count": "items"}


def fetch(cfg: dict, at: datetime, out: Path, offline: bool, history: bool):
    """Revision histories (cached) and sprint calendar for one product."""
    since = (at - timedelta(days=cfg["history_days"])).date().isoformat() if history else None
    histories, tree = ado.load_histories(cfg, out / "cache" / slug(cfg["name"]), offline, since)
    return histories, backlog.load_sprints(tree), backlog.estimate_field(histories, cfg)


def items_at(histories: dict, cfg: dict, at: datetime, est_field):
    items = backlog.build_items(histories, cfg, at, est_field)
    return items, backlog.fill_estimates(items, cfg)


def _placeholder(cfg: dict, mode: str, status: str, msg: str) -> metrics.Result:
    r = metrics.Result(product=cfg["name"], mode=mode, as_of=date.today().isoformat(),
                       estimate_unit=UNITS.get(cfg["estimate"], cfg["estimate"]), group=cfg.get("group"), status=status)
    r.warnings.append(msg)
    print(f"\n=== {cfg['name']}  [{status}] {msg}", file=sys.stderr)
    return r


def each_product(args, mode: str, fn):
    """Run fn(cfg) per product; one failing product never stops an enterprise run."""
    runs = []
    for cfg in products(args):
        try:
            run = fn(cfg)
        except Exception as e:  # report and carry on
            run = (_placeholder(cfg, mode, "error", f"{type(e).__name__}: {str(e)[:300]}"), [], ZoneInfo(cfg["timezone"]))
        if run:
            run[0].group = cfg.get("group")
            runs.append(run)
    return runs


# ------------------------------------------------------------------ commands

def cmd_baseline(args):
    out = Path(args.out)

    def one(cfg):
        at, tz = moment(cfg, args.as_of), ZoneInfo(cfg["timezone"])
        histories, sprints, est_field = fetch(cfg, at, out, args.offline, history=True)
        items, warns = items_at(histories, cfg, at, est_field)
        team = backlog.team_sprints(histories, sprints)
        if cfg["velocity"] == "auto":
            vel, detail = backlog.velocity(items, team, at, tz, cfg["velocity_sprints"])
        else:
            vel, detail = float(cfg["velocity"]), []
        open_items = [i for i in items if not i.delivered]
        warns += backlog.forecast(open_items, team, at, tz, vel)
        r = metrics.baseline(cfg["name"], items, cfg, at, UNITS[cfg["estimate"]], vel, detail)
        r.warnings = warns + r.warnings
        report.print_result(r, f", estimate field {est_field or 'count'}")

        bdir = Path(args.baselines) / slug(cfg["name"])
        bdir.mkdir(parents=True, exist_ok=True)
        path = bdir / f"{at.astimezone(tz).date().isoformat()}.json"
        path.write_text(json.dumps(metrics.baseline_doc(r, items, cfg), indent=1, default=str))
        pdir = out / slug(cfg["name"])
        pdir.mkdir(parents=True, exist_ok=True)
        report.chart(r, open_items, tz, pdir / "baseline_plan.png")
        report.items_csv(open_items, tz, pdir / "baseline_items.csv")
        print(f"  -> {path}  (commit this file: it is the frozen plan)")
        return r, open_items, tz

    runs = each_product(args, "baseline", one)
    failed = [r for r, _, _ in runs if r.status == "error"]
    if failed:
        print(f"\n{len(failed)} product(s) failed: " + ", ".join(r.product for r in failed), file=sys.stderr)


def pick_baseline(cfg: dict, args) -> Path | None:
    if args.baseline:
        return Path(args.baseline)
    if cfg.get("baseline"):
        return Path(cfg["baseline"])
    files = sorted((Path(args.baselines) / slug(cfg["name"])).glob("*.json"))
    if cfg.get("run_start"):
        before = [f for f in files if f.stem <= cfg["run_start"]]
        files = before[-1:] or files
    return files[0] if files else None


def trend_dates(start: datetime, end: datetime, step: str) -> list[datetime]:
    if step == "none":
        return []
    delta = timedelta(days=1 if step == "daily" else 7)
    out, d = [], start + delta
    while d < end:
        out.append(d)
        d += delta
    return out + [end]


def cmd_compare(args):
    out = Path(args.out)

    def one(cfg):
        if cfg["source"] == "csv":  # no revision history to compare against: fall back to retro
            return _retro_one(cfg, args, out)
        bpath = pick_baseline(cfg, args)
        if not bpath:
            return _placeholder(cfg, "compare", "no_baseline",
                                "no baseline yet: run `agentic-benchmark baseline` before the agentic run starts"), [], ZoneInfo(cfg["timezone"])
        at, tz = moment(cfg, args.as_of), ZoneInfo(cfg["timezone"])
        base = json.loads(bpath.read_text())
        histories, _, est_field = fetch(cfg, at, out, args.offline, history=True)
        unit = UNITS[cfg["estimate"]]
        items, warns = items_at(histories, cfg, at, est_field)
        r = metrics.compare(cfg["name"], base, items, cfg, at, unit)
        r.warnings = warns + r.warnings
        for d in trend_dates(metrics.parse_dt(base["summary"]["as_of"]), at, args.trend):
            p = metrics.compare(cfg["name"], base, items_at(histories, cfg, d, est_field)[0], cfg, d, unit)
            r.trend.append({"date": d.astimezone(tz).date().isoformat(), "compression": p.compression,
                            "delivered_share": p.delivered_estimate / p.total_estimate if p.total_estimate else 0,
                            "agentic_share": p.agentic_share_of_delivered, "projected": p.projected_compression})
        report.print_result(r, f", baseline {bpath.name}")
        return _write(r, items, tz, out)

    _portfolio(each_product(args, "compare", one), out)


def _retro_one(cfg, args, out: Path):
    at, tz = moment(cfg, args.as_of), ZoneInfo(cfg["timezone"])
    if cfg["source"] == "csv":
        items, histories, sprints, unit = metrics.items_from_csv(cfg, at), {}, {}, UNITS[cfg["estimate"]]
        warns = backlog.fill_estimates(items, cfg)
    else:
        histories, sprints, est_field = fetch(cfg, at, out, args.offline, history=False)
        items, warns = items_at(histories, cfg, at, est_field)
        unit = UNITS[cfg["estimate"]]
    r = metrics.retro(cfg["name"], items, histories, sprints, cfg, at, unit)
    r.warnings = warns + r.warnings
    report.print_result(r)
    return _write(r, items, tz, out)


def cmd_retro(args):
    out = Path(args.out)
    _portfolio(each_product(args, "retro", lambda cfg: _retro_one(cfg, args, out)), out)


def _write(r, items, tz, out: Path):
    pdir = out / slug(r.product)
    pdir.mkdir(parents=True, exist_ok=True)
    report.items_csv(items, tz, pdir / f"{r.mode}_items.csv")
    (pdir / f"{r.mode}_summary.json").write_text(json.dumps(r.__dict__, indent=2, default=str))
    report.chart(r, items, tz, pdir / f"{r.mode}_burndown.png")
    report.timeline(r, items, tz, pdir / f"{r.mode}_timeline.png")
    report.trend_chart(r, pdir / f"{r.mode}_trend.png")
    return r, items, tz


def _portfolio(runs, out: Path):
    if runs:
        results = [r for r, _, _ in runs]
        out.mkdir(parents=True, exist_ok=True)
        report.portfolio(results, out)
        report.portfolio_chart(results, out / "portfolio_compression.png")
        htmlreport.write(runs, out)
        print(f"\nWrote {out}/report.html  (plus portfolio_summary.md/.csv, enterprise_summary.json and per-product charts)")


def cmd_discover(args):
    cfg = {**config.DEFAULTS, **(products(args)[0] if (args.config or args.repo) else {})}
    if args.org:
        cfg.update(org=args.org, project=args.project, name=args.project)
    if args.area_path:
        cfg["area_path"] = args.area_path
    t = ado.transport_for(cfg)
    since = (date.today() - timedelta(days=cfg["history_days"])).isoformat()
    q = (f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{cfg['project']}' "
         f"AND [System.ChangedDate] >= '{since}'")
    if cfg.get("area_path"):
        q += f" AND [System.AreaPath] UNDER '{cfg['area_path']}'"
    ids = t.wiql_ids(q)
    est = backlog.POINT_FIELDS + [cfg["hours_field"]]
    rows = [w["fields"] for w in t.fields_batch(ids, ["System.WorkItemType", "System.State", "System.AreaPath",
                                                      "System.IterationPath", "System.Tags", *est])]
    print(f"{cfg['project']}: {len(rows)} work items changed since {since}\n")
    by_type = collections.defaultdict(collections.Counter)
    for f in rows:
        by_type[f["System.WorkItemType"]][f["System.State"]] += 1
    print("Types and states:")
    for ty, states in sorted(by_type.items(), key=lambda x: -sum(x[1].values())):
        fill = {e.split(".")[-1]: sum(1 for f in rows if f["System.WorkItemType"] == ty and f.get(e))
                for e in est}
        fill = ", ".join(f"{k} {v}" for k, v in fill.items() if v) or "no estimates"
        print(f"  {ty:24} {dict(states)}  | estimated: {fill}")
    for label, key, n in [("Area paths", "System.AreaPath", 12), ("Iterations", "System.IterationPath", 12)]:
        print(f"\n{label}:")
        for v, c in collections.Counter(f.get(key) for f in rows).most_common(n):
            print(f"  {c:5}  {v}")
    tags = collections.Counter(t.strip() for f in rows for t in (f.get("System.Tags") or "").split(";") if t.strip())
    print("\nTags:", ", ".join(f"{k} ({v})" for k, v in tags.most_common(15)) or "none")
    agent_tags = [k for k in tags if re.search(r"agent|ai|claude|copilot", k, re.I)]
    agent_areas = sorted({f["System.AreaPath"] for f in rows if re.search(r"agent", f["System.AreaPath"] or "", re.I)})
    rule = (f'{{ type = "tag", value = "{agent_tags[0]}" }}' if agent_tags else
            f'{{ type = "area_path", value = "{agent_areas[0]}" }}'.replace("\\", "\\\\") if agent_areas else
            '{ type = "tag", value = "Agentic" }   # no agent marker found yet: agree one with the team')
    print("\nSuggested .agentic-benchmark.toml:\n")
    print(f'[product]\nname = "{cfg["project"]}"\norg = "{cfg["org"]}"\nproject = "{cfg["project"]}"')
    if cfg.get("area_path"):
        print(f'area_path = "{cfg["area_path"]}"'.replace("\\", "\\\\"))
    print(f"agentic_rule = {rule}")
    fills = {e: sum(1 for f in rows if f.get(e)) for e in est}
    best = max(fills, key=fills.get)
    estimated_types = sorted({f["System.WorkItemType"] for f in rows if f.get(best)})
    done_like = sorted({s for st in by_type.values() for s in st} & set(cfg["done_states"]))
    if fills[best]:
        mode = "hours" if best == cfg["hours_field"] else "points"
        print(f"work_item_types = {json.dumps(estimated_types)}\nestimate = \"{mode}\"")
        if mode == "points":
            print(f'points_field = "{best}"')
    else:
        print('estimate = "count"   # nothing is estimated: throughput (items) instead of points')
    if done_like:
        print(f"done_states = {json.dumps(done_like)}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agentic-benchmark", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("discover", cmd_discover), ("baseline", cmd_baseline),
                     ("compare", cmd_compare), ("retro", cmd_retro)]:
        p = sub.add_parser(name, help=fn.__doc__)
        p.set_defaults(fn=fn)
        p.add_argument("--config", help="portfolio TOML file")
        p.add_argument("--repo", action="append", help="GitHub owner/name holding .agentic-benchmark.toml (repeatable)")
        p.add_argument("--github-org", help="scan every repo in this GitHub org for .agentic-benchmark.toml")
        p.add_argument("--product", action="append", help="only these product names (repeatable)")
        p.add_argument("--as-of", help="YYYY-MM-DD: act as if it were the end of this day")
        p.add_argument("--offline", action="store_true", help="reuse cached ADO data")
        p.add_argument("--out", default="out", help="output directory (default: out)")
        p.add_argument("--baselines", default="baselines", help="baseline directory (default: baselines)")
        if name == "compare":
            p.add_argument("--baseline", help="specific baseline JSON (default: picked per product)")
            p.add_argument("--trend", choices=["weekly", "daily", "none"], default="weekly",
                           help="rebuild readings since the baseline for the trend charts (default: weekly)")
        if name == "discover":
            p.add_argument("--org"), p.add_argument("--project"), p.add_argument("--area-path")
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
