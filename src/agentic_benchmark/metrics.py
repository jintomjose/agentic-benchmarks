"""The three measurements: baseline (freeze the plan), compare (plan vs actual later), retro (history only)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .backlog import Item, first_assignment, parse_dt


@dataclass
class Result:
    product: str
    mode: str                      # baseline | compare | retro
    as_of: str
    estimate_unit: str
    work_items: int = 0
    total_estimate: float = 0
    delivered_estimate: float = 0
    remaining_estimate: float = 0
    agentic_share_of_scope: float = 0
    agentic_share_of_delivered: float = 0
    compared_items: int = 0
    compared_estimate: float = 0
    actual_start: str | None = None
    actual_end: str | None = None
    actual_days: int | None = None
    planned_start: str | None = None
    planned_end: str | None = None
    planned_days: int | None = None
    planned_sprints: int = 0
    compression: float | None = None
    projected_end: str | None = None         # compare: whole baseline scope at the observed pace
    projected_compression: float | None = None
    velocity: float | None = None
    baseline_end: str | None = None          # compare: end date of the full baseline plan
    group: str | None = None                 # business unit / domain, for enterprise rollups
    status: str = "ok"                       # ok | paused | no_baseline | no_delivery | error
    last_activity: str | None = None         # last delivery of any in-scope item (the "last build")
    idle_days: int | None = None             # days from last_activity to as-of
    paused_since: str | None = None          # set when idle > pause_after_days with work remaining
    measured_to: str | None = None           # end of the measured period (as-of, or last build if paused)
    excluded: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    trend: list[dict] = field(default_factory=list)  # compare: weekly readings since the baseline


def _days(a: date, b: date) -> int:
    return (b - a).days + 1


def _windows(r: Result, cmp: list[Item], tz: ZoneInfo, start: date, plan_start: date):
    a1 = max(i.delivered.astimezone(tz).date() for i in cmp)
    p1 = max(i.planned_finish for i in cmp)
    r.actual_start, r.actual_end, r.actual_days = start.isoformat(), a1.isoformat(), _days(start, a1)
    r.planned_start, r.planned_end, r.planned_days = plan_start.isoformat(), p1.isoformat(), _days(plan_start, p1)
    r.planned_sprints = len({i.planned_sprint for i in cmp})
    r.compression = r.planned_days / r.actual_days
    late = [i for i in cmp if i.delivered.astimezone(tz).date() > i.planned_finish]
    if late:
        r.warnings.append(f"{len(late)} compared items were delivered AFTER their planned sprint")


# ------------------------------------------------------------------ baseline

def baseline(name: str, items: list[Item], cfg: dict, at: datetime, unit: str, vel: float, vel_detail: list[str]) -> Result:
    """Scope = items open at `at`; plan = sprint assignment or forecast (already applied to items)."""
    open_items = [i for i in items if not i.delivered]
    r = Result(product=name, mode="baseline", as_of=at.isoformat(timespec="minutes"), estimate_unit=unit,
               work_items=len(open_items), velocity=vel or None)
    r.total_estimate = r.remaining_estimate = sum(i.estimate for i in open_items)
    r.agentic_share_of_scope = (sum(i.estimate for i in open_items if i.agentic) / r.total_estimate) if r.total_estimate else 0
    planned = [i for i in open_items if i.planned_finish]
    if planned:
        start = at.astimezone(ZoneInfo(cfg["timezone"])).date()
        r.planned_start, r.planned_end = start.isoformat(), max(i.planned_finish for i in planned).isoformat()
        r.planned_days = _days(start, max(i.planned_finish for i in planned))
        r.planned_sprints = len({i.planned_sprint for i in planned})
    r.excluded = {"unplanned": sum(i.estimate for i in open_items if not i.planned_finish)}
    if vel_detail:
        r.warnings.append("velocity from history: " + "; ".join(vel_detail))
    return r


def baseline_doc(r: Result, items: list[Item], cfg: dict) -> dict:
    keep = ["org", "project", "area_path", "work_item_types", "estimate", "done_states",
            "agentic_rule", "timezone", "repo"]
    rows = []
    for i in items:
        if i.delivered:
            continue
        rows.append({"id": i.id, "title": i.title, "type": i.type, "state": i.state, "estimate": i.estimate,
                     "estimate_filled": i.estimate_filled, "agentic": i.agentic, "planned_sprint": i.planned_sprint,
                     "planned_start": i.planned_start.isoformat() if i.planned_start else None,
                     "planned_finish": i.planned_finish.isoformat() if i.planned_finish else None,
                     "plan_source": i.plan_source})
    return {"schema": 1, "summary": asdict(r), "config": {k: cfg.get(k) for k in keep}, "items": rows}


# ------------------------------------------------------------------ compare

def compare(name: str, base: dict, items: list[Item], cfg: dict, at: datetime, unit: str) -> Result:
    """Baseline items delivered since the baseline vs the sprint the baseline planned them in."""
    tz = ZoneInfo(cfg["timezone"])
    base_at = parse_dt(base["summary"]["as_of"])
    start = base_at.astimezone(tz).date()
    if cfg.get("run_start"):
        start = max(start, date.fromisoformat(cfg["run_start"]))
    plan = {row["id"]: row for row in base["items"]}
    now = {i.id: i for i in items}

    r = Result(product=name, mode="compare", as_of=at.isoformat(timespec="minutes"), estimate_unit=unit)
    scope = [now[k] for k in plan if k in now]
    r.work_items = len(plan)
    r.total_estimate = sum(row["estimate"] for row in plan.values())
    # Baseline estimates are used throughout, so re-estimating later cannot move the result.
    for i in scope:
        row = plan[i.id]
        i.estimate, i.planned_sprint, i.plan_source = row["estimate"], row["planned_sprint"], "baseline"
        i.planned_start = date.fromisoformat(row["planned_start"]) if row["planned_start"] else None
        i.planned_finish = date.fromisoformat(row["planned_finish"]) if row["planned_finish"] else None
    done = [i for i in scope if i.delivered and i.delivered > base_at]
    r.delivered_estimate = sum(i.estimate for i in done)
    r.remaining_estimate = r.total_estimate - r.delivered_estimate
    r.agentic_share_of_scope = (sum(i.estimate for i in scope if i.agentic) / r.total_estimate) if r.total_estimate else 0
    r.agentic_share_of_delivered = (sum(i.estimate for i in done if i.agentic) / r.delivered_estimate) if r.delivered_estimate else 0

    gone = [k for k in plan if k not in now]
    added = [i for i in items if i.id not in plan and not (i.delivered and i.delivered <= base_at)]
    r.excluded = {"removed_since_baseline": sum(plan[k]["estimate"] for k in gone),
                  "added_since_baseline": sum(i.estimate for i in added),
                  "unplanned_in_baseline": sum(i.estimate for i in done if not i.planned_finish)}
    if gone:
        r.warnings.append(f"{len(gone)} baseline items were removed or moved out of scope")
    if added:
        r.warnings.append(f"{len(added)} items were added after the baseline; reported, not compared")

    for i in done:
        i.in_comparison = bool(i.planned_finish)
        if not i.in_comparison:
            i.note = "no planned sprint in baseline"
    for i in added:
        i.note = "added after baseline"
    cmp = [i for i in done if i.in_comparison]
    r.compared_items, r.compared_estimate = len(cmp), sum(i.estimate for i in cmp)
    plan_end = max((i.planned_finish for i in scope if i.planned_finish), default=None)
    r.baseline_end = plan_end.isoformat() if plan_end else None
    if not cmp:
        r.status = "no_delivery"
        r.warnings.append("nothing from the baseline has been delivered yet")
        return r
    _windows(r, cmp, tz, start, start)

    # Projection for the whole baseline scope at the pace observed so far.
    # Pause diagnostic: the "last build" is the last delivery of any in-scope item, baseline or added.
    last = max(i.delivered.astimezone(tz).date() for i in items if i.delivered and i.delivered > base_at)
    _pause(r, last, at.astimezone(tz).date(), cfg)
    # Pace is measured up to as-of while the product is active, and up to the last build once it is
    # paused, so an idle tail is not counted.
    end = date.fromisoformat(r.measured_to)
    elapsed = _days(start, end)
    if plan_end and r.remaining_estimate > 0:
        pace = r.delivered_estimate / elapsed
        days_total = round(r.total_estimate / pace)
        r.projected_end = date.fromordinal(start.toordinal() + days_total - 1).isoformat()
        r.projected_compression = _days(start, plan_end) / days_total
    elif plan_end:
        r.projected_end, r.projected_compression = r.actual_end, _days(start, plan_end) / r.actual_days
    return r


def _pause(r: Result, last: date, today: date, cfg: dict):
    """Mark the product paused when nothing has been delivered for more than pause_after_days and
    baseline work remains; the measured period then stops at the last build."""
    r.last_activity, r.idle_days = last.isoformat(), (today - last).days
    r.measured_to = today.isoformat()
    if r.remaining_estimate > 0 and r.idle_days > cfg["pause_after_days"]:
        r.status, r.paused_since, r.measured_to = "paused", (last + timedelta(days=1)).isoformat(), last.isoformat()
        r.warnings.append(f"paused: no build for {r.idle_days} days (last build {last}); the clock stopped at the "
                          f"last build and the idle tail is not measured")


# ------------------------------------------------------------------ retro

def retro(name: str, items: list[Item], histories: dict, sprints: dict, cfg: dict, at: datetime, unit: str) -> Result:
    """No baseline file: reconstruct the original plan from revision history (first sprint ever assigned
    or the sprint at a fixed baseline date)."""
    from .backlog import snapshot, end_of_day
    tz = ZoneInfo(cfg["timezone"])
    by_id = {str(k): sorted(v, key=lambda r: r["rev"]) for k, v in histories.items()}
    for i in items:
        if cfg["plan_baseline"] == "first_assignment":
            path = first_assignment(by_id.get(i.id, []), sprints) if by_id else i.planned_sprint
        else:
            f = snapshot(by_id.get(i.id, []), end_of_day(cfg["plan_baseline"], tz))
            path = f.get("System.IterationPath") if f else None
        if by_id and path in sprints:
            i.planned_sprint, (i.planned_start, i.planned_finish) = path, sprints[path]
            i.plan_source = cfg["plan_baseline"] if cfg["plan_baseline"] == "first_assignment" else "baseline_date"

    r = Result(product=name, mode="retro", as_of=at.date().isoformat(), estimate_unit=unit, work_items=len(items))
    done = [i for i in items if i.delivered]
    r.total_estimate = sum(i.estimate for i in items)
    r.delivered_estimate = sum(i.estimate for i in done)
    r.remaining_estimate = r.total_estimate - r.delivered_estimate
    r.agentic_share_of_scope = (sum(i.estimate for i in items if i.agentic) / r.total_estimate) if r.total_estimate else 0
    r.agentic_share_of_delivered = (sum(i.estimate for i in done if i.agentic) / r.delivered_estimate) if r.delivered_estimate else 0

    run_start = date.fromisoformat(cfg["run_start"]) if cfg["run_start"] else None
    excl = {"backfilled": 0.0, "unplanned": 0.0, "outside_window": 0.0}
    for i in done:
        if cfg["exclude_backfilled"] and i.backfilled:
            i.note, excl["backfilled"] = "backfilled: created already done", excl["backfilled"] + i.estimate
        elif run_start and i.delivered.astimezone(tz).date() < run_start:
            i.note, excl["outside_window"] = "delivered before run_start", excl["outside_window"] + i.estimate
        elif not i.planned_finish:
            i.note, excl["unplanned"] = "no dated original sprint", excl["unplanned"] + i.estimate
        else:
            i.in_comparison = True
    r.excluded = excl
    cmp = [i for i in done if i.in_comparison]
    r.compared_items, r.compared_estimate = len(cmp), sum(i.estimate for i in cmp)
    if not cmp:
        r.status = "no_delivery"
        r.warnings.append("no delivered items left to compare")
        return r
    a0 = run_start or min(i.delivered.astimezone(tz).date() for i in cmp)
    p0 = a0 if cfg["plan_clock"] == "run_start" and run_start else min(i.planned_start for i in cmp)
    _windows(r, cmp, tz, a0, p0)
    _pause(r, max(i.delivered.astimezone(tz).date() for i in done), at.astimezone(tz).date(), cfg)
    return r


def items_from_csv(cfg: dict, at: datetime) -> list[Item]:
    """Normalised export (Jira or any tracker); the exporter supplies the original plan."""
    import csv
    from datetime import timedelta
    out = []
    with open(cfg["csv_path"], newline="") as fh:
        for row in csv.DictReader(fh):
            created, delivered = parse_dt(row.get("created")), parse_dt(row.get("delivered"))
            if created and created > at:
                continue
            if delivered and delivered > at:
                delivered = None
            est = float(row.get("estimate") or row.get("points") or 0) or None
            ps, pf = row.get("planned_start"), row.get("planned_finish")
            out.append(Item(
                id=row["id"], title=row.get("title", "") if cfg["include_titles"] else "", type=row.get("type", ""),
                state=row.get("state", ""), estimate=1.0 if cfg["estimate"] == "count" else est,
                agentic=row.get("agentic", "").strip().lower() in {"1", "true", "yes", "y"},
                created=created, delivered=delivered, planned_sprint=row.get("planned_sprint") or None,
                planned_start=date.fromisoformat(ps) if ps else None,
                planned_finish=date.fromisoformat(pf) if pf else None, plan_source="csv",
                backfilled=bool(delivered and created and
                                delivered - created <= timedelta(minutes=cfg["backfill_minutes"]))))
    return out


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
