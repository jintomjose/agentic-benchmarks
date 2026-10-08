# CLAUDE.md

Guidance for Claude Code (and humans) working on this repo.

## What this is

`agentic-benchmark` measures how much faster agentic delivery lands than a product's **own plan** in Azure DevOps:
1. Freeze a baseline before the agentic run.
2. Compare later.
3. Report ×-speed per product and for the enterprise.

User docs:
- [README.md](README.md): features, measures, configuration
- [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md): step by step
- [docs/METHOD.md](docs/METHOD.md): definitions and caveats
- [RELEASE_NOTES.md](RELEASE_NOTES.md): what changed

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[test]"
pytest -q                                                                 # offline, no ADO needed
agentic-benchmark retro --config examples/portfolio.toml --out out/demo   # offline demo, writes out/demo/report.html
agentic-benchmark discover|baseline|compare|retro --help
```

## Code map (`src/agentic_benchmark/`)

| Module | Responsibility |
|---|---|
| `cli.py` | Subcommands. `each_product()` isolates every product: a failure becomes a status (`error`, `no_baseline`), never a crash. `trend_dates()` sets up the trend readings |
| `config.py` | `DEFAULTS` (every config key and its default), TOML loading, `.agentic-benchmark.toml` from GitHub via `gh`, `slug()` |
| `ado.py` | Read-only ADO access. `AzCliTransport` and `RestTransport` share one interface. `transport = "auto"` picks REST when `ADO_PAT`/`ADO_TOKEN` is set. Revisions are cached under `out/cache/` |
| `backlog.py` | Revision history → `Item` as of a moment: `snapshot`, `delivered_at` (last entry into a done state), estimates, `first_assignment`, `velocity`, `forecast` |
| `metrics.py` | `Result`, plus `baseline`, `baseline_doc`, `compare` (including projection and stall warning) and `retro`. Also CSV loading |
| `enterprise.py` | Unit-free rollup: `stats`, `by_group`, `trend`, `delivered_share`, `weeks_pulled_forward` |
| `report.py` | matplotlib charts (burndown, timeline, product and enterprise trend, portfolio), item CSVs, `portfolio_summary.md/csv` |
| `htmlreport.py` | The self-contained `report.html`: enterprise overview, per-product views, the View selector |

## Measures (keep README, METHOD.md and the code in sync)

**Per product**

| Measure | Definition |
|---|---|
| ×-speed | planned calendar days ÷ actual calendar days, same delivered baseline scope, both inclusive, local timezone |
| Clocks | both start on the baseline date (or `run_start` if later). Retro: `plan_clock = run_start | first_sprint` |
| Delivered | done at as-of, *and* its last entry into done came after the baseline |
| Plan per item | team's current or future sprint at baseline; otherwise a forecast in priority order into each sprint's leftover capacity (velocity minus what's scheduled); otherwise *unplanned* |
| Velocity | mean delivered estimate over the last N finished team sprints (backfilled items excluded), or a fixed value |
| % delivered | delivered baseline estimate ÷ total baseline estimate |
| Agentic share | delivered estimate matching `agentic_rule`, evaluated at as-of |
| Pause diagnostic | last build = last delivery of any in-scope item after the baseline. Idle > `pause_after_days` (14) with work remaining → `status = paused`, `paused_since`, `measured_to = last build` |
| Projection | total ÷ (delivered ÷ days of the measured period). The measured period ends at as-of, or at the **last build when paused**, so the idle tail is not counted |
| Weeks vs plan | (baseline end − projected end) ÷ 7 |

**Enterprise**

| Measure | Definition |
|---|---|
| Funnel | onboarded → baselined → delivering → ≥ 50% delivered, plus a paused count |
| Medians | ×-speed (with middle half or range), % delivered, agentic share, projected ×, weeks vs plan |
| Rollup | the same per `group` |
| Trend | per ISO week, the median of each product's latest reading, with `n` |

## Invariants: do not break these

1. **Read-only against ADO.** No POST except WIQL and `workitemsbatch` reads.
2. **Never sum or average estimates across products.** Points and hours are team-relative. Enterprise numbers use counts, ratios and calendar weeks, one vote per product.
3. **The baseline file is the contract.** `compare` uses the baseline's estimates and planned dates, so re-estimating or re-sprinting in ADO must not move results. Scope added after the baseline is reported, never compared.
4. **The plan is never the current iteration path** when history says otherwise. Items get re-sprinted after they're done.
5. **No personal data in outputs.** No assignees or emails in CSV, JSON, charts or HTML. `out/cache/` holds raw revisions (with names) and is git-ignored.
6. **Never silently tune numbers.** Every exclusion goes into `Result.excluded` or `warnings` and shows in the report.
7. **Caveats ship with every report:** plan vs actual (not a controlled experiment), calendar time (not labour hours), and so on.
8. **One product's failure never stops an enterprise run.**
9. **Paused is always visible.** Stopping the clock at the last build must come with a `paused since` badge, a warning and the funnel count. Never drop or hide a paused product.

## Conventions

- Python ≥ 3.11, stdlib plus matplotlib only. No new runtime dependencies without a strong reason.
- Datetimes are timezone-aware (UTC from ADO). Convert to the configured `timezone` only when turning them into calendar days.
- Tests (`tests/test_core.py`) build synthetic revision histories with `rev(...)`. Add a test for every new measure or guard.
- When you add a config key: put it in `config.DEFAULTS` (with a comment), the README configuration table, and the examples if relevant.
- When you add or change a measure: update the README "Features and measures" section, `docs/METHOD.md`, this file, and `RELEASE_NOTES.md`.
- Bump `version` in `pyproject.toml` and `src/agentic_benchmark/__init__.py` with each release note entry.
- The upstream repo (`jintomjose/agentic-benchmarks`) skips scheduled workflow runs on purpose. Keep the `if:` guard in `.github/workflows/benchmark.yml`.
