# Run & Demo Sheet

Everything needed to stand ContextGuard up, demo it, and run the evaluation.
Architecture is in `README.md`; working rules for the code are in `CLAUDE.md`.

---

## 1. One-time setup

System dependency — Tesseract, used to locate text in **images** (PDFs use their
own text layer and do not need it):

```bash
brew install tesseract              # macOS
sudo apt-get install tesseract-ocr  # Ubuntu
```

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Frontend:

```bash
cd frontend && npm install
```

---

## 2. Configure the mode

`backend/.env`:

```text
CONTEXTGUARD_MODE=local            # no API calls — passthrough plan, stub answer
CONTEXTGUARD_MODEL=sonnet
SESSION_ROOT=/tmp/contextguard-agentic
ANTHROPIC_API_KEY=                 # optional if the Claude Code CLI is logged in
```

For the demo, switch to `CONTEXTGUARD_MODE=claude`.

> **Restart uvicorn after editing `.env`.** `--reload` watches `.py` files only.
> A running server keeps answering in `local` mode — no privacy decisions, no
> redaction, Released identical to Original — and the UI shows an amber banner
> saying so.

`load_dotenv(override=True)` means **`.env` beats shell variables**, so
`CONTEXTGUARD_MODE=local uvicorn ...` will *not* override the file.

---

## 3. Start it

Two terminals:

```bash
# backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --reload-include .env --port 8000

# frontend
cd frontend && npm run dev          # http://localhost:5173
```

Pre-flight — confirm the live mode before demoing:

```bash
curl -s localhost:8000/health
# {"status":"ok","mode":"claude","model":"sonnet"}
```

Open **http://localhost:5173**. `127.0.0.1:5173` also works — the frontend
calls whichever host served the page, and CORS accepts both.

---

## 4. Demo script (~90 seconds)

Files are in the repo. Expect **~20 s per analysis** in `claude` mode.

### Act 1 — task-relative necessity, the whole thesis

Upload **`data/pdfs/invoice_classic.pdf`**.

**Question 1:** `Which item has the highest price?`

- Privacy Decisions: name, address, email, phone, IBAN → **REDACT**; line items → **KEEP**
- Released Context: black bars over identity and payment, prices readable
- Answer: *Hydraulic Pump — EUR 4,250.00*

**Question 2 (same document):** `What IBAN should this invoice be paid to?`

- The IBAN flips to **KEEP** / `task_required: true`; identity stays REDACT
- This is the point: sensitivity is a property of a field *given a task*

Say while it runs: *the downstream agent never sees the original — only the
redacted copy.*

### Act 2 — it is a real redaction, not a black rectangle

Click **Download redacted**, open the PDF, try to select the blacked-out IBAN.
Nothing is there — `apply_redactions()` removes the glyphs. A drawn rectangle
would leave the text selectable underneath.

### Act 3 — multimodal

Upload **`data/images/insurance_claim_02.png`**, ask
`What is the estimated damage amount?` → *€2,525*, with claimant, address, phone,
policy number, IBAN and the medical note all redacted.

### Act 4 (optional) — it fails closed

Upload a PDF carrying an embedded attachment and it is refused before the agent
ever sees it:

> *carries content redaction cannot reach: 1 embedded file attachment(s)*

---

## 5. Evaluation

Run from the **repo root** with the **backend venv** — the harness imports `app.*`.

```bash
# PDFs — 15 tasks across 5 invoices
CONTEXTGUARD_MODE=claude backend/.venv/bin/python evaluation/harness.py \
  --golden evaluation/golden/invoices.json --out evaluation/results/pdfs.json

# Images — one per family, 15 of 60 tasks
CONTEXTGUARD_MODE=claude backend/.venv/bin/python evaluation/harness.py \
  --golden evaluation/golden/images.json --per-family 1 \
  --out evaluation/results/images.json

# Report
backend/.venv/bin/python evaluation/report.py \
  --in evaluation/results/pdfs.json,evaluation/results/images.json \
  --out evaluation/results/report.html
```

Open `evaluation/results/report.html`. Roughly **$0.07 and 20 s per task**.

Live progress per task looks like:

```
[1/15] invoice_classic.pdf :: Which item has the highest price?
    recall=1.0 necessity=1.0 located=1.0 leak_free=True answered=True (18.2s)
```

Narrow a run with `--limit N`, `--document <id>`, `--per-family N`.
Details and metric definitions: `evaluation/README.md`.

Unit tests (no API calls, ~1 s):

```bash
cd backend && source .venv/bin/activate && python -m pytest tests/
```

---

## 6. Troubleshooting

| Symptom | Cause & fix |
|---|---|
| **"Cannot reach the ContextGuard API"** | The request never reached the server: backend down, or it restarted mid-request. Check DevTools — a dead server shows `net::ERR_`, a CORS block names itself. (Origin mismatch is no longer a cause: `localhost` and `127.0.0.1` are both accepted.) |
| **Amber "Local fallback mode" banner** | Server is in `local` mode. You edited `.env` without restarting uvicorn. Confirm with `/health`. |
| **Analysis returns 500** | Read the `detail`. `error_max_turns` means the agent ran out of turns; "Privacy policy rejected plan" is the **gate working** — the agent produced a plan keeping a sensitive, non-required region. |
| **Document withheld, not released** | Fail-closed. Reason is shown in Released Context: no plan entry, `document_required=false`, or a `redact` region the locator could not place. |
| **PDF upload refused** | Scanned PDF (no text layer), password-protected, over the page cap, or carrying attachments/JavaScript/XFA. The message says which. |
| **PDF preview blank in the UI** | `<embed>` needs the browser's PDF viewer. Fine in Chrome/Safari/Firefox; absent in headless. |
| **Frontend edits full-reload the page** | Restart `npm run dev` so `vite.config.js` (React Fast Refresh) is picked up. |

---

## 7. Known gaps — say these before someone finds them

- **Scanned PDFs are refused**; only text-layer PDFs work.
- **`review` regions are released unredacted** — the action means "a human should
  look", not "protected". Faces and signatures land here.
- **The Task Agent's sandbox is prompt-enforced**, not mechanism-enforced.
- **Originals are never deleted** from `SESSION_ROOT`.
- **Leak-free rate is 52%** in evaluation; every leak is identifier-class business
  data (`project_ref`, `claim_id`, `employee_id`), never personal data.

## 8. Next, in order of value

1. Delete `original/` after release — closes the sandbox gap *and* the retention gap.
2. Name business identifiers explicitly in `PRIVACY_SYSTEM_PROMPT`; re-run the eval.
3. Rasterise route for scanned PDFs.
4. Progressive context request between Task Agent and Privacy Agent.
