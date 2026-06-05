"""Teams meeting transcripts connector.

Discovers meetings one of two ways, then lists each meeting's transcripts and
emits only those created since last_run (the dedup mechanism):

- a configured list of meeting join-URLs/IDs (``microsoft.teams_meetings.meetings``)
  — works with transcripts-only scope (OnlineMeetings.Read +
  OnlineMeetingTranscript.Read.All); or
- otherwise, by walking the calendar over a rolling window (needs Calendars.Read).

Transcripts are pulled deliberately, so there is no relevance gate. Carries
over resolve/list/fetch logic from the pull_transcript.py prototype."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import requests

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.microsoft.graph.auth import (
    GRAPH,
    MicrosoftAuthError,
    get_token,
    have_token,
)
from ghostbrain.connectors.microsoft.graph.client import GraphClient

log = logging.getLogger("ghostbrain.connectors.teams_meetings")

DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_BODY_CAP_CHARS = 200_000

_MEET_ID_RE = re.compile(r"/meet/(\d+)")


def extract_meeting_id(ref: str) -> str | None:
    """Pull the numeric Meeting ID from a short ``/meet/<id>`` link or a bare
    numeric ID. Returns None for a long join URL (resolved by JoinWebUrl)."""
    m = _MEET_ID_RE.search(ref)
    if m:
        return m.group(1)
    bare = ref.replace(" ", "")
    return bare if bare.isdigit() else None


class TeamsMeetingsConnector(Connector):
    name = "teams_meetings"
    version = "1.0"

    def __init__(self, config, queue_dir, state_dir, *, client=None) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.lookback_days = int(config.get("calendar_lookback_days") or DEFAULT_LOOKBACK_DAYS)
        self.body_cap = int(config.get("body_cap_chars") or DEFAULT_BODY_CAP_CHARS)
        self.configured_meetings = [
            str(m).strip() for m in (config.get("meetings") or []) if str(m).strip()
        ]
        self._client = client  # injected in tests

    def health_check(self) -> bool:
        return have_token(self.config)

    def _graph(self) -> GraphClient:
        if self._client is not None:
            return self._client
        return GraphClient(get_token(self.config))

    def fetch(self, since: datetime) -> list[dict]:
        client = self._graph()
        refs = self._meeting_refs(client)
        events: list[dict] = []
        for ref in refs:
            try:
                meeting = self._resolve_meeting_ref(client, ref)
            except MicrosoftAuthError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("could not resolve meeting %s: %s", ref, e)
                continue
            events.extend(self._transcripts_for(client, meeting, since))
        log.info(
            "teams_meetings fetch: %d new transcript(s) from %d meeting source(s)",
            len(events), len(refs),
        )
        return events

    def normalize(self, raw: dict) -> dict:
        return raw  # fetch already produces normalized events

    # -- Discovery -----------------------------------------------------------

    def _meeting_refs(self, client) -> list[str]:
        """Meeting references (join-URLs/IDs) to pull transcripts for.

        Prefers the configured list (works with transcripts-only scope);
        falls back to walking the calendar (needs Calendars.Read)."""
        if self.configured_meetings:
            return self.configured_meetings
        window_start = datetime.now(timezone.utc) - timedelta(days=self.lookback_days)
        refs: list[str] = []
        for ev in self._list_calendar_online_meetings(client, window_start):
            join_url = (ev.get("onlineMeeting") or {}).get("joinUrl")
            if join_url:
                refs.append(join_url)
        return refs

    # -- Graph calls ---------------------------------------------------------

    def _list_calendar_online_meetings(self, client, window_start) -> list[dict]:
        # Use calendarView, not /me/events: Graph requires a date range via the
        # startDateTime/endDateTime query params for windowed event queries, and
        # rejects $filter/$orderby on start/dateTime against /me/events.
        params = {
            "startDateTime": window_start.isoformat(),
            "endDateTime": datetime.now(timezone.utc).isoformat(),
            "$select": "id,subject,isOnlineMeeting,onlineMeeting",
            "$top": 50,
            "$orderby": "start/dateTime desc",
        }
        return client.get_all("/me/calendarView", params, max_items=100)

    def _resolve_meeting_ref(self, client, ref: str) -> dict:
        """Resolve an onlineMeeting from a join URL, a short ``/meet/<id>`` link,
        or a bare numeric Meeting ID."""
        meeting_id = extract_meeting_id(ref)
        if meeting_id:
            params = {"$filter": f"joinMeetingIdSettings/joinMeetingId eq '{meeting_id}'"}
            how = f"meeting id {meeting_id}"
        else:
            # Escape single quotes for the OData string literal.
            safe = ref.replace("'", "''")
            params = {"$filter": f"JoinWebUrl eq '{safe}'"}
            how = "join url"
        items = client.get("/me/onlineMeetings", params).get("value") or []
        if not items:
            raise ValueError(f"no onlineMeeting matched {how}")
        return items[0]

    def _transcripts_for(self, client, meeting: dict, since: datetime) -> list[dict]:
        meeting_id = meeting["id"]
        listed = client.get(f"/me/onlineMeetings/{meeting_id}/transcripts").get("value") or []
        out: list[dict] = []
        for t in listed:
            created = _parse_dt(t.get("createdDateTime"))
            if created is None or created <= since:
                continue
            text = self._fetch_transcript_text(client, meeting_id, t["id"])
            out.append(_normalize_transcript(meeting, t, text, self.body_cap))
        return out

    def _fetch_transcript_text(self, client, meeting_id: str, transcript_id: str) -> str:
        # Transcript content is VTT text, not JSON, so bypass GraphClient.get
        # (which parses JSON) and fetch raw text.
        url = f"/me/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content"
        return _raw_text(client, url)


# -- pure helpers ------------------------------------------------------------


def _raw_text(client: GraphClient, path: str) -> str:
    """Fetch VTT transcript content as text (not JSON)."""
    url = path if path.startswith("http") else f"{GRAPH}{path}"
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {client._token}"},
        params={"$format": "text/vtt"},
        timeout=30,
    )
    if r.status_code == 401:
        raise MicrosoftAuthError("Graph 401 fetching transcript; re-run auth.")
    r.raise_for_status()
    return r.text


def _parse_dt(value):
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    v = re.sub(r"(\.\d{6})\d+", r"\1", v)
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _normalize_transcript(meeting: dict, transcript: dict, text: str, body_cap: int) -> dict:
    meeting_id = meeting.get("id") or ""
    transcript_id = transcript.get("id") or ""
    subject = meeting.get("subject") or "meeting"
    ts = transcript.get("endDateTime") or transcript.get("createdDateTime") or ""
    parsed_ts = _parse_dt(ts)
    organizer = ((meeting.get("participants") or {}).get("organizer") or {})
    return {
        "id": f"microsoft:transcript:{meeting_id}:{transcript_id}",
        "source": "teams_meetings",
        "type": "meeting_transcript",
        "timestamp": parsed_ts.isoformat() if parsed_ts else ts,
        "actorId": f"microsoft:{organizer.get('upn')}" if organizer.get("upn") else "",
        "title": subject,
        "body": (text or "")[:body_cap],
        "sourceUrl": meeting.get("joinWebUrl") or "",
        "metadata": {
            "meetingId": meeting_id,
            "transcriptId": transcript_id,
            "joinWebUrl": meeting.get("joinWebUrl") or "",
            "organizer": organizer.get("upn") or "",
        },
    }
