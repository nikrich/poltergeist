"""One note chunk → validated observed candidates. A candidate whose quote is
not actually in the note is discarded (the main hallucination guard)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ghostbrain.llm import client as llm
from ghostbrain.ontology.prompts import EXTRACT_PROMPT
from ghostbrain.ontology.sanitize import neutralise, one_line
from ghostbrain.ontology.schema import DOMAIN_KINDS, RELATION_TYPES
from ghostbrain.paths import vault_path

EXTRACTOR_VERSION = "m1-2026-10-10"
EXTRACT_MODEL = "sonnet"
EXTRACT_BUDGET_USD = 2.0
EXTRACT_TIMEOUT_S = 300
MAX_QUOTE = 300
MIN_QUOTE = 8
REPAIR_SUFFIX = "\n\nYour previous answer was invalid. Return ONLY JSON matching the schema."

CANDIDATE_JSON_SCHEMA: dict = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "name", "statement", "value", "existing_uid", "relations",
                     "quote", "locator", "confidence", "topic"],
        "properties": {
            "kind": {"type": "string", "enum": list(DOMAIN_KINDS)},
            "name": {"type": "string"},
            "statement": {"type": "string"},
            "value": {"type": ["string", "null"]},
            "existing_uid": {"type": ["string", "null"]},
            "relations": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["type", "target_uid"],
                "properties": {"type": {"type": "string", "enum": list(RELATION_TYPES)},
                               "target_uid": {"type": "string"}}}},
            "quote": {"type": "string"},
            "locator": {"type": "string"},
            "confidence": {"type": "number"},
            "topic": {"type": "string"},
        }}}},
}

_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
_WS = re.compile(r"\s+")
_PLACEHOLDER = re.compile(r"\{\{(KINDS|DIGEST|TITLE|TEXT|PROJECT|SEEDS|TOPICS)\}\}")


class ExtractionFailed(RuntimeError):
    pass


@dataclass
class CandidateIn:
    kind: str
    name: str
    statement: str
    value: str | None
    existing_uid: str | None
    relations: list[dict] = field(default_factory=list)
    quote: str = ""
    locator: str = ""
    confidence: float = 0.5
    topic: str = ""


def normalise(text: str) -> str:
    return _WS.sub(" ", text.translate(_QUOTES)).strip().casefold()


def chunk_text(text: str, max_chars: int = 24_000) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sections = re.split(r"(?m)^(?=#{1,3} )", text)
    chunks: list[str] = []
    current = ""
    for sec in sections:
        if len(current) + len(sec) <= max_chars:
            current += sec
            continue
        if current:
            chunks.append(current)
        while len(sec) > max_chars:
            chunks.append(sec[:max_chars])
            sec = sec[max_chars:]
        current = sec
    if current:
        chunks.append(current)
    return chunks


def _template() -> str:
    override = vault_path() / "90-meta" / "prompts" / "ontology-extract.md"
    if override.is_file():
        return override.read_text(encoding="utf-8")
    return EXTRACT_PROMPT


def build_prompt(title: str, text: str, digest: list[dict], *, project_name: str = "",
                 seeds: list[str] | None = None,
                 topics: list[dict] | None = None) -> str:
    lines = [
        one_line(f"[{d['uid']}] {d['kind']}: {d['name']}" + (f" = {d['value']}" if d.get("value") else ""))
        for d in digest
    ] or ["(empty — nothing ratified yet)"]
    topic_lines = [
        one_line(f"- {t['name']}" + {"in": " (in scope)", "out": " (out of scope)"}.get(t.get("status"), ""))
        for t in topics or []
    ] or ["(none yet)"]
    # Single pass: substituted values are never re-scanned for placeholders.
    # Every single-line value is flattened so it cannot fake prompt structure; note text keeps
    # its line breaks but is neutralised so it cannot end the data block or forge a header.
    values = {
        "KINDS": ", ".join(DOMAIN_KINDS),
        "DIGEST": "\n".join(lines),
        "TITLE": one_line(title),
        "PROJECT": one_line(project_name) or "(unnamed)",
        "SEEDS": one_line(", ".join(seeds or [])) or "(none)",
        "TOPICS": "\n".join(topic_lines),
        "TEXT": neutralise(text),
    }
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], _template())


def validate(raw_items: list[dict], source_text: str, digest_uids: set[str]) -> tuple[list[CandidateIn], int]:
    source = normalise(source_text)
    valid: list[CandidateIn] = []
    discarded = 0
    for it in raw_items:
        try:
            kind = it["kind"]
            name = str(it["name"]).strip()
            statement = str(it["statement"]).strip()
            quote = str(it["quote"]).strip()[:MAX_QUOTE]
        except (KeyError, TypeError):
            discarded += 1
            continue
        if (kind not in DOMAIN_KINDS or not name or not statement or not quote
                or len(normalise(quote)) < MIN_QUOTE or normalise(quote) not in source):
            discarded += 1
            continue
        existing = it.get("existing_uid")
        relations = [
            {"type": r["type"], "target_uid": r["target_uid"]}
            for r in it.get("relations") or []
            if isinstance(r, dict) and r.get("type") in RELATION_TYPES and r.get("target_uid") in digest_uids
        ]
        try:
            confidence = min(1.0, max(0.0, float(it.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        value = it.get("value")
        valid.append(CandidateIn(
            kind=kind, name=name, statement=statement,
            value=str(value).strip() if value not in (None, "") else None,
            existing_uid=existing if existing in digest_uids else None,
            relations=relations, quote=quote, locator=str(it.get("locator") or "")[:200],
            confidence=confidence, topic=one_line(it.get("topic") or "", 60),
        ))
    return valid, discarded


def extract_chunk(title: str, text: str, digest: list[dict], *, run=None, project_name: str = "",
                  seeds: list[str] | None = None,
                  topics: list[dict] | None = None) -> tuple[list[CandidateIn], int]:
    run = run or llm.run
    prompt = build_prompt(title, text, digest, project_name=project_name, seeds=seeds, topics=topics)
    uids = {d["uid"] for d in digest}
    last_error = "unknown"
    for attempt in range(2):
        try:
            result = run(prompt + (REPAIR_SUFFIX if attempt else ""), model=EXTRACT_MODEL,
                         json_schema=CANDIDATE_JSON_SCHEMA, budget_usd=EXTRACT_BUDGET_USD,
                         timeout_s=EXTRACT_TIMEOUT_S)
            data = result.as_json()
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise ValueError("response has no items list")
            return validate(data["items"], text, uids)
        except (llm.LLMError, ValueError, TypeError) as e:
            last_error = str(e)
    raise ExtractionFailed(last_error)
