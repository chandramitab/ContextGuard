# ContextGuard

A **task-aware multimodal privacy layer for AI agents.** A downstream agent gets a
redacted copy of your documents containing exactly what its task requires - and
nothing else.

The same invoice, two questions:

| Task | IBAN | Customer name | Line items |
|---|---|---|---|
| "Which item has the highest price?" | redacted | redacted | kept |
| "What IBAN should this be paid to?" | **kept** | redacted | kept |

Sensitivity is not a property of a field. It is a property of a field *given a task*.

## Architecture

```text
User task + 1..N images or text-layer PDFs
        |
        v
  upload inspector          deterministic: sniffs content bytes, refuses PDFs
        |                   carrying attachments / JavaScript / XFA
        v
  Claude Privacy Agent      sees originals; decides what is sensitive and
        |                   whether THIS task needs it  ->  PrivacyPlan
        v
  policy gate               deterministic: rejects any plan that keeps a
        |                   sensitive, non-task-required region
        v
  locator                   deterministic: finds WHERE.
        |                     images -> Tesseract, fuzzy-matched
        |                     PDFs   -> text layer, exact
        v
  redaction                 deterministic: images painted; PDFs have glyphs
        |                   REMOVED (apply_redactions), never just covered.
        |                   Fails closed — a document it cannot fully redact
        v                   is withheld, not released.
  released/ trust zone
        |
        v
  Claude Task Agent         sees released/ only; answers the task
```

**Principle:** agents handle ambiguous reasoning; deterministic code protects the
security invariants. The whole deterministic layer costs ~18 ms on a PDF.

## Quick start

System dependency (OCR for images):

```bash
brew install tesseract          # macOS; apt-get install tesseract-ocr on Ubuntu
```

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --reload-include .env --port 8000
```

Frontend (Vite + React 19, plain JavaScript):

```bash
cd frontend && npm install && npm run dev     # http://localhost:5173
```

`CONTEXTGUARD_MODE=local` runs with no API calls (passthrough plan, stub answer);
`claude` runs the real agents. **Restart uvicorn after editing `.env`** — check
which mode is live with `curl -s localhost:8000/health`.

Full demo script: `WEDNESDAY_RUNBOOK.md`.

## Why a local locator exists

OCR is not the privacy detector. Claude decides **what** must go; the locator only
finds **where that exact text sits** so deterministic code can remove it. For PDFs
the text layer answers directly, which is both exact and ~220× faster than OCR.

## Evaluation

`evaluation/` scores all six pipeline stages against ground truth and renders an
HTML report. See `evaluation/README.md`.

Latest run — 29 tasks across 5 PDFs and 5 images:

| Measure | Result |
|---|---|
| Answer accuracy | 100% |
| Localization rate | 100% |
| Required data intact (no over-redaction) | 100% |
| PII recall | 98% |
| **Leak-free runs** | **52%** |

Every leak is identifier-class business data — `project_ref`, `claim_id`,
`employee_id` — not personal data. The Privacy Agent's prompt says "sensitive"
without defining scope, and the model reads that as *personal*.

## Known limitations

- **Scanned PDFs are refused.** Only text-layer PDFs are supported; the rasterise
  route is not built.
- **`review` regions are released unredacted.** The action means "a human should
  look at this", not "this was protected". Faces and signatures land here.
- **The Task Agent's sandbox is prompt-enforced, not mechanism-enforced.** See the
  invariants section of `CLAUDE.md`.
- **Originals are never deleted** from `SESSION_ROOT`.
- **`FORBIDDEN_VALUES` is module-global**, so concurrent requests clobber each other.
