"""Live ```query``` blocks (smart templates C2): grammar and runner."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import pytest

from ghostbrain.templates.query import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_QUERY_CHARS,
    MAX_QUERY_LINES,
    Mention,
    Query,
    parse_query_block,
)

TODAY = date(2026, 10, 10)


def _parse(text: str):
    return parse_query_block(text, today=TODAY)


def _codes(diags):
    return [(d.line, d.col, d.severity, d.code) for d in diags]


def test_one_on_one_block_parses():
    q, diags = _parse(
        'type: action_item\nmentions: "[[30-cross-context/people/alex]]"\n'
        "status: open\nsort: created desc\n"
    )
    assert diags == []
    assert q == Query(
        type="action_item",
        mentions=Mention("30-cross-context/people/alex.md", "alex"),
        status="open",
        sort="created",
        descending=True,
        limit=DEFAULT_LIMIT,
    )


def test_defaults_comments_quotes_and_case():
    q, diags = _parse("# open decisions\n\n  Type: 'Decision'\nCONTEXT: \"Work\"\n")
    assert diags == []
    assert q == Query(type="decision", context="work")
    assert (q.sort, q.descending, q.limit) == ("created", True, 20)


@pytest.mark.parametrize("value, expected", [
    ("Alex", Mention("Alex.md", "Alex")),
    ("@Alex", Mention("Alex.md", "Alex")),
    ('"[[Alex]]"', Mention("Alex.md", "Alex")),
    ("[[30-cross-context/people/alex|@Alex]]", Mention("30-cross-context/people/alex.md", "Alex")),
    ("[[30-cross-context/people/alex#Notes]]", Mention("30-cross-context/people/alex.md", "alex")),
])
def test_mentions_forms(value, expected):
    q, diags = _parse(f"mentions: {value}")
    assert diags == []
    assert q.mentions == expected


def test_tag_and_status_are_normalised():
    q, diags = _parse("tag: #Roadmap\nstatus: Open")
    assert diags == []
    assert (q.tag, q.status) == ("roadmap", "open")


@pytest.mark.parametrize("value, expected", [
    ("7d", date(2026, 10, 3)),
    ("2w", date(2026, 9, 26)),
    ("0d", TODAY),
    ("2026-10-01", date(2026, 10, 1)),
])
def test_since_forms(value, expected):
    q, diags = _parse(f"type: decision\nsince: {value}")
    assert diags == []
    assert q.since == expected


def test_sort_and_limit():
    q, diags = _parse("type: decision\nsort: updated asc\nlimit: 5")
    assert diags == []
    assert (q.sort, q.descending, q.limit) == ("updated", False, 5)
    q, _ = _parse("type: decision\nsort: Updated")
    assert (q.sort, q.descending) == ("updated", True)


def test_limit_over_the_cap_is_capped_with_a_warning():
    q, diags = _parse("type: decision\nlimit: 999999")
    assert q is not None and q.limit == MAX_LIMIT == 100
    assert _codes(diags) == [(2, 8, "warning", "limit-capped")]


@pytest.mark.parametrize("text, expected", [
    ("type: decision\nowner: alex", [(2, 1, "error", "unknown-key")]),
    ("type: decision\ntype: meeting", [(2, 1, "error", "duplicate-key")]),
    ("type decision", [(1, 1, "error", "syntax")]),
    ("type:", [(1, 6, "error", "empty-value")]),
    ("", [(1, 1, "error", "empty-query")]),
    ("# only a comment\n", [(1, 1, "error", "empty-query")]),
    ("since: yesterday", [(1, 8, "error", "bad-value")]),
    ("since: 2026-13-40", [(1, 8, "error", "bad-value")]),
    ("sort: title", [(1, 7, "error", "bad-value")]),
    ("limit: 0", [(1, 8, "error", "bad-value")]),
    ("limit: ten", [(1, 8, "error", "bad-value")]),
    ("status: not done", [(1, 9, "error", "bad-value")]),
    ("mentions: [[90-meta/assets/x.png]]", [(1, 11, "error", "bad-value")]),
    ("mentions: Alex [[b]]", [(1, 11, "error", "bad-value")]),
    ('mentions: "{{person.link}}"', [(1, 11, "error", "unresolved-placeholder")]),
    ("  tag: '#'", [(1, 8, "error", "bad-value")]),
])
def test_errors_carry_line_and_column(text, expected):
    q, diags = _parse(text)
    assert q is None
    assert _codes(diags) == expected


def test_unknown_key_message_lists_the_keys():
    _, diags = _parse("owner: alex")
    assert "use one of: type, context, tag, mentions, status, since, sort, limit" in diags[0].message


def test_size_caps():
    q, diags = _parse("type: decision\n" + "#\n" * MAX_QUERY_LINES)
    assert q is None and [d.code for d in diags] == ["query-too-long"]
    q, diags = _parse("type: " + "x" * MAX_QUERY_CHARS)
    assert q is None and [d.code for d in diags] == ["query-too-long"]
    q, diags = _parse("type: " + "x" * 201)
    assert q is None and [d.code for d in diags] == ["value-too-long"]


def test_rendered_one_on_one_starter_query_parses():
    """The C1 starter's fence, after rendering, is a valid C2 query."""
    from ghostbrain.templates.parse import parse_template
    from ghostbrain.templates.render import RenderEnv, render
    from ghostbrain.templates.starters import STARTER_TEMPLATES

    env = RenderEnv(now=datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2))),
                    default_context="work", contexts=("work", "personal"))
    template = parse_template(STARTER_TEMPLATES["one-on-one.md"], "one-on-one").template
    body = render(template, {"person": "Alex"}, env).body
    fences = re.findall(r"^```query\n(.*?)^```", body, flags=re.MULTILINE | re.DOTALL)
    assert len(fences) == 1
    q, diags = _parse(fences[0])
    assert diags == []
    assert q == Query(type="action_item", mentions=Mention("Alex.md", "Alex"), status="open")
