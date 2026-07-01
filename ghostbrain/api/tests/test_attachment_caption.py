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
