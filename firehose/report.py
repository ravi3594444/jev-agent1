"""Self-contained HTML digest. No external assets, no network at view time."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any

from .pipeline import DROP, KEEP, REVIEW, Result

# Palette roles (validated categorical slots 1 & 2; fixed status steps for state)
CSS = """
:root{
  color-scheme:light;
  --surface-0:#f6f6f4; --surface-1:#fcfcfb; --border:#e3e2dd;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#82817c;
  --series-1:#2a78d6; --series-2:#eb6834;
  --good:#0ca30c; --warning:#fab219; --neutral:#a8a79f;
  --track:#eceae5;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --surface-0:#111110; --surface-1:#1a1a19; --border:#33332f;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8f8e85;
    --series-1:#3987e5; --series-2:#d95926;
    --good:#0ca30c; --warning:#fab219; --neutral:#6d6c66;
    --track:#2a2a27;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --surface-0:#111110; --surface-1:#1a1a19; --border:#33332f;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8f8e85;
  --series-1:#3987e5; --series-2:#d95926;
  --good:#0ca30c; --warning:#fab219; --neutral:#6d6c66;
  --track:#2a2a27;
}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);
  font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
.wrap{max-width:1000px;margin:0 auto;padding:32px 16px 64px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between;margin-bottom:6px}
h1{font-size:22px;margin:0;letter-spacing:-.01em}
h2{font-size:15px;margin:32px 0 10px;color:var(--text-secondary);font-weight:600;
  text-transform:uppercase;letter-spacing:.06em}
.sub{color:var(--text-muted);font-size:13px;margin:0 0 24px}
button{font:inherit;font-size:13px;color:var(--text-secondary);background:var(--surface-1);
  border:1px solid var(--border);border-radius:8px;padding:5px 11px;cursor:pointer}
button:hover{color:var(--text-primary)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.kpi{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:14px 16px}
.kpi .n{font-size:26px;font-weight:650;letter-spacing:-.02em;line-height:1.15}
.kpi .l{font-size:12px;color:var(--text-muted);margin-top:3px}
.dist{display:flex;gap:2px;margin:20px 0 4px;height:12px}
.dist span{border-radius:3px}
.distlab{display:flex;flex-wrap:wrap;gap:16px;font-size:12px;color:var(--text-secondary)}
.distlab i{width:9px;height:9px;border-radius:3px;display:inline-block;margin-right:6px}
.item{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;
  padding:14px 16px;margin-bottom:8px}
.item a{color:var(--text-primary);text-decoration:none;font-weight:600}
.item a:hover{text-decoration:underline;text-underline-offset:2px}
.meta{font-size:12px;color:var(--text-muted);margin-top:4px}
.sig{font-size:12.5px;color:var(--text-secondary);margin-top:7px}
.bars{display:flex;gap:18px;margin-top:9px;flex-wrap:wrap}
.bar{display:flex;align-items:center;gap:7px;font-size:11.5px;color:var(--text-secondary);
  font-variant-numeric:tabular-nums}
.track{width:74px;height:5px;background:var(--track);border-radius:3px;overflow:hidden}
.fill{height:100%;border-radius:3px;display:block}
.tag{font-size:11px;font-weight:650;letter-spacing:.04em;text-transform:uppercase;
  padding:2px 7px;border-radius:999px;border:1px solid var(--border);white-space:nowrap}
.tag.keep{color:var(--good)} .tag.review{color:var(--warning)} .tag.drop{color:var(--text-muted)}
.row{display:flex;gap:10px;align-items:flex-start;justify-content:space-between}
details{margin-top:10px} summary{cursor:pointer;color:var(--text-secondary);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--text-muted);font-weight:600;font-size:12px}
.warn{background:var(--surface-1);border:1px solid var(--border);border-left:3px solid var(--warning);
  border-radius:8px;padding:10px 14px;font-size:13px;color:var(--text-secondary);margin-bottom:8px}
footer{margin-top:40px;font-size:12px;color:var(--text-muted);border-top:1px solid var(--border);padding-top:14px}
"""

JS = """
const root=document.documentElement;
const saved=(()=>{try{return localStorage.getItem('fh-theme')}catch(e){return null}})();
if(saved) root.setAttribute('data-theme',saved);
document.getElementById('theme').onclick=()=>{
  const dark=getComputedStyle(root).getPropertyValue('--surface-0').trim()==='#111110';
  const next=dark?'light':'dark';
  root.setAttribute('data-theme',next);
  try{localStorage.setItem('fh-theme',next)}catch(e){}
};
document.getElementById('tableview').onclick=()=>{
  const t=document.getElementById('tbl'), c=document.getElementById('cards');
  const show=t.hasAttribute('hidden');
  t.toggleAttribute('hidden',!show); c.toggleAttribute('hidden',show);
};
"""


def _esc(s: Any) -> str:
    return html.escape(str(s or ""), quote=True)


def _bar(label: str, value: float, color_var: str) -> str:
    pct = max(0.0, min(1.0, value)) * 100
    return (
        f'<span class="bar">{_esc(label)} <span class="track">'
        f'<span class="fill" style="width:{pct:.0f}%;background:var({color_var})"></span></span>'
        f'<b style="font-weight:600">{value:.2f}</b></span>'
    )


def _item_card(r: Result) -> str:
    link = f'<a href="{_esc(r.item.url)}" target="_blank" rel="noopener">{_esc(r.item.title)}</a>' \
        if r.item.url else f"<strong>{_esc(r.item.title)}</strong>"
    return f"""<article class="item">
  <div class="row"><div>{link}</div><span class="tag {r.verdict}">{r.verdict}</span></div>
  <div class="meta">{_esc(r.item.source)}{' · ' + _esc(r.item.published) if r.item.published else ''}</div>
  {f'<div class="sig">{_esc(r.reason)}</div>' if r.reason else ''}
  <div class="bars">{_bar('relevance', r.relevance, '--series-1')}{_bar('confidence', r.certainty, '--series-2')}</div>
</article>"""


def _table(results: list[Result]) -> str:
    rows = "".join(
        f"<tr><td>{_esc(r.item.title)}</td><td>{_esc(r.item.stream)}</td>"
        f"<td>{r.verdict}</td><td>{r.relevance:.2f}</td><td>{r.certainty:.2f}</td>"
        f"<td>{_esc(r.reason)}</td></tr>"
        for r in results
    )
    return ("<table><thead><tr><th>Item</th><th>Stream</th><th>Verdict</th>"
            "<th>Relevance</th><th>Confidence</th><th>Signals</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>")


def render(
    results: list[Result],
    stats: Any,
    warnings: list[str],
    streams: dict[str, str] | None = None,
    title: str = "Firehose digest",
    mock: bool = False,
) -> str:
    keep = [r for r in results if r.verdict == KEEP]
    review = [r for r in results if r.verdict == REVIEW]
    drop = [r for r in results if r.verdict == DROP]
    total = len(results) or 1
    when = datetime.now(timezone.utc).astimezone().strftime("%d %b %Y, %H:%M")

    seg = ""
    for count, var, _lab in ((len(keep), "--good", "kept"),
                             (len(review), "--warning", "review"),
                             (len(drop), "--neutral", "dropped")):
        if count:
            seg += f'<span style="flex:{count};background:var({var})"></span>'

    per_item_ms = stats.mean_ms if getattr(stats, "mean_ms", 0) else 0.0
    kpis = [
        (f"{len(keep)}", "kept - worth your time"),
        (f"{len(review)}", "review - model unsure"),
        (f"{len(drop)}", "dropped - never shown"),
        (f"{len(results)}", "items scored"),
        (f"${stats.cost_usd:.4f}", "total cost"),
        (f"{per_item_ms:.0f} ms" if per_item_ms >= 1 else "—", "per item"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="n">{_esc(n)}</div><div class="l">{_esc(l)}</div></div>'
        for n, l in kpis
    )

    body = ""
    stream_names = streams or {}
    for sid in sorted({r.item.stream for r in keep + review}):
        label = stream_names.get(sid, sid)
        s_keep = [r for r in keep if r.item.stream == sid]
        s_rev = [r for r in review if r.item.stream == sid]
        if not s_keep and not s_rev:
            continue
        body += f"<h2>{_esc(label)}</h2>"
        body += "".join(_item_card(r) for r in s_keep) or \
            '<div class="warn">Nothing cleared the keep gate in this stream.</div>'
        if s_rev:
            body += (f"<details><summary>{len(s_rev)} borderline item"
                     f"{'s' if len(s_rev) != 1 else ''} the model was not confident about</summary>"
                     + "".join(_item_card(r) for r in s_rev) + "</details>")

    warn_html = ""
    if mock:
        warn_html += (
            '<div class="warn"><strong>Mock run.</strong> No API key was used. These '
            "verdicts come from a lexical stand-in, not from Jev - it has no semantics, so "
            "treat the numbers as a layout preview only. Run without <code>--mock</code> "
            "for real judgements.</div>"
        )
    warn_html += "".join(f'<div class="warn">{_esc(w)}</div>' for w in warnings)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title><style>{CSS}</style></head><body>
<div class="wrap">
  <header>
    <h1>{_esc(title)}</h1>
    <div style="display:flex;gap:8px">
      <button id="tableview" type="button">Table view</button>
      <button id="theme" type="button">Theme</button>
    </div>
  </header>
  <p class="sub">{_esc(when)} · {len(results)} items scored by Jev · ${stats.cost_usd:.4f}</p>
  <div class="kpis">{kpi_html}</div>
  <div class="dist">{seg}</div>
  <div class="distlab">
    <span><i style="background:var(--good)"></i>kept {len(keep)} ({len(keep)/total:.0%})</span>
    <span><i style="background:var(--warning)"></i>review {len(review)} ({len(review)/total:.0%})</span>
    <span><i style="background:var(--neutral)"></i>dropped {len(drop)} ({len(drop)/total:.0%})</span>
  </div>
  {warn_html}
  <div id="cards">{body}</div>
  <div id="tbl" hidden>{_table(results)}</div>
  <footer>Relevance and confidence come from Jev (typed, calibrated). Items land in
  <em>review</em> when confidence falls below the gate - that is the model declining to
  guess, not a weak keep.</footer>
</div>
<script>{JS}</script></body></html>"""
