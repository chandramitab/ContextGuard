from PIL import Image, ImageDraw, ImageFont

from app.models import PrivacyPlan, DocumentPlan, RegionPlan, BBox
from app.services.locator import attach_locations
from app.services.ocr_locator import locate_text

FONT = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 26)


def _page(path, lines):
    image = Image.new("RGB", (760, 60 + 40 * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines):
        draw.text((36, 20 + 40 * i), line, fill="black", font=FONT)
    image.save(path)
    return path


def test_locates_text_despite_ocr_misreads(tmp_path):
    page = _page(tmp_path / "doc.png", ["Email: billing@acme.example",
                                        "IBAN: DE89370400440532013000"])
    assert locate_text(page, "billing@acme.example") is not None
    assert locate_text(page, "DE89370400440532013000") is not None


def test_box_stays_on_one_line(tmp_path):
    page = _page(tmp_path / "doc.png", ["Customer: Acme Corp",
                                        "Address: 14 Harbour Road, Bristol",
                                        "Widget 2 45.00"])
    box = locate_text(page, "Acme Corp")
    assert box is not None
    # A window spanning rows would produce a box far taller than one text line.
    assert box["y2"] - box["y1"] < 40


def test_absent_text_is_not_located(tmp_path):
    page = _page(tmp_path / "doc.png", ["Widget 2 45.00"])
    assert locate_text(page, "+44 7700 900123") is None


def test_attach_locations_normalizes_document_id_and_builds_bbox(tmp_path):
    _page(tmp_path / "doc.png", ["IBAN: DE89370400440532013000"])
    plan = PrivacyPlan(task_summary="t", documents=[
        DocumentPlan(document_id="./doc.png", regions=[
            RegionPlan(text="DE89370400440532013000", category="iban",
                       sensitive=True, task_required=False, action="redact",
                       reason="test"),
        ]),
    ])
    plan = attach_locations(tmp_path, plan)
    assert plan.documents[0].document_id == "doc.png"
    # Redaction needs a real BBox; a plain dict only fails later.
    assert isinstance(plan.documents[0].regions[0].bbox, BBox)
    assert plan.documents[0].regions[0].page == 1
