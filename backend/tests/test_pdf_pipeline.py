import pymupdf
import pytest

from app.models import PrivacyPlan, DocumentPlan, RegionPlan
from app.services.locator import attach_locations
from app.services.pdf_locator import locate_in_pdf
from app.services.redaction_service import release_documents

IBAN = "IBAN: DE89370400440532013000"


def _multipage(path, metadata=None, annot=False):
    doc = pymupdf.open()
    bodies = [
        ["INVOICE #1000", "Widget       2    45.00"],
        ["Customer: Acme Corp", IBAN, "Gizmo        1   120.00"],
        ["Terms: net 30"],
    ]
    for body in bodies:
        page = doc.new_page()
        y = 100
        for line in body:
            page.insert_text((72, y), line, fontsize=13)
            y += 28
        if annot:
            page.add_text_annot((400, 400), "claimant is Paul Lehmann")
    if metadata:
        doc.set_metadata(metadata)
    doc.save(path)
    doc.close()
    return path


def _plan(**region_kw):
    return PrivacyPlan(task_summary="t", documents=[
        DocumentPlan(document_id="claim.pdf", regions=[
            RegionPlan(text=IBAN, category="iban", sensitive=True,
                       task_required=False, action="redact", reason="t", **region_kw),
        ]),
    ])


def _dirs(tmp_path):
    orig, rel = tmp_path / "original", tmp_path / "released"
    orig.mkdir(); rel.mkdir()
    return orig, rel


def test_locator_finds_the_page_by_sweeping(tmp_path):
    pdf = _multipage(tmp_path / "claim.pdf")
    found = locate_in_pdf(pdf, IBAN)
    assert found is not None
    page, box = found
    assert page == 2                       # discovered, not declared
    assert box.x2 > box.x1 and box.y2 > box.y1


def test_locator_returns_none_for_absent_text(tmp_path):
    pdf = _multipage(tmp_path / "claim.pdf")
    assert locate_in_pdf(pdf, "+44 7700 900123") is None


def test_dispatcher_fills_page_and_bbox(tmp_path):
    _multipage(tmp_path / "claim.pdf")
    plan = attach_locations(tmp_path, _plan())
    region = plan.documents[0].regions[0]
    assert region.page == 2 and region.bbox is not None


def test_released_pdf_has_glyphs_removed_not_covered(tmp_path):
    orig, rel = _dirs(tmp_path)
    _multipage(orig / "claim.pdf")
    plan = attach_locations(orig, _plan())

    released, withheld = release_documents(orig, rel, plan)
    assert released == ["claim.pdf"] and withheld == []

    with pymupdf.open(rel / "claim.pdf") as doc:
        text = "".join(page.get_text() for page in doc)
    # The whole point: not merely painted over.
    assert "DE89370400440532013000" not in text
    # Task-relevant content survives.
    assert "120.00" in text and "INVOICE #1000" in text


def test_release_strips_metadata_and_annotations(tmp_path):
    orig, rel = _dirs(tmp_path)
    _multipage(orig / "claim.pdf",
               metadata={"author": "Paul Lehmann", "title": "Claim 3001"},
               annot=True)
    plan = attach_locations(orig, _plan())

    release_documents(orig, rel, plan)
    with pymupdf.open(rel / "claim.pdf") as doc:
        assert not doc.metadata.get("author")
        assert not doc.metadata.get("title")
        assert not doc.has_annots()


def test_unlocatable_region_withholds_the_pdf(tmp_path):
    orig, rel = _dirs(tmp_path)
    _multipage(orig / "claim.pdf")
    plan = PrivacyPlan(task_summary="t", documents=[
        DocumentPlan(document_id="claim.pdf", regions=[
            RegionPlan(text="NOT ON ANY PAGE", category="phone", sensitive=True,
                       task_required=False, action="redact", reason="t"),
        ]),
    ])
    released, withheld = release_documents(orig, rel, attach_locations(orig, plan))
    assert released == []
    assert "Could not locate" in withheld[0]["reason"]
