"""Source selection: every configured calendar block whose platform
requirements are met becomes an active source; `recorder.meeting_sources`
in config.yaml pins the list explicitly."""
from __future__ import annotations

import sys

from ghostbrain.recorder.sources.base import MeetingEvent, MeetingSource

__all__ = ["MeetingEvent", "MeetingSource", "select_sources", "dedupe_events"]


def select_sources(
    routing: dict, recorder_cfg: dict, platform: str | None = None,
) -> tuple[list[MeetingSource], list[str]]:
    plat = platform or sys.platform
    calendar = routing.get("calendar") or {}
    pinned = [str(s) for s in (recorder_cfg.get("meeting_sources") or [])]
    sources: list[MeetingSource] = []
    excluded: list[str] = []

    def wanted(source_id: str) -> bool:
        return not pinned or source_id in pinned

    macos_accounts = (calendar.get("macos") or {}).get("accounts") or {}
    if macos_accounts and wanted("macos"):
        if plat == "darwin":
            from ghostbrain.recorder.sources.macos import MacosSource
            sources.append(MacosSource(dict(macos_accounts)))
        else:
            excluded.append("macos: Apple Calendar source requires macOS")

    google_accounts = (calendar.get("google") or {}).get("accounts") or {}
    if google_accounts and wanted("google"):
        from ghostbrain.recorder.sources.google import GoogleSource
        sources.append(GoogleSource(dict(google_accounts)))

    ms_cfg = routing.get("microsoft") or {}
    if ms_cfg and wanted("microsoft"):
        context = str(ms_cfg.get("calendar_context") or "")
        if context:
            from ghostbrain.recorder.sources.microsoft import MicrosoftSource
            sources.append(MicrosoftSource(dict(ms_cfg), context))
        else:
            excluded.append(
                "microsoft: calendar_context not set in routing.yaml "
                "(microsoft.calendar_context: <context>)"
            )
    return sources, excluded


def dedupe_events(events: list[MeetingEvent]) -> list[MeetingEvent]:
    seen: set[str] = set()
    out: list[MeetingEvent] = []
    for ev in events:
        if ev.event_id in seen:
            continue
        seen.add(ev.event_id)
        out.append(ev)
    return out
