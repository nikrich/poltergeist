"""``ghostbrain-transcribe <wav>`` — transcribes the WAV with whisper-cli,
finds the matching calendar event by start time, writes the transcript
note into the vault, links it back to the event note's frontmatter."""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from ghostbrain.recorder.linker import link_transcript
from ghostbrain.recorder.transcribe import TranscribeError, transcribe
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.recorder.main")


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe a WAV and link it to the vault.")
    parser.add_argument("wav", type=Path, help="Path to the recorded WAV.")
    parser.add_argument("--model", type=Path, default=None,
                        help="Override the Whisper model path.")
    parser.add_argument("--keep-audio", action="store_true",
                        help="Keep the WAV after transcription. Default: delete.")
    parser.add_argument("--started-at",
                        help="ISO start timestamp. Default: WAV file's mtime - duration.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    wav: Path = args.wav.expanduser().resolve()
    if not wav.exists():
        raise SystemExit(f"WAV not found: {wav}")

    started_at, duration_s = _infer_start_and_duration(wav, args.started_at)

    print(f"Transcribing {wav.name} (started ~ "
          f"{started_at.astimezone().strftime('%Y-%m-%d %H:%M %Z')}, "
          f"duration {duration_s/60:.1f} min)...")

    try:
        txt_path = transcribe(wav, model_path=args.model)
    except TranscribeError as e:
        audit_log("transcribe_failed", wav.name, error=str(e))
        raise SystemExit(str(e))

    print(f"Transcript: {txt_path}")

    result = link_transcript(
        txt_path,
        started_at=started_at,
        duration_s=duration_s,
        audio_path=None if not args.keep_audio else wav,
    )

    audit_log(
        "transcript_linked",
        wav.name,
        transcript=str(result.transcript_note),
        parent=str(result.parent_event_path) if result.parent_event_path else None,
        matched=result.matched_title,
    )

    print(f"Note:       {result.transcript_note}")
    if result.parent_event_path:
        print(f"Linked to:  {result.parent_event_path.name}")
        print(f"Matched:    {result.matched_title}")
    else:
        print("No matching calendar event within ±15 min — saved under cross/.")

    if not args.keep_audio:
        wav.unlink()
        # Also remove the .txt next to the wav (already copied into the note).
        if txt_path.exists():
            txt_path.unlink()
        print("Audio + raw .txt cleaned up. (Use --keep-audio to keep them.)")


def _infer_start_and_duration(
    wav: Path,
    explicit_started_at: str | None,
) -> tuple[datetime, float]:
    """Compute when the recording started + how long it lasted.

    Strategy: ffprobe gives the duration. The WAV's mtime is roughly the
    end time. Start = end - duration. The user can override via
    ``--started-at`` for replays.
    """
    duration_s = _ffprobe_duration_seconds(wav)
    if explicit_started_at:
        started = datetime.fromisoformat(explicit_started_at.replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.astimezone()
        return started, duration_s

    end_ts = datetime.fromtimestamp(wav.stat().st_mtime, tz=timezone.utc)
    started = end_ts.fromtimestamp(end_ts.timestamp() - duration_s, tz=timezone.utc)
    return started, duration_s


def _ffprobe_duration_seconds(wav: Path) -> float:
    import subprocess
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(wav),
            ],
            text=True, timeout=30,
        ).strip()
        return float(out)
    except Exception as e:  # noqa: BLE001
        log.warning("ffprobe failed: %s — assuming 0s duration", e)
        return 0.0


if __name__ == "__main__":
    main()
