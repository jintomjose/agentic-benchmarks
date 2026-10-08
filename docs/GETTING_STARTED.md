# Getting started

Pick your path:

- **[A. Try it in 5 minutes](#a-try-it-in-5-minutes-no-azure-devops-needed)**: no Azure DevOps access needed.
- **[B. Product team](#b-product-team-measure-your-own-product)**: measure your own product.
- **[C. Central admin](#c-central-admin-many-products)**: measure many products from one place.

---

## A. Try it in 5 minutes (no Azure DevOps needed)

**macOS / Linux**
```bash
git clone https://github.com/jintomjose/agentic-benchmarks.git
cd agentic-benchmarks
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
pytest -q
agentic-benchmark retro --config examples/portfolio.toml --out out/demo
```

**Windows (PowerShell)**
```powershell
git clone https://github.com/jintomjose/agentic-benchmarks.git
cd agentic-benchmarks
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest -q
agentic-benchmark retro --config examples/portfolio.toml --out out/demo
```

**You should see:** `7 passed`, then two synthetic products, with these files in `out/demo/`:

```
=== Synthetic product A  [retro, as of 2026-10-08]
  Scope 60 items / 206 points | delivered 134 | remaining 72
  ...
  Calendar compression ≈8.6×
...
Wrote out/demo/portfolio_summary.md, portfolio_summary.csv, portfolio_compression.png
```

Open `out/demo/portfolio_summary.md` and `out/demo/synthetic-product-a/retro_burndown.png` to see what the reports look like.

---

## B. Product team: measure your own product

You run three commands over the life of the change:

- `discover` once, to set up.
- `baseline` once, **before** agents start.
- `compare` whenever you want a reading.

### B1. Install (once)

You don't need to clone this repo. Install the tool, then run it from inside your product repo:

```bash
python3 -m venv ~/.venvs/agentic-benchmark
source ~/.venvs/agentic-benchmark/bin/activate        # Windows: ~\.venvs\agentic-benchmark\Scripts\Activate.ps1
pip install "git+https://github.com/jintomjose/agentic-benchmarks.git"
agentic-benchmark --help
```

### B2. Give it read access to Azure DevOps (once)

Pick **one** option.

**Option 1: Azure CLI (recommended on a company laptop, uses your SSO)**
```bash
az extension add --name azure-devops
az login                                   # if your org has several tenants: az login --tenant <tenant-id>
az boards query --org https://dev.azure.com/<org> --project <project> --wiql "SELECT [System.Id] FROM WorkItems" --query "length(@)"
```
If the last command prints a number, you're set.

**Option 2: Personal Access Token (PAT)**
1. In Azure DevOps, go to *User settings → Personal access tokens → New token*.
2. Scope: **Work Items: Read**, and nothing else. Set a short expiry.
3. Put it in an environment variable for the session. Never put it in a file you commit.
   ```bash
   export ADO_PAT=<token>                     # Windows: $env:ADO_PAT = "<token>"
   ```
The tool only ever reads from Azure DevOps.

### B3. Discover your backlog and write the config (once)

From the root of your product repo:

```bash
agentic-benchmark discover --org https://dev.azure.com/<org> --project "<project>" --area-path "<project>\<team area>"
```

It prints your work item types and states, which estimate field your team actually fills, your area paths and iterations, any tags, and a **suggested config**. Paste that config into `.agentic-benchmark.toml` at your repo root and check these items:

- [ ] `work_item_types`: only the types you estimate and deliver (usually User Story / PBI and Bug).
- [ ] `estimate`: `points` if most items have points. If fewer than about 70% are estimated, use `unestimated = "median"`, or `estimate = "count"` if you don't estimate at all.
- [ ] `done_states`: the states that mean "delivered" in your process.
- [ ] `agentic_rule`: **agree it now, before agents start.** The simplest is a tag: `agentic_rule = { type = "tag", value = "Agentic" }`. Every agent-built item must carry it.
- [ ] `run_start`: the day the agentic way of working starts, e.g. `run_start = "2026-11-02"`.

See [examples/team-repo/.agentic-benchmark.toml](../examples/team-repo/.agentic-benchmark.toml) for a complete example. Commit the file.

### B4. Freeze the baseline (once, before agents start)

```bash
agentic-benchmark baseline --config .agentic-benchmark.toml
```

**You should see** your open scope, your velocity, the plan's end date and any warnings, then:
```
  -> baselines/<product>/<date>.json  (commit this file: it is the frozen plan)
```
Commit `baselines/`, and add `out/` to your `.gitignore`. `out/cache/` holds raw ADO history, which includes people's names. The baseline file is the contract: re-estimating or re-planning in ADO later doesn't change it. A picture of the plan is written to `out/<product>/baseline_plan.png`.

Check the warnings before you commit:
- *"N items have no estimate; excluded"*: estimate them, or switch to `unestimated = "median"`, then re-run.
- *"N open items have no sprint and no velocity is available"*: add `velocity = <your average per sprint>` to the config, then re-run.

### B5. Measure (any time after)

```bash
agentic-benchmark compare --config .agentic-benchmark.toml
```

**You should see:**
```
=== <product>  [compare, as of ..., baseline <date>.json]
  Scope 38 items / 131 points | delivered 64 | remaining 67
  Agentic: 94% of scope, 95% of delivered
  Plan   2026-06-11 → 2026-09-06 = 88 days, 5 sprints
  Actual 2026-06-11 → 2026-06-13 = 3 days
  Calendar compression ≈29.3×
  Projection, full baseline scope at current pace: ends 2026-06-16, ≈17.0×
```

Read `out/<product>/compare_burndown.png` and `out/<product>/compare_items.csv`; every number can be traced to a row in that CSV. Before you share a number, read the caveats in [METHOD.md](METHOD.md).

To see the numbers as they stood on an earlier day: `agentic-benchmark compare --config .agentic-benchmark.toml --as-of 2026-12-01`.

---

## C. Central admin: many products

### C1. Install and authenticate

Install as in [B1](#b1-install-once). Authenticate to ADO as in [B2](#b2-give-it-read-access-to-azure-devops-once); the PAT needs *Work Items: Read* on every ADO org in scope. Then sign in to GitHub so the tool can read each team's config file:

```bash
gh auth login
```

### C2. Collect the products

Use either source:

- **Team-owned configs (recommended):** each team commits `.agentic-benchmark.toml` (section B3). You point at their repos:
  ```bash
  agentic-benchmark discover --repo my-org/mortgage-app     # checks one team's config against ADO
  agentic-benchmark baseline --github-org my-org            # every repo in the org that has the file
  ```
- **One central file:** copy [examples/portfolio.toml](../examples/portfolio.toml) and add a `[[product]]` block per product. Use this for products whose code is in Azure Repos.
  ```bash
  agentic-benchmark baseline --config portfolio.toml
  ```

### C3. Measure and report

```bash
agentic-benchmark compare --github-org my-org --out out/2026-12
```

`out/2026-12/portfolio_summary.md` holds one row per product, and `portfolio_compression.png` is the chart for leadership.

### C4. Run it automatically with GitHub Actions

1. Import this repo into your organisation (*New repository → Import a repository*), or fork it. Forks keep scheduled workflows off until you enable them in the **Actions** tab.
2. Under *Settings → Secrets and variables → Actions*, add:

   | Name | Kind | Value |
   |---|---|---|
   | `ADO_PAT` | Secret | Azure DevOps PAT, *Work Items: Read* |
   | `CONFIG_READ_TOKEN` | Secret | GitHub fine-grained token, *Contents: Read-only* on the product repos |
   | `PRODUCT_GITHUB_ORG` | Variable | the GitHub org that holds the product repos |

3. Go to *Actions → agentic-benchmark → Run workflow → baseline*. The new baselines arrive as a pull request; review and merge it.
4. From then on, `compare` runs **every day at 06:00 UTC**. Reports are attached to each run as an artifact.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `no products: pass --config, --repo ... or --github-org` | The config file path is wrong, or the repo has no `.agentic-benchmark.toml` at its root (or you lack access: try `gh repo view <repo>`) |
| `az ... failed: ... AADSTS` / tenant errors | `az login --tenant <tenant-id>`, or use a PAT (`export ADO_PAT=...`) |
| `transport = 'rest' needs ADO_PAT or ADO_TOKEN` | Set `ADO_PAT`, or remove `transport = "rest"` to use the Azure CLI |
| Scope is 0 or far too small | Check `work_item_types`, `area_path` (it must match ADO exactly, including the project prefix) and the estimate field. Re-run `discover` |
| `nothing from the baseline has been delivered yet` | Expected early on. Check that `done_states` matches your process |
| Agentic share is 0% | Items aren't marked yet, or `agentic_rule` doesn't match what the team uses. `discover` lists the tags and area paths that are actually in use |
| Huge × in the first week | A handful of quick items. Lead with the projection line and wait until a meaningful share of the baseline is delivered ([METHOD.md](METHOD.md), caveat 6) |
| Slow on large backlogs | One revision call per item. Narrow with `area_path`, use a PAT (REST is faster than `az`), and use `--offline` to reuse the cache when re-running |
