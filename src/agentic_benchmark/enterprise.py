"""Enterprise rollup. Estimates are team-relative, so nothing is summed across products:
every product gets one vote, and only unit-free measures (ratios, counts, calendar weeks) are aggregated."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

from .metrics import Result


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _quartiles(xs):
    xs = sorted(x for x in xs if x is not None)
    if len(xs) < 4:
        return (xs[0], xs[-1]) if xs else (None, None)
    q = statistics.quantiles(xs, n=4)
    return q[0], q[2]


def delivered_share(r: Result) -> float | None:
    return r.delivered_estimate / r.total_estimate if r.total_estimate else None


def weeks_pulled_forward(r: Result) -> float | None:
    if r.baseline_end and r.projected_end:
        return (date.fromisoformat(r.baseline_end) - date.fromisoformat(r.projected_end)).days / 7
    return None


def stats(results: list[Result]) -> dict:
    measured = [r for r in results if r.status not in ("no_baseline", "error")]
    delivering = [r for r in measured if r.compression]
    xs = [r.compression for r in delivering]
    lo, hi = _quartiles(xs)
    return {
        "products": len(results),
        "baselined": len(measured),
        "delivering": len(delivering),
        "half_delivered": sum(1 for r in measured if (delivered_share(r) or 0) >= .5),
        "no_baseline": sum(1 for r in results if r.status == "no_baseline"),
        "errors": sum(1 for r in results if r.status == "error"),
        "median_x": _med(xs), "x_p25": lo, "x_p75": hi,
        "min_x": min(xs) if xs else None, "max_x": max(xs) if xs else None,
        "median_delivered_share": _med([delivered_share(r) for r in measured]),
        "median_agentic_share": _med([r.agentic_share_of_delivered for r in delivering]),
        "median_weeks_forward": _med([weeks_pulled_forward(r) for r in delivering]),
        "median_projected_x": _med([r.projected_compression for r in delivering]),
    }


def by_group(results: list[Result]) -> dict[str, dict]:
    groups = defaultdict(list)
    for r in results:
        groups[r.group or "Ungrouped"].append(r)
    return {g: stats(rs) for g, rs in sorted(groups.items())}


def trend(results: list[Result]) -> list[dict]:
    """Per calendar week (ending Sunday): median across products of their latest reading that week."""
    weekly = defaultdict(dict)
    for r in results:
        for p in r.trend:
            d = date.fromisoformat(p["date"])
            wk = d + timedelta(days=6 - d.weekday())
            weekly[wk][r.product] = p  # readings are chronological, so the last one in the week wins
    out = []
    for wk in sorted(weekly):
        ps = list(weekly[wk].values())
        out.append({"date": wk.isoformat(), "n": len(ps),
                    "compression": _med([p["compression"] for p in ps]),
                    "projected": _med([p["projected"] for p in ps]),
                    "delivered_share": _med([p["delivered_share"] for p in ps]) or 0,
                    "agentic_share": _med([p["agentic_share"] for p in ps if p["compression"]])})
    return out
