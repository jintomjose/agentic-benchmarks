"""Charts, item CSVs and the portfolio table."""
from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .backlog import Item
from .metrics import Result

PLAN, ACTUAL, INK, MUTED = "#8C96A3", "#E8561A", "#1F2933", "#616E7C"


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#CBD2D9")
    ax.tick_params(colors=MUTED, labelsize=11)
    ax.grid(axis="y", alpha=.25)


def _steps(events, start):
    remaining = sum(p for _, p in events)
    xs, ys = [start], [remaining]
    for when, p in sorted(events):
        remaining -= p
        xs.append(when)
        ys.append(remaining)
    return xs, ys


def chart(r: Result, items: list[Item], tz: ZoneInfo, path: Path):
    import matplotlib.dates as mdates
    plt = _plt()
    unit = r.estimate_unit
    fig, ax = plt.subplots(figsize=(14, 7.5), dpi=150)

    if r.mode == "baseline":
        plan_items = [i for i in items if not i.delivered and i.planned_finish]
        if not plan_items:
            plt.close(fig)
            return
        p0 = datetime.combine(date.fromisoformat(r.planned_start), datetime.min.time())
        ax.step(*_steps([(datetime.combine(i.planned_finish, datetime.max.time()), i.estimate) for i in plan_items], p0),
                where="post", lw=3, color=PLAN, label=f"Current plan: {r.planned_sprints} sprints, {r.planned_days} days")
        title = f"{r.product}: baseline plan for {r.total_estimate:.0f} {unit}"
        sub = f"frozen {r.as_of[:10]}  ·  ends {r.planned_end}" + (f"  ·  velocity {r.velocity:g}/sprint" if r.velocity else "")
    else:
        cmp = [i for i in items if i.in_comparison]
        if not cmp:
            plt.close(fig)
            return
        p0 = datetime.combine(date.fromisoformat(r.planned_start), datetime.min.time())
        a0 = datetime.combine(date.fromisoformat(r.actual_start), datetime.min.time())
        ax.step(*_steps([(datetime.combine(i.planned_finish, datetime.max.time()), i.estimate) for i in cmp], p0),
                where="post", lw=3, color=PLAN, label=f"Plan: {r.planned_sprints} sprints, {r.planned_days} days")
        ax.step(*_steps([(i.delivered.astimezone(tz).replace(tzinfo=None), i.estimate) for i in cmp], a0),
                where="post", lw=4, color=ACTUAL,
                label=f"Actual (agentic share {r.agentic_share_of_delivered:.0%}): {r.actual_days} days")
        title = f"{r.product}: plan vs actual on the same {r.compared_estimate:.0f} {unit}"
        sub = f"≈{r.compression:.1f}× calendar compression  ·  calendar time, not labour hours  ·  as of {r.as_of[:10]}"

    fig.suptitle(title, x=.06, ha="left", fontsize=20, weight="bold", color=INK)
    ax.set_title(sub, loc="left", fontsize=12, color=MUTED)
    ax.set_ylabel(f"{unit.capitalize()} remaining", fontsize=12, color=MUTED)
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    _style(ax)
    ax.legend(frameon=False, fontsize=12, loc="upper right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def portfolio_chart(results: list[Result], path: Path):
    plt = _plt()
    rows = sorted((r for r in results if r.compression), key=lambda r: r.compression)
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(12, 1.4 + .55 * len(rows)), dpi=150)
    ax.barh([r.product for r in rows], [r.compression for r in rows], color=ACTUAL, height=.55)
    for y, r in enumerate(rows):
        ax.text(r.compression, y, f"  ≈{r.compression:.1f}×  ({r.compared_estimate:.0f} {r.estimate_unit}, "
                f"{r.planned_days}d planned → {r.actual_days}d actual)", va="center", fontsize=10, color=INK)
    ax.axvline(1, color=PLAN, lw=1, ls="--")
    ax.text(1, len(rows) - .45, " 1× = on plan", color=MUTED, fontsize=9, va="bottom")
    ax.set_xlabel("Calendar compression (planned days ÷ actual days)", color=MUTED)
    ax.set_title("Agentic delivery vs plan, by product", loc="left", fontsize=15, weight="bold", color=INK)
    ax.set_xlim(0, max(r.compression for r in rows) * 1.7)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", alpha=.25)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def items_csv(items: list[Item], tz: ZoneInfo, path: Path):
    """Rows behind the chart. No assignees or other personal data."""
    cols = ["id", "title", "type", "state", "estimate", "estimate_filled", "agentic", "delivered_local",
            "planned_sprint", "planned_start", "planned_finish", "plan_source", "backfilled", "in_comparison", "note"]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for i in sorted(items, key=lambda i: (i.delivered is None, i.delivered.isoformat() if i.delivered else "", i.id)):
            w.writerow([i.id, i.title, i.type, i.state, f"{i.estimate:g}" if i.estimate is not None else "",
                        i.estimate_filled, i.agentic,
                        i.delivered.astimezone(tz).isoformat(timespec="minutes") if i.delivered else "",
                        i.planned_sprint or "", i.planned_start or "", i.planned_finish or "", i.plan_source,
                        i.backfilled, i.in_comparison, i.note])


def portfolio(results: list[Result], out: Path):
    cols = [k for k in asdict(results[0]) if k not in ("warnings", "excluded", "trend")]
    with open(out / "portfolio_summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols + ["excluded"])
        w.writeheader()
        for r in results:
            d = asdict(r)
            w.writerow({**{k: d[k] for k in cols}, "excluded": d["excluded"]})

    def fmt(r):
        plan = f"{r.planned_start} → {r.planned_end} ({r.planned_days}d)" if r.planned_days else "n/a"
        act = f"{r.actual_start} → {r.actual_end} ({r.actual_days}d)" if r.actual_days else "–"
        x = f"≈{r.compression:.1f}×" if r.compression else "–"
        proj = f"≈{r.projected_compression:.1f}× (ends {r.projected_end})" if r.projected_compression else "–"
        return (f"| {r.product} | {r.mode} | {r.as_of[:10]} | {r.total_estimate:.0f} {r.estimate_unit} | "
                f"{r.delivered_estimate:.0f} | {r.agentic_share_of_scope:.0%} | {plan} | {act} | {x} | {proj} |")

    lines = ["| Product | Mode | As of | Scope | Delivered | Agentic | Plan | Actual | Compression | Projected (full scope) |",
             "|---|---|---|---|---|---|---|---|---|---|", *map(fmt, results)]
    notes = [f"- **{r.product}**: {w}" for r in results for w in r.warnings]
    text = "# Agentic delivery vs plan\n\n" + "\n".join(lines) + "\n"
    if notes:
        text += "\n## Data-quality notes\n\n" + "\n".join(notes) + "\n"
    text += ("\nCompression = planned calendar days ÷ actual calendar days on the same delivered scope. "
             "Calendar time, not labour hours. Projection assumes the observed pace continues. See docs/METHOD.md.\n")
    (out / "portfolio_summary.md").write_text(text)


def print_result(r: Result, note: str = ""):
    u = r.estimate_unit
    print(f"\n=== {r.product}  [{r.mode}, as of {r.as_of[:16]}{note}]")
    if r.mode == "baseline":
        print(f"  Open scope: {r.work_items} items, {r.total_estimate:g} {u} | agentic-tagged {r.agentic_share_of_scope:.0%}")
        if r.velocity:
            print(f"  Velocity: {r.velocity:g} {u}/sprint")
        if r.planned_days:
            print(f"  Plan: {r.planned_start} → {r.planned_end} = {r.planned_days} days over {r.planned_sprints} sprints")
    else:
        print(f"  Scope {r.work_items} items / {r.total_estimate:g} {u} | delivered {r.delivered_estimate:g} | "
              f"remaining {r.remaining_estimate:g}")
        print(f"  Agentic: {r.agentic_share_of_scope:.0%} of scope, {r.agentic_share_of_delivered:.0%} of delivered")
        print(f"  Compared: {r.compared_items} items / {r.compared_estimate:g} {u}  (excluded {r.excluded})")
        if r.compression:
            print(f"  Plan   {r.planned_start} → {r.planned_end} = {r.planned_days} days, {r.planned_sprints} sprints")
            print(f"  Actual {r.actual_start} → {r.actual_end} = {r.actual_days} days")
            print(f"  Calendar compression ≈{r.compression:.1f}×")
        if r.projected_compression:
            print(f"  Projection, full baseline scope at current pace: ends {r.projected_end}, ≈{r.projected_compression:.1f}×")
        if r.last_activity:
            state = (f"PAUSED since {r.paused_since}: clock stopped at last build {r.last_activity}" if r.status == "paused"
                     else f"active: last build {r.last_activity}")
            print(f"  Pause diagnostic: {state} ({r.idle_days} days ago); measured to {r.measured_to}")
    for w in r.warnings:
        if not w.startswith("paused:"):
            print(f"  ! {w}")


def timeline(r: Result, items: list[Item], tz: ZoneInfo, path: Path):
    """Baseline vs agentic timeline: per planned sprint, the planned window (grey) and the span in
    which that sprint's scope was actually delivered (orange)."""
    import matplotlib.dates as mdates
    from collections import defaultdict
    from datetime import timedelta
    cmp = [i for i in items if i.in_comparison]
    if not cmp:
        return
    plt = _plt()
    groups = defaultdict(list)
    for i in cmp:
        groups[(i.planned_start, i.planned_finish, i.planned_sprint)].append(i)
    rows = sorted(groups.items(), key=lambda g: (g[0][1], g[0][0]))
    fig, ax = plt.subplots(figsize=(14, 1.6 + .62 * len(rows)), dpi=150)
    labels = []
    for y, ((s, f, name), its) in enumerate(rows):
        pts = sum(i.estimate for i in its)
        ax.barh(y - .17, (f - s).days + 1, left=s, height=.32, color=PLAN, alpha=.8)
        d = sorted(i.delivered.astimezone(tz).date() for i in its)
        ax.barh(y + .17, max((d[-1] - d[0]).days + 1, 1), left=d[0], height=.32, color=ACTUAL)
        ax.text(f + timedelta(days=1), y - .17, f" planned by {f:%b %d}", va="center", fontsize=9, color=MUTED)
        ax.text(d[-1] + timedelta(days=1), y + .17, f" delivered by {d[-1]:%b %d}", va="center", fontsize=9, color=INK)
        labels.append(f"{(name or '').split(chr(92))[-1]}  ·  {len(its)} item{'s' if len(its) != 1 else ''}, {pts:g} {r.estimate_unit}")
    ax.set_yticks(range(len(rows)), labels)
    ax.invert_yaxis()
    start = date.fromisoformat(r.actual_start)
    ax.axvline(start, color=INK, lw=1, ls=":")
    ax.text(start, len(rows) - .45, " agentic run starts", fontsize=9, color=INK, va="bottom")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    lo = min(min(s for (s, _, _), _ in rows), start)
    ax.set_xlim(lo - timedelta(days=2), max(f for (_, f, _), _ in rows) + timedelta(days=(max(f for (_, f, _), _ in rows) - lo).days * .22 + 6))
    fig.suptitle(f"{r.product}: baseline plan vs agentic delivery, by planned sprint", x=.02, ha="left",
                 fontsize=16, weight="bold", color=INK)
    ax.set_title("grey = sprint the work was planned in  ·  orange = when it was actually delivered",
                 loc="left", fontsize=11, color=MUTED)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", alpha=.25)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _two_panel(points, title, path, n_label=None):
    """Left: ×-speed over time; right: share of baseline delivered over time."""
    import matplotlib.dates as mdates
    plt = _plt()
    xs = [date.fromisoformat(p["date"]) for p in points]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 4.2), dpi=150)
    comp = [(x, p["compression"]) for x, p in zip(xs, points) if p.get("compression")]
    if comp:
        a1.plot(*zip(*comp), color=ACTUAL, lw=3, marker="o", ms=4, label="×-speed (delivered scope)")
    proj = [(x, p["projected"]) for x, p in zip(xs, points) if p.get("projected")]
    if proj:
        a1.plot(*zip(*proj), color=PLAN, lw=2, ls="--", label="projected, full baseline")
    a1.axhline(1, color=PLAN, lw=1, ls=":")
    a1.set_title("Calendar ×-speed", loc="left", fontsize=12, color=INK, weight="bold")
    a1.set_ylim(bottom=0)
    a1.legend(frameon=False, fontsize=9)
    a2.plot(xs, [100 * p["delivered_share"] for p in points], color=INK, lw=3, marker="o", ms=4)
    a2.set_ylim(0, 105)
    a2.set_title("% of baseline delivered", loc="left", fontsize=12, color=INK, weight="bold")
    if n_label:
        for x, p in zip(xs, points):
            a2.annotate(str(p[n_label]), (x, 100 * p["delivered_share"]), textcoords="offset points",
                        xytext=(0, 7), ha="center", fontsize=8, color=MUTED)
    for a in (a1, a2):
        a.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        _style(a)
    fig.suptitle(title, x=.02, ha="left", fontsize=15, weight="bold", color=INK)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def trend_chart(r: Result, path: Path):
    if len(r.trend) >= 2:
        _two_panel(r.trend, f"{r.product}: progress since the baseline", path)


def enterprise_trend_chart(points: list[dict], path: Path):
    if len(points) >= 2:
        _two_panel(points, "Enterprise: median across products (numbers = products reporting)", path, n_label="n")
