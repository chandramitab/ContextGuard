from __future__ import annotations
from pathlib import Path
from difflib import SequenceMatcher
from PIL import Image
import pytesseract
from pytesseract import Output

from app.models import BBox

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Tesseract routinely misreads characters ("billing@" -> "billng@", "DE89" ->
# "DEB9"), so exact string matching silently drops redactions the Privacy Agent
# asked for. Match fuzzily instead, with a stricter ratio for short targets so we
# do not black out unrelated words.
MAX_WINDOW = 10
LONG_TARGET = 8
LONG_RATIO = 0.72
SHORT_RATIO = 0.85


def _norm(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum())


def _threshold(target_norm: str) -> float:
    return LONG_RATIO if len(target_norm) >= LONG_TARGET else SHORT_RATIO


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _read_tokens(image_path: Path):
    image = Image.open(image_path).convert("RGB")
    data = pytesseract.image_to_data(image, output_type=Output.DICT)
    tokens = []
    for i, raw in enumerate(data["text"]):
        norm = _norm((raw or "").strip())
        if not norm:
            continue
        tokens.append({
            "line": (data["block_num"][i], data["par_num"][i], data["line_num"][i]),
            "norm": norm,
            "x": int(data["left"][i]),
            "y": int(data["top"][i]),
            "w": int(data["width"][i]),
            "h": int(data["height"][i]),
        })
    return tokens


def _group_by_line(tokens):
    lines, current, key = [], [], None
    for token in tokens:
        if token["line"] != key:
            if current:
                lines.append(current)
            current, key = [], token["line"]
        current.append(token)
    if current:
        lines.append(current)
    return lines


def _box(boxes):
    return {
        "x1": min(b["x"] for b in boxes),
        "y1": min(b["y"] for b in boxes),
        "x2": max(b["x"] + b["w"] for b in boxes),
        "y2": max(b["y"] + b["h"] for b in boxes),
    }


def locate_text(image_path: Path, target: str):
    """Claude decides WHAT to redact; this helper only finds WHERE."""
    target_norm = _norm(target)
    if not target_norm:
        return None

    tokens = _read_tokens(image_path)
    if not tokens:
        return None

    best_score, best_boxes = 0.0, None

    # Windows never cross an OCR line, otherwise the min/max bounding box spans
    # whole rows of the page and blacks out unrelated content.
    for line in _group_by_line(tokens):
        for start in range(len(line)):
            combined = ""
            boxes = []
            for token in line[start:start + MAX_WINDOW]:
                combined += token["norm"]
                boxes.append(token)

                score = _ratio(target_norm, combined)
                # A long target sitting inside the window is a certain hit.
                if len(target_norm) >= LONG_TARGET and target_norm in combined:
                    score = 1.0
                if score > best_score:
                    best_score, best_boxes = score, list(boxes)

                # Once the window dwarfs the target, extending it only hurts.
                if len(combined) > len(target_norm) * 2 + 4:
                    break

    if best_boxes and best_score >= _threshold(target_norm):
        return _box(best_boxes)
    return None


def attach_image_bboxes(image_path: Path, document) -> None:
    """Fill in bbox for every region this image document wants redacted."""
    for region in document.regions:
        if region.action != "redact":
            continue
        bbox = locate_text(image_path, region.text)
        if bbox:
            # Must be a BBox, not a dict: pydantic does not validate on
            # assignment, so a dict here only explodes later in redaction.
            region.page = 1
            region.bbox = BBox(**bbox)
