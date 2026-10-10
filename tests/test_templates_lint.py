"""lint(): parse diagnostics plus registry checks of every placeholder."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ghostbrain.templates import lint as lint_mod
from ghostbrain.templates.lint import MAX_LINT_DIAGNOSTICS, lint
from ghostbrain.templates.parse import Diagnostic, parse_template
from ghostbrain.templates.render import RenderEnv, RenderError, render
from ghostbrain.templates.starters import STARTER_TEMPLATES
from ghostbrain.templates.values import ProjectValue

HEAD = """---
template:
  name: T
  prompts:
    - id: person
      ask: Who?
      type: person
    - id: topic
      ask: What?
      type: text
    - id: when
      ask: When?
      type: date
      optional: true
---
"""
BODY_LINE = 16
ENV = RenderEnv(
    now=datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2))),
    default_context="work",
    contexts=("work",),
    projects={"work/alpha": ProjectValue("work/alpha", "Alpha", "alpha", "work")},
    user_name="Sam",
)
ANSWERS = {"person": "Alex", "topic": "Planning"}


def found(src: str) -> list[tuple[int, int, str, str]]:
    return [(d.line, d.col, d.severity, d.code) for d in lint(src, "t")]


@pytest.fixture
def no_query_parser(monkeypatch):
    monkeypatch.setattr(lint_mod, "query_parser", lambda: None)


def test_starter_templates_lint_clean():
    for name, src in STARTER_TEMPLATES.items():
        assert lint(src, name.removesuffix(".md")) == [], name


def test_known_names_fields_and_filters_are_clean():
    src = HEAD + (
        "{{person.link}} {{topic | upper}} {{date | format: D MMM}} {{now.date.iso}}\n"
        "{{user.name}} {{title}} {{project.name | default: none}} {{when.iso}} {{time}}\n"
    )
    assert lint(src, "t") == []


def test_unknown_name_is_a_warning_at_its_position_with_a_suggestion():
    src = HEAD + "line one\n  {{persn.name}}\n"
    [d] = lint(src, "t")
    assert (d.line, d.col, d.severity, d.code) == (BODY_LINE + 1, 3, "warning", "unknown-name")
    assert "`persn`" in d.message and "did you mean `person`?" in d.message


def test_unknown_field_lists_the_fields_of_the_owner():
    [d] = lint(HEAD + "{{person.email}}\n", "t")
    assert d.code == "unknown-field"
    assert "`person` has no field `email`; fields: link, name, path" in d.message


def test_field_of_a_text_value():
    [d] = lint(HEAD + "{{topic.name}}\n", "t")
    assert (d.code, d.message) == ("unknown-field", "`topic` has no fields")


def test_nested_field_owner_is_named_by_its_path():
    [d] = lint(HEAD + "{{now.date.year}}\n", "t")
    assert "`now.date` has no field `year`; fields: iso" in d.message


def test_filter_problems():
    src = HEAD + "{{topic | shout}}\n{{date | format}}\n{{topic | upper: x}}\n"
    assert found(src) == [
        (BODY_LINE, 1, "warning", "unknown-filter"),
        (BODY_LINE + 1, 1, "warning", "filter-arg"),
        (BODY_LINE + 2, 1, "warning", "filter-arg"),
    ]
    msgs = [d.message for d in lint(src, "t")]
    assert msgs[1] == "`format` needs an argument, e.g. {{date | format: D MMM YYYY}}"
    assert msgs[2] == "`upper` takes no argument"


def test_malformed_placeholder_is_flagged():
    [d] = lint(HEAD + "{{ topic + 1 }}\n", "t")
    assert (d.code, d.severity) == ("malformed", "warning")


def test_frontmatter_placeholders_use_whole_file_positions():
    src = '---\ntemplate:\n  name: T\n  file:\n    name: "{{date | format: YYYY}} {{persn}}"\n---\nbody\n'
    assert found(src) == [(5, 36, "warning", "unknown-name")]


def test_parse_errors_come_back_and_skip_placeholder_checks():
    src = "---\ntemplate:\n  name: [unclosed\n---\n{{nope}}\n"
    diags = lint(src, "t")
    assert diags and all(d.code == "yaml" for d in diags)


def test_crlf_source_keeps_line_numbers():
    src = (HEAD + "x\n{{nope}}\n").replace("\n", "\r\n")
    assert found(src) == [(BODY_LINE + 1, 1, "warning", "unknown-name")]


def test_output_is_capped(no_query_parser):
    src = HEAD + "{{nope}}\n" * (MAX_LINT_DIAGNOSTICS + 5)
    diags = lint(src, "t")
    assert len(diags) == MAX_LINT_DIAGNOSTICS + 1
    assert diags[-1].code == "truncated" and "5 more" in diags[-1].message


@pytest.mark.parametrize(
    "expr",
    [
        "person", "person.link", "person.nope", "topic.name", "nope", "date.iso", "date.nope",
        "now.date.iso", "user.name", "project.slug", "when.iso", "topic | shout",
        "date | format", "topic | upper: x", "topic | default: x", "topic | slug | upper",
        "context.name", "time | lower",
    ],
)
def test_lint_flags_exactly_what_render_leaves_literal(expr, no_query_parser):
    src = HEAD + "{{" + expr + "}}\n"
    flagged = bool(lint(src, "t"))
    note = render(parse_template(src, "t").template, ANSWERS, ENV)
    assert flagged == ("{{" + expr + "}}" in note.body), expr


# ── `title` is not in scope while file.name / file.folder render ───────────


def _with_file(name: str, folder: str = "Notes") -> str:
    return HEAD.replace(
        "  name: T\n", f'  name: T\n  file:\n    name: "{name}"\n    folder: "{folder}"\n'
    )


TITLE_MESSAGE = (
    "`title` is the note's title, made from file.name; it isn't available in file.name or file.folder"
)


def test_title_in_file_name_is_flagged():
    [d] = lint(_with_file("{{title}} {{topic}}") + "# {{title}}\n", "t")
    assert (d.line, d.col, d.severity, d.code, d.message) == (
        5, 12, "warning", "unknown-name", TITLE_MESSAGE)


def test_title_in_file_folder_is_flagged():
    [d] = lint(_with_file("{{topic}}", "Notes/{{title | slug}}") + "body\n", "t")
    assert (d.line, d.col, d.code, d.message) == (6, 20, "unknown-name", TITLE_MESSAGE)


def test_title_in_block_scalar_file_name_is_flagged():
    src = HEAD.replace("  name: T\n", "  name: T\n  file:\n    name: >-\n      Notes {{title}}\n")
    assert found(src + "body\n") == [(6, 13, "warning", "unknown-name")]


def test_title_in_the_body_and_other_frontmatter_is_clean():
    src = _with_file("{{topic}}").replace(
        '    folder: "Notes"\n', '    folder: "Notes"\n  frontmatter:\n    heading: "{{title}}"\n')
    assert lint(src + "# {{title}}\n", "t") == []


def test_render_leaves_title_literal_in_file_name_and_rejects_it_in_folder(no_query_parser):
    src = _with_file("{{title}} {{topic}}")
    assert lint(src, "t")
    note = render(parse_template(src, "t").template, ANSWERS, ENV)
    assert "{{title}}" in note.title
    src = _with_file("{{topic}}", "Notes/{{title}}")
    assert lint(src, "t")
    with pytest.raises(RenderError, match="unresolved placeholder"):
        render(parse_template(src, "t").template, ANSWERS, ENV)


# ── query blocks (C2) ──────────────────────────────────────────────────────


def _stub_parser(text: str):
    diags = []
    for n, line in enumerate(text.split("\n"), start=1):
        if line.startswith("bogus"):
            diags.append(Diagnostic(n, 1, "error", "unknown key `bogus`", "unknown-key"))
        if "{{" in line:
            diags.append(Diagnostic(n, 11, "error", "placeholder", "unresolved-placeholder"))
    return None, diags


def test_query_block_diagnostics_map_to_file_lines(monkeypatch):
    monkeypatch.setattr(lint_mod, "query_parser", lambda: _stub_parser)
    src = HEAD + "intro\n```query\ntype: action_item\nmentions: \"{{person.link}}\"\nbogus: 1\n```\n"
    assert found(src) == [(BODY_LINE + 4, 1, "error", "unknown-key")]


def test_unclosed_query_fence_is_a_warning(monkeypatch):
    monkeypatch.setattr(lint_mod, "query_parser", lambda: _stub_parser)
    assert found(HEAD + "```query\ntype: x\n") == [(BODY_LINE, 1, "warning", "unclosed-query")]


def test_other_fences_are_not_query_linted(monkeypatch):
    monkeypatch.setattr(lint_mod, "query_parser", lambda: _stub_parser)
    assert found(HEAD + "```text\nbogus: 1\n```\n") == []


def test_query_blocks_are_skipped_without_c2(no_query_parser):
    assert found(HEAD + "```query\nbogus: 1\n```\n") == []


def test_real_query_parser_flags_a_bad_key_in_a_template():
    pytest.importorskip("ghostbrain.templates.query")
    src = HEAD + '```query\ntype: action_item\nmentions: "{{person.link}}"\ncolour: red\n```\n'
    assert [(d.line, d.code) for d in lint(src, "t")] == [(BODY_LINE + 3, "unknown-key")]
