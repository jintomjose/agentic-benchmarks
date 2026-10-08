# Release notes

## 0.4.0 (2026-10-08): pause diagnostic

### New
- **Pause diagnostic.**
  - **What counts as paused:** a product with no build for more than `pause_after_days` (default 14) while baseline work remains. A build is the delivery of any in-scope item, baseline or added.
  - **What happens:** the product is marked **paused since <date>**, its **clock stops at the last build**, and the idle tail is not measured.
  - **Where it shows:** every `compare` and `retro` run prints a line per product, e.g. `Pause diagnostic: PAUSED since 2026-06-25: clock stopped at last build 2026-06-24 (106 days ago)`.
- **Enterprise overview:** the paused count sits next to the adoption funnel and in the summary sentence. Paused products get an amber "paused since" badge in the selector and the product table, plus an "N days idle" tile on their own page.
- `enterprise_summary.json` gains a `paused` count. Each product result gains `last_activity`, `idle_days`, `paused_since` and `measured_to`.

### Changed
- **Projection is measured over active time:** up to as-of while a product is active, and up to the last build once it is paused. This replaces 0.3.0's "all elapsed time", which counted a pause as a stall. Example from the pilot product, paused after Jun 24: the projection is ≈3.8× (finishing Jul 7 against a planned Sep 20), with "paused since 2026-06-25". In 0.3.0 the same product showed 0.4×.
- The 0.3.0 stall warning is replaced by the pause diagnostic.

## 0.3.0 (2026-10-08): enterprise reporting

### New

**Enterprise overview in `report.html`**, for senior management:
- **Adoption funnel:** onboarded → baseline frozen → delivering → ≥ 50% of baseline delivered.
- **Median ×-speed with its spread:** the middle half, or the range when there are fewer than 4 products.
- **Further medians:** % of baseline delivered, agentic share, projected ×-speed, and projected weeks against the baseline end date.
- **Business-unit rollup:** set the new `group` key in each product's config.
- **Weekly enterprise trend:** the median of each product's latest reading per week, with the number of products reporting.
- **All-products table:** with a status per product, and clickable.
- **Rules:** one vote per product, and only unit-free measures are rolled up. Points are never added up across teams.

**Product switcher.** A **View** selector at the top of `report.html` lists the Enterprise overview and every product, grouped by business unit. Each view has its own link (`report.html#<product>`). Without JavaScript, or when printed, every view shows in sequence.

**The shareable report.** `compare` and `retro` now write `out/report.html`, one self-contained file with images embedded. Per product it contains:
- Headline figures
- A **baseline vs agentic timeline** (planned sprint windows against actual delivery)
- A sprint-by-sprint table (planned done-by, actually done-by, days early, agentic share)
- A **progress trend** (×-speed, projection and % delivered per week)
- The burndown on the same scope
- All exclusions and warnings
- The caveats

**Trend from history.** `compare --trend weekly|daily|none` (default `weekly`) rebuilds every reading since the baseline from ADO revision history, so no stored state is needed.

**`out/enterprise_summary.json`.** The overall, per-business-unit and trend numbers, for dashboards.

**Docs.**
- `docs/GETTING_STARTED.md`:
  - a 5-minute offline demo
  - step-by-step paths for a product team and a central admin, including token scopes and the `az login` tenant fix
  - expected output and troubleshooting
- `CLAUDE.md` for contributors.
- A "Features and measures" section in the README.

### Changed
- **Projection measures pace over all elapsed time** up to the as-of date, not just up to the last delivery. A stalled product now projects late instead of early. A **stall warning** appears when no baseline item has been delivered for more than 14 days. On a real pilot backlog this changed the projection from "+11 weeks early" to "0.4×, ends 4 months late", which was correct.
- **Enterprise runs continue past failures.** A product with no baseline, or an access or config error, is listed with its status instead of stopping the run.
- **CSV products in `compare`** fall back to the `retro` method, so they still appear in the enterprise report.
- **GitHub Action** runs `compare` **daily** (06:00 UTC) in imported copies, and skips scheduled runs on the upstream template repo.
- **README** uses the real clone URL, `pip install git+https://…` for teams, and links to the guide.

## 0.2.0 (2026-10-08): first public version

- **Commands:**
  - `discover`: inspects an ADO project and suggests a config.
  - `baseline`: freezes the current plan (estimates, team sprints, velocity forecast for unscheduled items).
  - `compare`: measures delivered baseline scope against its plan.
  - `retro`: rebuilds the plan from revision history.
- **Estimation styles:** points, effort, size, hours, or item count, with the `unestimated = exclude | median` policy.
- **Process templates:** Scrum, Agile, CMMI and Basic. Done and removed states are configurable.
- **Agentic marker:** set by tag, area path or a custom field.
- **Product sources:** a central `portfolio.toml`, `.agentic-benchmark.toml` read from GitHub repos (`--repo`, `--github-org`), or a normalised CSV for other trackers.
- **Access:** read-only, via the `az` CLI (SSO) or `ADO_PAT` / `ADO_TOKEN`.
- **Data guards:** items re-sprinted after they were done keep their original plan. Backfilled items, scope added after the baseline, and removed items are reported but not compared.
- **Outputs:** burndown charts, per-item CSVs, and a portfolio summary (markdown, CSV, chart).
- **Claude Code skill** and a GitHub Actions workflow (baselines arrive as a pull request).
- **Validated** against a pilot product's published numbers. See `docs/METHOD.md`.
