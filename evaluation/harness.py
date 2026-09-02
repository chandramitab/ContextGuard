"""Stage-by-stage evaluation of the ContextGuard pipeline.

Runs the real pipeline in-process (not over HTTP) so every stage can be scored
against `golden/`, and writes one JSON record per (document, task).

The central idea: the must-not-appear set is *task-relative*. The IBAN is a leak
when the task is "which item costs most" and the expected answer when the task is
"what IBAN should this be paid to". A single global PII blocklist would score this
system as broken by design, so necessity comes from the golden file, not the plan.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv                    # noqa: E402

# The harness imports `pipeline` directly, so main.py's load_dotenv never runs.
# Without this, ANTHROPIC_API_KEY and CONTEXTGUARD_MODE in backend/.env are
# invisible to evaluation runs.
load_dotenv(ROOT / "backend" / ".env", override=False)

import pymupdf                                    # noqa: E402
import pytesseract                                # noqa: E402
from PIL import Image                             # noqa: E402
from starlette.datastructures import UploadFile   # noqa: E402

from app.services.pipeline import run_pipeline, UnsupportedUpload  # noqa: E402

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


# ── text comparison ──────────────────────────────────────────────────

def _loose(s: str) -> str:
    """Case-fold and collapse whitespace so spacing differences do not matter."""
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _tight(s: str) -> str:
    """Also drop separators, so 'DE00 0000' matches 'DE000000'."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# Tesseract confuses these glyph pairs constantly. Without folding them, a leak
# check against OCR text reports "clean" for an IBAN sitting in plain sight:
# 'DE00' reads back as 'DEOO', and 'Kaiserstraße' as 'KaiserstraBe'.
_CONFUSABLE = str.maketrans({"o": "0", "l": "1", "i": "1", "ß": "b"})


def _fold(s: str) -> str:
    """Accent-stripped, confusable-folded form for comparing against OCR text."""
    decomposed = unicodedata.normalize("NFKD", (s or "").lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", stripped.translate(_CONFUSABLE))


def contains(haystack: str, needle: str) -> bool:
    """Is `needle` present in `haystack`?

    Three increasingly forgiving forms, OR-ed. All three are exact substring
    tests after normalisation — deliberately not a fuzzy ratio. These documents
    carry IBANs differing in 4 of 26 characters, and any ratio loose enough to
    absorb OCR damage also matches a *different* customer's account.
    """
    if not needle:
        return False
    return (
        _loose(needle) in _loose(haystack)
        or _tight(needle) in _tight(haystack)
        or _fold(needle) in _fold(haystack)
    )


def region_covers(region_text: str, value: str) -> bool:
    """Does a plan region refer to this ground-truth value?

    Matched in both directions — the agent may quote the whole line
    ("Project Ref: ORION-47") or just the value — but a very short region text
    is not allowed to match a long value, which would over-credit coverage.
    """
    if contains(region_text, value):
        return True
    return len(_tight(region_text)) >= 4 and contains(value, region_text)


def answer_matches(answer: str, expected: str) -> bool:
    """Every substantive part of the expected answer must appear.

    Expected answers look like "Hydraulic Pump - EUR 4,250.00"; the agent phrases
    it freely, so require the parts rather than the exact string.
    """
    # Split on " - " only. Splitting on commas shatters "4,250.00" into
    # fragments that no correctly-phrased answer contains.
    parts = [p.strip() for p in re.split(r"\s+-\s+", expected) if p.strip()]
    parts = [_strip_currency(p) for p in parts]
    parts = [p for p in parts if _tight(p)]
    return all(contains(answer, p) for p in parts) if parts else contains(answer, expected)


def _strip_currency(s: str) -> str:
    """Drop currency markers so 'EUR 4,250.00' matches '€ 4,250.00'."""
    return re.sub(r"\b(eur|usd|gbp)\b|[€$£]", " ", s, flags=re.I).strip()


# ── reading what was actually released ───────────────────────────────

def released_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            return "".join(page.get_text() for page in doc)
    if path.suffix.lower() in IMAGE_EXTS:
        return pytesseract.image_to_string(Image.open(path))
    return ""


def _upload(path: Path) -> UploadFile:
    return UploadFile(filename=path.name, file=io.BytesIO(path.read_bytes()))


# ── scoring one (document, task) ─────────────────────────────────────

def score(doc: dict, task: dict, result: dict, released_dir: Path) -> dict:
    pii = doc["pii"]
    required = set(task.get("requires", []))
    must_go = {f: v for f, v in pii.items() if f not in required}
    must_stay = {f: pii[f] for f in required if f in pii}

    regions = [r for d in result["privacy_plan"]["documents"] for r in d["regions"]]

    # Stage 2 — did the Privacy Agent notice each piece of PII at all?
    detected = {f: any(region_covers(r["text"], v) for r in regions)
                for f, v in pii.items()}

    # Stage 2 — did it get necessity right, given this task?
    def decided_redact(value: str) -> bool:
        return any(region_covers(r["text"], value) and r["action"] != "keep" for r in regions)

    def decided_keep(value: str) -> bool:
        return any(region_covers(r["text"], value) and r["action"] == "keep" for r in regions)

    necessity = {}
    for f, v in must_go.items():
        necessity[f] = {"should": "redact", "ok": decided_redact(v)}
    for f, v in must_stay.items():
        necessity[f] = {"should": "keep", "ok": decided_keep(v) or not decided_redact(v)}

    # Stage 4 — localization
    redacts = [r for r in regions if r["action"] == "redact"]
    located = [r for r in redacts if r.get("bbox")]

    # Stage 5/6 — what actually left the boundary
    released = [released_dir / Path(u).name for u in result["released_urls"]]
    corpus = "".join(released_text(p) for p in released if p.exists())

    leaked = {f: v for f, v in must_go.items() if contains(corpus, v)}
    survived = {f: v for f, v in must_stay.items() if contains(corpus, v)}
    answered = answer_matches(result["final_answer"], task["expected_answer"])

    return {
        "document": doc["id"],
        "question": task["question"],
        "expected_answer": task["expected_answer"],
        "answer": result["final_answer"],
        "stages": {
            "intake": {"accepted": True, "inspections": result.get("inspections", [])},
            "privacy_agent": {
                "regions": len(regions),
                "pii_detected": detected,
                "pii_recall": round(sum(detected.values()) / len(detected), 3) if detected else None,
                "necessity": necessity,
                "necessity_accuracy": round(
                    sum(n["ok"] for n in necessity.values()) / len(necessity), 3
                ) if necessity else None,
            },
            "policy_gate": {"verdict": result["gate"]},
            "locate": {
                "redact_regions": len(redacts),
                "located": len(located),
                "localization_rate": round(len(located) / len(redacts), 3) if redacts else None,
            },
            "release": {
                "released": [p.name for p in released],
                "withheld": result["withheld"],
                "leaked": leaked,
                "leak_free": not leaked,
                "required_survived": survived,
                "required_intact": len(survived) == len(must_stay),
            },
            "task_agent": {"answered_correctly": answered},
        },
        "timings": result.get("timings", {}),
        "usage": result.get("usage", {}),
        "kind": doc.get("kind", "image"),
        "family": doc.get("family", ""),
        "regions": [
            {"text": r["text"], "category": r["category"], "action": r["action"],
             "task_required": r["task_required"], "page": r.get("page"),
             "located": bool(r.get("bbox"))}
            for r in regions
        ],
    }


async def run_one(doc: dict, task: dict) -> dict:
    src = ROOT / doc["path"]
    started = time.perf_counter()
    try:
        result = await run_pipeline(task["question"], [_upload(src)])
    except UnsupportedUpload as exc:
        return {"document": doc["id"], "question": task["question"],
                "error": f"rejected at intake: {exc}", "elapsed": None}
    except Exception as exc:
        return {"document": doc["id"], "question": task["question"],
                "error": f"{type(exc).__name__}: {exc}", "elapsed": None}

    released_dir = (Path(os.getenv("SESSION_ROOT", "/tmp/contextguard-agentic"))
                    / result["session_id"] / "released")
    row = score(doc, task, result, released_dir)
    row["elapsed"] = round(time.perf_counter() - started, 2)
    return row


async def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate the ContextGuard pipeline.")
    ap.add_argument("--golden", default="evaluation/golden/invoices.json")
    ap.add_argument("--out", default="evaluation/results/latest.json")
    ap.add_argument("--limit", type=int, help="only run the first N (doc, task) pairs")
    ap.add_argument("--document", help="only this document id")
    ap.add_argument("--per-family", type=int,
                    help="sample at most N documents from each document family")
    args = ap.parse_args()

    golden = json.loads((ROOT / args.golden).read_text())
    documents = golden["documents"]
    if args.document:
        documents = [d for d in documents if d["id"] == args.document]
    if args.per_family:
        seen, sampled = {}, []
        for d in documents:
            family = d.get("family", d["id"])
            if seen.get(family, 0) < args.per_family:
                seen[family] = seen.get(family, 0) + 1
                sampled.append(d)
        documents = sampled
    pairs = [(d, t) for d in documents for t in d["tasks"]]
    if args.limit:
        pairs = pairs[:args.limit]

    print(f"mode={os.getenv('CONTEXTGUARD_MODE', 'local')}  pairs={len(pairs)}\n")
    rows = []
    for i, (doc, task) in enumerate(pairs, 1):
        print(f"[{i}/{len(pairs)}] {doc['id']} :: {task['question']}")
        row = await run_one(doc, task)
        rows.append(row)
        if "error" in row:
            print(f"    ERROR {row['error']}")
        else:
            s = row["stages"]
            print(f"    recall={s['privacy_agent']['pii_recall']} "
                  f"necessity={s['privacy_agent']['necessity_accuracy']} "
                  f"located={s['locate']['localization_rate']} "
                  f"leak_free={s['release']['leak_free']} "
                  f"answered={s['task_agent']['answered_correctly']} "
                  f"({row['elapsed']}s)")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows}, indent=2, ensure_ascii=False))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
