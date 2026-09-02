import pymupdf
import pytest
from PIL import Image

from app.services.upload_inspector import inspect_upload, sniff_kind, MAX_PDF_PAGES


def _image_bytes(tmp_path, fmt="PNG", name="x"):
    p = tmp_path / f"{name}.{fmt.lower()}"
    Image.new("RGB", (40, 40), "white").save(p, fmt)
    return p.read_bytes()


def _pdf_bytes(pages=1, text="Customer: Acme Corp", metadata=None, annot=False):
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_text((72, 100), text, fontsize=14)
        if annot:
            page.add_text_annot((200, 200), "reviewer note: claimant is Paul Lehmann")
    if metadata:
        doc.set_metadata(metadata)
    data = doc.tobytes()
    doc.close()
    return data


# ── content sniffing ────────────────────────────────────────────────

def test_sniffs_each_supported_kind(tmp_path):
    assert sniff_kind(_image_bytes(tmp_path, "PNG")) == "png"
    assert sniff_kind(_image_bytes(tmp_path, "JPEG")) == "jpeg"
    assert sniff_kind(_image_bytes(tmp_path, "WEBP")) == "webp"
    assert sniff_kind(_pdf_bytes()) == "pdf"
    assert sniff_kind(b"just some text") is None


def test_png_is_accepted(tmp_path):
    v = inspect_upload("invoice.png", _image_bytes(tmp_path, "PNG"))
    assert v.accepted and v.kind == "png"


def test_jpg_extension_matches_jpeg_content(tmp_path):
    v = inspect_upload("photo.jpg", _image_bytes(tmp_path, "JPEG"))
    assert v.accepted, v.reason


def test_file_that_misdescribes_itself_is_refused():
    # A PDF renamed to .png previously sailed past the extension check and only
    # blew up later inside PIL.
    v = inspect_upload("secret.png", _pdf_bytes())
    assert not v.accepted
    assert "misdescribes itself" in v.reason


def test_unrecognised_and_empty_are_refused():
    assert not inspect_upload("notes.txt", b"hello there").accepted
    assert not inspect_upload("empty.png", b"").accepted


# ── PDF routing ─────────────────────────────────────────────────────

def test_text_pdf_routes_to_text():
    v = inspect_upload("claim.pdf", _pdf_bytes(text="IBAN: DE89370400440532013000"))
    assert v.accepted and v.route == "text" and v.page_count == 1


def test_scanned_pdf_routes_to_raster():
    # No text layer: only an embedded image, as a scan would be.
    doc = pymupdf.open()
    page = doc.new_page()
    img = pymupdf.open()
    tmp = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200))
    tmp.clear_with(255)
    page.insert_image(pymupdf.Rect(0, 0, 200, 200), pixmap=tmp)
    data = doc.tobytes()
    doc.close(); img.close()
    v = inspect_upload("scan.pdf", data)
    assert v.accepted and v.route == "raster"


def test_page_limit_is_enforced():
    v = inspect_upload("long.pdf", _pdf_bytes(pages=MAX_PDF_PAGES + 1))
    assert not v.accepted
    assert f"limit is {MAX_PDF_PAGES}" in v.reason


def test_corrupt_pdf_is_refused():
    assert not inspect_upload("broken.pdf", b"%PDF-1.7\nnot really a pdf").accepted


# ── channels redaction cannot reach ─────────────────────────────────

def test_embedded_attachment_blocks_the_document():
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "cover page", fontsize=14)
    doc.embfile_add("hidden", b"IBAN: DE89370400440532013000")
    data = doc.tobytes()
    doc.close()
    v = inspect_upload("carrier.pdf", data)
    assert not v.accepted
    assert "attachment" in v.reason


def test_metadata_is_flagged_for_stripping_not_blocked():
    data = _pdf_bytes(metadata={"author": "Paul Lehmann", "title": "Claim 3001"})
    v = inspect_upload("claim.pdf", data)
    assert v.accepted, v.reason
    assert any("metadata" in s for s in v.strip)


def test_annotations_are_flagged_for_stripping():
    v = inspect_upload("claim.pdf", _pdf_bytes(annot=True))
    assert v.accepted, v.reason
    assert any("annotation" in s for s in v.strip)


def test_clean_pdf_needs_no_stripping():
    v = inspect_upload("claim.pdf", _pdf_bytes())
    assert v.accepted and v.strip == []


def test_document_javascript_blocks_the_document():
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "invoice", fontsize=14)
    cat = doc.pdf_catalog()
    js_xref = doc.get_new_xref()
    doc.update_object(js_xref, "<</S/JavaScript/JS(app.alert\\('hi'\\);)>>")
    names_xref = doc.get_new_xref()
    doc.update_object(names_xref, f"<</Names[(A) {js_xref} 0 R]>>")
    doc.xref_set_key(cat, "Names", f"<</JavaScript {names_xref} 0 R>>")
    data = doc.tobytes()
    doc.close()

    v = inspect_upload("macro.pdf", data)
    assert not v.accepted
    assert "JavaScript" in v.reason
