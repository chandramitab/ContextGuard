"""Locate plan regions inside a PDF's text layer.

The image locator has to bridge two independent readings of the same page —
Claude's transcription and Tesseract's — which is why it matches fuzzily. Here
both sides quote the same text layer, so the match is exact and the rectangle
comes straight from the glyph positions.

The page number is discovered by sweeping, not declared by the model: like the
bounding box, which page a region sits on is a localization detail.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

from app.models import BBox


def locate_in_pdf(pdf_path: Path, target: str) -> tuple[int, BBox] | None:
    """Return (1-indexed page, box in points) for `target`, or None."""
    if not target.strip():
        return None

    with pymupdf.open(pdf_path) as doc:
        for index in range(doc.page_count):
            hits = doc[index].search_for(target)
            if not hits:
                continue
            # A phrase wrapping across lines comes back as several rects; the
            # union covers the whole run.
            rect = hits[0]
            for extra in hits[1:]:
                rect |= extra
            return index + 1, BBox(
                x1=int(rect.x0), y1=int(rect.y0),
                x2=int(rect.x1) + 1, y2=int(rect.y1) + 1,
            )
    return None


def attach_pdf_locations(pdf_path: Path, document) -> None:
    """Fill in page + bbox for every region this document wants redacted."""
    for region in document.regions:
        if region.action != "redact":
            continue
        found = locate_in_pdf(pdf_path, region.text)
        if found:
            region.page, region.bbox = found
