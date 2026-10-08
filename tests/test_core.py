"""Offline tests on synthetic ADO revision histories (no network)."""
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from agentic_benchmark import backlog, metrics
from agentic_benchmark.config import DEFAULTS

UTC = ZoneInfo("UTC")
CFG = {**DEFAULTS, "timezone": "UTC", "work_item_types": ["User Story"],
       "points_field": "Microsoft.VSTS.Scheduling.StoryPoints", "name": "Test"}
SP = "Microsoft.VSTS.Scheduling.StoryPoints"
S0 = date(2026, 1, 5)
SPRINTS = {f"P\\S{n}": (S0 + timedelta(14 * (n - 1)), S0 + timedelta(14 * (n - 1) + 13)) for n in range(1, 6)}


def rev(n, when, state="New", it="P\\S2", pts=3, tags="", created="2026-01-01T09:00:00Z", prio=None):
    f = {"System.ChangedDate": when, "System.CreatedDate": created, "System.State": state,
         "System.WorkItemType": "User Story", "System.IterationPath": it, "System.Title": "t", "System.Tags": tags}
    if pts is not None:
        f[SP] = pts
    if prio is not None:
        f["Microsoft.VSTS.Common.BacklogPriority"] = prio
    return {"rev": n, "fields": f}


def at(d):
    return backlog.end_of_day(d, UTC)


def test_delivered_at_uses_last_entry_into_done_and_respects_reopen():
    revs = [rev(1, "2026-01-02T00:00:00Z"), rev(2, "2026-01-10T00:00:00Z", "Done"),
            rev(3, "2026-01-11T00:00:00Z", "Active"), rev(4, "2026-01-12T00:00:00Z", "Done")]
    assert backlog.delivered_at(revs, at("2026-01-10"), {"Done"}).day == 10
    assert backlog.delivered_at(revs, at("2026-01-11"), {"Done"}) is None
    assert backlog.delivered_at(revs, at("2026-01-31"), {"Done"}).day == 12


def test_original_plan_survives_resprinting_after_done():
    revs = [rev(1, "2026-01-02T00:00:00Z", it="P\\S4"), rev(2, "2026-01-08T00:00:00Z", "Done", it="P\\S4"),
            rev(3, "2026-01-09T00:00:00Z", "Done", it="P\\S1")]  # moved into the sprint it was finished in
    assert backlog.first_assignment(revs, SPRINTS) == "P\\S4"


def test_unestimated_items_excluded_or_median_filled():
    h = {1: [rev(1, "2026-01-02T00:00:00Z", pts=2)], 2: [rev(1, "2026-01-02T00:00:00Z", pts=None)],
         3: [rev(1, "2026-01-02T00:00:00Z", pts=4)]}
    items = backlog.build_items(h, CFG, at("2026-01-03"), SP)
    assert "excluded" in backlog.fill_estimates(items, CFG)[0] and len(items) == 2
    items = backlog.build_items(h, CFG, at("2026-01-03"), SP)
    backlog.fill_estimates(items, {**CFG, "unestimated": "median"})
    assert sorted(i.estimate for i in items) == [2, 3, 4]


def test_count_mode_gives_every_item_weight_one():
    h = {1: [rev(1, "2026-01-02T00:00:00Z", pts=None)], 2: [rev(1, "2026-01-02T00:00:00Z", pts=8)]}
    items = backlog.build_items(h, {**CFG, "estimate": "count"}, at("2026-01-03"), None)
    assert [i.estimate for i in items] == [1.0, 1.0]


def test_velocity_and_forecast_fill_future_sprints_by_priority():
    hist = {n: [rev(1, "2026-01-02T00:00:00Z", it="P\\S1"), rev(2, f"2026-01-1{n}T10:00:00Z", "Done", it="P\\S1")]
            for n in range(1, 4)}  # 3 x 3 pts done in S1 -> velocity 9
    for n, prio in [(10, 2), (11, 1), (12, 3), (13, 4)]:
        hist[n] = [rev(1, "2026-01-02T00:00:00Z", it="P", pts=5, prio=prio)]  # unscheduled, 20 pts
    now = at("2026-01-19")
    items = backlog.build_items(hist, CFG, now, SP)
    vel, _ = backlog.velocity(items, SPRINTS, now, UTC, 3)
    assert vel == 9
    open_items = [i for i in items if not i.delivered]
    backlog.forecast(open_items, SPRINTS, now, UTC, vel)
    plan = {i.id: i.planned_sprint for i in open_items}
    assert plan == {"11": "P\\S2", "10": "P\\S3", "12": "P\\S4", "13": "P\\S5"}


def test_compare_uses_baseline_plan_and_reports_compression():
    hist = {1: [rev(1, "2026-01-02T00:00:00Z", it="P\\S3", pts=5)],
            2: [rev(1, "2026-01-02T00:00:00Z", it="P\\S5", pts=3)]}
    t0 = at("2026-01-19")
    items = backlog.build_items(hist, CFG, t0, SP)
    backlog.forecast(items, SPRINTS, t0, UTC, 0)
    r0 = metrics.baseline("Test", items, CFG, t0, "points", 0, [])
    doc = metrics.baseline_doc(r0, items, CFG)
    assert r0.planned_end == "2026-03-15" and r0.total_estimate == 8

    hist[1].append(rev(2, "2026-01-20T12:00:00Z", "Done", it="P\\S3", pts=13))  # re-estimated: ignored
    hist[2].append(rev(2, "2026-01-22T12:00:00Z", "Done", it="P\\S5"))
    hist[3] = [rev(1, "2026-01-21T00:00:00Z", created="2026-01-21T00:00:00Z")]  # added later: not compared
    now = at("2026-01-31")
    r = metrics.compare("Test", doc, backlog.build_items(hist, CFG, now, SP), CFG, now, "points")
    assert r.compared_estimate == 8
    assert (r.planned_days, r.actual_days) == (56, 4)  # Jan 19 -> Mar 15 vs Jan 19 -> Jan 22
    assert r.compression == 14
    assert r.excluded["added_since_baseline"] == 3


def test_backfilled_items_excluded_from_retro_time_comparison():
    hist = {1: [rev(1, "2026-01-20T09:00:00Z", created="2026-01-20T09:00:00Z", it="P\\S1"),
                rev(2, "2026-01-20T09:05:00Z", "Done", it="P\\S1", created="2026-01-20T09:00:00Z")],
            2: [rev(1, "2026-01-02T00:00:00Z", it="P\\S4"), rev(2, "2026-01-21T00:00:00Z", "Done", it="P\\S4")]}
    now = at("2026-01-31")
    items = backlog.build_items(hist, CFG, now, SP)
    r = metrics.retro("Test", items, hist, SPRINTS, {**CFG, "run_start": "2026-01-20"}, now, "points")
    assert r.excluded["backfilled"] == 3 and r.compared_estimate == 3
