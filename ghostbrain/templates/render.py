"""Render a parsed template with answers into a note (spec: render.py).

Single pass with no recursion: a placeholder's value is inserted as text and
never re-scanned, so an answer containing ``{{…}}`` stays literal. Total
output is budgeted, frontmatter values are serialised with
``yaml.safe_dump`` (answers can't inject keys), and the target folder is
validated before anything can be written.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any

import yaml

from ghostbrain.templates.functions import (
    FIELD_IMPLS,
    FIELDS,
    FILTER_IMPLS,
    FILTERS_BY_NAME,
    PROMPT_VALUE_TYPES,
    VARIABLES,
)
from ghostbrain.templates.lang import Placeholder, Text, tokenize
from ghostbrain.templates.parse import MAX_TREE_DEPTH, MAX_TREE_NODES, SHADOWABLE, Template
from ghostbrain.templates.values import (
    EMPTY,
    DateTimeValue,
    DateValue,
    PersonValue,
    ProjectValue,
    UserValue,
    Value,
    slugify,
    to_text,
    value_type,
)

MAX_ANSWER_CHARS = 10_000
MAX_OUTPUT_CHARS = 1_000_000
MAX_TITLE_CHARS = 200
MAX_PERSON_NAME_CHARS = 200
MAX_FOLDER_DEPTH = 10
MAX_SEGMENT_CHARS = 120
FILENAME_SLUG_MAX = 80
# 90-meta is the system area (templates, config); 80-profile feeds CLAUDE.md.
PROTECTED_TOP_LEVEL = frozenset({"90-meta", "80-profile"})
_BAD_SEGMENT_CHARS = frozenset('<>:"|?*\\')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Wikilink / heading / table markup and line breaks, banned in typed names and note paths alike.
_PERSON_MARKUP_RE = re.compile(r"[\[\]|#\r\n]")
_VARIABLE_TYPES: Mapping[str, str] = {s.name: s.type for s in VARIABLES}
_FIELD_TYPES: Mapping[tuple[str | None, str], str] = {(s.owner, s.name): s.type for s in FIELDS}


class AnswerError(ValueError):
    """An answer is missing or invalid; ``field`` is the prompt id."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class RenderError(ValueError):
    """The rendered note can't be filed: bad folder, or too large."""


def _no_title(_path: str) -> str | None:
    return None


@dataclass(frozen=True)
class RenderEnv:
    now: datetime
    default_context: str
    contexts: tuple[str, ...]
    projects: Mapping[str, ProjectValue] = field(default_factory=dict)
    user_name: str = ""
    person_title: Callable[[str], str | None] = _no_title


@dataclass(frozen=True)
class RenderedNote:
    template_id: str
    folder: str
    filename: str
    title: str
    frontmatter: dict[str, Any]
    body: str

    @property
    def path(self) -> str:
        return f"{self.folder}/{self.filename}"

    def markdown(self) -> str:
        fm = yaml.safe_dump(self.frontmatter, sort_keys=False, allow_unicode=True,
                            default_flow_style=False)
        return f"---\n{fm}---\n\n{self.body}"


class Budget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.left = limit

    def take(self, n: int) -> None:
        self.left -= n
        if self.left < 0:
            raise RenderError(f"the rendered note is larger than {self.limit} characters")


class Scope(dict[str, Value]):
    """Name → value, plus each name's declared value type, so a field of an
    empty value (an unanswered optional prompt) is still checked against the
    registry and an unknown field stays literal."""

    def __init__(self, values: Mapping[str, Value], types: Mapping[str, str]) -> None:
        super().__init__(values)
        self.types: dict[str, str] = dict(types)


def _humanize(stem: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_\s]+", stem) if w) or stem


def _coerce_person(field_id: str, raw: str, env: RenderEnv) -> PersonValue:
    if _PERSON_MARKUP_RE.search(raw):
        raise AnswerError(field_id, "a person can't contain [ ] | # or line breaks")
    if "/" in raw or "\\" in raw or raw.lower().endswith(".md"):
        parts = raw.split("/")
        if (
            "\\" in raw
            or raw.startswith("/")
            or any(ord(c) < 32 for c in raw)
            or any(p in ("", ".", "..") or p.startswith(".") or ":" in p for p in parts)
        ):
            raise AnswerError(field_id, "a person must be a vault note path or a name")
        path = raw if raw.lower().endswith(".md") else f"{raw}.md"
        stem = PurePosixPath(path).stem
        title = env.person_title(path)
        return PersonValue(name=title if title and title != stem else _humanize(stem), path=path)
    if len(raw) > MAX_PERSON_NAME_CHARS:
        raise AnswerError(field_id, f"a person's name is longer than {MAX_PERSON_NAME_CHARS} characters")
    return PersonValue(name=raw, path="")


def _coerce_one(kind: str, field_id: str, raw: str, env: RenderEnv, options: tuple[str, ...]) -> Value:
    if kind == "text":
        return raw
    if kind == "choice":
        if raw not in options:
            raise AnswerError(field_id, f"pick one of: {', '.join(options)}")
        return raw
    if kind == "date":
        try:
            if not _DATE_RE.fullmatch(raw):
                raise ValueError(raw)
            return DateValue(date.fromisoformat(raw))
        except ValueError:
            raise AnswerError(field_id, "use a date like 2026-10-09") from None
    if kind == "context":
        if raw not in env.contexts:
            raise AnswerError(field_id, f"unknown context `{raw}`")
        return raw
    if kind == "project":
        project = env.projects.get(raw)
        if project is None:
            raise AnswerError(field_id, f"unknown project `{raw}`")
        return project
    return _coerce_person(field_id, raw, env)


def coerce_answers(template: Template, answers: Mapping[str, str], env: RenderEnv) -> dict[str, Value]:
    prompt_ids = {p.id for p in template.prompts}
    for key, raw in answers.items():
        if key not in prompt_ids and key not in SHADOWABLE:
            raise AnswerError(key, f"unknown answer `{key}`")
        if not isinstance(raw, str):
            raise AnswerError(key, "answers must be text")
        if len(raw) > MAX_ANSWER_CHARS:
            raise AnswerError(key, f"answer is longer than {MAX_ANSWER_CHARS} characters")
    values: dict[str, Value] = {}
    for p in template.prompts:
        raw = (answers.get(p.id) or "").strip()
        if not raw:
            if p.default is not None:
                raw = p.default
            elif p.optional:
                values[p.id] = EMPTY
                continue
            else:
                raise AnswerError(p.id, "an answer is required")
        values[p.id] = _coerce_one(p.type, p.id, raw, env, p.options)
    for key, kind in SHADOWABLE.items():
        raw = (answers.get(key) or "").strip()
        if key not in prompt_ids and raw:
            values[key] = _coerce_one(kind, key, raw, env, ())
    return values


def build_scope(
    values: Mapping[str, Value], env: RenderEnv, types: Mapping[str, str] | None = None
) -> Scope:
    """Builtins (see functions.VARIABLES, minus `title`) overlaid with answers.

    ``types`` are the answers' declared value types (prompt id → value type);
    they let ``evaluate`` check fields of an empty answer against the registry.
    """
    scope: dict[str, Value] = {
        "date": DateValue(env.now.date()),
        "time": f"{env.now.hour:02d}:{env.now.minute:02d}",
        "now": DateTimeValue(env.now),
        "context": env.default_context,
        "project": EMPTY,
        "user": UserValue(env.user_name),
    }
    declared = {**_VARIABLE_TYPES, **(types or {})}
    for key, value in values.items():
        if value is EMPTY and key in ("date", "context"):
            continue  # an unanswered optional date/context prompt keeps the builtin
        scope[key] = value
    return Scope(scope, declared)


def evaluate(ph: Placeholder, scope: Mapping[str, Value]) -> Value | None:
    """The placeholder's value, or None to render it literally."""
    if ph.path is None or ph.path[0] not in scope:
        return None
    value = scope[ph.path[0]]
    declared = scope.types.get(ph.path[0]) if isinstance(scope, Scope) else None
    for name in ph.path[1:]:
        if value is EMPTY:
            # No value to read, but the field must still exist for the declared
            # type; an unknown field (or an untyped empty) stays literal.
            declared = _FIELD_TYPES.get((declared, name))
            if declared is None:
                return None
            continue
        impl = FIELD_IMPLS.get((value_type(value), name))
        if impl is None:
            return None
        value = impl(value)
    for call in ph.filters:
        spec = FILTERS_BY_NAME.get(call.name)
        if spec is None or (spec.arg_required and call.arg is None) or (spec.arg is None and call.arg is not None):
            return None
        value = FILTER_IMPLS[call.name](value, call.arg)
    return value


def render_string(text: str, scope: Mapping[str, Value], budget: Budget | None = None) -> str:
    budget = budget or Budget(MAX_OUTPUT_CHARS)
    out: list[str] = []
    for seg in tokenize(text):
        if isinstance(seg, Text):
            piece = seg.text
        else:
            value = evaluate(seg, scope)
            piece = seg.raw if value is None else to_text(value)
        budget.take(len(piece))
        out.append(piece)
    return "".join(out)


def validate_folder(folder: str) -> str:
    f = folder.strip().rstrip("/")
    if not f:
        raise RenderError("the template's folder rendered empty")
    if "{{" in f or "}}" in f:
        raise RenderError(f"folder has an unresolved placeholder: {f}")
    if f.startswith("/") or "\\" in f:
        raise RenderError("folder must be a vault-relative path using /")
    if _PERCENT_ESCAPE_RE.search(f):
        raise RenderError("folder can't contain URL-encoded characters")
    parts = f.split("/")
    if len(parts) > MAX_FOLDER_DEPTH:
        raise RenderError(f"folder is deeper than {MAX_FOLDER_DEPTH} levels")
    for part in parts:
        if (
            part in ("", ".", "..")
            or part.startswith(".")
            or part.endswith(".")
            or part != part.strip()
            or len(part) > MAX_SEGMENT_CHARS
            or any(c in _BAD_SEGMENT_CHARS or ord(c) < 32 for c in part)
            or part.split(".")[0].upper() in _WINDOWS_RESERVED
        ):
            raise RenderError(f"folder segment {part!r} is not allowed")
    if parts[0].lower() in PROTECTED_TOP_LEVEL:
        raise RenderError(f"templates can't file notes under {parts[0]} (protected area)")
    return "/".join(parts)


def _render_tree(value: Any, scope: Mapping[str, Value], budget: Budget, depth: int, nodes: list[int]) -> Any:
    nodes[0] += 1
    if nodes[0] > MAX_TREE_NODES or depth > MAX_TREE_DEPTH:
        raise RenderError("template frontmatter is too large or too deeply nested")
    if isinstance(value, str):
        return render_string(value, scope, budget)
    if isinstance(value, dict):
        return {str(k): _render_tree(v, scope, budget, depth + 1, nodes) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_tree(v, scope, budget, depth + 1, nodes) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def render(template: Template, answers: Mapping[str, str], env: RenderEnv) -> RenderedNote:
    budget = Budget(MAX_OUTPUT_CHARS)
    types = {p.id: PROMPT_VALUE_TYPES[p.type] for p in template.prompts}
    scope = build_scope(coerce_answers(template, answers, env), env, types)
    raw_title = render_string(template.file.name, scope, budget)
    title = " ".join(raw_title.split())[:MAX_TITLE_CHARS] or template.name
    folder = validate_folder(render_string(template.file.folder, scope, budget))
    scope = Scope({**scope, "title": title}, scope.types)
    rendered_fm = _render_tree(dict(template.frontmatter), scope, budget, 0, [0])
    body = render_string(template.body, scope, budget)
    stamp = env.now.isoformat(timespec="seconds")
    frontmatter = {"title": title, "created": stamp, "updated": stamp, **rendered_fm,
                   "fromTemplate": template.id}
    filename = slugify(title, FILENAME_SLUG_MAX) + ".md"
    return RenderedNote(template.id, folder, filename, title, frontmatter, body)
