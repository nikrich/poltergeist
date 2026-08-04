"""Per-session profile-diff proposer.

Called from the worker pipeline after extraction. Reads the current
profile, the session digest, and asks the LLM to propose diffs. Each
proposal lands as a JSON line in
``<vault>/80-profile/_proposed/YYYY-MM-DD.jsonl``. The weekly applier
groups these and decides what to auto-apply.

Errors don't bubble — profile evolution is a best-effort layer; failing
here must not block the rest of the pipeline.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ghostbrain.llm import client as llm
from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.profile.diff")

ALLOWED_FIELDS = (
    "current-projects", "preferences", "working-style", "people", "decisions",
)
ALLOWED_OPERATIONS = ("add", "update", "contradict")

PROFILE_UPDATER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["diffs"],
    "properties": {
        "diffs": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "operation", "after", "evidence", "confidence"],
                "properties": {
                    "field": {"type": "string", "enum": list(ALLOWED_FIELDS)},
                    "operation": {"type": "string", "enum": list(ALLOWED_OPERATIONS)},
                    "before": {"type": "string", "maxLength": 400},
                    "after": {"type": "string", "maxLength": 400},
                    "evidence": {"type": "string", "maxLength": 400},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
            },
        },
    },
}


@dataclasses.dataclass
class ProposedDiff:
    field: str
    operation: str
    before: str
    after: str
    evidence: str
    confidence: float
    proposed_at: str
    parent_event_id: str
    parent_session_id: str | None = None
    parent_note_path: str | None = None

    def to_jsonl(self) -> str:
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False)


def propose_for_session(
    *,
    excerpt: str,
    parent_event_id: str,
    parent_session_id: str | None = None,
    parent_note_path: Path | None = None,
    config: dict | None = None,
) -> list[ProposedDiff]:
    """Generate profile diffs for one Claude session and persist them.

    Returns the proposals written. Empty list when the LLM declines, errors,
    or the excerpt is too thin to classify.
    """
    if not excerpt.strip():
        return []

    config = config or {}
    profile = _read_profile_for_prompt()
    prompt = _build_prompt(profile, excerpt)
    model = (config.get("llm") or {}).get("profile_model", "sonnet")

    try:
        result = llm.run(
            prompt,
            model=model,
            json_schema=PROFILE_UPDATER_JSON_SCHEMA,
            budget_usd=0.5,
        )
        envelope = result.as_json()
    except llm.LLMError as e:
        log.warning("profile-updater LLM failed for parent=%s: %s",
                    parent_event_id, e)
        return []

    diffs_raw = (envelope or {}).get("diffs", []) if isinstance(envelope, dict) else []
    if not isinstance(diffs_raw, list):
        log.warning("profile-updater returned unexpected shape for parent=%s",
                    parent_event_id)
        return []

    now_iso = datetime.now(timezone.utc).isoformat()
    proposals: list[ProposedDiff] = []
    for raw in diffs_raw:
        if not isinstance(raw, dict):
            continue
        try:
            confidence = float(raw.get("confidence") or 0)
        except (TypeError, ValueError):
            continue
        if confidence < 0.7:
            continue
        field = str(raw.get("field") or "").strip()
        operation = str(raw.get("operation") or "").strip()
        if field not in ALLOWED_FIELDS or operation not in ALLOWED_OPERATIONS:
            continue
        after = str(raw.get("after") or "").strip()
        if not after:
            continue

        proposals.append(ProposedDiff(
            field=field,
            operation=operation,
            before=str(raw.get("before") or "").strip(),
            after=after,
            evidence=str(raw.get("evidence") or "").strip(),
            confidence=confidence,
            proposed_at=now_iso,
            parent_event_id=parent_event_id,
            parent_session_id=parent_session_id,
            parent_note_path=str(parent_note_path) if parent_note_path else None,
        ))

    if proposals:
        _append_proposals(proposals)
        log.info("proposed %d profile diff(s) for parent=%s",
                 len(proposals), parent_event_id)
    return proposals


def _build_prompt(profile_text: str, excerpt: str) -> str:
    template = _read_prompt("profile-updater.md")
    return (
        template
        .replace("{{profile}}", profile_text)
        .replace("{{conversation}}", excerpt)
    )


def _read_prompt(name: str) -> str:
    f = vault_path() / "90-meta" / "prompts" / name
    if not f.exists():
        raise FileNotFoundError(
            f"missing prompt {name}; re-run `ghostbrain-bootstrap`"
        )
    return f.read_text(encoding="utf-8")


def _read_profile_for_prompt() -> str:
    """Compose a single string the profile-updater can compare against.

    Includes the three stable/current layer files. We keep this small —
    bigger inputs raise cache-creation cost and dilute the model's focus.
    """
    profile_dir = vault_path() / "80-profile"
    parts: list[str] = []
    for name in ("working-style.md", "preferences.md", "current-projects.md"):
        f = profile_dir / name
        if not f.exists():
            continue
        body = f.read_text(encoding="utf-8").strip()
        if body:
            parts.append(f"### {name}\n\n{body}")
    return "\n\n".join(parts) if parts else "(profile is empty)"


def _append_proposals(proposals: list[ProposedDiff]) -> None:
    today = date.today().isoformat()
    out = vault_path() / "80-profile" / "_proposed" / f"{today}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        for p in proposals:
            f.write(p.to_jsonl() + "\n")
