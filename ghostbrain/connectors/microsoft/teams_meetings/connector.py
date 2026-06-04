"""Teams meeting transcripts connector.

Walks the calendar over a rolling window, resolves each online meeting,
lists its transcripts, and emits only transcripts created since last_run
(the dedup mechanism). Transcripts are pulled deliberately, so there is no
relevance gate. Carries over resolve/list/fetch logic from the
pull_transcript.py prototype."""

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


class TeamsMeetingsConnector(Connector):
    name = "teams_meetings"
    version = "1.0"

    def __init__(self, config, queue_dir, state_dir, *, client=None) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.lookback_days = int(config.get("calendar_lookback_days") or DEFAULT_LOOKBACK_DAYS)
        self.body_cap = int(config.get("body_cap_chars") or DEFAULT_BODY_CAP_CHARS)
        self._client = client  # injected in tests

    def health_check(self) -> bool:
        return have_token(self.config)

    def _graph(self) -> GraphClient:
        if self._client is not None:
            return self._client
        return GraphClient(get_token(self.config))

    def fetch(self, since: datetime) -> list[dict]:
        client = self._graph()
        window_start = datetime.now(timezone.utc) - timedelta(days=self.lookback_days)
        events: list[dict] = []
        for ev in self._list_calendar_online_meetings(client, window_start):
            join_url = (ev.get("onlineMeeting") or {}).get("joinUrl")
            if not join_url:
                continue
            try:
                meeting = self._resolve_meeting(client, join_url)
            except MicrosoftAuthError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("could not resolve meeting %s: %s", join_url, e)
                continue
            events.extend(self._transcripts_for(client, meeting, since))
        log.info("teams_meetings fetch: %d new transcript(s)", len(events))
        return events

    def normalize(self, raw: dict) -> dict:
        return raw  # fetch already produces normalized events

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

    def _resolve_meeting(self, client, join_url: str) -> dict:
        # Escape single quotes for the OData string literal.
        safe = join_url.replace("'", "''")
        params = {"$filter": f"JoinWebUrl eq '{safe}'"}
        items = client.get("/me/onlineMeetings", params).get("value") or []
        if not items:
            raise ValueError("no onlineMeeting matched join url")
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
