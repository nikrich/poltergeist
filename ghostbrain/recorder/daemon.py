"""Autonomous meeting recorder daemon.

Polls Apple Calendar every ``poll_interval_s`` seconds. When an eligible
meeting is in-progress (or about to start), starts ffmpeg recording from
BlackHole + mic, switches system audio output to the Multi-Output Device
that includes BlackHole, and tracks the active recording in a state file.

When the meeting's scheduled-end + grace passes, stops ffmpeg, restores
the user's previous audio output device, transcribes the WAV, and links
the transcript to the calendar event note in the vault.

Eligibility is decided by ``recorder.policy.should_record`` from the
``recorder`` block in ``vault/90-meta/config.yaml``.
"""

from __future__ import annotations

import dataclasses
import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from ghostbrain.connectors.calendar.macos import MacosCalendarConnector
from ghostbrain.paths import queue_dir, state_dir, vault_path
from ghostbrain.recorder import audio_capture, audio_switcher, state as state_mod
from ghostbrain.recorder.linker import link_transcript
from ghostbrain.recorder.policy import RecorderPolicy, should_record
from ghostbrain.recorder.transcribe import TranscribeError, transcribe
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.recorder.daemon")


DEFAULT_POLL_INTERVAL_S = 30
DEFAULT_END_GRACE_S = 60
DEFAULT_AUDIO_DEVICE = "Ghost Brain"
DEFAULT_RECORDINGS_DIR = Path.home() / "ghostbrain" / "recorder" / "recordings"

_running = True


def _handle_signal(signum, _frame) -> None:
    global _running
    log.info("recorder daemon received signal %s, shutting down", signum)
    _running = False


@dataclasses.dataclass
class DaemonConfig:
    poll_interval_s: int
    end_grace_s: int
    audio_device: str
    fallback_output: str       # restore target if no original captured
    policy: RecorderPolicy
    macos_accounts: dict[str, str]

    @classmethod
    def load(cls) -> "DaemonConfig":
        cfg_file = vault_path() / "90-meta" / "config.yaml"
        cfg: dict[str, Any] = {}
        if cfg_file.exists():
            cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}

        rec = cfg.get("recorder") or {}
        policy = RecorderPolicy(
            enabled=bool(rec.get("enabled", True)),
            excluded_titles=tuple(rec.get("excluded_titles") or ("Focus", "focus")),
            excluded_contexts=tuple(rec.get("excluded_contexts") or ()),
            included_contexts=tuple(rec.get("included_contexts") or ()),
        )

        routing_file = vault_path() / "90-meta" / "routing.yaml"
        routing: dict = {}
        if routing_file.exists():
            routing = yaml.safe_load(routing_file.read_text(encoding="utf-8")) or {}
        accounts = (
            ((routing.get("calendar") or {}).get("macos") or {}).get("accounts") or {}
        )

        return cls(
            poll_interval_s=int(rec.get("poll_interval_seconds")
                                or DEFAULT_POLL_INTERVAL_S),
            end_grace_s=int(rec.get("end_grace_seconds") or DEFAULT_END_GRACE_S),
            audio_device=str(rec.get("audio_device") or DEFAULT_AUDIO_DEVICE),
            fallback_output=str(rec.get("fallback_output") or ""),
            policy=policy,
            macos_accounts=dict(accounts),
        )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_loop() -> None:
    config = DaemonConfig.load()
    state = state_mod.load()
    state_mod.prune_processed(state)
    state_mod.save(state)

    audit_log(
        "recorder_started",
        poll=config.poll_interval_s,
        contexts=sorted(config.macos_accounts.values()),
    )
    log.info("recorder daemon starting; poll every %ds", config.poll_interval_s)

    DEFAULT_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while _running:
        try:
            run_once(config, state)
        except Exception:  # noqa: BLE001
            log.exception("daemon tick failed; will retry next loop")
        time.sleep(config.poll_interval_s)

    # Graceful shutdown: if a recording is in flight, stop + try to transcribe
    # so we don't lose the audio.
    if state.active is not None:
        log.info("shutdown with active recording; finalizing %s",
                 state.active.event_id)
        _finalize(state.active, config, state, reason="daemon_shutdown")
        state.active = None
        state_mod.save(state)

    audit_log("recorder_stopped")
    log.info("recorder daemon stopped")


def run_once(config: DaemonConfig, state: state_mod.RecorderState) -> None:
    """One daemon tick: handle active recording end + maybe start a new one."""
    now = datetime.now(timezone.utc)

    if state.active is not None:
        if _should_finalize(state.active, now, config):
            _finalize(state.active, config, state, reason="scheduled_end")
            state.active = None
            state_mod.save(state)
        else:
            return

    # No active recording — look for a meeting to start.
    candidate = _next_eligible_event(config, state, now)
    if candidate is None:
        return

    _start_recording(candidate, config, state)


# ---------------------------------------------------------------------------
# Active-recording lifecycle
# ---------------------------------------------------------------------------


def _should_finalize(
    active: state_mod.ActiveRecording,
    now: datetime,
    config: DaemonConfig,
) -> bool:
    """Time to stop? Either the scheduled end (with grace) has passed, or
    ffmpeg has died, or the WAV file disappeared."""
    if not audio_capture.is_running(active.pid):
        log.info("ffmpeg pid=%d no longer running for %s; finalizing",
                 active.pid, active.event_id)
        return True

    try:
        end_at = datetime.fromisoformat(active.scheduled_end)
    except ValueError:
        # Bad data; just stop.
        return True

    return now >= end_at


def _start_recording(
    candidate: "_Candidate",
    config: DaemonConfig,
    state: state_mod.RecorderState,
) -> None:
    """Switch audio output, spawn ffmpeg, persist active state."""
    # Capture the user's current output so we can restore it after.
    try:
        previous_output = audio_switcher.current_output()
    except audio_switcher.AudioSwitcherError as e:
        log.warning("could not read current audio output: %s", e)
        previous_output = config.fallback_output

    if previous_output and previous_output != config.audio_device:
        try:
            audio_switcher.switch_to(config.audio_device)
        except audio_switcher.AudioSwitcherError as e:
            log.warning("audio switch failed (%s); continuing — recording may "
                        "still capture if Ghost Brain is current output", e)
    else:
        log.info("system output already %s; not switching", config.audio_device)

    wav_path = DEFAULT_RECORDINGS_DIR / _filename_for(candidate)
    log_path = DEFAULT_RECORDINGS_DIR / "ffmpeg.log"

    try:
        handle = audio_capture.start_capture(wav_path, log_path=log_path)
    except Exception as e:  # noqa: BLE001
        log.exception("ffmpeg failed to start: %s", e)
        # Restore audio if we changed it.
        if previous_output and previous_output != config.audio_device:
            try:
                audio_switcher.switch_to(previous_output)
            except audio_switcher.AudioSwitcherError:
                pass
        audit_log("recorder_start_failed", candidate.event_id, error=str(e))
        # Mark processed so we don't retry every tick.
        state.processed[candidate.event_id] = datetime.now(timezone.utc).isoformat()
        state_mod.save(state)
        return

    scheduled_end = candidate.end + timedelta(seconds=config.end_grace_s)
    state.active = state_mod.ActiveRecording(
        event_id=candidate.event_id,
        title=candidate.title,
        context=candidate.context,
        pid=handle.pid,
        wav_path=str(handle.wav_path),
        started_at=datetime.now(timezone.utc).isoformat(),
        scheduled_end=scheduled_end.isoformat(),
    )
    # Stash previous output in processed map under a special key.
    state.processed[f"_audio_before:{candidate.event_id}"] = previous_output

    state_mod.save(state)
    audit_log(
        "recording_started",
        candidate.event_id,
        title=candidate.title,
        context=candidate.context,
        wav=str(handle.wav_path),
        pid=handle.pid,
        end=scheduled_end.isoformat(),
    )
    log.info("recording started: pid=%d event=%s ctx=%s end=%s",
             handle.pid, candidate.title, candidate.context,
             scheduled_end.isoformat())


def _finalize(
    active: state_mod.ActiveRecording,
    config: DaemonConfig,
    state: state_mod.RecorderState,
    *,
    reason: str,
) -> None:
    """Stop ffmpeg, restore audio, transcribe, link to vault, mark processed."""
    log.info("finalizing recording event=%s reason=%s", active.event_id, reason)

    audio_capture.stop_capture(active.pid)

    # Restore audio output.
    previous = state.processed.pop(
        f"_audio_before:{active.event_id}", "",
    )
    target = previous or config.fallback_output
    if target and target != config.audio_device:
        try:
            audio_switcher.switch_to(target)
        except audio_switcher.AudioSwitcherError as e:
            log.warning("could not restore audio output to %s: %s", target, e)

    wav = Path(active.wav_path)
    state.processed[active.event_id] = datetime.now(timezone.utc).isoformat()

    if not wav.exists() or wav.stat().st_size < 100_000:
        log.warning("WAV %s missing or too small; skipping transcription", wav)
        audit_log("recording_discarded", active.event_id, reason="empty_wav")
        return

    try:
        txt_path = transcribe(wav)
    except TranscribeError as e:
        log.warning("transcribe failed for %s: %s", active.event_id, e)
        audit_log("transcribe_failed", active.event_id, error=str(e))
        return

    try:
        started_at = datetime.fromisoformat(active.started_at)
    except ValueError:
        started_at = datetime.now(timezone.utc)

    try:
        result = link_transcript(
            txt_path,
            started_at=started_at,
            duration_s=(datetime.now(timezone.utc) - started_at).total_seconds(),
        )
    except Exception as e:  # noqa: BLE001
        log.exception("link failed for %s: %s", active.event_id, e)
        audit_log("transcript_link_failed", active.event_id, error=str(e))
        return

    audit_log(
        "transcript_linked",
        active.event_id,
        transcript=str(result.transcript_note),
        parent=str(result.parent_event_path) if result.parent_event_path else None,
        title=active.title,
    )

    # Cleanup audio + raw .txt; the artifact note has the content.
    try:
        wav.unlink()
    except OSError:
        pass
    try:
        txt_path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Calendar polling
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Candidate:
    event_id: str
    title: str
    context: str
    start: datetime
    end: datetime


def _next_eligible_event(
    config: DaemonConfig,
    state: state_mod.RecorderState,
    now: datetime,
) -> _Candidate | None:
    """Query Apple Calendar for events in [now-30s, now+60s] and pick one
    we haven't recorded yet."""
    if not config.macos_accounts:
        return None

    connector = MacosCalendarConnector(
        config={
            "accounts": config.macos_accounts,
            "lookahead_hours": 1,  # narrow scan; we filter below
        },
        queue_dir=queue_dir(),
        state_dir=state_dir(),
    )
    try:
        events = connector.fetch(now)
    except Exception as e:  # noqa: BLE001
        log.warning("calendar query failed: %s", e)
        return None

    candidates: list[_Candidate] = []
    for ev in events:
        meta = ev.get("metadata") or {}
        event_id = ev.get("id", "")
        if event_id in state.processed:
            continue
        if event_id.startswith("_audio_before:"):
            continue

        start = _parse_iso(str(meta.get("start") or ""))
        end = _parse_iso(str(meta.get("end") or ""))
        if start is None or end is None:
            continue
        # In progress, or starting in next 60s.
        if not (start - timedelta(seconds=60) <= now < end):
            continue

        title = str(ev.get("title") or "")
        context = config.macos_accounts.get(meta.get("account", ""), "")
        if not context:
            continue

        ok, reason = should_record(
            title=title, context=context, policy=config.policy,
        )
        if not ok:
            log.info("skipping %s: %s", title, reason)
            # Mark so we don't keep evaluating it every tick.
            state.processed[event_id] = now.isoformat()
            continue

        candidates.append(_Candidate(
            event_id=event_id,
            title=title,
            context=context,
            start=start,
            end=end,
        ))

    if not candidates:
        return None

    # Earliest start wins.
    candidates.sort(key=lambda c: c.start)
    return candidates[0]


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _filename_for(c: _Candidate) -> str:
    ts = c.start.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug_id = c.event_id.split(":")[-1][:12].replace("/", "-")
    return f"meeting-{ts}-{slug_id}.wav"
