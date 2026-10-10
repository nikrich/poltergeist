"""render(): variables, typed fields, filters, literals, filing, frontmatter."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import yaml

from ghostbrain.templates.functions import VARIABLES
from ghostbrain.templates.parse import parse_template
from ghostbrain.templates.render import (
    AnswerError,
    RenderEnv,
    build_scope,
    render,
)
from ghostbrain.templates.values import ProjectValue

NOW = datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2)))
ENV = RenderEnv(
    now=NOW,
    default_context="work",
    contexts=("work", "personal"),
    projects={"work/alpha": ProjectValue("work/alpha", "Alpha", "alpha", "work")},
    user_name="Sam",
    person_title=lambda p: {"30-cross-context/people/alex.md": "Alex"}.get(p),
)
PROMPTS = """  prompts:
    - id: person
      ask: Who?
      type: person
    - id: focus
      ask: Focus?
      type: text
      optional: true
"""


def tpl(body: str, *, prompts: str = PROMPTS, file: str = "", fm: str = ""):
    src = f"---\ntemplate:\n  name: T\n{prompts}{file}{fm}---\n{body}"
    r = parse_template(src, "t")
    assert r.ok, r.diagnostics
    return r.template


ALEX = {"person": "30-cross-context/people/alex"}


def test_scope_covers_exactly_the_registry_variables():
    assert set(build_scope({}, ENV)) | {"title"} == {s.name for s in VARIABLES}


def test_variables_and_typed_fields():
    t = tpl("{{person.name}}|{{person.link}}|{{person.path}}|{{date.iso}}|{{time}}|{{user.name}}|{{context}}|{{now.iso}}")
    assert render(t, ALEX, ENV).body == (
        "Alex|[[30-cross-context/people/alex]]|30-cross-context/people/alex.md|2026-10-09|14:30|Sam|work"
        "|2026-10-09T14:30:00+02:00"
    )


def test_person_name_falls_back_to_humanized_stem():
    t = tpl("{{person.name}}")
    assert render(t, {"person": "30-cross-context/people/jo-ann-lee.md"}, ENV).body == "Jo Ann Lee"


def test_freeform_person_name_links_by_name():
    t = tpl("{{person.name}} {{person.link}} [{{person.path}}]")
    assert render(t, {"person": "Alex"}, ENV).body == "Alex [[Alex]] []"


def test_filters():
    t = tpl(
        "{{date | format: D MMM YYYY}}|{{date | format: dddd [the] D}}|{{now | format: HH:mm}}"
        "|{{focus | upper}}|{{focus | lower}}|{{focus | slug}}"
    )
    assert render(t, {**ALEX, "focus": "Hello World"}, ENV).body == (
        "9 Oct 2026|Friday the 9|14:30|HELLO WORLD|hello world|hello-world"
    )


def test_default_filter_and_quoted_arg():
    t = tpl('{{focus | default: n/a}}|{{focus | default: "a | b"}}')
    assert render(t, ALEX, ENV).body == "n/a|a | b"


def test_unknown_names_fields_and_filters_stay_literal():
    body = "{{nope}} {{person.age}} {{date | shout}} {{date | format}} {{ bad expr }}"
    assert render(tpl(body), ALEX, ENV).body == body


def test_unknown_fields_of_an_empty_value_stay_literal():
    # focus is an unanswered optional text prompt; project is the empty builtin.
    body = "{{focus.bogus}}|{{focus.name}}|[{{focus}}]|{{project.bogus}}|[{{project.name}}]|{{project.name.x}}"
    assert render(tpl(body), ALEX, ENV).body == (
        "{{focus.bogus}}|{{focus.name}}|[]|{{project.bogus}}|[]|{{project.name.x}}"
    )


def test_prompt_default_and_required():
    prompts = (
        "  prompts:\n    - id: status\n      ask: Status\n      type: choice\n"
        "      options: [proposed, accepted]\n      default: accepted\n"
        "    - id: who\n      ask: Who?\n      type: text\n"
    )
    t = tpl("{{status}} {{who}}", prompts=prompts)
    assert render(t, {"who": "x"}, ENV).body == "accepted x"
    with pytest.raises(AnswerError) as e:
        render(t, {}, ENV)
    assert e.value.field == "who" and "required" in str(e.value)
    with pytest.raises(AnswerError) as e:
        render(t, {"who": "x", "status": "maybe"}, ENV)
    assert e.value.field == "status"


@pytest.mark.parametrize(
    "answers, field",
    [
        ({**ALEX, "colour": "red"}, "colour"),
        ({**ALEX, "date": "9 Oct"}, "date"),
        ({**ALEX, "context": "nowhere"}, "context"),
        ({**ALEX, "project": "work/ghost"}, "project"),
        ({"person": "Al [[x]]"}, "person"),
        ({**ALEX, "focus": "x" * 10_001}, "focus"),
    ],
)
def test_bad_answers_name_their_field(answers, field):
    with pytest.raises(AnswerError) as e:
        render(tpl("{{focus}}"), answers, ENV)
    assert e.value.field == field


def test_implicit_context_project_and_date_answers():
    t = tpl("{{context}} {{project.name}} {{project.path}} {{date | format: D MMM}}",
            file='  file:\n    folder: "20-contexts/{{context}}/x"\n')
    note = render(t, {**ALEX, "context": "personal", "project": "work/alpha", "date": "2026-12-01"}, ENV)
    assert note.body == "personal Alpha 20-contexts/work/projects/alpha 1 Dec"
    assert note.folder == "20-contexts/personal/x"


def test_unanswered_optional_typed_prompt_is_empty_everywhere():
    prompts = "  prompts:\n    - id: project\n      ask: P\n      type: project\n      optional: true\n"
    t = tpl("[{{project.name}}] [{{project.name | default: none}}]", prompts=prompts)
    assert render(t, {}, ENV).body == "[] [none]"


def test_title_is_the_rendered_name_and_literal_inside_it():
    t = tpl("# {{title}}", file='  file:\n    name: "{{date | format: YYYY-MM-DD}} {{person.name}} {{title}}"\n')
    note = render(t, ALEX, ENV)
    assert note.title == "2026-10-09 Alex {{title}}"
    assert note.body == "# 2026-10-09 Alex {{title}}"


def test_filing_folder_filename_and_path():
    t = tpl("x", file='  file:\n    folder: "20-contexts/{{context}}/one-on-ones"\n'
                      '    name: "{{date | format: YYYY-MM-DD}} {{person.name}} 1-1"\n')
    note = render(t, ALEX, ENV)
    assert (note.folder, note.filename, note.title) == (
        "20-contexts/work/one-on-ones", "2026-10-09-alex-1-1.md", "2026-10-09 Alex 1-1")
    assert note.path == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md"


def test_long_titles_cap_the_filename_at_80():
    t = tpl("x", file='  file:\n    name: "{{focus}}"\n')
    note = render(t, {**ALEX, "focus": "word " * 40}, ENV)
    # 80-char cut lands on a dash, which is then stripped (make_slug rule).
    assert note.filename == ("word-" * 16).rstrip("-") + ".md"
    assert note.title == ("word " * 40).strip()


def test_punctuation_only_title_slugs_to_untitled():
    t = tpl("x", file='  file:\n    name: "{{focus}}"\n')
    assert render(t, {**ALEX, "focus": "???"}, ENV).filename == "untitled.md"
    note = render(t, {**ALEX, "focus": "Ünïcödé ✓"}, ENV)
    assert note.filename == "n-c-d.md" and note.title == "Ünïcödé ✓"


def test_frontmatter_defaults_rendering_and_markdown():
    fm = ('  frontmatter:\n    type: meeting\n    attendees: ["{{person.link}}"]\n'
          '    meta: {who: "{{person.name}}", n: 3, ok: true}\n    title: Custom\n'
          '    fromTemplate: hijack\n')
    note = render(tpl("Body {{person.name}}\n", fm=fm), ALEX, ENV)
    assert note.frontmatter == {
        "title": "Custom",
        "created": "2026-10-09T14:30:00+02:00",
        "updated": "2026-10-09T14:30:00+02:00",
        "type": "meeting",
        "attendees": ["[[30-cross-context/people/alex]]"],
        "meta": {"who": "Alex", "n": 3, "ok": True},
        "fromTemplate": "t",
    }
    text = note.markdown()
    assert text.startswith("---\n")
    head, body = text[4:].split("---\n\n", 1)
    assert yaml.safe_load(head) == note.frontmatter
    assert body == "Body Alex\n"


def test_placeholders_inside_query_fences_are_resolved():
    body = '```query\ntype: action_item\nmentions: "{{person.link}}"\nstatus: open\n```\n'
    assert render(tpl(body), ALEX, ENV).body == (
        '```query\ntype: action_item\nmentions: "[[30-cross-context/people/alex]]"\nstatus: open\n```\n'
    )
