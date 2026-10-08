"""One self-contained HTML report per run: an enterprise overview plus one view per product,
switched with a selector (grouped by business unit). Without JavaScript every view is shown in sequence."""
from __future__ import annotations

import base64
import json
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from . import enterprise, report
from .config import slug

CSS = """
:root{--bg:#fff;--fg:#1f2933;--muted:#616e7c;--line:#e4e7eb;--card:#f7f8fa;--accent:#e8561a;--plan:#8c96a3;
--ok:#2f7d4f;--warn:#b7791f;--bad:#c53030}
@media (prefers-color-scheme:dark){:root{--bg:#14181d;--fg:#e4e7eb;--muted:#9aa5b1;--line:#2b323b;--card:#1c2228;
--ok:#68d391;--warn:#f6ad55;--bad:#fc8181}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line)}
.bar{max-width:1140px;margin:0 auto;padding:10px 16px;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}
.bar strong{font-size:16px;margin-right:auto}.bar label{font-size:13px;color:var(--muted)}
select{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);max-width:100%}
main{max-width:1140px;margin:0 auto;padding:16px 16px 64px}
h1{font-size:26px;margin:16px 0 4px}h2{font-size:19px;margin:32px 0 8px}h3{font-size:16px;margin:24px 0 8px}
.muted{color:var(--muted)}.lead{font-size:17px;margin:14px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile b{display:block;font-size:23px;line-height:1.2}.tile.hero b{color:var(--accent);font-size:29px}
.tile span{font-size:13px;color:var(--muted)}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600}.num{text-align:right}
a{color:inherit}td a{font-weight:600}
img{max-width:100%;height:auto;border-radius:8px;background:#fff;margin:8px 0}
.warn{border-left:3px solid var(--accent);padding:6px 12px;background:var(--card);margin:6px 0;font-size:14px}
.badge{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid currentColor}
.s-ok{color:var(--ok)}.s-no_delivery{color:var(--warn)}.s-no_baseline{color:var(--muted)}.s-error{color:var(--bad)}
.funnel div{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:14px}
.funnel i{display:block;height:18px;background:var(--accent);border-radius:4px;min-width:2px}
.funnel span{width:230px;flex:none;color:var(--muted)}
.back{font-size:14px}
@media (max-width:640px){.funnel span{width:130px}}
@media print{header{position:static}section[hidden]{display:block!important}}
"""

JS = """
const sel=document.getElementById('view');
const views=[...document.querySelectorAll('section[data-view]')];
function show(v){if(!views.some(s=>s.dataset.view===v))v='enterprise';
 views.forEach(s=>s.hidden=s.dataset.view!==v);sel.value=v;
 if(location.hash.slice(1)!==v)history.replaceState(null,'','#'+v);window.scrollTo(0,0);}
sel.addEventListener('change',()=>show(sel.value));
window.addEventListener('hashchange',()=>show(location.hash.slice(1)));
show(location.hash.slice(1)||'enterprise');
"""

STATUS = {"ok": "measured", "no_delivery": "baselined, nothing delivered yet",
          "no_baseline": "no baseline yet", "error": "error"}


def _img(path: Path) -> str:
    if not path.exists():
        return ""
    return f'<img alt="{escape(path.stem)}" src="data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}">'


def _x(v) -> str:
    return f"≈{v:.1f}×" if v else "–"


def _pct(v) -> str:
    return f"{v:.0%}" if v is not None else "–"


def _wk(v) -> str:
    if v is None:
        return "–"
    return f"{v:.0f} wk early" if v >= .5 else f"{-v:.0f} wk late" if v <= -.5 else "on plan"


def _tiles(tiles) -> str:
    return '<div class=tiles>' + "".join(
        f'<div class="tile {c}"><b>{escape(str(v))}</b><span>{escape(t)}</span></div>' for c, v, t in tiles) + "</div>"


def _badge(r) -> str:
    return f'<span class="badge s-{r.status}">{escape(STATUS.get(r.status, r.status))}</span>'


# ------------------------------------------------------------------ enterprise view

def _enterprise(runs, out: Path) -> str:
    results = [r for r, _, _ in runs]
    s = enterprise.stats(results)
    groups = enterprise.by_group(results)
    trend = enterprise.trend(results)
    report.enterprise_trend_chart(trend, out / "enterprise_trend.png")
    (out / "enterprise_summary.json").write_text(json.dumps(
        {"overall": s, "by_group": groups, "trend": trend}, indent=2, default=str))

    n_groups = len([g for g in groups if g != "Ungrouped"])
    if s["delivering"]:
        spread = (f" (middle half {s['x_p25']:.1f}×–{s['x_p75']:.1f}×)" if s["delivering"] >= 4 else
                  f" (range {s['min_x']:.1f}×–{s['max_x']:.1f}×)" if s["delivering"] > 1 else "")
        lead = (f"{s['products']} products in scope{f' across {n_groups} business units' if n_groups else ''}; "
                f"<b>{s['delivering']}</b> are delivering against a frozen baseline. Their delivered scope landed a median "
                f"<b>{s['median_x']:.1f}×</b> faster in calendar time than planned{spread}, with a median "
                f"{_pct(s['median_delivered_share'])} of the baseline delivered and {_pct(s['median_agentic_share'])} of it agentic.")
        if s["median_weeks_forward"] is not None:
            w = s["median_weeks_forward"]
            lead += (f" At the pace so far, the median product finishes its baseline <b>{_wk(w)}</b> against plan (projection,"
                     " measured over all elapsed time, so stalls count).")
    else:
        lead = f"{s['products']} products in scope. None has delivered baseline scope yet."

    tiles = _tiles([
        ("hero", _x(s["median_x"]), "median ×-speed (delivering products)"),
        ("", f"{s['delivering']} / {s['products']}", "products delivering"),
        ("", _pct(s["median_delivered_share"]), "median % of baseline delivered"),
        ("", _pct(s["median_agentic_share"]), "median agentic share of delivered"),
        ("", _wk(s["median_weeks_forward"]), "median vs baseline end (projected)"),
        ("", _x(s["median_projected_x"]), "median projected ×, full baseline"),
    ])
    stages = [("Onboarded (config found)", s["products"]), ("Baseline frozen", s["baselined"]),
              ("Delivering baseline scope", s["delivering"]), ("≥ 50% of baseline delivered", s["half_delivered"])]
    funnel = '<div class=funnel>' + "".join(
        f'<div><span>{escape(t)}</span><i style="width:{(60 * n / max(s["products"], 1)):.1f}%"></i><b>{n}</b></div>'
        for t, n in stages) + "</div>"
    if s["errors"]:
        funnel += f'<div class=warn>{s["errors"]} product(s) could not be read; see their status below.</div>'

    grow = "".join(
        f'<tr><td>{escape(g)}</td><td class=num>{v["products"]}</td><td class=num>{v["baselined"]}</td>'
        f'<td class=num>{v["delivering"]}</td><td class=num><b>{_x(v["median_x"])}</b></td>'
        f'<td class=num>{_pct(v["median_delivered_share"])}</td><td class=num>{_pct(v["median_agentic_share"])}</td>'
        f'<td class=num>{_wk(v["median_weeks_forward"])}</td></tr>' for g, v in groups.items())
    group_table = ("" if list(groups) == ["Ungrouped"] else
                   "<h2>By business unit</h2><div class=scroll><table><tr><th>Business unit</th><th class=num>Products</th>"
                   "<th class=num>Baselined</th><th class=num>Delivering</th><th class=num>Median ×</th>"
                   "<th class=num>Median % delivered</th><th class=num>Median agentic</th><th class=num>Median vs plan (projected)</th></tr>"
                   f"{grow}</table></div>")

    order = {"ok": 0, "no_delivery": 1, "no_baseline": 2, "error": 3}
    prow = "".join(
        f'<tr><td><a href="#{slug(r.product)}">{escape(r.product)}</a></td><td>{escape(r.group or "–")}</td>'
        f'<td>{_badge(r)}</td><td class=num>{_pct(enterprise.delivered_share(r))}</td>'
        f'<td class=num>{_pct(r.agentic_share_of_delivered) if r.compression else "–"}</td>'
        f'<td class=num>{r.planned_days or "–"} → {r.actual_days or "–"}</td><td class=num><b>{_x(r.compression)}</b></td>'
        f'<td class=num>{_x(r.projected_compression)}</td><td class=num>{_wk(enterprise.weeks_pulled_forward(r))}</td></tr>'
        for r in sorted(results, key=lambda r: (order.get(r.status, 9), -(r.compression or 0))))
    products = ("<h2>All products</h2><p class=muted>Click a product for its detail, or use the selector at the top.</p>"
                "<div class=scroll><table><tr><th>Product</th><th>Business unit</th><th>Status</th>"
                "<th class=num>% baseline delivered</th><th class=num>Agentic</th><th class=num>Days planned → actual</th>"
                "<th class=num>×-speed</th><th class=num>Projected ×</th><th class=num>Vs plan (projected)</th></tr>"
                f"{prow}</table></div>")

    return (f'<section data-view="enterprise"><h1>Enterprise overview</h1><p class=lead>{lead}</p>{tiles}'
            f"<h2>Adoption funnel</h2>{funnel}"
            + (f"<h2>Trend</h2>{_img(out / 'enterprise_trend.png')}" if len(trend) >= 2 else "")
            + group_table + products
            + (f"<h2>×-speed by product</h2>{_img(out / 'portfolio_compression.png')}" if s["delivering"] > 1 else "")
            + "<h2>How the enterprise numbers are built</h2><p class=muted>Estimates are relative to each team, so no points "
              "are added up across products. Every product counts once, and only unit-free measures are rolled up: ratios "
              "(×-speed, % delivered, agentic share), counts, and calendar weeks. The trend rebuilds each product's reading "
              "for every week since its baseline from Azure DevOps history, then takes the median across the products "
              "reporting that week.</p></section>")


# ------------------------------------------------------------------ product view

def _sprint_table(r, items, tz) -> str:
    groups = defaultdict(list)
    for i in items:
        if i.in_comparison:
            groups[(i.planned_finish, i.planned_sprint)].append(i)
    if not groups:
        return ""
    rows = []
    for (finish, name), its in sorted(groups.items(), key=lambda g: g[0][0]):
        last = max(i.delivered.astimezone(tz).date() for i in its)
        tot = sum(i.estimate for i in its)
        rows.append(f"<tr><td>{escape((name or '').split(chr(92))[-1])}</td><td class=num>{len(its)}</td>"
                    f"<td class=num>{tot:g}</td><td>{finish:%d %b %Y}</td><td>{last:%d %b %Y}</td>"
                    f"<td class=num>{(finish - last).days:+d}</td>"
                    f"<td class=num>{sum(i.estimate for i in its if i.agentic) / tot:.0%}</td></tr>")
    return ("<h3>Baseline vs agentic, by planned sprint</h3><div class=scroll><table><tr><th>Planned sprint</th>"
            f"<th class=num>Items</th><th class=num>{escape(r.estimate_unit.capitalize())}</th><th>Planned done by</th>"
            "<th>Actually done by</th><th class=num>Days early</th><th class=num>Agentic</th></tr>"
            + "".join(rows) + "</table></div>")


def _product(r, items, tz, out: Path) -> str:
    d, u = out / slug(r.product), escape(r.estimate_unit)
    head = (f'<section data-view="{slug(r.product)}"><p class=back><a href="#enterprise">← Enterprise overview</a></p>'
            f'<h1>{escape(r.product)}</h1><p class=muted>{escape(r.group or "No business unit")} · {_badge(r)} · '
            f'{escape(r.mode)} · as of {escape(r.as_of[:10])}</p>')
    if r.status in ("no_baseline", "error"):
        return head + "".join(f'<div class=warn>{escape(w)}</div>' for w in r.warnings) + "</section>"
    share = enterprise.delivered_share(r) or 0
    tiles = [("hero", _x(r.compression), "calendar ×-speed on delivered scope"),
             ("", f"{r.planned_days or '–'} → {r.actual_days or '–'} days", "planned → actual"),
             ("", f"{r.compared_estimate:g} {u}", f"compared, {r.compared_items} items"),
             ("", f"{share:.0%}", f"of {'baseline' if r.mode == 'compare' else 'scope'} delivered"),
             ("", _pct(r.agentic_share_of_delivered), "of delivered work agentic")]
    if r.projected_compression:
        tiles.append(("", _x(r.projected_compression), f"projected, full baseline (ends {r.projected_end})"))
    if enterprise.weeks_pulled_forward(r) is not None:
        tiles.append(("", _wk(enterprise.weeks_pulled_forward(r)), f"projected vs baseline end {r.baseline_end}"))
    excl = {k.replace("_", " "): v for k, v in (r.excluded or {}).items() if v}
    notes = ([f"Excluded from the comparison: " + ", ".join(f"{k} {v:g} {u}" for k, v in excl.items())] if excl else [])
    notes += r.warnings
    scope = (f'<p class=muted>Scope {r.total_estimate:g} {u} · delivered {r.delivered_estimate:g} · remaining '
             f'{r.remaining_estimate:g}.' + (f' Plan {r.planned_start} → {r.planned_end} ({r.planned_sprints} sprints) vs '
                                             f'actual {r.actual_start} → {r.actual_end}.' if r.compression else '') + '</p>')
    return (head + scope + _tiles(tiles)
            + _img(d / f"{r.mode}_timeline.png") + _sprint_table(r, items, tz)
            + _img(d / f"{r.mode}_trend.png") + _img(d / f"{r.mode}_burndown.png")
            + "".join(f'<div class=warn>{escape(n)}</div>' for n in notes)
            + f'<p class=muted>Every row: <code>{escape(slug(r.product))}/{r.mode}_items.csv</code></p></section>')


# ------------------------------------------------------------------ page

def write(runs, out: Path):
    results = [r for r, _, _ in runs]
    as_of = max(r.as_of[:10] for r in results)
    by_group = defaultdict(list)
    for r in results:
        by_group[r.group or "Ungrouped"].append(r)
    opts = '<option value="enterprise">Enterprise overview</option>' + "".join(
        f'<optgroup label="{escape(g)}">' + "".join(
            f'<option value="{slug(r.product)}">{escape(r.product)}{"" if r.compression else " (" + STATUS.get(r.status, r.status) + ")"}</option>'
            for r in sorted(rs, key=lambda r: r.product.lower())) + "</optgroup>"
        for g, rs in sorted(by_group.items()))
    header = (f'<header><div class=bar><strong>Agentic delivery vs plan <span class=muted>· as of {as_of}</span></strong>'
              f'<label for=view>View</label><select id=view>{opts}</select></div></header>')
    caveats = ("<h2>How to read this</h2><ol>"
               "<li><b>Plan vs actual, not a controlled experiment.</b> The plan is the team's own, frozen at baseline. "
               "Plans carry padding, dependencies and capacity limits the agentic run may not have faced.</li>"
               "<li><b>Calendar time, not labour hours.</b> ×-speed says nothing about effort, cost or quality on its own.</li>"
               "<li><b>Compare ×-speed across products, never raw points.</b> Estimates are team-relative.</li>"
               "<li><b>Agentic share depends on tagging discipline.</b> Spot-check the item CSVs.</li>"
               "<li><b>Early readings are noisy.</b> When little of the baseline is delivered, lead with the projection.</li>"
               "<li>Scope added after the baseline, removed items and backfilled items are reported but not compared.</li></ol>"
               f"<p class=muted>Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by agentic-benchmark.</p>")
    body = (header + "<main>" + _enterprise(runs, out)
            + "".join(_product(r, items, tz, out) for r, items, tz in runs) + caveats + "</main>")
    html = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>Agentic delivery report</title>'
            f"<style>{CSS}</style></head><body>{body}<script>{JS}</script></body></html>")
    (out / "report.html").write_text(html)
