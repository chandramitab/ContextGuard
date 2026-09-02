from pathlib import Path

from PIL import Image, ImageDraw

from app.models import PrivacyPlan, DocumentPlan, RegionPlan, BBox
from app.services.session_service import create_session
from app.services.redaction_service import release_documents


def _image(path: Path):
    Image.new("RGB", (200, 80), "white").save(path)


def _dirs(tmp_path):
    orig, rel = tmp_path / "original", tmp_path / "released"
    orig.mkdir(); rel.mkdir()
    return orig, rel


def _region(action="redact", bbox=None):
    return RegionPlan(text="DE89", category="iban", sensitive=True,
                      task_required=False, action=action, reason="test", bbox=bbox)


def test_create_session_returns_id_and_two_dirs():
    # The pipeline unpacks this tuple; a shape change breaks every request.
    session_id, original_dir, released_dir = create_session()
    assert isinstance(session_id, str)
    assert original_dir.is_dir() and released_dir.is_dir()


def test_document_missing_from_plan_is_withheld(tmp_path):
    orig, rel = _dirs(tmp_path)
    _image(orig / "unplanned.png")
    released, withheld = release_documents(orig, rel, PrivacyPlan(task_summary="t"))
    assert released == []
    assert withheld[0]["document_id"] == "unplanned.png"


def test_unlocatable_redaction_withholds_document(tmp_path):
    orig, rel = _dirs(tmp_path)
    _image(orig / "invoice.png")
    plan = PrivacyPlan(task_summary="t", documents=[
        DocumentPlan(document_id="invoice.png", regions=[_region(bbox=None)]),
    ])
    released, withheld = release_documents(orig, rel, plan)
    assert released == []
    assert "Could not locate" in withheld[0]["reason"]


def test_located_redaction_is_painted_black(tmp_path):
    orig, rel = _dirs(tmp_path)
    src = orig / "invoice.png"
    _image(src)
    ImageDraw.Draw(Image.open(src)).rectangle([0, 0, 1, 1])
    plan = PrivacyPlan(task_summary="t", documents=[
        DocumentPlan(document_id="invoice.png",
                     regions=[_region(bbox=BBox(x1=20, y1=20, x2=60, y2=40))]),
    ])
    released, withheld = release_documents(orig, rel, plan)
    assert released == ["invoice.png"] and withheld == []
    assert Image.open(rel / "invoice.png").getpixel((40, 30)) == (0, 0, 0)


def test_document_not_required_is_dropped(tmp_path):
    orig, rel = _dirs(tmp_path)
    _image(orig / "passport.png")
    plan = PrivacyPlan(task_summary="t", documents=[
        DocumentPlan(document_id="passport.png", document_required=False,
                     reason="irrelevant to task"),
    ])
    released, withheld = release_documents(orig, rel, plan)
    assert released == []
    assert withheld[0]["reason"] == "irrelevant to task"
