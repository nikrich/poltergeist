"""AI template drafting (C4): prompt, extraction, validation, one repair turn."""
from __future__ import annotations

import pytest

from ghostbrain.templates import generate
from ghostbrain.templates.functions import FIELDS, FILTERS, PROMPT_TYPES, VARIABLES
from ghostbrain.templates.generate import (
    MAX_DRAFT_CHARS,
    TEMPLATE_TOOLS,
    DraftInvalid,
    GenerateError,
    build_prompt,
    check_draft,
    draft_template,
    extract_draft,
    run_turn,
    system_prompt,
)
from ghostbrain.templates.starters import STARTER_TEMPLATES

GOOD = """---
template:
  name: Standup
  description: Daily standup notes
  prompts:
    - id: team
      ask: Which team?
      type: text
  file:
    folder: "20-contexts/{{context}}/standups"
    name: "{{date | format: YYYY-MM-DD}} {{team}} standup"
---
# {{team}} standup — {{date | format: D MMM}}

## Blockers

```query
type: action_item
status: open
```
"""


def codes(draft: str) -> list[str]:
    return [d.code for d in check_draft(draft).problems]


def test_system_prompt_documents_every_registry_entry_and_the_rules():
    text = system_prompt()
    for spec in (*VARIABLES, *FILTERS, *PROMPT_TYPES):
        assert f"- {spec.name}" in text
    for spec in FIELDS:
        assert f"- {spec.owner}.{spec.name}:" in text
    assert "never under 90-meta" in text and "---" in text


def test_build_prompt_fences_the_request_as_data():
    p = build_prompt("  weekly review with Alex  ")
    assert p.endswith("<<<\nweekly review with Alex\n>>>")


@pytest.mark.parametrize(
    "answer",
    [
        GOOD,
        "```markdown\n" + GOOD + "```",
        "```\n" + GOOD + "```\n",
        "Here is your template:\n\n" + GOOD,
        GOOD.replace("\n", "\r\n"),
    ],
)
def test_extract_draft_unwraps_the_file(answer):
    assert extract_draft(answer) == GOOD


def test_good_draft_and_every_starter_pass():
    assert check_draft(GOOD).ok
    for src in STARTER_TEMPLATES.values():
        assert check_draft(src).ok


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (("name: Standup", "name: [oops"), "yaml"),
        (("## Blockers", '<script src="x.js"></script>'), "forbidden"),
        (("## Blockers", '<img src="x" onerror="alert(1)">'), "forbidden"),
        (("## Blockers", "[x](javascript:alert(1))"), "forbidden"),
        (("```query", "```js"), "forbidden"),
        (("```query", "```dataviewjs"), "forbidden"),
        (("# {{team}}", "# {{teem}}"), "unknown-placeholder"),
        (("# {{team}}", "# {{team.name}}"), "unknown-placeholder"),
        (("# {{team}}", "# {{team | shout}}"), "unknown-placeholder"),
        (('"20-contexts/{{context}}/standups"', '"../../outside"'), "render"),
        (('"20-contexts/{{context}}/standups"', '"90-meta/templates"'), "render"),
    ],
)
def test_bad_drafts_are_rejected_with_a_located_problem(change, code):
    draft = GOOD.replace(*change)
    assert draft != GOOD
    found = check_draft(draft)
    assert not found.ok
    assert code in [d.code for d in found.problems]
    assert all(d.line >= 1 and d.severity == "error" for d in found.problems)


def test_oversize_draft_is_rejected():
    assert codes(GOOD + "x" * MAX_DRAFT_CHARS) == ["too-long"]


def test_mermaid_and_plain_fences_are_allowed():
    draft = GOOD.replace("## Blockers", "```mermaid\ngraph TD; A-->B\n```\n\n```\nplain\n```")
    assert check_draft(draft).ok


def test_valid_first_draft_needs_one_turn():
    calls = []

    def turn(prompt, *, turn_key):
        calls.append((prompt, turn_key))
        return GOOD

    d = draft_template("standup notes", turn=turn)
    assert d.source == GOOD and d.template.name == "Standup"
    assert len(calls) == 1 and calls[0][1].startswith("templates:generate:")


def test_invalid_draft_gets_one_repair_turn_with_the_problems():
    answers = iter([GOOD.replace("# {{team}}", "# {{teem}}"), GOOD])
    prompts = []

    def turn(prompt, *, turn_key):
        prompts.append(prompt)
        return next(answers)

    assert draft_template("standup", turn=turn).source == GOOD
    assert len(prompts) == 2
    assert "is not a known placeholder" in prompts[1] and "{{teem}}" in prompts[1]


def test_invalid_twice_raises_with_the_last_draft():
    bad = GOOD.replace("## Blockers", "<script>x</script>")
    with pytest.raises(DraftInvalid) as e:
        draft_template("standup", turn=lambda prompt, *, turn_key: bad)
    assert e.value.draft == bad
    assert e.value.problems[0].code == "forbidden"
    assert str(e.value).startswith("the draft is not a valid template (line ")


class _Provider:
    def __init__(self, events):
        self.events = events
        self.requests = []

    def chat(self, req):
        self.requests.append(req)
        yield from self.events


def test_run_turn_is_read_only_and_uses_no_user_servers(monkeypatch):
    provider = _Provider([{"type": "delta", "text": "---"}, {"type": "done", "text": GOOD}])
    monkeypatch.setattr("ghostbrain.llm.providers.get_provider", lambda cfg=None: provider)
    assert run_turn("p", turn_key="k") == GOOD
    [req] = provider.requests
    assert req.user_servers == [] and req.session_id is None
    assert req.allowed_tools == TEMPLATE_TOOLS
    assert "poltergeist_write_doc" not in req.allowed_tools and "poltergeist_ask" not in req.allowed_tools
    assert req.system_prompt == system_prompt()


def test_run_turn_falls_back_to_deltas_and_reports_errors(monkeypatch):
    provider = _Provider([{"type": "delta", "text": "a"}, {"type": "delta", "text": "b"},
                          {"type": "done", "text": ""}])
    monkeypatch.setattr("ghostbrain.llm.providers.get_provider", lambda cfg=None: provider)
    assert run_turn("p", turn_key="k") == "ab"
    monkeypatch.setattr("ghostbrain.llm.providers.get_provider",
                        lambda cfg=None: _Provider([{"type": "error", "message": "rate limited"}]))
    with pytest.raises(GenerateError, match="rate limited"):
        run_turn("p", turn_key="k")
    monkeypatch.setattr("ghostbrain.llm.providers.get_provider",
                        lambda cfg=None: _Provider([{"type": "done", "text": "  "}]))
    with pytest.raises(GenerateError, match="nothing"):
        run_turn("p", turn_key="k")


def test_draft_template_uses_run_turn_by_default(monkeypatch):
    monkeypatch.setattr(generate, "run_turn", lambda prompt, *, turn_key: GOOD)
    assert draft_template("x").source == GOOD


@pytest.mark.parametrize(
    "html",
    ["<div>hi</div>", '<img src="x">', "<!-- note -->", "text <b>bold</b> text"],
)
def test_raw_html_is_rejected(html):
    found = check_draft(GOOD.replace("## Blockers", html))
    assert not found.ok
    [problem] = [d for d in found.problems if d.code == "forbidden"]
    assert problem.severity == "error"
    assert problem.line == GOOD.split("\n").index("## Blockers") + 1


def test_html_already_flagged_is_reported_once_per_line():
    found = check_draft(GOOD.replace("## Blockers", "<script>x</script>"))
    assert [d.code for d in found.problems] == ["forbidden"]


def test_html_inside_a_code_fence_is_inert():
    draft = GOOD.replace("## Blockers", "```\n<div>shown as text</div>\n```")
    assert check_draft(draft).ok


@pytest.mark.parametrize(
    "image",
    [
        "![](https://example.com/p.png?{{team}})",
        "![chart](http://example.com/c.png)",
        "![x](//example.com/x.png)",
        "![x]( <https://example.com/x.png> )",
        "![x][logo]\n\n[logo]: https://example.com/logo.png",
        "![logo]\n\n[LOGO]: //example.com/logo.png",
    ],
)
def test_remote_images_are_rejected(image):
    found = check_draft(GOOD.replace("## Blockers", image))
    assert not found.ok
    problems = [d for d in found.problems if d.code == "forbidden"]
    assert problems and all(d.severity == "error" for d in problems)
    assert "remote images are not allowed" in problems[0].message
    assert problems[0].line == GOOD.split("\n").index("## Blockers") + 1


def test_links_and_local_images_are_allowed():
    draft = GOOD.replace(
        "## Blockers",
        "[docs](https://example.com)\n\n![local](attachments/x.png)\n\n"
        "[ref]: https://example.com/page",
    )
    assert check_draft(draft).ok
