"""Extract specs/decisions/code/prompts/unresolved questions from a session
and write each as its own artifact note.

Uses the extractor prompt at ``vault/90-meta/prompts/extractor.md``. Returns
the list of artifact paths written. If the LLM returns nothing
extractable — common for short or chatty sessions — we return [] and that's
fine.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ghostbrain.llm import client as llm
from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.worker.extractor")

ARTIFACT_TYPES = ("spec", "decision", "code", "prompt", "unresolved")

# NOTE: `claude -p --json-schema` only accepts object roots — array roots
# fail with "tools.N.custom.input_schema.type: Input should be 'object'".
# We wrap the array in an `items` envelope; the LLM sees this as a single
# field, the extractor unwraps after parsing.
EXTRACTOR_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "title", "content"],
                "properties": {
                    "type": {"type": "string", "enum": list(ARTIFACT_TYPES)},
                    "title": {"type": "string", "maxLength": 200},
                    "content": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 8,
                    },
                },
            },
        },
    },
}


@dataclasses.dataclass
class ExtractedArtifact:
    type: str
    title: str
    content: str
    tags: list[str]


def extract(
    excerpt: str,
    *,
    context: str,
    parent_note_id: str,
    parent_note_path: Path | None,
    config: dict | None = None,
) -> list[Path]:
    """Run the extractor LLM and persist each artifact. Returns paths written."""
    if not excerpt.strip():
        return []

    prompt_template = _read_prompt("extractor.md")
    prompt = prompt_template.replace("{{content}}", excerpt)

    config = config or {}
    model = (config.get("llm") or {}).get("extractor_model", "sonnet")

    try:
        result = llm.run(
            prompt,
            model=model,
            json_schema=EXTRACTOR_JSON_SCHEMA,
            budget_usd=1.0,  # extractor tends to be larger; relax cap
        )
        envelope = result.as_json()
    except llm.LLMError as e:
        log.warning("extractor LLM failed for parent=%s: %s", parent_note_id, e)
        return []

    # Schema wraps the array in `{"items": [...]}` — see EXTRACTOR_JSON_SCHEMA.
    if isinstance(envelope, dict) and "items" in envelope:
        items = envelope["items"]
    elif isinstance(envelope, list):
        # Tolerant fallback: caller didn't use schema, returned raw array.
        items = envelope
    else:
        log.warning("extractor returned unexpected shape for parent=%s: %r",
                    parent_note_id, envelope)
        return []

    if not isinstance(items, list):
        log.warning("extractor `items` field not a list for parent=%s: %r",
                    parent_note_id, items)
        return []

    written: list[Path] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            artifact = ExtractedArtifact(
                type=str(raw["type"]),
                title=str(raw["title"]).strip(),
                content=str(raw["content"]).strip(),
                tags=[str(t) for t in (raw.get("tags") or [])][:8],
            )
        except (KeyError, ValueError):
            continue
        if artifact.type not in ARTIFACT_TYPES:
            continue
        if not artifact.title or not artifact.content:
            continue
        path = _write_artifact(
            artifact,
            context=context,
            parent_note_id=parent_note_id,
            parent_note_path=parent_note_path,
        )
        written.append(path)

    log.info("extracted %d artifact(s) for parent=%s",
             len(written), parent_note_id)
    return written


def _write_artifact(
    artifact: ExtractedArtifact,
    *,
    context: str,
    parent_note_id: str,
    parent_note_path: Path | None,
) -> Path:
    artifact_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    folder = _ARTIFACT_FOLDERS[artifact.type]
    target_dir = vault_path() / "20-contexts" / context / "claude" / "artifacts" / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    front: dict[str, Any] = {
        "id": artifact_id,
        "context": context,
        "type": "artifact",
        "artifactType": artifact.type,
        "source": "claude-code",
        "created": ts,
        "ingestedAt": ts,
        "parent": _wikilink_for(parent_note_path) if parent_note_path else parent_note_id,
        "tags": artifact.tags,
    }
    yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    body = f"# {artifact.title}\n\n{artifact.content}\n"
    rendered = f"---\n{yaml_block}\n---\n\n{body}"

    filename = _artifact_filename(artifact, artifact_id)
    path = target_dir / filename
    path.write_text(rendered, encoding="utf-8")
    return path


def _artifact_filename(artifact: ExtractedArtifact, artifact_id: str) -> str:
    slug = _slugify(artifact.title)[:60] or artifact.type
    return f"{slug}-{artifact_id[:8]}.md"


def _slugify(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9\-_ ]", "", text).strip().lower()
    return re.sub(r"\s+", "-", text)


def _wikilink_for(path: Path) -> str:
    """Best-effort Obsidian wikilink to the parent note (relative to vault)."""
    try:
        rel = path.relative_to(vault_path())
        # Strip extension for Obsidian-style links.
        return f"[[{rel.with_suffix('').as_posix()}]]"
    except ValueError:
        return f"[[{path.stem}]]"


def _read_prompt(name: str) -> str:
    f = vault_path() / "90-meta" / "prompts" / name
    if not f.exists():
        raise FileNotFoundError(
            f"missing prompt {name}; re-run `ghostbrain-bootstrap`"
        )
    return f.read_text(encoding="utf-8")


_ARTIFACT_FOLDERS: dict[str, str] = {
    "spec": "specs",
    "decision": "decisions",
    "code": "code",
    "prompt": "prompts",
    "unresolved": "unresolved",
}
