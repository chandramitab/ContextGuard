"""Release a PDF with sensitive glyphs removed, not merely covered.

`draw_rect` paints a black box over text that stays in the content stream and
stays selectable — the classic redaction failure. `apply_redactions` removes the
glyphs underneath. Only the second is redaction.

The same pass strips the channels the inspector flagged: metadata, annotations
and form fields all carry text that survives page-level redaction.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

_BLANK_METADATA = {
    "title": "", "author": "", "subject": "", "keywords": "",
    "creator": "", "producer": "",
}


def _strip_channels(doc) -> None:
    """Remove text-bearing structures that page redaction does not touch."""
    doc.set_metadata(_BLANK_METADATA)
    doc.del_xml_metadata()
    for page in doc:
        for annot in list(page.annots()):
            page.delete_annot(annot)
        for widget in list(page.widgets()):
            page.delete_widget(widget)


def redact_pdf(src: Path, dst: Path, document) -> None:
    """Write a redacted copy of `src` to `dst` following `document`'s plan.

    Assumes every `redact` region already carries a page and bbox; the caller
    withholds the document otherwise, so an unlocatable region never reaches here.
    """
    with pymupdf.open(src) as doc:
        for region in document.regions:
            if region.action != "redact" or not region.bbox or not region.page:
                continue
            page = doc[region.page - 1]
            b = region.bbox
            page.add_redact_annot(pymupdf.Rect(b.x1, b.y1, b.x2, b.y2), fill=(0, 0, 0))

        for page in doc:
            # Removes the glyphs under every annotation added above.
            page.apply_redactions()

        _strip_channels(doc)
        doc.save(dst, garbage=4, deflate=True, clean=True)
