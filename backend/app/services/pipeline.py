from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import os
import time
import aiofiles

from app.agents.local_fallback import build_local_plan, local_answer
from app.agents.privacy_agent import run_privacy_agent
from app.agents.task_agent import run_task_agent
from app.services.session_service import create_session
from app.services.policy_service import validate_plan
from app.services.locator import attach_locations
from app.services.redaction_service import release_documents
from app.hooks.privacy_hook import set_forbidden_values
from app.services.upload_inspector import inspect_upload

class UnsupportedUpload(ValueError):
    """Raised for an upload this MVP cannot redact, so it is never released."""


@contextmanager
def _timed(timings, stage):
    """Record wall-clock seconds per stage, for the trace and for evaluation."""
    start = time.perf_counter()
    try:
        yield
    finally:
        timings[stage] = round(time.perf_counter() - start, 3)

async def run_pipeline(task, uploads):
    mode = os.getenv("CONTEXTGUARD_MODE", "local").lower()
    model = os.getenv("CONTEXTGUARD_MODEL", "sonnet")

    session_id, original_dir, released_dir = create_session()
    timings: dict[str, float] = {}
    started = time.perf_counter()

    filenames = []
    inspections: list[dict] = []
    with _timed(timings, "intake"):
        for upload in uploads:
            name = Path(upload.filename or "upload.bin").name
            data = await upload.read()

            # Structural gate: deterministic, and runs before anything is written
            # to disk so a refused file never lands in the session at all.
            verdict = inspect_upload(name, data)
            if not verdict.accepted:
                raise UnsupportedUpload(verdict.reason)
            if verdict.kind == "pdf" and verdict.route == "raster":
                raise UnsupportedUpload(
                    f"{name}: this PDF has no text layer (a scan). Rasterised PDF "
                    "support is not wired up yet."
                )

            async with aiofiles.open(original_dir / name, "wb") as f:
                await f.write(data)
            filenames.append(name)
            inspections.append({
                "document_id": name, "kind": verdict.kind, "route": verdict.route,
                "page_count": verdict.page_count,
                "strip": verdict.strip, "flags": verdict.flags,
            })

    # Ambiguous reasoning -> Claude agent.
    usage: dict[str, dict] = {}
    with _timed(timings, "privacy_agent"):
        if mode == "claude":
            plan, usage["privacy_agent"] = await run_privacy_agent(
                task, original_dir, filenames, model=model
            )
        else:
            plan = build_local_plan(task, filenames)

    # Security invariant -> deterministic application code.
    with _timed(timings, "policy_gate"):
        allowed, issues = validate_plan(plan)
    if not allowed:
        raise RuntimeError("Privacy policy rejected plan: " + "; ".join(issues))

    # Claude decides WHAT; deterministic locators find WHERE.
    with _timed(timings, "locate"):
        plan = attach_locations(original_dir, plan)

    forbidden = [
        region.text
        for document in plan.documents
        for region in document.regions
        if region.sensitive and not region.task_required and region.action != "keep"
    ]
    set_forbidden_values(forbidden)

    with _timed(timings, "release"):
        released_names, withheld = release_documents(original_dir, released_dir, plan)

    # Separate downstream agent gets released/ only.
    with _timed(timings, "task_agent"):
        if mode == "claude":
            answer, usage["task_agent"] = await run_task_agent(
                task, released_dir, released_names, model=model
            )
        else:
            answer = local_answer(task)

    usage["total"] = {
        key: sum(u.get(key, 0) or 0 for u in usage.values())
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                    "cache_read_input_tokens", "total_tokens", "cost_usd")
    }

    timings["total"] = round(time.perf_counter() - started, 3)

    return {
        "session_id": session_id,
        "mode": mode,
        "privacy_plan": plan.model_dump(),
        "released_urls": [
            f"/api/session/{session_id}/released/{name}"
            for name in released_names
        ],
        "final_answer": answer,
        "withheld": withheld,
        "inspections": inspections,
        "timings": timings,
        "usage": usage,
        "gate": "PASS",
    }
