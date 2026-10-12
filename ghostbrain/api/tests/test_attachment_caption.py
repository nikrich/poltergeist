from pathlib import Path

import pytest

from ghostbrain.api.repo import attachment_caption as cap
from ghostbrain.llm import client as llm_client


def test_is_image():
    assert cap.is_image("a.png", "image/png")
    assert cap.is_image("a.JPG", "")
    assert cap.is_image("a.webp", "image/webp")
    assert not cap.is_image("a.pdf", "application/pdf")
    assert not cap.is_image("a.txt", "text/plain")


def test_image_ext():
    assert cap.image_ext("a.png", "image/png") == ".png"
    assert cap.image_ext("photo.JPEG", "") == ".jpeg"
    assert cap.image_ext("noext", "image/gif") == ".gif"
    assert cap.image_ext("noext", "") == ".png"  # last-resort default


def test_caption_image_returns_text(monkeypatch, tmp_path):
    class _R:
        text = "A whiteboard with three boxes labelled A, B, C."

    called = {}

    def fake_run(prompt, *, image_paths=None, model=None, **kw):
        called["image_paths"] = image_paths
        called["model"] = model
        return _R()

    monkeypatch.setattr(llm_client, "run", fake_run)
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG fake")
    out = cap.caption_image(img)
    assert "whiteboard" in out
    assert called["image_paths"] == [str(img)]
    assert called["model"] == "sonnet"


def test_caption_image_empty_on_llm_error(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise llm_client.LLMError("vision unavailable")

    monkeypatch.setattr(llm_client, "run", boom)
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG fake")
    assert cap.caption_image(img) == ""


def test_caption_image_empty_on_generic_exception(monkeypatch, tmp_path):
    """caption_image must never raise, even for non-LLMError failures
    (e.g. an OSError bubbling up from the subprocess call)."""

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(llm_client, "run", boom)
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG fake")
    assert cap.caption_image(img) == ""


def _image_pdf(*sizes: tuple[int, int]) -> bytes:
    """An image-only PDF (no text layer): one page per size, each a picture."""
    import io

    from PIL import Image

    pages = [Image.new("RGB", s, (200, 30, 30)) for s in sizes]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


def test_caption_pdf_images_captions_each_page(monkeypatch, tmp_path):
    seen = []

    def fake_caption(path):
        seen.append(Path(path).suffix)
        assert Path(path).read_bytes()  # a real image file on disk
        return f"caption {len(seen)}"

    monkeypatch.setattr(cap, "caption_image", fake_caption)
    out = cap.caption_pdf_images(_image_pdf((400, 300), (400, 300)))
    assert out == "## Page 1\n\ncaption 1\n\n## Page 2\n\ncaption 2"
    assert all(s in cap.IMAGE_EXTENSIONS for s in seen)


def test_caption_pdf_images_single_page_has_no_heading(monkeypatch, tmp_path):
    monkeypatch.setattr(cap, "caption_image", lambda p: "the infographic")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(_image_pdf((400, 300)))
    assert cap.caption_pdf_images(pdf) == "the infographic"


def test_caption_pdf_images_skips_tiny_images_and_caps_count(monkeypatch):
    calls = []
    monkeypatch.setattr(cap, "caption_image", lambda p: calls.append(p) or "c")
    monkeypatch.setattr(cap, "MAX_PDF_IMAGES", 2)
    cap.caption_pdf_images(_image_pdf((16, 16), (400, 300), (400, 300), (400, 300)))
    assert len(calls) == 2


def test_caption_pdf_images_empty_when_unreadable_or_uncaptioned(monkeypatch):
    monkeypatch.setattr(cap, "caption_image", lambda p: "")
    assert cap.caption_pdf_images(_image_pdf((400, 300))) == ""
    assert cap.caption_pdf_images(b"not a pdf") == ""


def test_extract_or_caption_falls_back_for_image_only_pdf(monkeypatch):
    monkeypatch.setattr(cap, "caption_image", lambda p: "the infographic")
    assert cap.extract_or_caption("a.pdf", "application/pdf", _image_pdf((400, 300))) == "the infographic"


def test_extract_or_caption_reraises_when_nothing_captions(monkeypatch):
    from ghostbrain.api.repo.attachment_extract import ExtractionError

    monkeypatch.setattr(cap, "caption_image", lambda p: "")
    with pytest.raises(ExtractionError):
        cap.extract_or_caption("a.pdf", "application/pdf", _image_pdf((400, 300)))
