"""Turn ADO revision histories into backlog items as they stood at a moment in time."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

POINT_FIELDS = [
    "Microsoft.VSTS.Scheduling.StoryPoints",
    "Microsoft.VSTS.Scheduling.Effort",
    "Microsoft.VSTS.Scheduling.Size",
]
PRIORITY_FIELDS = ["Microsoft.VSTS.Common.BacklogPriority", "Microsoft.VSTS.Common.StackRank"]


@dataclass
class Item:
    id: str
    title: str
    type: str
    state: str
    estimate: float | None
    agentic: bool
    created: datetime | None
    delivered: datetime | None            # last entry into a done state (None if not done)
    iteration: str | None = None          # iteration path at the snapshot moment
    priority: float = 0.0
    planned_sprint: str | None = None
    planned_start: date | None = None
    planned_finish: date | None = None
    plan_source: str = ""                 # sprint | forecast | first_assignment | baseline | unplanned
    backfilled: bool = False
    estimate_filled: bool = False         # estimate imputed from the team median
    in_comparison: bool = False
    note: str = ""


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def end_of_day(d: str | date, tz: ZoneInfo) -> datetime:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return datetime.combine(d, datetime.max.time(), tz)


def load_sprints(tree: dict) -> dict[str, tuple[date, date]]:
    """Iteration path (as in System.IterationPath) -> (start, finish)."""
    sprints = {}

    def walk(node, path):
        a = node.get("attributes") or {}
        if a.get("startDate") and a.get("finishDate"):
            sprints[path] = (parse_dt(a["startDate"]).date(), parse_dt(a["finishDate"]).date())
        for child in node.get("children", []):
            walk(child, f"{path}\\{child['name']}")

    walk(tree, tree["name"])
    return sprints


def _changed(r: dict) -> datetime:
    return parse_dt(r["fields"]["System.ChangedDate"])


def snapshot(revs: list[dict], at: datetime) -> dict | None:
    known = [r for r in revs if _changed(r) <= at]
    return known[-1]["fields"] if known else None


def delivered_at(revs: list[dict], at: datetime, done: set[str]) -> datetime | None:
    """When the item last entered a done state, provided it is still done at `at`."""
    when, prev = None, None
    for r in revs:
        if _changed(r) > at:
            break
        st = r["fields"]["System.State"]
        if st in done and prev not in done:
            when = _changed(r)
        prev = st
    return when if prev in done else None


def is_agentic(fields: dict, rule: dict) -> bool:
    kind, value = rule["type"], rule["value"]
    if kind == "area_path":
        area = fields.get("System.AreaPath") or ""
        return area == value or area.startswith(value + "\\")
    if kind == "tag":
        return value.lower() in [t.strip().lower() for t in (fields.get("System.Tags") or "").split(";")]
    if kind == "field":
        return str(fields.get(rule["field"]) or "").lower() == str(value).lower()
    raise ValueError(f"unknown agentic_rule type {kind!r}")


def estimate_field(histories: dict[int, list[dict]], cfg: dict) -> str | None:
    if cfg["estimate"] == "count":
        return None
    if cfg["estimate"] == "hours":
        return cfg["hours_field"]
    if cfg["points_field"] != "auto":
        return cfg["points_field"]
    fill = {f: sum(1 for revs in histories.values() if revs and revs[-1]["fields"].get(f)) for f in POINT_FIELDS}
    return max(fill, key=fill.get)


def team_sprints(histories: dict[int, list[dict]], sprints: dict) -> dict[str, tuple[date, date]]:
    """Sprints this team actually uses: any iteration an item was ever in, plus its siblings."""
    used = {r["fields"].get("System.IterationPath") for revs in histories.values() for r in revs}
    parents = {p.rsplit("\\", 1)[0] for p in used if p in sprints}
    return {p: d for p, d in sprints.items() if p in used or p.rsplit("\\", 1)[0] in parents}


def build_items(histories: dict[int, list[dict]], cfg: dict, at: datetime, est_field: str | None) -> list[Item]:
    done, removed = set(cfg["done_states"]), set(cfg["removed_states"])
    items = []
    for wid, revs in histories.items():
        revs = sorted(revs, key=lambda r: r["rev"])
        f = snapshot(revs, at)
        if not f or f["System.WorkItemType"] not in cfg["work_item_types"] or f["System.State"] in removed:
            continue
        if cfg.get("area_path") and not (f.get("System.AreaPath") or "").startswith(cfg["area_path"]):
            continue
        if est_field is None:
            est = 1.0
        else:
            raw = f.get(est_field)
            est = float(raw) if raw not in (None, "") and float(raw) > 0 else None
        created, delivered = parse_dt(f.get("System.CreatedDate")), delivered_at(revs, at, done)
        items.append(Item(
            id=str(wid), title=f.get("System.Title", "") if cfg["include_titles"] else "",
            type=f["System.WorkItemType"], state=f["System.State"], estimate=est,
            agentic=is_agentic(f, cfg["agentic_rule"]), created=created, delivered=delivered,
            iteration=f.get("System.IterationPath"),
            priority=next((float(f[p]) for p in PRIORITY_FIELDS if f.get(p) is not None), float(wid)),
            backfilled=bool(delivered and created and
                            delivered - created <= timedelta(minutes=cfg["backfill_minutes"]))))
    return items


def fill_estimates(items: list[Item], cfg: dict) -> list[str]:
    """Apply the `unestimated` policy. Returns warnings."""
    missing = [i for i in items if i.estimate is None]
    if not missing:
        return []
    known = [i.estimate for i in items if i.estimate is not None]
    msg = f"{len(missing)} of {len(items)} items have no estimate"
    if cfg["unestimated"] == "median" and known:
        med = statistics.median(known)
        for i in missing:
            i.estimate, i.estimate_filled = med, True
        return [f"{msg}; filled with team median {med:g}"]
    items[:] = [i for i in items if i.estimate is not None]
    return [f"{msg}; excluded (set unestimated = \"median\" or estimate = \"count\" to include them)"]


def first_assignment(revs: list[dict], sprints: dict) -> str | None:
    return next((r["fields"].get("System.IterationPath") for r in sorted(revs, key=lambda r: r["rev"])
                 if r["fields"].get("System.IterationPath") in sprints), None)


def velocity(items: list[Item], sprints: dict, at: datetime, tz: ZoneInfo, n: int) -> tuple[float, list[str]]:
    """Average delivered estimate per sprint over the last n finished sprints before `at`."""
    finished = sorted((d for d in sprints.values() if d[1] < at.astimezone(tz).date()), key=lambda d: d[1])[-n:]
    if not finished:
        return 0.0, []
    per = []
    for s, f in finished:
        per.append(sum(i.estimate for i in items if i.delivered and not i.backfilled
                       and s <= i.delivered.astimezone(tz).date() <= f))
    return sum(per) / len(per), [f"{s}..{f}: {v:g}" for (s, f), v in zip(finished, per)]


def forecast(open_items: list[Item], sprints: dict, at: datetime, tz: ZoneInfo, vel: float) -> list[str]:
    """Give every open item a planned sprint.

    Items already in a current or future sprint keep it (the team's own plan). The rest are
    queued in backlog priority order into the remaining capacity (velocity minus what is already
    scheduled) of each future sprint; past the last defined sprint, sprints of the same length
    are synthesised. Without a velocity, unscheduled items stay unplanned.
    """
    today = at.astimezone(tz).date()
    future = sorted(((p, d) for p, d in sprints.items() if d[1] >= today), key=lambda x: x[1][0])
    load = {p: 0.0 for p, _ in future}
    queue = []
    for i in open_items:
        if i.iteration in load:
            s, f = sprints[i.iteration]
            i.planned_sprint, i.planned_start, i.planned_finish, i.plan_source = i.iteration, s, f, "sprint"
            load[i.iteration] += i.estimate
        else:
            queue.append(i)
    if not queue:
        return []
    if vel <= 0:
        for i in queue:
            i.plan_source, i.note = "unplanned", "no sprint and no velocity to forecast with"
        return [f"{len(queue)} open items have no sprint and no velocity is available; set velocity = <n>"]

    queue.sort(key=lambda i: i.priority)
    calendar = list(future)
    last_end = calendar[-1][1][1] if calendar else today
    length = (calendar[-1][1][1] - calendar[-1][1][0]).days + 1 if calendar else 14
    k, idx, used = 0, 0, None
    for i in queue:
        while True:
            if idx >= len(calendar):
                k += 1
                start = last_end + timedelta(days=1 + (k - 1) * length)
                calendar.append((f"Forecast sprint +{k}", (start, start + timedelta(days=length - 1))))
                load[calendar[-1][0]] = 0.0
            path, (s, f) = calendar[idx]
            used = load[path]
            if used == 0 or used + i.estimate <= vel:
                break
            idx += 1
        load[path] += i.estimate
        i.planned_sprint, i.planned_start, i.planned_finish, i.plan_source = path, s, f, "forecast"
    return [f"{len(queue)} unscheduled items forecast at velocity {vel:g} per sprint"]
