"""Template language tokenizer (spec: render.py tiny tokenizer)."""
from __future__ import annotations

import pytest

from ghostbrain.templates.lang import (
    MAX_EXPR_CHARS,
    MAX_FILTERS,
    FilterCall,
    Placeholder,
    Text,
    parse_expression,
    tokenize,
)


def test_plain_text_is_one_text_segment():
    assert tokenize("hello world") == [Text("hello world")]


def test_placeholder_with_dotted_name_and_position():
    segs = tokenize("a {{ person.name }} b")
    assert segs[0] == Text("a ")
    ph = segs[1]
    assert isinstance(ph, Placeholder)
    assert ph.raw == "{{ person.name }}"
    assert (ph.start, ph.end, ph.line, ph.col) == (2, 19, 1, 3)
    assert ph.path == ("person", "name")
    assert ph.filters == ()
    assert segs[2] == Text(" b")


def test_filters_with_bare_and_missing_args():
    ph = tokenize("{{date | format: D MMM YYYY | upper}}")[0]
    assert ph.path == ("date",)
    assert ph.filters == (FilterCall("format", "D MMM YYYY"), FilterCall("upper", None))


def test_quoted_arg_may_contain_pipes_colons_and_escaped_quotes():
    ph = tokenize('{{x | default: "a | b: \\"c\\""}}')[0]
    assert ph.filters == (FilterCall("default", 'a | b: "c"'),)


def test_line_and_col_count_across_newlines():
    segs = tokenize("one\ntwo {{x}}\n{{y}}")
    phs = [s for s in segs if isinstance(s, Placeholder)]
    assert [(p.line, p.col) for p in phs] == [(2, 5), (3, 1)]


@pytest.mark.parametrize(
    "expr",
    [
        "{{ }}",
        "{{1abc}}",
        "{{a..b}}",
        "{{a | }}",
        '{{a | default: "unterminated}}',
        "{{a b}}",
        "{{_private}}",
        "{{a.b.c.d.e}}",
        "{{a | default:}}",
        "{{a | 9bad}}",
    ],
)
def test_invalid_expressions_are_placeholders_without_path(expr):
    ph = tokenize(expr)[0]
    assert isinstance(ph, Placeholder)
    assert ph.path is None
    assert ph.raw == expr


def test_too_many_filters_is_not_an_expression():
    chain = " | ".join(["upper"] * (MAX_FILTERS + 1))
    assert parse_expression(f"x | {chain}") is None
    assert parse_expression("x | " + " | ".join(["upper"] * MAX_FILTERS)) is not None


def test_unclosed_open_braces_stay_text():
    assert tokenize("a {{x b") == [Text("a {{x b")]


def test_overlong_expression_stays_text():
    src = "{{" + "a" * (MAX_EXPR_CHARS + 1) + "}}"
    assert tokenize(src) == [Text(src)]


def test_inner_open_braces_restart_the_scan():
    segs = tokenize("use {{ to open {{date}}")
    assert segs[0] == Text("use {{ to open ")
    assert isinstance(segs[1], Placeholder) and segs[1].path == ("date",)
