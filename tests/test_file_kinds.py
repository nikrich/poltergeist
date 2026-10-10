"""Shared file-kind classification used by chat attachments and the docs library."""
import pytest

from ghostbrain.api.repo import file_kinds


@pytest.mark.parametrize(
    "name,mime,kind",
    [
        ("a.md", "", "text"),
        ("a.py", "", "text"),
        ("notes", "text/plain", "text"),
        ("a.png", "", "image"),
        ("a", "image/jpeg", "image"),
        ("a.pdf", "", "pdf"),
        ("a.docx", "", "docx"),
        ("a.xlsx", "", "xlsx"),
        ("a.zip", "application/zip", None),
    ],
)
def test_classify(name, mime, kind):
    assert file_kinds.classify(name, mime) == kind


def test_caps():
    assert file_kinds.cap_for("text") == 1_000_000
    assert file_kinds.cap_for("image") == 20_000_000
    assert file_kinds.cap_for("pdf") == 20_000_000
    assert file_kinds.cap_for("opaque") == 20_000_000


def test_text_body_fences_code_and_passes_markdown():
    assert file_kinds.text_body("a.md", b"# hi") == "# hi"
    assert file_kinds.text_body("a.py", b"x = 1") == "```py\nx = 1\n```"
    with pytest.raises(UnicodeDecodeError):
        file_kinds.text_body("a.txt", b"\xff\xfe\x00")
