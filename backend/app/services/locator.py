"""Dispatch each document to the locator that suits its file type."""
from __future__ import annotations

from pathlib import Path

from app.services.ocr_locator import IMAGE_EXTS, attach_image_bboxes
from app.services.pdf_locator import attach_pdf_locations


def attach_locations(original_dir: Path, plan):
    for document in plan.documents:
        # Claude sometimes emits "./invoice.png" or a path prefix when several
        # files are in play; the plan must key off the same basename the
        # redaction service iterates over, or the document falls through unmatched.
        document.document_id = Path(document.document_id).name
        path = original_dir / document.document_id
        if not path.exists():
            continue

        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTS:
            attach_image_bboxes(path, document)
        elif suffix == ".pdf":
            attach_pdf_locations(path, document)
    return plan
