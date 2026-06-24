# ghostbrain/api/tests/test_extract_photo.py
from unittest.mock import patch
from ghostbrain.api.repo import notes_manual


def test_extract_appends_callout(tmp_vault):  # tmp_vault: existing fixture creating a vault + inbox jot
    rec = notes_manual.write_inbox_jot("whiteboard shot\n\n")
    asset = "90-meta/assets/jots/2026/06/x-1.jpg"

    class R:  # minimal LLMResult stand-in
        text = "Events flow Kinesis to handler. DLQ on failure."

    with patch.object(notes_manual, "llm_run", return_value=R()):
        out = notes_manual.extract_photo_into_jot(rec["id"], asset)

    assert out["extracted"] is True
    assert "> **Extracted from photo**" in out["body"]
    assert "Events flow Kinesis" in out["body"]


def test_extract_rejects_path_outside_asset_dir(tmp_vault):
    rec = notes_manual.write_inbox_jot("hi\n\n")
    out = notes_manual.extract_photo_into_jot(rec["id"], "../../etc/passwd")
    assert out["extracted"] is False
    assert "asset" in out["reason"].lower()


def test_extract_blank_vision_result_returns_extracted_false(tmp_vault):
    """When the LLM returns empty/whitespace text, return extracted=False and
    leave the body unchanged (no callout appended)."""
    rec = notes_manual.write_inbox_jot("whiteboard shot\n\n")
    original_body = notes_manual.read_jot(rec["id"])["body"]
    asset = "90-meta/assets/jots/2026/06/x-blank.jpg"

    class R:  # minimal LLMResult stand-in
        text = "   \n  "  # whitespace only

    with patch.object(notes_manual, "llm_run", return_value=R()):
        out = notes_manual.extract_photo_into_jot(rec["id"], asset)

    assert out["extracted"] is False
    assert out["reason"] == "no readable content in photo"
    # Body must not have been modified — no callout appended.
    assert out["body"] == original_body
    assert "> **Extracted from photo**" not in out["body"]
