"""Deterministic pre-flight for every upload.

Runs before the Privacy Agent sees anything. Answers two structural questions
that are not judgement calls and so must not be delegated to a model:

  1. Is this file what it claims to be, and can we open it?
  2. Does it carry content our redactor cannot reach?

A PDF can hide an entire second document inside itself as an attachment, carry
active JavaScript, or keep the claimant's name in its metadata long after every
visible pixel has been blacked out. None of that is visible in a released
preview, so it is caught here or not at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os

import pymupdf

# Extension is a hint; these bytes are the evidence.
_MAGIC: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"%PDF-", "pdf"),
]

IMAGE_KINDS = {"png", "jpeg", "webp"}

# A PDF page is a separate vision read for the Privacy Agent, so page count is a
# cost and latency ceiling, not just a sanity check.
MAX_PDF_PAGES = int(os.getenv("CONTEXTGUARD_MAX_PDF_PAGES", "10"))

# Below this, a "text layer" is likely stray artefacts rather than real content.
TEXT_LAYER_MIN_CHARS = 20

_METADATA_FIELDS = ("title", "author", "subject", "keywords", "creator", "producer")


@dataclass
class UploadVerdict:
    """What the pipeline may do with one uploaded file."""

    accepted: bool
    kind: str | None = None
    reason: str = ""
    # PDFs only: "text" -> redact via the text layer; "raster" -> render pages
    # to images and fall back to the OCR path.
    route: str | None = None
    page_count: int = 1
    # Channels the release step must strip before this document leaves the
    # boundary. Non-fatal precisely because we can remove them deterministically.
    strip: list[str] = field(default_factory=list)
    # Things the operator should see but that are neither fatal nor removable.
    flags: list[str] = field(default_factory=list)


def sniff_kind(data: bytes) -> str | None:
    """Identify a file from its leading bytes, ignoring its name."""
    for magic, kind in _MAGIC:
        if data.startswith(magic):
            return kind
    # WEBP is "RIFF" + 4 size bytes + "WEBP".
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _invisible_text(doc) -> str:
    """Text present in the layer but never painted on the page.

    Render mode 3 (and zero opacity) means the glyphs are extractable but
    invisible. Scanners produce this legitimately for the OCR layer under a
    scan, so it is not fatal — but it is text no human reviewing the released
    document can see, and the Privacy Agent reads it, so the operator is told.
    """
    total = 0
    for page in doc:
        for span in page.get_texttrace():
            if span.get("type") == 3 or span.get("opacity") == 0:
                total += len(span.get("chars", ()))
    if not total:
        return ""
    return (
        f"{total} character(s) of invisible text (extractable but never rendered). "
        "Legitimate for a scanned page's OCR layer; also the channel a document "
        "would use to hide instructions from a human reviewer."
    )


def _pdf_findings(doc) -> tuple[list[str], list[str], list[str]]:
    """Split a PDF's hidden channels into blocking, strippable and advisory."""
    blocking: list[str] = []
    strip: list[str] = []
    flags: list[str] = []

    if doc.embfile_count() > 0:
        blocking.append(
            f"{doc.embfile_count()} embedded file attachment(s) — a whole document "
            "inside the document, which page redaction cannot reach"
        )

    catalog = doc.pdf_catalog()
    if doc.xref_get_key(catalog, "Names/JavaScript")[0] != "null":
        blocking.append("embedded JavaScript (active content)")
    if doc.xref_get_key(catalog, "AcroForm/XFA")[0] != "null":
        blocking.append("an XFA form — field data lives outside the page content")

    # Strippable: we can delete these deterministically when releasing.
    if any(doc.metadata.get(f) for f in _METADATA_FIELDS):
        present = [f for f in _METADATA_FIELDS if doc.metadata.get(f)]
        strip.append(f"document metadata ({', '.join(present)})")
    if doc.has_annots():
        strip.append("annotations (their text survives page redaction)")
    if doc.is_form_pdf:
        strip.append("form fields (their values survive page redaction)")

    if (hidden := _invisible_text(doc)):
        flags.append(hidden)

    return blocking, strip, flags


def _inspect_pdf(data: bytes) -> UploadVerdict:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        return UploadVerdict(False, "pdf", f"could not be parsed as a PDF ({exc}).")

    with doc:
        if doc.needs_pass or doc.is_encrypted:
            return UploadVerdict(
                False, "pdf",
                "is password-protected. ContextGuard cannot redact a document it "
                "cannot fully parse.",
            )

        pages = doc.page_count
        if pages == 0:
            return UploadVerdict(False, "pdf", "contains no pages.")
        if pages > MAX_PDF_PAGES:
            return UploadVerdict(
                False, "pdf",
                f"has {pages} pages; the limit is {MAX_PDF_PAGES} "
                "(each page is a separate agent inspection).",
            )

        blocking, strip, flags = _pdf_findings(doc)
        if blocking:
            return UploadVerdict(
                False, "pdf", "carries content redaction cannot reach: "
                + "; ".join(blocking) + ".",
                page_count=pages,
            )

        chars = sum(len(doc[i].get_text().strip()) for i in range(pages))
        route = "text" if chars >= TEXT_LAYER_MIN_CHARS else "raster"

    return UploadVerdict(
        True, "pdf", route=route, page_count=pages, strip=strip, flags=flags
    )


def inspect_upload(filename: str, data: bytes) -> UploadVerdict:
    """Decide whether one uploaded file may enter the pipeline."""
    if not data:
        return UploadVerdict(False, reason=f"{filename}: file is empty.")

    kind = sniff_kind(data)
    if kind is None:
        return UploadVerdict(
            False,
            reason=f"{filename}: unrecognised file type. ContextGuard accepts "
                   "PNG, JPEG, WEBP and PDF.",
        )

    declared = Path(filename).suffix.lower().lstrip(".")
    declared = {"jpg": "jpeg"}.get(declared, declared)
    if declared and declared != kind:
        return UploadVerdict(
            False, kind,
            f"{filename}: content is a {kind.upper()} but the name claims "
            f".{declared}. Refusing a file that misdescribes itself.",
        )

    if kind in IMAGE_KINDS:
        return UploadVerdict(True, kind)

    verdict = _inspect_pdf(data)
    if not verdict.accepted:
        verdict.reason = f"{filename}: {verdict.reason}"
    return verdict
