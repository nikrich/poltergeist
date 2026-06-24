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
