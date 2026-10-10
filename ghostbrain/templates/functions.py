"""The single registry of everything a template can name.

Rendering (render.py), GET /v1/templates/functions (completions and hover
docs) and the C3 linter all read from here. Tests assert that every spec has
an implementation and every implementation a spec, so the docs can't drift
from the behavior.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from ghostbrain.templates.values import (
    EMPTY,
    DateTimeValue,
    DateValue,
    Value,
    format_date,
    slugify,
    to_text,
)

Kind = Literal["variable", "field", "filter", "prompt_type", "query_key"]
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    kind: Kind
    type: str
    doc: str
    example: str
    owner: str | None = None
    accepts: tuple[str, ...] = ()
    arg: str | None = None
    arg_required: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name, "kind": self.kind, "type": self.type, "doc": self.doc,
            "example": self.example, "owner": self.owner, "accepts": list(self.accepts),
            "arg": self.arg, "argRequired": self.arg_required,
        }


VARIABLES: tuple[FunctionSpec, ...] = (
    FunctionSpec("date", "variable", "date",
                 "Today's date, or the answer to a `date` prompt with id `date`.",
                 "{{date | format: D MMM YYYY}}"),
    FunctionSpec("time", "variable", "text", "The current local time as HH:mm.", "{{time}}"),
    FunctionSpec("now", "variable", "datetime", "The current local date and time.",
                 "{{now | format: YYYY-MM-DD HH:mm}}"),
    FunctionSpec("context", "variable", "text",
                 "The context: a `context` prompt, else the one picked when creating, "
                 "else your first context.", "20-contexts/{{context}}/notes"),
    FunctionSpec("project", "variable", "project",
                 "The project picked when creating; empty when none.",
                 "{{project.name | default: none}}"),
    FunctionSpec("title", "variable", "text",
                 "The note's title (the rendered file name). Not available inside `file.name`.",
                 "# {{title}}"),
    FunctionSpec("user", "variable", "user",
                 "You. Set `user: {name: …}` in 90-meta/config.yaml.", "{{user.name}}"),
)

FIELDS: tuple[FunctionSpec, ...] = (
    FunctionSpec("name", "field", "text", "The person's name: their page title, or the typed name.",
                 "{{person.name}}", owner="person"),
    FunctionSpec("link", "field", "text", "A wikilink to the person's page.",
                 "{{person.link}}", owner="person"),
    FunctionSpec("path", "field", "text", "The person's page path (empty for a typed name).",
                 "{{person.path}}", owner="person"),
    FunctionSpec("name", "field", "text", "The project's name.", "{{project.name}}", owner="project"),
    FunctionSpec("slug", "field", "text", "The project's folder slug.", "{{project.slug}}",
                 owner="project"),
    FunctionSpec("context", "field", "text", "The context the project belongs to.",
                 "{{project.context}}", owner="project"),
    FunctionSpec("path", "field", "text", "The project's folder, e.g. 20-contexts/work/projects/alpha.",
                 "{{project.path}}", owner="project"),
    FunctionSpec("iso", "field", "text", "The date as YYYY-MM-DD.", "{{date.iso}}", owner="date"),
    FunctionSpec("iso", "field", "text", "The date and time in ISO 8601.", "{{now.iso}}",
                 owner="datetime"),
    FunctionSpec("date", "field", "date", "Just the date part.", "{{now.date | format: D MMM}}",
                 owner="datetime"),
    FunctionSpec("name", "field", "text", "Your name.", "{{user.name}}", owner="user"),
)

FIELD_IMPLS: Mapping[tuple[str, str], Callable[[Any], Value]] = {
    ("person", "name"): lambda v: v.name,
    ("person", "link"): lambda v: v.link,
    ("person", "path"): lambda v: v.path,
    ("project", "name"): lambda v: v.name,
    ("project", "slug"): lambda v: v.slug,
    ("project", "context"): lambda v: v.context,
    ("project", "path"): lambda v: v.path,
    ("date", "iso"): lambda v: v.value.isoformat(),
    ("datetime", "iso"): lambda v: v.value.isoformat(timespec="seconds"),
    ("datetime", "date"): lambda v: DateValue(v.value.date()),
    ("user", "name"): lambda v: v.name,
}


def _format(value: Value, arg: str | None) -> Value:
    pattern = arg or ""
    if isinstance(value, (DateValue, DateTimeValue)):
        return format_date(value.value, pattern)
    if isinstance(value, str) and _ISO_DATE_RE.fullmatch(value.strip()):
        try:
            return format_date(date.fromisoformat(value.strip()), pattern)
        except ValueError:
            return value
    return value


def _text_filter(fn: Callable[[str], str]) -> Callable[[Value, str | None], Value]:
    def apply(value: Value, _arg: str | None) -> Value:
        return EMPTY if value is EMPTY else fn(to_text(value))

    return apply


def _default(value: Value, arg: str | None) -> Value:
    if value is EMPTY or to_text(value).strip() == "":
        return arg or ""
    return value


FILTERS: tuple[FunctionSpec, ...] = (
    FunctionSpec("format", "filter", "text",
                 "Formats a date. Tokens: YYYY YY MMMM MMM MM M DD D dddd ddd HH H mm ss; "
                 "wrap literal text in [brackets].",
                 "{{date | format: D MMM YYYY}}", accepts=("date", "datetime", "text"),
                 arg="<pattern>", arg_required=True),
    FunctionSpec("slug", "filter", "text",
                 "Lower-case with dashes for anything that isn't a letter or digit (max 32).",
                 "{{person.name | slug}}", accepts=("*",)),
    FunctionSpec("upper", "filter", "text", "UPPER CASE.", "{{context | upper}}", accepts=("*",)),
    FunctionSpec("lower", "filter", "text", "lower case.", "{{person.name | lower}}", accepts=("*",)),
    FunctionSpec("default", "filter", "text",
                 "Text to use when the value is empty (an unanswered optional prompt).",
                 "{{focus | default: nothing planned}}", accepts=("*",),
                 arg="<text>", arg_required=True),
)

FILTER_IMPLS: Mapping[str, Callable[[Value, str | None], Value]] = {
    "format": _format,
    "slug": _text_filter(slugify),
    "upper": _text_filter(str.upper),
    "lower": _text_filter(str.lower),
    "default": _default,
}
FILTERS_BY_NAME: Mapping[str, FunctionSpec] = {s.name: s for s in FILTERS}

PROMPT_TYPES: tuple[FunctionSpec, ...] = (
    FunctionSpec("text", "prompt_type", "text", "Free text.", "type: text"),
    FunctionSpec("person", "prompt_type", "person",
                 "A person: pick their page (name, link, path) or type a name.", "type: person"),
    FunctionSpec("date", "prompt_type", "date", "A date (YYYY-MM-DD).", "type: date"),
    FunctionSpec("choice", "prompt_type", "text", "One of `options`.", "type: choice"),
    FunctionSpec("context", "prompt_type", "text", "One of your contexts.", "type: context"),
    FunctionSpec("project", "prompt_type", "project",
                 "One of your projects (name, slug, context, path).", "type: project"),
)
PROMPT_VALUE_TYPES: Mapping[str, str] = {s.name: s.type for s in PROMPT_TYPES}

# Keys of a ```query``` block (spec C2). query.py builds its whitelist from
# this tuple, so the parser, the docs and C3's completions cannot drift apart.
QUERY_KEYS: tuple[FunctionSpec, ...] = (
    FunctionSpec("type", "query_key", "text",
                 "Notes whose frontmatter `artifactType` or `type` equals this, e.g. action_item, "
                 "decision or meeting.", "type: action_item"),
    FunctionSpec("context", "query_key", "text",
                 "Notes in this context: the 20-contexts/<name> folder, or frontmatter `context`.",
                 "context: work"),
    FunctionSpec("tag", "query_key", "text",
                 "Notes with this tag, in frontmatter `tags` or as #tag in the text.", "tag: roadmap"),
    FunctionSpec("mentions", "query_key", "text",
                 "Notes that link to this page, or else name it in their text. A wikilink or a name.",
                 'mentions: "[[30-cross-context/people/alex]]"'),
    FunctionSpec("status", "query_key", "text",
                 "`open` = status is not done or closed (notes with no status count as open). "
                 "Any other word matches exactly.", "status: open"),
    FunctionSpec("since", "query_key", "text",
                 "Created on or after: `7d`, `2w`, or a date like 2026-10-01.", "since: 7d"),
    FunctionSpec("sort", "query_key", "text",
                 "`created` or `updated`, then `asc` or `desc`. Default: created desc.",
                 "sort: created desc"),
    FunctionSpec("limit", "query_key", "number",
                 "How many notes to show: default 20, at most 100.", "limit: 20"),
)


def find_spec(kind: Kind, name: str, owner: str | None = None) -> FunctionSpec | None:
    for spec in (*VARIABLES, *FIELDS, *FILTERS, *PROMPT_TYPES, *QUERY_KEYS):
        if spec.kind == kind and spec.name == name and (owner is None or spec.owner == owner):
            return spec
    return None


def registry_json() -> dict[str, list[dict[str, Any]]]:
    return {
        "variables": [s.to_json() for s in VARIABLES],
        "fields": [s.to_json() for s in FIELDS],
        "filters": [s.to_json() for s in FILTERS],
        "promptTypes": [s.to_json() for s in PROMPT_TYPES],
        "queryKeys": [s.to_json() for s in QUERY_KEYS],
    }
