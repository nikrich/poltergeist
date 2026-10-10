"""The registry is the single source for rendering, intellisense and docs."""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from ghostbrain.templates.functions import (
    FIELD_IMPLS,
    FIELDS,
    FILTER_IMPLS,
    FILTERS,
    PROMPT_TYPES,
    PROMPT_VALUE_TYPES,
    VARIABLES,
    find_spec,
    registry_json,
)
from ghostbrain.templates.values import (
    EMPTY,
    DateTimeValue,
    DateValue,
    PersonValue,
    ProjectValue,
    UserValue,
    format_date,
    slugify,
    to_text,
    value_type,
)

D = date(2026, 10, 9)  # a Friday
DT = datetime(2026, 10, 9, 14, 30, 5)


@pytest.mark.parametrize(
    "pattern, expected",
    [
        ("YYYY-MM-DD", "2026-10-09"),
        ("D MMM YYYY", "9 Oct 2026"),
        ("MMMM YY", "October 26"),
        ("dddd [the] D", "Friday the 9"),
        ("ddd HH:mm:ss", "Fri 14:30:05"),
        ("M/D H", "10/9 14"),
    ],
)
def test_format_date_tokens(pattern, expected):
    assert format_date(DT, pattern) == expected


def test_format_date_on_a_plain_date_has_midnight_time():
    assert format_date(D, "HH:mm") == "00:00"


def test_slugify_matches_make_slug_rules():
    from ghostbrain.api.repo.notes_manual import make_slug

    for text in ["Hello World!", "  --  ", "Ünïcödé ✓", "a" * 50, "2026-10-09 Alex 1-1", "???"]:
        assert slugify(text) == make_slug(text)
    assert slugify("x" * 100, 80) == "x" * 80


def test_value_types_and_text():
    alex = PersonValue("Alex", "30-cross-context/people/alex.md")
    alpha = ProjectValue("work/alpha", "Alpha", "alpha", "work")
    assert [value_type(v) for v in ("t", DateValue(D), DateTimeValue(DT), alex, alpha, UserValue("Sam"), EMPTY)] == [
        "text", "date", "datetime", "person", "project", "user", "empty",
    ]
    assert to_text(DateValue(D)) == "2026-10-09"
    assert to_text(DateTimeValue(DT)) == "2026-10-09T14:30"
    assert to_text(alex) == "Alex" and to_text(EMPTY) == ""
    assert alex.link == "[[30-cross-context/people/alex]]"
    assert PersonValue("Alex", "").link == "[[Alex]]"
    assert alpha.path == "20-contexts/work/projects/alpha"


def test_every_field_spec_has_an_impl_and_back():
    assert {(s.owner, s.name) for s in FIELDS} == set(FIELD_IMPLS)


def test_every_filter_spec_has_an_impl_and_back():
    assert {s.name for s in FILTERS} == set(FILTER_IMPLS)


def test_prompt_types_match_the_parser_literal():
    from typing import get_args

    from ghostbrain.templates.parse import PromptType  # created in Task 3

    assert {s.name for s in PROMPT_TYPES} == set(get_args(PromptType))
    assert PROMPT_VALUE_TYPES["person"] == "person" and PROMPT_VALUE_TYPES["choice"] == "text"


def test_variable_names():
    assert {s.name for s in VARIABLES} == {"date", "time", "now", "context", "project", "title", "user"}


def test_every_spec_is_documented_and_json_ready():
    data = registry_json()
    assert set(data) == {"variables", "fields", "filters", "promptTypes"}
    json.dumps(data)
    for group in data.values():
        for spec in group:
            assert spec["doc"] and spec["example"]
    fmt = next(s for s in data["filters"] if s["name"] == "format")
    assert fmt["argRequired"] is True and fmt["arg"] == "<pattern>"


def test_find_spec():
    assert find_spec("filter", "format").arg_required is True
    assert find_spec("field", "link", owner="person").owner == "person"
    assert find_spec("field", "link", owner="project") is None
    assert find_spec("variable", "nope") is None


def test_filter_behaviour():
    fmt, dflt = FILTER_IMPLS["format"], FILTER_IMPLS["default"]
    assert fmt(DateValue(D), "D MMM") == "9 Oct"
    assert fmt("2026-10-09", "D MMM") == "9 Oct"
    assert fmt("not a date", "D MMM") == "not a date"
    assert fmt(EMPTY, "D MMM") is EMPTY
    assert dflt(EMPTY, "n/a") == "n/a"
    assert dflt("   ", "n/a") == "n/a"
    assert dflt("kept", "n/a") == "kept"
    assert FILTER_IMPLS["slug"]("Hello World", None) == "hello-world"
    assert FILTER_IMPLS["upper"]("hi", None) == "HI"
    assert FILTER_IMPLS["lower"]("HI", None) == "hi"
    for name in ("slug", "upper", "lower"):
        assert FILTER_IMPLS[name](EMPTY, None) is EMPTY
