# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# ContextGuard

A minimal enterprise-friendly privacy workspace, not a chat clone. UI blocks: Task, Input Documents, Privacy Decisions, Released Context, Final Answer; Agent Trace collapsible. Never expose original files to the downstream Task Agent. Claude reasons; deterministic code enforces/redacts. Preserve multi-image support.

## Commands

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --reload-include .env --port 8000
```

Run tests (from `backend/` with venv active):
```bash
python -m pytest tests/
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run build
```

### Evaluation

Run from the **repo root**, using the backend venv (the harness imports `app.*`):

```bash
CONTEXTGUARD_MODE=claude backend/.venv/bin/python evaluation/harness.py \
  --golden evaluation/golden/invoices.json --out evaluation/results/pdfs.json

backend/.venv/bin/python evaluation/report.py \
  --in evaluation/results/pdfs.json,evaluation/results/images.json \
  --out evaluation/results/report.html
```

Every run costs real API calls. See `evaluation/README.md`.

### System dependency

```bash
brew install tesseract   # macOS; apt-get install tesseract-ocr on Ubuntu
```

## Architecture

### Pipeline (`backend/app/services/pipeline.py`)

The core flow for every `POST /api/analyze`:

1. Files saved to `SESSION_ROOT/<session_id>/original/`
2. **Privacy Agent** (`claude` mode) or local fallback inspects originals → `PrivacyPlan`
3. **Policy gate** (`policy_service.py`) deterministically rejects any plan that `keep`s a sensitive, non-task-required region
4. **Locator** (`locator.py`) dispatches by file type — `ocr_locator.py` (Tesseract, fuzzy, images) or `pdf_locator.py` (text-layer `search_for`, exact). Claude decides *what*; the locator fills in `page` and `bbox`
5. **Redaction service** (`redaction_service.py`) copies files to `released/`, painting black rectangles over located regions. It **fails closed**: a document is withheld (never copied) if it has no plan entry, if `document_required=False`, or if any `redact` region has no bbox — better to release nothing than to release sensitive pixels intact
6. **Task Agent** (`claude` mode) gets only the `released/` directory; answers the user task
7. Response includes `privacy_plan`, `released_urls`, `final_answer`, `withheld` (documents held back, with reasons), and `gate: PASS`

### Mode switch

Controlled by `CONTEXTGUARD_MODE` env var:
- `local` — no API calls; passthrough plan + stub answer (safe for dev)
- `claude` — uses `claude-agent-sdk` with `ANTHROPIC_API_KEY` and `CONTEXTGUARD_MODEL` (`sonnet` default)

### Key invariants

- The Task Agent's `cwd` is always `released/` and it must never see originals. **This is currently enforced by `TASK_SYSTEM_PROMPT` alone, not by a mechanism** — a `Read` of `../original/<name>` succeeds if the model attempts it, and `allowed_tools=["Read"]` is a permission allowlist, not a capability ceiling (the agent can still call `Glob`). Deleting `original/` before the Task Agent starts would make the invariant structural.
- `policy_service.validate_plan` is the security gate — it is deterministic code, not an LLM. Do not bypass it.
- `upload_inspector.py` is the structural gate: it sniffs content bytes (not the extension), and refuses PDFs carrying channels redaction cannot reach (embedded attachments, JavaScript, XFA). Metadata/annotations/form fields are stripped at release instead of blocking.
- PDFs are redacted with `apply_redactions()`, which removes glyphs. Never `draw_rect` — a painted rectangle leaves the text selectable in the content stream.
- `ocr_locator` matches fuzzily (Tesseract misreads characters) but never lets a match window cross an OCR line, or the bounding box would black out unrelated rows.
- `privacy_hook.py` maintains an in-memory `FORBIDDEN_VALUES` set; the `outbound_privacy_hook` function is wired as a `PreToolUse` hook to block leakage in task agent tool calls.
- Purely visual sensitive regions (faces, signatures) that OCR cannot localize must use action `review`, not `redact`, in the MVP.

### Models (`backend/app/models.py`)

`PrivacyPlan → DocumentPlan → RegionPlan`. The `Action` literal is `keep | redact | drop_document | generalize | extract_only | review`.

### Frontend (`frontend/src/main.jsx`)

Single-file **Vite + React 19 app in plain JavaScript/JSX — no TypeScript**, no CSS framework (`styles.css` is hand-written, using CSS custom properties). Posts to `${window.location.hostname}:8000/api/analyze` with `multipart/form-data`; fetches released documents via `/api/session/{sid}/released/{filename}`.

This is a privacy workspace, not a chat clone. The six blocks, in order:

1. **Task** — large text field; the sample question is a placeholder, never a prefilled value
2. **Input Documents** — drag/drop, multiple thumbnails, PDFs shown as a chip
3. **Privacy Decisions** — whole-document KEEP/DROP, region category, KEEP/REDACT/REVIEW, one-line reason, `Privacy Gate: PASS`
4. **Released Context** — original vs released comparison, tabs for multiple documents, withheld documents with their reason, download buttons
5. **Final Answer** — with `Answered from released context only`
6. **Agent Trace** — collapsed by default

Visual style: light mode, off-white ground, white cards with restrained radius, dark neutral type, muted green for KEEP/PASS, muted red for REDACT, amber for REVIEW. No gradients, no hero, minimal animation. Desktop-first at 1280×800; after processing, blocks 3–5 should be readable with minimal scrolling.

`vite.config.js` loads `@vitejs/plugin-react` — without it there is no Fast Refresh, and every edit full-reloads the page, aborting any in-flight `/api/analyze` request.

## API contract

`POST /api/analyze` — `multipart/form-data`: `task` (string) + `files` (1..N images or text-layer PDFs). Do not change the route or remove response fields.

`GET /api/session/{sid}/released/{filename}` — serves a redacted image from the session's released directory.
