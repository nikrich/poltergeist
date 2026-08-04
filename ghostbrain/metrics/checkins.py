"""Check-in suggestions per SPEC §8.4. "Worth a check-in with X because Y" —
not metric-based judgements about people.

Heuristics covered in v1:
- PR you authored, review-requested → reviewer waiting too long.
- Jira ticket with assignee, status unchanged > N days.
- Calendar 1:1 with someone, last meeting > 14 days ago.

Skipped in v1 (need data we don't have):
- "Hasn't shipped anything in 5 days" — needs PR merge history.
- Sentiment-based escalation in Slack — needs Slack + LLM.
"""

from __future__ import annotations

import dataclasses
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import frontmatter

from ghostbrain.paths import vault_path

DEFAULT_PR_REVIEW_LATE_DAYS = 3
DEFAULT_TICKET_STALE_DAYS = 7
DEFAULT_LAST_1_1_GAP_DAYS = 14
ONE_ON_ONE_TITLE_PATTERN = re.compile(
    r"\b(1[:/-]1|one[\s-]?on[\s-]?one|sync with|catch[\s-]?up with|\d+:\d+\s+with)\b",
    re.IGNORECASE,
)


@dataclasses.dataclass
class CheckinSuggestion:
    person: str            # name or email
    reason: str            # human-readable, fits "worth a check-in with <person> because <reason>"
    source_kind: str       # "pr" | "ticket" | "calendar"
    source_ref: str        # e.g. "ACME-1234" or note path
    last_activity: str     # ISO
    age_days: float


def suggest_checkins(
    *,
    now: datetime | None = None,
    pr_review_late_days: int = DEFAULT_PR_REVIEW_LATE_DAYS,
    ticket_stale_days: int = DEFAULT_TICKET_STALE_DAYS,
    last_1_1_gap_days: int = DEFAULT_LAST_1_1_GAP_DAYS,
) -> list[CheckinSuggestion]:
    now = now or datetime.now(timezone.utc)
    out: list[CheckinSuggestion] = []

    out.extend(_pr_review_waiting(now, pr_review_late_days))
    out.extend(_ticket_assignee_idle(now, ticket_stale_days))
    out.extend(_overdue_one_on_ones(now, last_1_1_gap_days))

    # Dedup by person — keep the most acute reason per person.
    by_person: dict[str, CheckinSuggestion] = {}
    for s in out:
        existing = by_person.get(s.person.lower())
        if existing is None or s.age_days > existing.age_days:
            by_person[s.person.lower()] = s

    return sorted(by_person.values(), key=lambda s: s.age_days, reverse=True)


# ---------------------------------------------------------------------------
# PR review-waiting
# ---------------------------------------------------------------------------


def _pr_review_waiting(
    now: datetime,
    pr_review_late_days: int,
) -> Iterable[CheckinSuggestion]:
    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        return
    for ctx_dir in contexts_root.iterdir():
        pr_dir = ctx_dir / "github" / "prs"
        if not pr_dir.exists():
            continue
        for note in pr_dir.glob("*.md"):
            meta = _safe_load(note)
            if meta is None:
                continue
            if str(meta.get("state") or "").upper() != "OPEN":
                continue

            origin = (
                (meta.get("rawData") or {}).get("metadata", {})
                or meta.get("metadata", {})
                or {}
            ).get("origin")

            # When ghostbrain wrote the note, did it land in the
            # "review-requested" set? Frontmatter stores `metadata` only
            # when bubbled — fall back to rawData metadata if needed.
            if origin and origin != "review-requested":
                continue
            # If we can't tell, only flag when the user is NOT the author.
            author = (
                (meta.get("rawData") or {}).get("author", {}) or {}
            ).get("login") or ""
            if origin is None and author and author == "nikrich":
                # Authored by the user; not a "waiting on you to review" case.
                continue

            last = _parse_iso(str(meta.get("updated") or meta.get("ingestedAt") or ""))
            if last is None:
                continue
            age = (now - last).total_seconds() / 86400
            if age < pr_review_late_days:
                continue

            person = author or "the PR author"
            ref = str(meta.get("repo") or "") + (
                f"#{meta.get('number')}" if meta.get("number") else ""
            )
            yield CheckinSuggestion(
                person=person,
                reason=(
                    f"PR {ref} has been review-requested for "
                    f"{age:.0f} days with no movement"
                ),
                source_kind="pr",
                source_ref=ref or note.stem,
                last_activity=last.isoformat(),
                age_days=round(age, 1),
            )


# ---------------------------------------------------------------------------
# Ticket assignee idle
# ---------------------------------------------------------------------------


def _ticket_assignee_idle(
    now: datetime,
    ticket_stale_days: int,
) -> Iterable[CheckinSuggestion]:
    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        return
    for ctx_dir in contexts_root.iterdir():
        tk_dir = ctx_dir / "jira" / "tickets"
        if not tk_dir.exists():
            continue
        for note in tk_dir.glob("*.md"):
            meta = _safe_load(note)
            if meta is None:
                continue
            status = str(meta.get("status") or "").lower()
            if status in ("done", "closed", "resolved", "cancelled"):
                continue

            assignee = (
                ((meta.get("rawData") or {}).get("fields", {}) or {})
                .get("assignee", {})
                or {}
            ).get("displayName")
            if not assignee:
                continue

            last = _parse_iso(str(meta.get("updated") or meta.get("ingestedAt") or ""))
            if last is None:
                continue
            age = (now - last).total_seconds() / 86400
            if age < ticket_stale_days:
                continue

            key = str(meta.get("key") or note.stem)
            yield CheckinSuggestion(
                person=assignee,
                reason=(
                    f"assigned {key} ({status}), unchanged for "
                    f"{age:.0f} days"
                ),
                source_kind="ticket",
                source_ref=key,
                last_activity=last.isoformat(),
                age_days=round(age, 1),
            )


# ---------------------------------------------------------------------------
# Overdue 1:1s
# ---------------------------------------------------------------------------


def _overdue_one_on_ones(
    now: datetime,
    last_1_1_gap_days: int,
) -> Iterable[CheckinSuggestion]:
    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        return

    # person → most-recent 1:1 timestamp
    last_seen: dict[str, datetime] = {}

    for ctx_dir in contexts_root.iterdir():
        cal_dir = ctx_dir / "calendar"
        if not cal_dir.exists():
            continue
        for note in cal_dir.glob("*.md"):
            meta = _safe_load(note)
            if meta is None:
                continue
            title = str(meta.get("title") or "")
            if not _looks_like_one_on_one(title):
                continue
            person = _person_from_one_on_one_title(title)
            if not person:
                continue
            start = _parse_iso(str(meta.get("start") or ""))
            if start is None:
                continue
            if start > now:
                # future event; the pattern would suggest "upcoming" but for
                # check-ins we want "haven't seen X for a while".
                continue
            existing = last_seen.get(person.lower())
            if existing is None or start > existing:
                last_seen[person.lower()] = start
                # Also track person spelled as the title's casing.
                last_seen.setdefault(person, start)

    seen_lower: set[str] = set()
    for person_key, start in last_seen.items():
        if person_key.lower() in seen_lower:
            continue
        seen_lower.add(person_key.lower())

        gap_days = (now - start).total_seconds() / 86400
        if gap_days < last_1_1_gap_days:
            continue

        yield CheckinSuggestion(
            person=person_key if person_key.lower() != person_key else person_key.title(),
            reason=f"last 1:1 was {gap_days:.0f} days ago",
            source_kind="calendar",
            source_ref="",
            last_activity=start.isoformat(),
            age_days=round(gap_days, 1),
        )


def _looks_like_one_on_one(title: str) -> bool:
    return bool(ONE_ON_ONE_TITLE_PATTERN.search(title))


def _person_from_one_on_one_title(title: str) -> str | None:
    """Best-effort extraction of the person's name from a 1:1 title.

    Matches patterns like:
    - "1:1 with Alex"
    - "Sync with Lawrence"
    - "Catch-up with Julia"
    - "Jannik / Alex 1:1"
    """
    m = re.search(
        r"(?:1[:/-]1|sync|catch[\s-]?up|one[\s-]?on[\s-]?one)\s+with\s+([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)*)",
        title, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    m = re.search(
        r"([A-Z][A-Za-z'\-]+)\s*[/&]\s*([A-Z][A-Za-z'\-]+)\s+1[:/-]1",
        title,
    )
    if m:
        # Pick the OTHER name (not the user) — for now we just take the second.
        return m.group(2).strip()

    return None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _safe_load(path: Path) -> dict | None:
    try:
        return frontmatter.load(path).metadata
    except Exception:  # noqa: BLE001
        return None


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
