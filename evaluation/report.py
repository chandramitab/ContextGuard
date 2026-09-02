"""Render an evaluation run as a self-contained HTML report.

    python evaluation/report.py [--in results/latest.json] [--out results/report.html]
    python evaluation/report.py --fragment      # body-only, for publishing

Reads the JSON the harness writes; computes no metrics of its own beyond
aggregation, so the numbers here are the numbers the harness scored.
"""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STAGES = [
    ("intake", "Intake"),
    ("privacy_agent", "Privacy Agent"),
    ("policy_gate", "Policy gate"),
    ("locate", "Locator"),
    ("release", "Release"),
    ("task_agent", "Task Agent"),
]


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


KIND_LABEL = {"pdf": "PDF (text layer)", "image": "Image (PNG)"}


def _usage(rows, *path):
    vals = []
    for r in rows:
        cur = r.get("usage") or {}
        for key in path:
            cur = cur.get(key) if isinstance(cur, dict) else None
        if cur:
            vals.append(cur)
    return sum(vals) / len(vals) if vals else 0.0


def by_kind(rows):
    groups = {}
    for r in rows:
        groups.setdefault(r.get("kind", "image"), []).append(r)
    return {KIND_LABEL.get(k, k): v for k, v in sorted(groups.items())}


def aggregate(rows):
    ok = [r for r in rows if "error" not in r]
    gate_rejected = [r for r in rows
                     if "error" in r and "policy rejected" in r["error"].lower()]
    n = len(ok) or 1
    st = lambda r, s: r["stages"][s]  # noqa: E731

    latency = {}
    for key, _ in STAGES:
        latency[key] = _mean(r["timings"].get(key) for r in ok) or 0.0
    total = _mean(r["timings"].get("total") for r in ok) or 0.0
    deterministic = sum(latency[k] for k in ("intake", "policy_gate", "locate", "release"))

    return {
        "n": len(ok),
        "errors": len(rows) - len(ok),
        "gate_rejected": len(gate_rejected),
        "kinds": {
            label: {
                "runs": len(rs),
                "tokens": _usage(rs, "total", "total_tokens"),
                "privacy": _usage(rs, "privacy_agent", "total_tokens"),
                "task": _usage(rs, "task_agent", "total_tokens"),
                "output": _usage(rs, "total", "output_tokens"),
                "cost": _usage(rs, "total", "cost_usd"),
                "seconds": sum(r.get("elapsed") or 0 for r in rs) / max(len(rs), 1),
                "locate_ms": 1000 * sum(r["timings"].get("locate", 0) for r in rs)
                             / max(len(rs), 1),
                "deterministic_ms": 1000 * sum(
                    sum(r["timings"].get(st, 0)
                        for st in ("intake", "policy_gate", "locate", "release"))
                    for r in rs) / max(len(rs), 1),
            }
            for label, rs in by_kind(ok).items()
        },
        "documents": len({r["document"] for r in ok}),
        "metrics": [
            ("PII recall", _mean(st(r, "privacy_agent")["pii_recall"] for r in ok),
             "Share of ground-truth PII the Privacy Agent flagged at all."),
            ("Necessity accuracy", _mean(st(r, "privacy_agent")["necessity_accuracy"] for r in ok),
             "Keep-vs-redact decisions that match what this task actually needs."),
            ("Localization rate", _mean(st(r, "locate")["localization_rate"] for r in ok),
             "Redact regions the locator could place on the page."),
            ("Leak-free rate", sum(st(r, "release")["leak_free"] for r in ok) / n,
             "Runs where no task-irrelevant PII survived into the released file."),
            ("Required data intact", sum(st(r, "release")["required_intact"] for r in ok) / n,
             "Runs where task-required data was NOT over-redacted."),
            ("Answer accuracy", sum(st(r, "task_agent")["answered_correctly"] for r in ok) / n,
             "Correct answers produced from released context only."),
        ],
        "latency": latency,
        "total": total,
        "deterministic": deterministic,
        "matrix": Counter(
            (st(r, "release")["leak_free"], st(r, "task_agent")["answered_correctly"]) for r in ok
        ),
        "leaks": Counter(f for r in ok for f in st(r, "release")["leaked"]),
        "rows": ok,
    }


# ── rendering ────────────────────────────────────────────────────────

def _pct(v):
    return "—" if v is None else f"{round(v * 100)}%"


def _bar_rows(agg):
    out = []
    for label, value, note in agg["metrics"]:
        v = 0.0 if value is None else value
        # Emphasis: the metric that is actually failing carries the critical
        # hue, a merely imperfect one carries warning, the rest stay in the
        # single sequential hue so the eye lands on the real problem.
        tone = "crit" if v < 0.8 else "warn" if v < 0.95 else "ok"
        out.append(
            f'<div class="bar-row"><div class="bar-label">{html.escape(label)}'
            f'<span class="bar-note">{html.escape(note)}</span></div>'
            f'<div class="bar-track" title="{html.escape(label)}: {_pct(value)}">'
            f'<div class="bar-fill bar-fill--{tone}" '
            f'style="width:{max(v * 100, 1.5):.1f}%"></div></div>'
            f'<div class="bar-value bar-value--{tone}">{_pct(value)}</div></div>'
        )
    return "\n".join(out)


def _latency_stack(agg):
    total = agg["total"] or 1
    parts = [
        ("Privacy Agent", agg["latency"]["privacy_agent"], "s1"),
        ("Task Agent", agg["latency"]["task_agent"], "s2"),
        ("Deterministic layer", agg["deterministic"], "s3"),
    ]
    segs, legend = [], []
    for name, seconds, slot in parts:
        share = seconds / total * 100
        segs.append(
            f'<div class="seg seg--{slot}" style="flex:{max(share, 0.6):.3f}" '
            f'title="{html.escape(name)}: {seconds:.3f}s"></div>'
        )
        legend.append(
            f'<div class="legend-item"><span class="swatch swatch--{slot}"></span>'
            f'<span class="legend-name">{html.escape(name)}</span>'
            f'<span class="legend-val">{seconds:.3f}s · {share:.1f}%</span></div>'
        )
    return "".join(segs), "".join(legend)


def _cost_panel(agg):
    kinds = agg["kinds"]
    if not kinds:
        return ""
    peak = max(max(v["privacy"], v["task"]) for v in kinds.values()) or 1
    rows = []
    for label, v in kinds.items():
        rows.append(
            f'<div class="cost-row">'
            f'<div class="cost-head"><span class="cost-name">{html.escape(label)}</span>'
            f'<span class="cost-meta">{v["runs"]} runs · {v["tokens"]:,.0f} tokens · '
            f'${v["cost"]:.3f} · {v["seconds"]:.1f}s</span></div>'
            f'<div class="cost-bars">'
            f'<div class="cost-bar">'
            f'<div class="cost-track"><div class="cost-fill cost-fill--s1" '
            f'style="width:{v["privacy"] / peak * 100:.1f}%" '
            f'title="Privacy Agent: {v["privacy"]:,.0f} tokens"></div></div>'
            f'<span class="cost-tag">Privacy Agent {v["privacy"]:,.0f}</span></div>'
            f'<div class="cost-bar">'
            f'<div class="cost-track"><div class="cost-fill cost-fill--s2" '
            f'style="width:{v["task"] / peak * 100:.1f}%" '
            f'title="Task Agent: {v["task"]:,.0f} tokens"></div></div>'
            f'<span class="cost-tag">Task Agent {v["task"]:,.0f}</span></div>'
            f'</div></div>'
        )
    return "".join(rows)


def _matrix(agg):
    m = agg["matrix"]
    cells = [
        ("Protected &amp; answered", m[(True, True)], "good", "the goal"),
        ("Protected, answer failed", m[(True, False)], "warn", "over-redaction"),
        ("Leaked, answered", m[(False, True)], "crit", "no better than no guard"),
        ("Leaked &amp; failed", m[(False, False)], "crit", "worst case"),
    ]
    return "".join(
        f'<div class="cell cell--{tone}"><div class="cell-n">{n}</div>'
        f'<div class="cell-label">{label}</div><div class="cell-note">{note}</div></div>'
        for label, n, tone, note in cells
    )


def _table(agg):
    head = ("<tr><th>Document</th><th>Task</th><th>Recall</th><th>Necessity</th>"
            "<th>Located</th><th>Leaked</th><th>Answered</th><th>Time</th></tr>")
    body = []
    for r in agg["rows"]:
        s = r["stages"]
        leaked = ", ".join(s["release"]["leaked"]) or "—"
        cls = "bad" if s["release"]["leaked"] else "good"
        body.append(
            f'<tr><td class="mono">{html.escape(r["document"])}</td>'
            f'<td>{html.escape(r["question"])}</td>'
            f'<td class="num">{_pct(s["privacy_agent"]["pii_recall"])}</td>'
            f'<td class="num">{_pct(s["privacy_agent"]["necessity_accuracy"])}</td>'
            f'<td class="num">{_pct(s["locate"]["localization_rate"])}</td>'
            f'<td class="{cls}">{html.escape(leaked)}</td>'
            f'<td class="num">{"yes" if s["task_agent"]["answered_correctly"] else "no"}</td>'
            f'<td class="num">{r.get("elapsed", "—")}s</td></tr>'
        )
    return head + "".join(body)


def render(agg, fragment=False):
    segs, legend = _latency_stack(agg)
    cost_panel = _cost_panel(agg)
    locate_note = " ".join(
        f"On <strong>{html.escape(label)}</strong> the locator takes "
        f"<strong>{v['locate_ms']:,.0f} ms</strong> "
        f"({v['deterministic_ms']:,.0f} ms for the whole deterministic layer)."
        for label, v in agg["kinds"].items()
    ) + (" Tesseract has to re-read the page; a PDF's text layer answers directly."
         if len(agg["kinds"]) > 1 else "")
    leaks = ", ".join(f"{f} ({n})" for f, n in agg["leaks"].most_common()) or "none"
    det_ms = agg["deterministic"] * 1000

    body = f"""
<div class="viz-root">
  <header class="head">
    <div class="eyebrow">ContextGuard · pipeline evaluation</div>
    <h1>Stage-by-stage results</h1>
    <p class="sub">{agg['n']} task runs across {agg['documents']} documents
      · {agg['gate_rejected']} rejected by the policy gate · every stage scored against
      <code>evaluation/golden/</code>.</p>
  </header>

  <section class="kpis">
    <div class="kpi"><div class="kpi-n">{_pct(agg['metrics'][5][1])}</div>
      <div class="kpi-l">Answer accuracy</div></div>
    <div class="kpi"><div class="kpi-n kpi-n--crit">{_pct(agg['metrics'][3][1])}</div>
      <div class="kpi-l">Leak-free runs</div></div>
    <div class="kpi"><div class="kpi-n">{_pct(agg['metrics'][2][1])}</div>
      <div class="kpi-l">Localization rate</div></div>
    <div class="kpi"><div class="kpi-n">{agg['total']:.1f}s</div>
      <div class="kpi-l">Mean end-to-end</div></div>
  </section>

  <section class="panel">
    <h2>Where the pipeline stands</h2>
    <p class="lede">Five of six measures are at or near ceiling. One is not — and
      it is the one the whole system exists to guarantee.</p>
    <div class="bars">{_bar_rows(agg)}</div>
  </section>

  <section class="panel">
    <h2>Privacy against utility</h2>
    <p class="lede">Every run placed in one of four outcomes. A system with no
      privacy layer sits permanently in “leaked &amp; answered”.</p>
    <div class="matrix">{_matrix(agg)}</div>
    <p class="foot">Leaked fields: <strong>{html.escape(leaks)}</strong></p>
  </section>

  <section class="panel">
    <h2>What a run costs, by document type</h2>
    <p class="lede">Mean tokens per run, split across the two agent calls.
      A PDF's text layer is not cheaper than an image — the agent harness's
      cached context dominates both.</p>
    <div class="cost">{cost_panel}</div>
  </section>

  <section class="panel">
    <h2>Where the time goes</h2>
    <p class="lede">The two agent calls are the entire cost. The deterministic
      security layer — intake gate, policy gate, locator, redaction — totals
      <strong>{det_ms:.0f} ms</strong> on average. That average hides the real
      story — see below.</p>
    <p class="lede">{locate_note}</p>
    <div class="stack">{segs}</div>
    <div class="legend">{legend}</div>
  </section>

  <section class="panel">
    <h2>Every run</h2>
    <div class="table-wrap"><table>{_table(agg)}</table></div>
  </section>
</div>
"""

    fonts = (
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600;700'
        '&display=swap">'
    )
    style = """
<style>
body{background:#f9f9f7;margin:0}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) body{background:#0d0d0d}}
:root[data-theme="dark"] body{background:#0d0d0d}
.viz-root{
  color-scheme:light;
  --surface-1:#fcfcfb; --plane:#f9f9f7;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
  --grid:#e1e0d9;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
  --seq:#2a78d6; --good:#0ca30c; --warn:#fab219; --crit:#d03b3b;
  background:var(--plane); color:var(--text-primary);
  font:15px/1.6 "IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,sans-serif;
  font-variant-numeric:tabular-nums;
  max-width:1080px; margin:0 auto; padding:36px 24px 80px;
}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{
  color-scheme:dark;
  --surface-1:#1a1a19; --plane:#0d0d0d;
  --text-primary:#fff; --text-secondary:#c3c2b7; --muted:#898781; --grid:#2c2c2a;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --seq:#3987e5;
}}
:root[data-theme="dark"] .viz-root{
  color-scheme:dark;
  --surface-1:#1a1a19; --plane:#0d0d0d;
  --text-primary:#fff; --text-secondary:#c3c2b7; --muted:#898781; --grid:#2c2c2a;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --seq:#3987e5;
}
.viz-root *{box-sizing:border-box}
.head{margin-bottom:26px}
.eyebrow{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;font-weight:600;
  letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
h1{margin:6px 0 4px;font-size:30px;font-weight:700;letter-spacing:-.025em;text-wrap:balance}
h2{margin:0 0 4px;font-size:16px}
.sub,.lede{margin:0 0 16px;color:var(--text-secondary);font-size:14px}
code{font-size:13px;background:var(--grid);padding:1px 5px;border-radius:4px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px}
.kpi{background:var(--surface-1);border:1px solid var(--grid);border-radius:10px;padding:16px 18px}
.kpi-n{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:34px;font-weight:600;
  letter-spacing:-.03em;line-height:1.1}
.kpi-n--crit{color:var(--crit)}
.kpi-l{font-size:12px;color:var(--text-secondary);margin-top:2px}
.panel{background:var(--surface-1);border:1px solid var(--grid);border-radius:10px;padding:20px;margin-bottom:16px}
.bars{display:flex;flex-direction:column;gap:12px}
.bar-row{display:grid;grid-template-columns:minmax(190px,260px) 1fr 56px;gap:14px;align-items:center}
.bar-label{font-size:13px;font-weight:600;display:flex;flex-direction:column}
.bar-note{font-weight:400;font-size:11.5px;color:var(--muted);line-height:1.35}
.bar-track{height:10px;background:var(--grid);border-radius:5px;overflow:hidden}
.bar-fill{height:100%;border-radius:5px}
.bar-fill--ok{background:var(--seq)}
.bar-fill--warn{background:var(--warn)}
.bar-fill--crit{background:var(--crit)}
.bar-value{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:13px;font-weight:600;text-align:right}
.bar-value--warn{color:var(--text-primary)}
.bar-value--crit{color:var(--crit)}
.cost{display:flex;flex-direction:column;gap:16px}
.cost-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;
  flex-wrap:wrap;margin-bottom:7px}
.cost-name{font-size:13px;font-weight:600}
.cost-meta{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px;color:var(--muted)}
.cost-bars{display:flex;flex-direction:column;gap:4px}
.cost-bar{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px}
.cost-track{min-width:0}
.cost-fill{height:13px;border-radius:4px;min-width:3px}
.cost-fill--s1{background:var(--s1)} .cost-fill--s2{background:var(--s2)}
.cost-tag{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;color:var(--text-secondary);white-space:nowrap}
.matrix{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.cell{border:1px solid var(--grid);border-radius:8px;padding:14px 16px;background:var(--plane)}
.cell-n{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:26px;font-weight:600;line-height:1.1}
.cell-label{font-size:12.5px;font-weight:600;margin-top:2px}
.cell-note{font-size:11.5px;color:var(--muted)}
.cell--good .cell-n{color:var(--good)}
.cell--warn .cell-n{color:var(--warn)}
.cell--crit .cell-n{color:var(--crit)}
.stack{display:flex;height:26px;border-radius:6px;overflow:hidden;gap:2px;background:var(--grid)}
.seg{height:100%}
.seg--s1{background:var(--s1)} .seg--s2{background:var(--s2)} .seg--s3{background:var(--s3)}
.legend{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:12px}
.legend-item{display:flex;align-items:center;gap:7px;font-size:12.5px}
.swatch{width:10px;height:10px;border-radius:3px;flex:none}
.swatch--s1{background:var(--s1)} .swatch--s2{background:var(--s2)} .swatch--s3{background:var(--s3)}
.legend-name{color:var(--text-primary)}
.legend-val{color:var(--muted);font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px}
.foot{margin:14px 0 0;font-size:12.5px;color:var(--text-secondary)}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10.5px;
   letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
   padding:6px 10px;border-bottom:1px solid var(--grid);white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid var(--grid);vertical-align:top}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px}
.bad{color:var(--crit);font-weight:600}
.good{color:var(--muted)}
</style>
"""
    if fragment:
        return f"<title>ContextGuard Evaluation</title>{fonts}{style}{body}"
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>ContextGuard Evaluation</title>"
            f"{fonts}{style}</head><body>{body}</body></html>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="evaluation/results/latest.json",
                    help="comma-separated result files; rows are merged")
    ap.add_argument("--out", default="evaluation/results/report.html")
    ap.add_argument("--fragment", action="store_true", help="body only, for publishing")
    args = ap.parse_args()

    rows = []
    for part in args.inp.split(","):
        rows += json.loads((ROOT / part.strip()).read_text())["rows"]
    agg = aggregate(rows)
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(agg, fragment=args.fragment), encoding="utf-8")
    print(f"wrote {args.out}  ({agg['n']} runs, {agg['errors']} errors)")


if __name__ == "__main__":
    main()
