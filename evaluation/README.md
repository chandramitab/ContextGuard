# Evaluation

Scores all six pipeline stages against ground truth and renders an HTML report.

Run everything from the **repo root** with the **backend venv** — the harness
imports `app.*` and resolves data paths relative to the repo root:

```bash
backend/.venv/bin/python evaluation/harness.py --help
```

## Layout

```
golden/invoices.json     ground truth ·  5 PDFs   · 15 tasks
golden/images.json       ground truth · 20 images · 60 tasks
harness.py               runs the pipeline, scores every stage -> results/*.json
report.py                results/*.json -> HTML report
build_images_golden.py   regenerates golden/images.json + data/images/test_messages.json
results/                 run output (gitignore-able; regenerated)
```

## Running

```bash
# PDFs — all 15 tasks
CONTEXTGUARD_MODE=claude backend/.venv/bin/python evaluation/harness.py \
  --golden evaluation/golden/invoices.json --out evaluation/results/pdfs.json

# Images — one document per family (15 of 60 tasks)
CONTEXTGUARD_MODE=claude backend/.venv/bin/python evaluation/harness.py \
  --golden evaluation/golden/images.json --per-family 1 \
  --out evaluation/results/images.json

# Report over both
backend/.venv/bin/python evaluation/report.py \
  --in evaluation/results/pdfs.json,evaluation/results/images.json \
  --out evaluation/results/report.html
```

`--limit N`, `--document <id>` and `--per-family N` narrow a run. `--fragment` on
`report.py` emits body-only HTML for publishing.

**Every run costs real API calls** — roughly $0.07 per task and ~20 s. The full
image set (60 tasks) is about $4.50 and 22 minutes. Never evaluate in `local`
mode: the passthrough plan scores perfect utility and zero privacy.

## What is measured

| Stage | Metric |
|---|---|
| Intake | accepted / refused, and why |
| Privacy Agent | PII recall · necessity accuracy (task-relative) |
| Policy gate | rejections, counted separately from errors |
| Locator | localization rate · latency (OCR vs text layer) |
| Release | **leak-free rate** · required-data-intact · withheld documents |
| Task Agent | answer accuracy from released context only |
| All | tokens and cost per agent, wall-clock per stage |

The headline is the 2×2 of *leak-free* against *answered*: a system with no privacy
layer sits permanently in "leaked & answered".

## How ground truth works

Each document lists its PII; each task declares which fields it legitimately
`requires`. Everything else becomes the must-not-appear set **for that task** —
so the IBAN is a leak for "which item costs most" and the expected answer for
"what IBAN should this be paid to". A global PII blocklist would score this system
as broken by design.

Two rules the golden files follow:

- **Every ground-truth string is verified findable in its own document.** A value
  that cannot be found makes the leak check silently measure nothing.
- **Comparison is exact after normalisation, never a fuzzy ratio.** These IBANs
  differ in 4 of 26 characters; any ratio loose enough to absorb OCR damage also
  matches a different customer's account. Accents are stripped and confusable
  glyphs folded (`DE00`/`DEOO`, `ß`/`B`) — validated in both directions across all
  20 images for zero missed detections and zero false positives.

## RedactionBench (optional, not wired to the harness)

`bootstrap_redactionbench.py` and `render_text_documents.py` pull and render an
external span-annotated corpus. They prepare data only — they score nothing, and
nothing else in `evaluation/` reads their output.

```bash
pip install -r evaluation/requirements.txt      # adds `datasets`
python evaluation/bootstrap_redactionbench.py --count 20
python evaluation/render_text_documents.py
```

Useful for raw sensitive-span recall against an external benchmark. It cannot
measure task-relative necessity — it is redaction-oriented, not query-relative —
which is why the golden sets above exist.
