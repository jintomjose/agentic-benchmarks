# Method and caveats

## The question

*How long would the scope we actually delivered have taken under the plan we had before the agentic SDLC started?*

## Forward method: `baseline` then `compare` (recommended)

**Baseline (T0).** Taken before the agentic run starts.

- **Scope**: every item of the configured types that is open at T0, has an estimate, and isn't removed. Unestimated items are either excluded with a warning or filled with the team median (`unestimated`). Teams that don't estimate use `estimate = "count"` (throughput).
- **Plan per item**:
  - If the item sits in a current or future sprint, its plan is that sprint's finish date (the team's own plan).
  - Otherwise it gets a forecast: unscheduled items are queued in backlog priority order (BacklogPriority / StackRank) into each future sprint's leftover capacity, which is velocity minus what's already scheduled there. Beyond the last defined sprint, sprints of the same length are added.
  - Items assigned to a sprint that has already ended are treated as unscheduled.
- **Velocity**: the average of the estimates delivered in the last `velocity_sprints` finished sprints (backfilled items don't count), or a fixed number. If there's no velocity, unscheduled items stay *unplanned* and are reported.
- The baseline is written to `baselines/<product>/<date>.json` and should be committed. From then on it is the contract: re-estimating or re-sprinting in ADO cannot change it.

**Compare (T1…Tn).**

- **Delivered**: a baseline item that is in a done state at Tn, and whose last entry into done came after T0. The timestamp comes from revision history.
- **Same scope on both lines**: each delivered baseline item burns down at its planned finish date (plan line) and at its actual delivery (actual line). Estimates come from the baseline.
- **×-speed (compression)** = planned calendar days ÷ actual calendar days. Both clocks start on the baseline day, or on `run_start` if that's later. Days are counted inclusively, in the configured timezone.
- **Pause diagnostic**: the *last build* is the last delivery of any in-scope item after the baseline (baseline or added scope). If nothing has been built for more than `pause_after_days` (default 14) and baseline work remains, the product is **paused since** the day after its last build. Its clock stops at the last build, so the idle tail is not measured. The product is flagged in the report, and its figures stay frozen until delivery resumes. A gap of 14 days or less counts as active time.
- **Projection**: the full baseline scope at the pace observed so far, compared with the baseline's end date. Pace = delivered estimate ÷ calendar days of the measured period: from the baseline (or `run_start`) to the as-of date, or to the last build if the product is paused. It is always labelled as a projection.
- **Trend**: `compare` rebuilds the reading for each week since the baseline from revision history (`--trend weekly|daily|none`).
- **Scope added after T0** is reported but never compared, because it has no prior plan. **Baseline items removed** since T0 are reported as well.
- **Agentic share**: the share of delivered items, by estimate, that match `agentic_rule` at Tn.

## Enterprise rollup

Estimates are relative to each team, so nothing is summed across products. Every product counts once, and only unit-free measures are rolled up:

- **Adoption funnel:** onboarded → baseline frozen → delivering → ≥ 50% of baseline delivered, plus how many products are paused.
- **Medians across delivering products:** ×-speed, with its spread (middle half, or the range when there are fewer than 4 products), % of baseline delivered, agentic share, and projected weeks against the baseline end date.
- **Trend:** per calendar week, the median of each product's latest reading that week. The number of products reporting is shown on the chart.
- **Business units:** the same measures per `group`.

A product that can't be read (missing baseline, auth error) is listed with its status and never stops the run.

## Retrospective method: `retro`

Use this when no baseline was taken. The plan is rebuilt from revision history: by default the first sprint each item was ever given, or the sprint it was in on a fixed date (`plan_baseline = "YYYY-MM-DD"`). This matters because teams often move finished items into the sprint they actually completed them in, so the current iteration path is not the plan. Items created already done (`backfill_minutes`) are logging events, not build events, and are excluded from the time comparison by default.

## Caveats to state wherever a number is used

1. **It compares plan with actual. It is not a controlled human-versus-agent experiment.** Plans contain padding, dependencies and capacity limits that an agentic run may not face, and the same plan could have been beaten by humans too.
2. **×-speed is calendar time, not labour hours.** It says nothing about effort, cost or quality on its own.
3. **Estimates are team-relative.** Compare ×-speed across products, never raw points.
4. **Agentic share depends on tagging discipline.** Spot-check `compare_items.csv`.
5. **Done is not value.** Report quality signals alongside speed: escaped defects, change failure rate, rework.
6. **Paused products are frozen, not finished.** Stopping the clock at the last build keeps idle time out of the numbers, but the work remaining is still open. Always show the paused status next to the figures. If a paused product resumes, the pause becomes a gap *inside* the measured period and counts as elapsed time.
7. **Early compares are noisy.** A few fast items can give a large × in week one. Prefer the projection, and quote numbers only once a meaningful share of the baseline has been delivered.

## Validation: Momentum (pilot product)

The tool reproduces the published Momentum numbers from live ADO history, as of 2026-06-14.

| Metric | Published | Tool | |
|---|---|---|---|
| Items / points / delivered / remaining | 75 / 248 / 118 / 130 | 75 / 248 / 118 / 130 | ✅ |
| Agentic share of scope | ~89% | 89% | ✅ |
| Actual window | Jun 11–13 | Jun 11–13 (UTC) | ✅ |
| Planned window | Jun 1 → Aug 9 | Jun 1 → Sep 6 | ❌ one 3-pt PBI was first planned in Sprint 8; without it the tool gives Jun 1 → Aug 9 (70 days) and ≈23× |
| ×-speed, `retro` strict (backfilled migration items excluded) | – | ≈29× on 66 pts | |
| ×-speed, `baseline` on Jun 11 → `compare` on Jun 14 | – | ≈29× on 64 pts | consistent with strict retro |
