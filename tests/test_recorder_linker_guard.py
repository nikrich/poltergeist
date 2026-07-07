"""Linker minimum-content guard.

Whisper hallucinates a lone word (classically "you") on silent recordings.
Such a transcript passed the linker's empty-check and became a junk
"untitled-meeting" note — 39 of them accumulated in production and, being
mutually similar, dominated generic semantic-search queries ("what meetings
did I have today") over real transcripts. Transcripts below a minimum word
count must be rejected with a distinct exception so the daemon can discard
the recording terminally instead of retrying it forever.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ghostbrain.recorder.linker import TranscriptTooShort, link_transcript


@pytest.fixture()
def tmp_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault = tmp_path / "vault"
    (vault / "20-contexts").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    return vault


def _txt(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "meeting-20260518-090022-manual.txt"
    p.write_text(body, encoding="utf-8")
    return p


def test_hallucinated_single_word_transcript_is_rejected(
    tmp_path: Path, tmp_vault: Path
) -> None:
    txt = _txt(tmp_path, "you")
    with pytest.raises(TranscriptTooShort):
        link_transcript(
            txt, started_at=datetime.now(timezone.utc), duration_s=828.0
        )
    # No junk note may be written anywhere in the vault.
    assert not list(tmp_vault.rglob("*.md"))


def test_short_filler_transcript_is_rejected(tmp_path: Path, tmp_vault: Path) -> None:
    txt = _txt(tmp_path, "Okay. Thank you. Bye.")
    with pytest.raises(TranscriptTooShort):
        link_transcript(
            txt, started_at=datetime.now(timezone.utc), duration_s=300.0
        )


def test_real_transcript_still_links(tmp_path: Path, tmp_vault: Path) -> None:
    body = (
        "Right, so the plan for the staging environment is to fix the "
        "self-service login flow first, then re-verify the architectural "
        "release from last week before the July fourteen soft launch. "
        "Cameron will confirm with Fred once the fix is deployed."
    )
    txt = _txt(tmp_path, body)
    result = link_transcript(
        txt, started_at=datetime.now(timezone.utc), duration_s=1800.0
    )
    assert result.transcript_note.exists()
    assert body.split()[0] in result.transcript_note.read_text(encoding="utf-8")


def test_empty_transcript_still_raises(tmp_path: Path, tmp_vault: Path) -> None:
    txt = _txt(tmp_path, "   \n")
    with pytest.raises(RuntimeError):
        link_transcript(
            txt, started_at=datetime.now(timezone.utc), duration_s=60.0
        )
