---
name: agentic-benchmark
description: Measure agentic delivery against a product's own plan in Azure DevOps. Use when a team wants to set up the benchmark, freeze a delivery baseline before starting agentic SDLC, compare progress against that baseline ("how many times faster are we?"), or write up ×-speed results for leadership. Triggers on "baseline our backlog", "agentic benchmark", "x-speed", "plan vs actual", "compression", "how much faster did the agents deliver".
---

# Agentic benchmark

You drive the `agentic-benchmark` CLI (`pip install` from this repo). It is read-only against Azure DevOps. Never write to work items.

## 1. Set up (once per team)
1. Ask for the ADO org URL, the project, and the team's area path if the project is shared.
2. Run `agentic-benchmark discover --org <url> --project <p> [--area-path <a>]`.
3. Review the suggestion with the user:
   - **Estimates**: which field is actually filled? If under ~70% of items are estimated, propose `unestimated = "median"` or `estimate = "count"`, and say why.
   - **Done states**: do they match how the team closes work?
   - **Agentic marker**: if discover found none, agree one *before* agents start (a tag such as `Agentic` is simplest) and tell the team it must be applied to every agent-built item.
4. Write `.agentic-benchmark.toml` at the repo root, with `run_start` set to the agreed start date.

## 2. Baseline (before agents start)
- Run `agentic-benchmark baseline --config .agentic-benchmark.toml`.
- Show the plan end date, velocity, and any warnings: unplanned items, excluded unestimated items.
- If velocity is 0 and items are unscheduled, ask the team for a velocity rather than inventing one.
- Ask the user to commit `baselines/<product>/<date>.json`. It is the contract.

## 3. Compare (any time after)
- Run `agentic-benchmark compare --config .agentic-benchmark.toml`.
- Report, in this order:
  1. ×-speed on the delivered scope, with planned days and actual days.
  2. How much of the baseline has been delivered (scope delivered as a %).
  3. The projection for the full scope.
  4. Agentic share of the delivered work.
  5. Every warning.
- Below ~25% of the baseline delivered, lead with the projection and call the number early.

## 4. Writing it up
Always include, in plain words:
- It compares plan with actual. It is not a controlled human-versus-agent experiment.
- ×-speed is calendar time, not labour hours.
- Anything that was excluded, and why (added scope, removed items, unplanned items).

Don't round in the product's favour, and don't drop warnings. Link `compare_items.csv` so anyone can check the rows.
