"""parse_template: valid, defaults, missing fields, bad prompt types, line numbers."""
from __future__ import annotations

from ghostbrain.templates.parse import parse_template

VALID = """---
template:
  name: 1-1
  description: Weekly 1-1
  prompts:
    - id: person
      ask: "Who's this 1-1 with?"
      type: person
    - id: focus
      ask: Anything specific?
      type: text
      optional: true
  file:
    folder: "20-contexts/{{context}}/one-on-ones"
    name: "{{date | format: YYYY-MM-DD}} {{person.name}} 1-1"
  frontmatter:
    type: meeting
    attendees: ["{{person.link}}"]
---
# 1-1 with {{person.link}}

{{focus}}
"""


def _codes(result):
    return [d.code for d in result.diagnostics]


def test_valid_template_parses():
    r = parse_template(VALID, "one-on-one")
    assert r.ok and r.diagnostics == ()
    t = r.template
    assert (t.id, t.name, t.description) == ("one-on-one", "1-1", "Weekly 1-1")
    assert [p.id for p in t.prompts] == ["person", "focus"]
    assert t.prompts[0].type == "person" and t.prompts[1].optional is True
    assert t.file.folder == "20-contexts/{{context}}/one-on-ones"
    assert t.file.name == "{{date | format: YYYY-MM-DD}} {{person.name}} 1-1"
    assert t.frontmatter == {"type": "meeting", "attendees": ["{{person.link}}"]}
    assert t.body == "# 1-1 with {{person.link}}\n\n{{focus}}\n"
    assert t.body_line == 20
    assert t.variables == ("context", "date", "focus", "person")


def test_defaults_for_minimal_template():
    t = parse_template("---\ntemplate:\n  name: Scratch\n---\nhello\n", "scratch").template
    assert t.prompts == () and t.frontmatter == {} and t.description == ""
    assert t.file.folder == "20-contexts/{{context}}/notes"
    assert t.file.name == "{{date | format: YYYY-MM-DD}} Scratch"
    assert t.variables == ("context", "date")


def test_choice_prompt_keeps_options_and_default():
    src = (
        "---\ntemplate:\n  name: D\n  prompts:\n    - id: status\n      ask: Status\n"
        "      type: choice\n      options: [proposed, accepted]\n      default: accepted\n---\n"
    )
    p = parse_template(src, "d").template.prompts[0]
    assert p.options == ("proposed", "accepted") and p.default == "accepted"
    assert p.to_json() == {
        "id": "status", "ask": "Status", "type": "choice", "optional": False,
        "default": "accepted", "options": ["proposed", "accepted"],
    }


def test_missing_name_points_at_template_key():
    r = parse_template("---\ntemplate:\n  description: x\n---\n", "t")
    assert not r.ok and _codes(r) == ["schema"]
    d = r.diagnostics[0]
    assert (d.line, d.col, d.severity) == (2, 1, "error")
    assert "template.name" in d.message and "Field required" in d.message


def test_bad_prompt_type_has_line_and_col():
    src = (
        "---\ntemplate:\n  name: Bad\n  prompts:\n    - id: who\n      ask: Who?\n"
        "      type: email\n---\nbody\n"
    )
    r = parse_template(src, "bad")
    assert not r.ok
    d = r.diagnostics[0]
    assert (d.line, d.col) == (7, 7)
    assert "template.prompts.0.type" in d.message


def test_choice_without_options_and_options_on_text():
    no_opts = "---\ntemplate:\n  name: X\n  prompts:\n    - id: s\n      ask: S\n      type: choice\n---\n"
    assert "needs `options`" in parse_template(no_opts, "x").diagnostics[0].message
    stray = (
        "---\ntemplate:\n  name: X\n  prompts:\n    - id: s\n      ask: S\n      type: text\n"
        "      options: [a]\n---\n"
    )
    assert "only allowed on choice" in parse_template(stray, "x").diagnostics[0].message


def test_duplicate_prompt_id_points_at_second():
    src = (
        "---\ntemplate:\n  name: Dup\n  prompts:\n    - id: who\n      ask: A\n      type: text\n"
        "    - id: who\n      ask: B\n      type: text\n---\n"
    )
    r = parse_template(src, "dup")
    assert _codes(r) == ["prompt-id"]
    assert (r.diagnostics[0].line, r.diagnostics[0].col) == (8, 7)


def test_reserved_and_shadowed_prompt_ids():
    reserved = "---\ntemplate:\n  name: X\n  prompts:\n    - id: title\n      ask: T\n      type: text\n---\n"
    assert "built-in" in parse_template(reserved, "x").diagnostics[0].message
    wrong = "---\ntemplate:\n  name: X\n  prompts:\n    - id: date\n      ask: When\n      type: text\n---\n"
    assert "must have type date" in parse_template(wrong, "x").diagnostics[0].message
    ok = "---\ntemplate:\n  name: X\n  prompts:\n    - id: date\n      ask: When\n      type: date\n---\n"
    assert parse_template(ok, "x").ok


def test_unknown_key_is_an_error():
    r = parse_template("---\ntemplate:\n  name: X\n  colour: red\n---\n", "x")
    assert "Extra inputs are not permitted" in r.diagnostics[0].message
    assert r.diagnostics[0].line == 4


def test_not_a_template():
    assert _codes(parse_template("# just markdown\n", "x")) == ["no-frontmatter"]
    assert _codes(parse_template("---\ntitle: x\n---\nbody\n", "x")) == ["no-template"]


def test_yaml_error_is_line_numbered():
    r = parse_template("---\ntemplate:\n  name: [unclosed\n---\n", "x")
    assert _codes(r) == ["yaml"] and r.diagnostics[0].line >= 2


def test_top_level_extra_key_is_only_a_warning():
    r = parse_template("---\ntags: [a]\ntemplate:\n  name: X\n---\n", "x")
    assert r.ok
    assert [(d.code, d.severity, d.line) for d in r.diagnostics] == [("ignored-key", "warning", 2)]


def test_crlf_template_parses_with_lf_and_right_lines():
    r = parse_template(VALID.replace("\n", "\r\n"), "one-on-one")
    assert r.ok
    t = r.template
    assert t.body == "# 1-1 with {{person.link}}\n\n{{focus}}\n"
    assert t.body_line == 20
    assert t.prompts[0].ask == "Who's this 1-1 with?"
    bad = (
        "---\r\ntemplate:\r\n  name: Bad\r\n  prompts:\r\n    - id: who\r\n      ask: Who?\r\n"
        "      type: email\r\n---\r\nbody\r\n"
    )
    d = parse_template(bad, "bad").diagnostics[0]
    assert (d.line, d.col) == (7, 7)


def test_defaults_and_options_are_coerced_to_text():
    src = (
        "---\ntemplate:\n  name: X\n  prompts:\n    - id: date\n      ask: When\n"
        "      type: date\n      default: 2026-10-09\n    - id: n\n      ask: N\n"
        "      type: choice\n      options: [1, 2, true]\n      default: 2\n---\n"
    )
    r = parse_template(src, "x")
    assert r.ok, r.diagnostics
    date_p, n_p = r.template.prompts
    assert date_p.default == "2026-10-09"
    assert n_p.options == ("1", "2", "true") and n_p.default == "2"


def test_yaml11_boolean_spellings_are_kept():
    src = (
        "---\ntemplate:\n  name: X\n  prompts:\n    - id: go\n      ask: Go?\n"
        "      type: choice\n      options: [yes, no, On]\n      default: no\n"
        "    - id: note\n      ask: Note\n      type: text\n      default: off\n---\n"
    )
    r = parse_template(src, "x")
    assert r.ok, r.diagnostics
    go, note = r.template.prompts
    assert go.options == ("yes", "no", "On") and go.default == "no"
    assert note.default == "off"
