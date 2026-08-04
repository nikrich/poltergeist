"""Decision-reversal detection.

When a new decision artifact lands, compare its content against prior
decisions in the same context. If the new one contradicts an older
one, write ``contradicts: [..]`` on the new note and ``reversed_by: [..]``
on the old. Surfaces in the daily digest as a "Reversals" section so
the user sees when their team is changing course.

Conservative on confidence — silence is better than false positives.
The LLM has to explicitly identify the contradicting decision; we
don't infer.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import frontmatter
import yaml

from ghostbrain.llm import client as llm
from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.worker.reversal")

DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_MAX_CANDIDATES = 25  # cap LLM input size

REVERSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reversals"],
    "properties": {
        "reversals": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["contradicts_id", "reasoning"],
                "properties": {
                    "contradicts_id": {"type": "string"},
                    "reasoning": {"type": "string", "maxLength": 240},
                },
            },
        },
    },
}


@dataclasses.dataclass
class _Candidate:
    artifact_id: str
    title: str
    content: str
    path: Path
    created: str


@dataclasses.dataclass
class ReversalResult:
    new_artifact_path: Path
    contradicted_paths: list[Path]


def check_for_reversals(
    new_artifact_path: Path,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    config: dict | None = None,
) -> ReversalResult:
    """Check whether the artifact at ``new_artifact_path`` reverses any
    earlier decision in its context. Best-effort — failures log and
    return an empty result so the surrounding pipeline never breaks.
    """
    empty = ReversalResult(new_artifact_path=new_artifact_path,
                           contradicted_paths=[])
    try:
        new_note = frontmatter.load(new_artifact_path)
    except Exception as e:  # noqa: BLE001
        log.warning("could not load new artifact %s: %s", new_artifact_path, e)
        return empty

    if str(new_note.metadata.get("artifactType")) != "decision":
        return empty

    context = str(new_note.metadata.get("context") or "")
    if not context:
        return empty

    new_id = str(new_note.metadata.get("id") or "")
    candidates = _gather_candidates(
        context=context,
        new_id=new_id,
        new_path=new_artifact_path,
        lookback_days=lookback_days,
    )
    if not candidates:
        return empty

    config = config or {}
    model = (config.get("llm") or {}).get("reversal_model", "haiku")

    new_title = str(new_note.metadata.get("title") or new_artifact_path.stem)
    new_body = (new_note.content or "").strip()

    prompt = _build_prompt(
        new_title=new_title, new_body=new_body, candidates=candidates,
    )

    try:
        result = llm.run(
            prompt, model=model, json_schema=REVERSAL_SCHEMA,
            budget_usd=0.25,
        )
        payload = result.as_json()
    except llm.LLMError as e:
        log.warning("reversal LLM failed for %s: %s", new_artifact_path, e)
        return empty

    reversals = payload.get("reversals") or []
    if not isinstance(reversals, list) or not reversals:
        return empty

    by_id = {c.artifact_id: c for c in candidates}
    contradicted: list[Path] = []
    rev_links: list[str] = []
    new_links: list[str] = []
    reasonings: dict[str, str] = {}

    for entry in reversals:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("contradicts_id") or "")
        reason = str(entry.get("reasoning") or "")
        cand = by_id.get(cid)
        if cand is None:
            continue
        contradicted.append(cand.path)
        rev_links.append(_wikilink_for(cand.path))
        new_links.append(_wikilink_for(new_artifact_path))
        reasonings[cid] = reason

    if not contradicted:
        return empty

    # Patch the new artifact with `contradicts:` pointers.
    new_note.metadata["contradicts"] = rev_links
    if reasonings:
        new_note.metadata["reversalReasons"] = list(reasonings.values())
    new_artifact_path.write_text(
        frontmatter.dumps(new_note), encoding="utf-8",
    )

    # Patch each contradicted artifact with `reversed_by:` pointer.
    for cand in [by_id[k] for k in reasonings if k in by_id]:
        try:
            old = frontmatter.load(cand.path)
        except Exception:  # noqa: BLE001
            continue
        existing = list(old.metadata.get("reversed_by") or [])
        link = _wikilink_for(new_artifact_path)
        if link not in existing:
            existing.append(link)
        old.metadata["reversed_by"] = existing
        try:
            cand.path.write_text(frontmatter.dumps(old), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("could not patch reversed_by on %s: %s", cand.path, e)

    log.info("decision %s reverses %d earlier decision(s)",
             new_artifact_path.stem, len(contradicted))
    return ReversalResult(new_artifact_path=new_artifact_path,
                          contradicted_paths=contradicted)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _gather_candidates(
    *,
    context: str,
    new_id: str,
    new_path: Path,
    lookback_days: int,
) -> list[_Candidate]:
    """Walk this context's calendar/artifacts/decisions/ + claude/artifacts/decisions/."""
    base = vault_path() / "20-contexts" / context
    candidates: list[_Candidate] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    decision_roots = [
        base / "calendar" / "artifacts" / "decisions",
        base / "claude" / "artifacts" / "decisions",
    ]
    for root in decision_roots:
        if not root.exists():
            continue
        for p in root.glob("*.md"):
            if p.resolve() == new_path.resolve():
                continue
            try:
                note = frontmatter.load(p)
            except Exception:  # noqa: BLE001
                continue
            meta = note.metadata
            artifact_id = str(meta.get("id") or p.stem)
            if artifact_id == new_id:
                continue
            created = str(meta.get("created") or "")
            try:
                created_dt = datetime.fromisoformat(
                    created.replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if created_dt < cutoff:
                continue
            candidates.append(_Candidate(
                artifact_id=artifact_id,
                title=str(meta.get("title") or p.stem),
                content=(note.content or "").strip()[:1500],
                path=p,
                created=created,
            ))

    candidates.sort(key=lambda c: c.created, reverse=True)
    return candidates[:DEFAULT_MAX_CANDIDATES]


def _build_prompt(
    *,
    new_title: str,
    new_body: str,
    candidates: list[_Candidate],
) -> str:
    template = _read_prompt("reversal-check.md")

    candidate_block_parts: list[str] = []
    for c in candidates:
        candidate_block_parts.append(
            f"---\nid: {c.artifact_id}\ncreated: {c.created}\n"
            f"title: {c.title}\n\n{c.content}\n"
        )
    candidate_block = "\n".join(candidate_block_parts)

    return (
        template
        .replace("{{new_title}}", new_title)
        .replace("{{new_body}}", new_body[:2000])
        .replace("{{candidates}}", candidate_block)
    )


def _read_prompt(name: str) -> str:
    f = vault_path() / "90-meta" / "prompts" / name
    if not f.exists():
        raise FileNotFoundError(
            f"missing prompt {name}; re-run `ghostbrain-bootstrap`"
        )
    return f.read_text(encoding="utf-8")


def _wikilink_for(path: Path) -> str:
    try:
        rel = path.relative_to(vault_path())
        return f"[[{rel.with_suffix('').as_posix()}]]"
    except ValueError:
        return f"[[{path.stem}]]"
