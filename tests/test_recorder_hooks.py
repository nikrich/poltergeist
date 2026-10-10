"""Recorder ``on_transcribed`` hook: fired once the meeting note is written
(manual recover and calendar daemon), never raising into transcription."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ghostbrain.recorder import hooks


@pytest.fixture(autouse=True)
def _only_test_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    # Importing the design module registers link_meeting; keep each test to
    # the callbacks it registers itself.
    monkeypatch.setattr(hooks, "_on_transcribed", [])


def test_fire_transcribed_calls_every_callback_with_paths(tmp_path: Path) -> None:
    seen = []
    hooks.on_transcribed(lambda wav, note: seen.append(("a", wav, note)))
    hooks.on_transcribed(lambda wav, note: seen.append(("b", wav, note)))
    hooks.fire_transcribed(tmp_path / "m.wav", tmp_path / "n.md")
    assert seen == [("a", tmp_path / "m.wav", tmp_path / "n.md"),
                    ("b", tmp_path / "m.wav", tmp_path / "n.md")]


def test_on_transcribed_registers_once() -> None:
    def cb(wav: Path, note: Path) -> None: ...

    hooks.on_transcribed(cb)
    hooks.on_transcribed(cb)
    assert hooks._on_transcribed == [cb]


def test_fire_transcribed_swallows_errors(tmp_path: Path) -> None:
    seen = []

    def boom(wav: Path, note: Path) -> None:
        raise RuntimeError("boom")

    hooks.on_transcribed(boom)
    hooks.on_transcribed(lambda wav, note: seen.append(note))
    hooks.fire_transcribed(tmp_path / "m.wav", tmp_path / "n.md")  # does not raise
    assert seen == [tmp_path / "n.md"]


def test_recover_one_fires_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostbrain.recorder import manual

    wav = tmp_path / "meeting-20261010-101500-manual.wav"
    wav.write_bytes(b"RIFF")
    txt = tmp_path / "meeting.txt"
    txt.write_text("we talked about the login screen")
    note = tmp_path / "vault" / "note.md"
    monkeypatch.setattr(manual, "_already_filed", lambda name: False)
    monkeypatch.setattr(manual, "transcribe", lambda w: txt)
    monkeypatch.setattr(manual, "_file_transcript", lambda **kw: note)
    monkeypatch.setattr(manual.slides_mod, "attach_slides", lambda *a, **k: 0)
    seen = []
    hooks.on_transcribed(lambda w, n: seen.append((w, n)))

    cfg = manual.ManualConfig(enabled=True, context="work", recordings_dir=tmp_path)
    assert manual.recover_one(wav, cfg, title_override="Login review") == note
    assert seen == [(wav, note)]


def test_recover_one_survives_a_failing_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostbrain.recorder import manual

    wav = tmp_path / "meeting-20261010-101500-manual.wav"
    wav.write_bytes(b"RIFF")
    txt = tmp_path / "meeting.txt"
    txt.write_text("words")
    note = tmp_path / "note.md"
    monkeypatch.setattr(manual, "_already_filed", lambda name: False)
    monkeypatch.setattr(manual, "transcribe", lambda w: txt)
    monkeypatch.setattr(manual, "_file_transcript", lambda **kw: note)
    monkeypatch.setattr(manual.slides_mod, "attach_slides", lambda *a, **k: 0)
    monkeypatch.setattr(hooks, "fire_transcribed", _raise)

    cfg = manual.ManualConfig(enabled=True, context="work", recordings_dir=tmp_path)
    assert manual.recover_one(wav, cfg, title_override="x") == note


def _raise(*a, **k):
    raise RuntimeError("hook module broken")


class _Backend:
    def stop_capture(self, pid):
        pass

    def end_meeting_route(self, handle):
        pass


def _finalize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, fire=None) -> tuple[Path, Path, list]:
    from ghostbrain.recorder import daemon
    from ghostbrain.recorder import state as state_mod
    from ghostbrain.recorder.linker import LinkResult
    from ghostbrain.recorder.policy import RecorderPolicy

    wav = tmp_path / "ev.wav"
    wav.write_bytes(b"\0" * 200_000)
    txt = tmp_path / "ev.txt"
    txt.write_text("transcript")
    note = tmp_path / "vault" / "transcript.md"
    monkeypatch.setattr(daemon, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(daemon, "transcribe", lambda w: txt)
    monkeypatch.setattr(daemon, "link_transcript", lambda *a, **k: LinkResult(note, None, None))
    monkeypatch.setattr(daemon.slides_mod, "attach_slides", lambda *a, **k: 0)
    seen: list = []
    if fire is not None:
        monkeypatch.setattr(hooks, "fire_transcribed", fire)
    else:
        hooks.on_transcribed(lambda w, n: seen.append((w, n)))
    now = datetime.now(UTC).isoformat()
    active = state_mod.ActiveRecording(
        event_id="ev", title="standup", context="work", pid=1, wav_path=str(wav),
        started_at=now, scheduled_end=now,
    )
    config = daemon.DaemonConfig(
        poll_interval_s=30, end_grace_s=60, audio_device="Ghost Brain",
        fallback_output="", policy=RecorderPolicy(), macos_accounts={},
    )
    daemon._finalize(active, config, state_mod.RecorderState(active=active), _Backend(),
                     reason="scheduled_end")
    return wav, note, seen


def test_daemon_finalize_fires_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav, note, seen = _finalize(tmp_path, monkeypatch)
    assert seen == [(wav, note)]


def test_daemon_finalize_survives_a_failing_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav, _, _ = _finalize(tmp_path, monkeypatch, fire=_raise)
    assert not wav.exists()  # cleanup after the hook still ran
