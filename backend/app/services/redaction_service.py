from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw
import shutil

from app.services.pdf_redactor import redact_pdf

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED_EXTS = IMAGE_EXTS | {".pdf"}


def _paint_image(src: Path, dst: Path, decision) -> None:
    shutil.copy2(src, dst)
    image = Image.open(dst).convert("RGB")
    draw = ImageDraw.Draw(image)
    for region in decision.regions:
        if region.action != "redact" or not region.bbox:
            continue
        b = region.bbox
        m = 4
        draw.rectangle(
            [
                max(0, b.x1 - m), max(0, b.y1 - m),
                min(image.width, b.x2 + m), min(image.height, b.y2 + m)
            ],
            fill="black"
        )
    image.save(dst)


def release_documents(original_dir: Path, released_dir: Path, plan):
    """Copy originals into released/ with sensitive pixels painted over.

    Fails closed: a document is released only when the plan covers it and every
    region marked `redact` has a bounding box we can actually paint. Anything
    else is withheld with a reason instead of leaking through unredacted.
    """
    released_names = []
    withheld = []
    by_id = {Path(d.document_id).name: d for d in plan.documents}

    for src in sorted(original_dir.iterdir()):
        if not src.is_file():
            continue

        decision = by_id.get(src.name)
        if decision is None:
            withheld.append({
                "document_id": src.name,
                "reason": "No privacy plan entry for this document; withheld.",
            })
            continue

        if not decision.document_required:
            withheld.append({
                "document_id": src.name,
                "reason": decision.reason or "Document not required for the task.",
            })
            continue

        if src.suffix.lower() not in SUPPORTED_EXTS:
            withheld.append({
                "document_id": src.name,
                "reason": "Unsupported file type; ContextGuard can only redact "
                          "images and PDFs.",
            })
            continue

        unlocated = [
            r.category for r in decision.regions
            if r.action == "redact" and not r.bbox
        ]
        if unlocated:
            withheld.append({
                "document_id": src.name,
                "reason": (
                    "Could not locate "
                    + ", ".join(sorted(set(unlocated)))
                    + " marked for redaction; document withheld rather than "
                      "released with the sensitive content intact."
                ),
            })
            continue

        dst = released_dir / src.name
        if src.suffix.lower() == ".pdf":
            redact_pdf(src, dst, decision)
        else:
            _paint_image(src, dst, decision)

        released_names.append(src.name)

    return released_names, withheld
