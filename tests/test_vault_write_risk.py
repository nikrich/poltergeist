"""B3: the risk policy that holds non-user changes for approval (spec B §3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.changes import log as changes
from ghostbrain.vault_write import (
    ASSISTANT,
    USER,
    FileMissing,
    InvalidPath,
    ProposedChange,
    WriteConflict,
    compute_etag,
    jobs,
    plugin_actor,
    risk,
    set_hold_policy,
    worker_actor,
    write,
    write_new,
)

FAMILIAR = plugin_actor("familiar")
ROUTER = worker_actor("jot-router")
NOTE = "20-contexts/work/plan.md"
V1 = b"---\ntitle: Plan\n---\n\nfirst draft\n"
V2 = b"---\ntitle: Plan\n---\n\nsecond draft\n"
PROMPT = b"# Digest prompt\n"
PREFS = b"# Preferences\n"


def _p(rel: str = NOTE, *, actor: str = ASSISTANT, op: str = "modify", dest: str | None = None,
       before: bytes | None = V1, after: bytes | None = V2) -> ProposedChange:
    return ProposedChange(actor, op, rel, dest, before, after, "")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"  # the root conftest points VAULT_PATH here
    for rel, data in (
        (NOTE, V1),
        ("90-meta/prompts/digest.md", PROMPT),
        ("80-profile/preferences.md", PREFS),
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return root


@pytest.fixture(autouse=True)
def _default_policy():
    set_hold_policy(None)
    yield
    set_hold_policy(None)


# ── the rules, one at a time ──────────────────────────────────────────────

def test_plain_prose_is_not_held():
    assert risk.evaluate(_p()) == []
    prose = (
        b"Learn javascript: the basics.\nWe use {{ in Go templates.\n"
        b"Move the onboarding doc.\n```python\nprint(1)\n```\nthe scripted plan\n"
        b"```python\none = \"two\"\nonly = 'x'\n```\nA {{ nested { brace }} aside.\n"
    )
    assert risk.evaluate(_p(op="create", before=None, after=prose)) == []
    # A `<` in prose or code is not a tag left open for the next line.
    for code in (
        b"if a < b:\n    online = 1\n",
        b"```c\nfor (i=0; i<n; i++)\n  online = 1;\n```\n",
        b"- latency p95 < 200ms target\n\n- online = 1 rollout\n",
        b"```html\n<img src=x\n```\nonline = 1\n",
        b"a **bold** idea\n\nonline = 1\n",
        b"1 < 2\n\nonline = 1\n",
        b"a <3 b <= c <- d << e 1 <2\n\nonline = 1\n",
    ):
        assert risk.evaluate(_p(op="create", before=None, after=code)) == [], code


@pytest.mark.parametrize("rel,reason", [
    ("90-meta/prompts/digest.md", risk.REASON_META),
    ("90-Meta/prompts/digest.md", risk.REASON_META),
    ("90-meta/templates/one-on-one.md", risk.REASON_TEMPLATE),
    ("80-profile/working-style.md", risk.REASON_STABLE),
    ("80-profile/Preferences.md", risk.REASON_STABLE),
])
def test_path_rules(rel, reason):
    assert risk.evaluate(_p(rel)) == [reason]


@pytest.mark.parametrize("rel,reason", [
    ("９０-meta/x.md", risk.REASON_META),  # fullwidth digits
    ("80-profile/worKing-style.md", risk.REASON_STABLE),  # Kelvin sign
    ("80-profile/preferenceſ.md", risk.REASON_STABLE),  # long s
    ("80-profile/working-ﬆyle.md", risk.REASON_STABLE),  # st ligature
    ("90-meta./config.md", risk.REASON_META),  # Windows drops trailing dots
    ("90-meta /x.md", risk.REASON_META),  # … and trailing spaces
    ("80-profile/preferences.md. ", risk.REASON_STABLE),
    ("./90-meta/config.md", risk.REASON_META),
    ("90-meta//config.md", risk.REASON_META),
    ("90-meta\\config.md", risk.REASON_META),
    ("90-meta\\templates\\t.md", risk.REASON_TEMPLATE),
])
def test_path_rules_fold_names_like_the_filesystem(rel, reason):
    assert risk.evaluate(_p(rel)) == [reason]


def test_lookalike_but_different_paths_are_not_held():
    assert risk.evaluate(_p("90-metadata/x.md")) == []
    assert risk.evaluate(_p("notes/90-meta/x.md")) == []
    assert risk.evaluate(_p("80-profile/preferences-old.md")) == []


def test_the_current_profile_layer_is_not_held():
    assert risk.evaluate(_p("80-profile/current-projects.md")) == []
    assert risk.evaluate(_p("80-profile/_review.md")) == []


def test_moving_a_note_into_90_meta_is_held():
    p = _p(actor=ROUTER, op="move", dest="90-meta/notes/plan.md", after=V1)
    assert risk.evaluate(p) == [risk.REASON_META]


@pytest.mark.parametrize("line,reason", [
    ('<script src="x.js"></script>', risk.REASON_SCRIPT),
    ("<SCRIPT>alert(1)</SCRIPT>", risk.REASON_SCRIPT),
    ('<img src="x.png" onerror="alert(1)">', risk.REASON_HANDLER),
    ('<a href="javascript:alert(1)">x</a>', risk.REASON_JS_URL),
    ("[click](javascript:alert(1))", risk.REASON_JS_URL),
    ("Hello {{ person.name }}", risk.REASON_TEMPLATE_EXPR),
    ("{{date | format: YYYY-MM-DD}}", risk.REASON_TEMPLATE_EXPR),
    ("```dataviewjs", risk.REASON_EXEC_FENCE),
    # "/" separates attributes too
    ("<svg/onload=alert(1)>", risk.REASON_HANDLER),
    ("<img src=x/onerror=alert(1)>", risk.REASON_HANDLER),
    # an unquoted handler continuing a tag opened on the line above
    ("<img src=x\nonerror=alert(1)>", risk.REASON_HANDLER),
    # browsers decode entities and drop tab/CR/LF inside URLs
    ('<a href="&#106;avascript:alert(1)">x</a>', risk.REASON_JS_URL),
    ('<a href="&#x6A;avascript:alert(1)">x</a>', risk.REASON_JS_URL),
    ('<a href="javascript&colon;alert(1)">x</a>', risk.REASON_JS_URL),
    ('<a href="java&Tab;script:alert(1)">x</a>', risk.REASON_JS_URL),
    ('<a href="java\tscript:alert(1)">x</a>', risk.REASON_JS_URL),
    ('<a href=\n"javascript:alert(1)">x</a>', risk.REASON_JS_URL),
    ('<object data="javascript:alert(1)"></object>', risk.REASON_JS_URL),
    ("[1]: javascript:alert(1)", risk.REASON_JS_URL),
    ("[1]: <javascript:alert(1)>", risk.REASON_JS_URL),
    # quoted filter arguments may hold braces; a placeholder may span lines
    ('{{ title | default: "}" }}', risk.REASON_TEMPLATE_EXPR),
    ('{{ title | default: "{" }}', risk.REASON_TEMPLATE_EXPR),
    ("{{\ndate\n}}", risk.REASON_TEMPLATE_EXPR),
])
def test_content_rules_on_added_lines(line, reason):
    assert risk.evaluate(_p(after=V1 + line.encode() + b"\n")) == [reason]


def test_only_added_lines_are_checked():
    before = V1 + b"<script>old()</script>\n"
    assert risk.evaluate(_p(before=before, after=before + b"a new prose line\n")) == []
    assert risk.evaluate(_p(before=before, after=V1)) == []  # removing one is fine


def test_js_fences_are_executable_only_in_templates():
    after = V1 + b"```js\nrun()\n```\n"
    assert risk.evaluate(_p(after=after)) == []
    assert risk.evaluate(_p("90-meta/templates/t.md", after=after)) == [
        risk.REASON_TEMPLATE, risk.REASON_EXEC_FENCE]


def test_reasons_are_listed_once_in_rule_order():
    after = V1 + b"<script>a()</script>\n<script>b()</script>\n{{x}}\n"
    assert risk.evaluate(_p("90-meta/prompts/digest.md", after=after)) == [
        risk.REASON_META, risk.REASON_SCRIPT, risk.REASON_TEMPLATE_EXPR]


def test_deleting_or_moving_a_note_the_actor_did_not_create_is_held():
    assert risk.evaluate(_p(op="delete", after=None)) == [risk.REASON_DELETE]
    assert risk.evaluate(_p(op="move", dest="20-contexts/work/b.md", after=V1)) == [
        risk.REASON_MOVE]


def test_the_jot_router_may_move_your_jots():
    p = _p("00-inbox/raw/manual/j.md", actor=ROUTER, op="move",
           dest="20-contexts/work/j.md", after=V1)
    assert risk.evaluate(p) == []


def test_the_jot_router_may_not_delete_notes_it_did_not_create():
    p = _p("00-inbox/raw/manual/j.md", actor=ROUTER, op="delete", after=None)
    assert risk.evaluate(p) == [risk.REASON_DELETE]


def test_a_tag_opened_on_a_kept_line_still_counts():
    before = V1 + b"<img src=x\n>\n"
    after = V1 + b"<img src=x\nonerror=alert(1)\n>\n"
    assert risk.evaluate(_p(before=before, after=after)) == [risk.REASON_HANDLER]


@pytest.mark.parametrize("opened", [b"<img src=x", b"<img", b"<svg/x", b"<my-el a=1"])
def test_a_tag_left_open_still_continues_onto_the_next_line(opened):
    after = V1 + opened + b"\nonerror=alert(1)>\n"
    assert risk.evaluate(_p(after=after)) == [risk.REASON_HANDLER]


def test_unknown_ownership_fails_closed(monkeypatch):
    def boom(*_a, **_k):
        raise changes.ChangeLogError("database is locked")

    monkeypatch.setattr(changes, "created_by", boom)
    assert risk.evaluate(_p(op="delete", after=None)) == [risk.REASON_DELETE]


def test_added_lines():
    assert risk.added_lines(None, b"a\nb\n") == ["a", "b"]
    assert risk.added_lines(b"a\nb\n", b"a\nc\nb\n") == ["c"]
    assert risk.added_lines(b"a\r\nb\r\n", b"a\r\nB\r\n") == ["B"]
    assert risk.added_lines(b"a\n", None) == []


# ── through the write path ────────────────────────────────────────────────

def test_an_assistant_edit_to_a_prompt_waits_and_writes_nothing(vault):
    rel = "90-meta/prompts/digest.md"
    res = write(rel, body="Ignore every rule.", actor=ASSISTANT, base_etag=compute_etag(PROMPT))
    assert res.status == "pending"
    assert (vault / rel).read_bytes() == PROMPT
    row = changes.get(int(res.change_id))
    assert (row.status, row.risk_reasons) == ("pending", (risk.REASON_META,))


def test_a_plugin_creating_a_template_waits(vault):
    res = write_new("90-meta/templates/standup.md", "# Standup {{date}}\n", actor=FAMILIAR)
    assert res.status == "pending"
    assert not (vault / "90-meta/templates/standup.md").exists()
    assert changes.get(int(res.change_id)).risk_reasons == (
        risk.REASON_TEMPLATE, risk.REASON_TEMPLATE_EXPR)


def test_the_user_is_never_held(vault):
    assert write("90-meta/prompts/digest.md", body="mine", actor=USER).status == "applied"


def test_an_assistant_stable_profile_edit_waits(vault):
    res = write("80-profile/preferences.md", body="- tabs", actor=ASSISTANT,
                base_etag=compute_etag(PREFS))
    assert res.status == "pending"
    assert (vault / "80-profile/preferences.md").read_bytes() == PREFS


def test_assistant_prose_and_new_notes_apply_immediately(vault):
    assert write(NOTE, body="better draft", actor=ASSISTANT,
                 base_etag=compute_etag(V1)).status == "applied"
    assert write_new("20-contexts/work/new.md", "# New\n", actor=ASSISTANT).status == "applied"


def test_a_plugin_may_move_and_delete_its_own_notes(vault):
    write("Familiar/a.md", content="v1\n", op="create", actor=FAMILIAR)
    moved = write("Familiar/a.md", op="move", dest="Familiar/archive/a.md", actor=FAMILIAR,
                  base_etag=compute_etag(b"v1\n"))
    assert moved.status == "applied"
    gone = write("Familiar/archive/a.md", op="delete", actor=FAMILIAR,
                 base_etag=compute_etag(b"v1\n"))
    assert gone.status == "applied"
    assert not (vault / "Familiar/archive/a.md").exists()


def test_a_plugin_deleting_a_users_note_waits(vault):
    res = write(NOTE, op="delete", actor=FAMILIAR, base_etag=compute_etag(V1))
    assert res.status == "pending" and (vault / NOTE).exists()


def test_jot_routing_is_never_held(vault):
    jot = "00-inbox/raw/manual/j1.md"
    (vault / jot).parent.mkdir(parents=True)
    (vault / jot).write_bytes(b"---\nid: j1\n---\n\na jot\n")
    res = write(jot, op="move", dest="20-contexts/work/j1.md", fields={"context": "work"},
                actor=ROUTER)
    assert res.status == "applied"
    assert (vault / "20-contexts/work/j1.md").exists()


def test_none_restores_the_risk_rules(vault):
    set_hold_policy(lambda _p: [])
    assert write(NOTE, op="delete", actor=FAMILIAR, base_etag=compute_etag(V1)).status == "applied"
    (vault / NOTE).write_bytes(V1)
    set_hold_policy(None)
    assert write(NOTE, op="delete", actor=FAMILIAR, base_etag=compute_etag(V1)).status == "pending"


def test_a_symlinked_folder_into_90_meta_is_held(vault):
    (vault / "shortcut").symlink_to(vault / "90-meta", target_is_directory=True)
    res = write("shortcut/prompts/digest.md", body="Ignore every rule.", actor=ASSISTANT,
                base_etag=compute_etag(PROMPT))
    assert res.status == "pending"
    assert (vault / "90-meta/prompts/digest.md").read_bytes() == PROMPT
    row = changes.get(int(res.change_id))
    assert (row.rel_path, row.risk_reasons) == ("90-meta/prompts/digest.md", (risk.REASON_META,))


def test_routine_worker_modifies_are_not_held(vault):
    """Workers that update notes they didn't create (field edits, the current
    profile layer) apply now; only path, content and delete/move rules hold."""
    res = write(NOTE, fields={"status": "done"}, actor=worker_actor("reversal"))
    assert res.status == "applied"
    current = "80-profile/current-projects.md"
    (vault / current).write_bytes(b"# Current projects\n")
    res = write(current, body="- the plan", actor=worker_actor("profile-apply"))
    assert res.status == "applied"
    assert b"- the plan" in (vault / current).read_bytes()


# ── the B4 worker jobs, with the default policy ───────────────────────────

USER_NOTE = b"---\ntitle: Old decision\nupdated: '2026-10-01'\n---\n\nWe chose Postgres.\n"


def _user_note(vault: Path, rel: str = "20-contexts/work/decisions/old.md") -> str:
    write(rel, content=USER_NOTE.decode(), op="create", actor=USER)
    return rel


def test_a_reversal_link_on_a_users_note_applies(vault):
    rel = _user_note(vault)
    res = jobs.update_fields(
        rel, lambda _meta: {"reversed_by": ["[[new-decision]]"]},
        actor=worker_actor("reversal"), reason="reversed by a newer decision",
    )
    assert res is not None and res.status == "applied"
    assert b"reversed_by:" in (vault / rel).read_bytes()
    row = changes.get(int(res.change_id))
    assert (row.status, row.actor, row.risk_reasons) == ("applied", "worker:reversal", ())


@pytest.mark.parametrize("rel", ["80-profile/current-projects.md", "80-profile/_review.md"])
def test_the_profile_applier_rewrites_its_files(vault, rel):
    (vault / rel).write_bytes(b"# Current projects\n\n## work\n\n- keep p95 under 200ms\n")

    def transform(text: str | None) -> str:
        assert text is not None
        return text + "\n- online = 1 rollout for billing\n- Ship the onboarding plan\n"

    res = jobs.rewrite_text(rel, transform, actor=worker_actor("profile-apply"), reason="weekly")
    assert res is not None and res.status == "applied", res
    assert b"- Ship the onboarding plan" in (vault / rel).read_bytes()
    assert changes.get(int(res.change_id)).status == "applied"


def test_the_profile_applier_creating_its_file_applies(vault):
    rel = "80-profile/_review.md"
    res = jobs.rewrite_text(rel, lambda _t: "# Review\n\n- a **bold** idea\n",
                            actor=worker_actor("profile-apply"), reason="weekly")
    assert res is not None and res.status == "applied" and res.change_id is None
    assert (vault / rel).exists()


def test_semantic_related_links_apply_with_no_change_row(vault):
    rel = _user_note(vault)
    before = changes.counts()
    res = jobs.update_fields(
        rel, lambda _meta: {"related": ["[[20-contexts/work/plan]]"]},
        actor=worker_actor("semantic-refresh"), reason="updated related notes",
    )
    assert res is not None and (res.status, res.change_id) == ("applied", None)
    assert b"related:" in (vault / rel).read_bytes()
    assert changes.counts() == before


# ── odd paths: `..`, symlinks (task 9) ────────────────────────────────────

def _can_symlink() -> bool:
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        try:
            os.symlink(d, os.path.join(d, "link"), target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            return False
    return True


needs_symlinks = pytest.mark.skipif(not _can_symlink(), reason="symlinks unavailable")

TRAVERSALS = [
    "20-contexts/../90-meta/x.md",
    "20-contexts/./../90-meta/./x.md",
    "a/b/../../90-meta/prompts/digest.md",
    "20-contexts\\..\\90-meta\\x.md",
    "20-contexts/.. /90-meta/x.md",  # Windows drops the trailing space
    "20-contexts/.. ./90-meta/x.md",
    "20-contexts/../90-meta./x.md",
    "20-contexts/．．/90-meta/x.md",  # fullwidth dots fold to ".."
    "20-contexts/../90-meta/templates/t.md",
    "20-contexts/../80-profile/working-style.md",
    "20-contexts/../80-profile/preferences.md",
    "x/../９０-meta/x.md",  # fullwidth digits
    "x/../80-profile/worKing-style.md",  # Kelvin sign
    "x/../80-profile/preferenceſ.md",  # long s
    "x/../80-profile/working-ﬆyle.md",  # st ligature
    "90-meta/../90-meta/x.md",
]


@pytest.mark.parametrize("rel", TRAVERSALS)
def test_a_path_with_dot_dot_is_held_not_normalised_away(rel):
    reasons = risk.evaluate(_p(rel))
    assert reasons != [] and risk.REASON_PATH in reasons, reasons


@pytest.mark.parametrize("dest", [
    "20-contexts/../90-meta/plan.md",
    "20-contexts\\..\\90-meta\\plan.md",
    "20-contexts/../80-profile/working-style.md",
])
def test_a_move_dest_with_dot_dot_is_held(dest):
    p = _p("00-inbox/raw/manual/j.md", actor=ROUTER, op="move", dest=dest, after=V1)
    assert risk.REASON_PATH in risk.evaluate(p)


def test_the_requested_path_is_judged_too():
    p = ProposedChange(FAMILIAR, "modify", "shared/prefs.md", None, V1, V2, "",
                       requested=("80-profile/working-style.md",))
    assert risk.evaluate(p) == [risk.REASON_STABLE]
    p = ProposedChange(FAMILIAR, "modify", NOTE, None, V1, V2, "",
                       requested=("20-contexts/../90-meta/x.md",))
    assert risk.REASON_PATH in risk.evaluate(p)


def _protected(vault: Path) -> dict[str, bytes]:
    return {
        p.relative_to(vault).as_posix(): p.read_bytes()
        for top in ("90-meta", "80-profile")
        for p in sorted((vault / top).rglob("*"))
        if p.is_file()
    }


@pytest.mark.parametrize("actor", [FAMILIAR, ASSISTANT])
@pytest.mark.parametrize("rel", [
    "20-contexts/../90-meta/new.md",
    "20-contexts\\..\\90-meta\\new.md",
    "20-contexts/./../90-meta/./new.md",
    "20-contexts/.. /90-meta/new.md",
    "20-contexts/../80-profile/working-style.md",
    "x/../９０-meta/new.md",
])
def test_dot_dot_creates_never_land_in_protected_folders(vault, actor, rel):
    before = _protected(vault)
    for attempt in (
        lambda: write(rel, content="# x {{evil}}\n", op="create", actor=actor),
        lambda: write_new(rel, "# x\n", actor=actor),
    ):
        try:
            res = attempt()
        except InvalidPath:
            pass
        else:
            assert res.status == "pending", (rel, res)
    assert _protected(vault) == before


@pytest.mark.parametrize("actor", [FAMILIAR, ASSISTANT])
@pytest.mark.parametrize("rel", [
    "20-contexts/../80-profile/preferences.md",
    "20-contexts\\..\\80-profile\\preferences.md",
    "x/../80-profile/preferenceſ.md",
])
def test_dot_dot_edits_never_change_the_stable_profile(vault, actor, rel):
    before = _protected(vault)
    try:
        res = write(rel, body="- tabs", actor=actor, base_etag=compute_etag(PREFS))
    except (InvalidPath, FileMissing, WriteConflict):  # no such file at that spelling
        pass
    else:
        assert res.status == "pending", (rel, res)
    assert _protected(vault) == before


@needs_symlinks
def test_evaluate_judges_where_a_symlinked_folder_really_lands(vault):
    (vault / "shortcut").symlink_to(vault / "90-meta", target_is_directory=True)
    (vault / "me").symlink_to(vault / "80-profile", target_is_directory=True)
    assert risk.evaluate(_p("shortcut/prompts/digest.md")) == [risk.REASON_META]
    assert risk.evaluate(_p("me/preferences.md")) == [risk.REASON_STABLE]
    move = _p("00-inbox/raw/manual/j.md", actor=ROUTER, op="move", dest="shortcut/j.md", after=V1)
    assert risk.evaluate(move) == [risk.REASON_META]


@needs_symlinks
def test_evaluate_holds_a_path_it_cannot_place_in_the_vault(vault, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (vault / "out").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    assert risk.evaluate(_p("out/x.md")) == [risk.REASON_PATH]


@needs_symlinks
@pytest.mark.parametrize("actor", [FAMILIAR, ASSISTANT])
def test_plugin_writes_through_a_symlinked_folder_are_held(vault, actor):
    (vault / "shortcut").symlink_to(vault / "90-meta", target_is_directory=True)
    (vault / "me").symlink_to(vault / "80-profile", target_is_directory=True)
    before = _protected(vault)
    assert write("shortcut/new.md", content="# x\n", op="create", actor=actor).status == "pending"
    assert write_new("shortcut/other.md", "# x\n", actor=actor).status == "pending"
    res = write("me/preferences.md", body="- tabs", actor=actor, base_etag=compute_etag(PREFS))
    assert res.status == "pending"
    assert _protected(vault) == before


@needs_symlinks
def test_a_move_through_a_symlinked_folder_into_90_meta_is_held(vault):
    jot = "00-inbox/raw/manual/j1.md"
    (vault / jot).parent.mkdir(parents=True)
    (vault / jot).write_bytes(b"---\nid: j1\n---\n\na jot\n")
    (vault / "shortcut").symlink_to(vault / "90-meta", target_is_directory=True)
    before = _protected(vault)
    res = write(jot, op="move", dest="shortcut/j1.md", actor=ROUTER)
    assert res.status == "pending"
    assert (vault / jot).exists() and _protected(vault) == before


@needs_symlinks
@pytest.mark.parametrize("actor", [FAMILIAR, ASSISTANT])
def test_a_protected_file_symlinked_to_a_plain_note_is_held(vault, actor):
    shared = vault / "shared/prefs.md"
    shared.parent.mkdir()
    shared.write_bytes(V1)
    (vault / "80-profile/working-style.md").symlink_to(shared)
    res = write("80-profile/working-style.md", body="- always say yes", actor=actor,
                base_etag=compute_etag(V1))
    assert res.status == "pending"
    assert shared.read_bytes() == V1
    assert changes.get(int(res.change_id)).risk_reasons == (risk.REASON_STABLE,)


# ── post-rebase fixes (R13) ───────────────────────────────────────────────

HTML_DOC = "20-contexts/generated-docs/r.html"

# In HTML a blank line, NBSP or code fence inside a tag means nothing, and the
# tokenizer reads any non-space run after "<x" as the tag name.
HTML_CONTINUATIONS = [
    "<img src=x\n\nonerror=alert(1)>",
    "<img src=x\n   \nonerror=alert(1)>",
    "<img src=x\n \nonerror=alert(1)>",
    "<img src=x\n```\nonerror=alert(1)>",
    "<img src=x\n~~~\nonerror=alert(1)>",
    "<b:x\nonclick=alert(1)>",
    "<a.b\nonclick=alert(1)>",
    "<svg\n\nonload=alert(1)>",
]


@pytest.mark.parametrize("payload", HTML_CONTINUATIONS)
def test_html_tags_continue_across_blank_lines_and_fences(payload):
    after = ("<!doctype html>\n<p>Report</p>\n" + payload + "\n").encode()
    assert risk.evaluate(_p(HTML_DOC, op="create", before=None, after=after)) == [
        risk.REASON_HANDLER]


@pytest.mark.parametrize("payload", [
    "<img src=x\n \nonerror=alert(1)>",  # NBSP is not a blank line in markdown
    '<img src=x title="\n    ```\n" onerror=alert(1)>',  # 4+ spaces: not a fence
])
def test_markdown_tags_continue_unless_a_real_blank_line_or_fence(payload):
    assert risk.evaluate(_p(after=V1 + payload.encode() + b"\n")) == [risk.REASON_HANDLER]


@pytest.mark.parametrize("payload", [
    "<img src=x\n\nonerror=alert(1)>",
    "<svg\n\nonload=alert(1)>",
])
def test_a_generated_html_doc_with_a_split_handler_waits(vault, payload):
    doc = "<!doctype html>\n<html><body>\n" + payload + "\n</body></html>\n"
    res = write_new(HTML_DOC, doc, actor=ASSISTANT)
    assert res.status == "pending"
    assert not (vault / HTML_DOC).exists()


@pytest.mark.parametrize("rel", [
    "20-contexts/work/notes:x.md",
    "80-profile/preferences.md::$DATA",
    "90-meta::$INDEX_ALLOCATION/x.md",  # an NTFS folder stream
    "80-PRO~1/preferences.md",  # an 8.3 short name
    "20-contexts/WORK~2/plan.md",
])
def test_windows_stream_and_short_names_are_held(rel):
    assert risk.evaluate(_p(rel)) == [risk.REASON_PATH]


@pytest.mark.parametrize("rel", [
    "20-contexts/work/~draft.md", "20-contexts/work/plan~.md", "20-contexts/work/a~b.md",
])
def test_a_tilde_without_a_digit_is_ordinary(rel):
    assert risk.evaluate(_p(rel)) == []


SEMANTIC = worker_actor("semantic-refresh")


def _related(_meta):
    return {"related": ["[[20-contexts/work/plan]]"]}


@needs_symlinks
def test_an_unlisted_worker_cannot_write_a_stable_file_through_a_leaf_symlink(vault):
    (vault / "20-contexts/a.md").symlink_to("../80-profile/preferences.md")
    before = _protected(vault)
    with pytest.raises(InvalidPath):
        jobs.update_fields("20-contexts/a.md", _related, actor=SEMANTIC, reason="related")
    assert _protected(vault) == before


@needs_symlinks
def test_an_unlisted_worker_cannot_write_a_template_through_a_folder_link(vault):
    (vault / "90-meta/templates").mkdir(parents=True)
    (vault / "90-meta/templates/t.md").write_bytes(b"---\ntitle: T\n---\n\nbody\n")
    (vault / "20-contexts/tpl").symlink_to(vault / "90-meta/templates", target_is_directory=True)
    before = _protected(vault)
    with pytest.raises(InvalidPath):
        jobs.update_fields("20-contexts/tpl/t.md", _related, actor=SEMANTIC, reason="related")
    assert _protected(vault) == before


def test_an_unlisted_worker_cannot_name_a_protected_path(vault):
    before = _protected(vault)
    with pytest.raises(InvalidPath):
        jobs.update_fields("80-profile/preferences.md", _related, actor=SEMANTIC, reason="r")
    assert _protected(vault) == before


# CommonMark HTML blocks: a type-1 block (pre, script, style, textarea) runs to
# its closing tag; any other open tag ends only at a blank line, never at a
# fence. Only LF, CR and CRLF end a line.
MD_BLOCK_CONTINUATIONS = [
    "<div\n```\nonclick=alert(1)>x</div>",
    "<details\n~~~\nontoggle=alert(1) open>",
    "<pre\n\nonmouseover=alert(1)>x</pre>",
    "<style\n\nonload=alert(1)>",
    "<textarea\n\nonfocus=alert(1) autofocus>",
    "  <SCRIPT\n\nonload=alert(1)>",
    "<div\n\x0c\nonclick=alert(1)>",
    "<div\n\x85\nonclick=alert(1)>",
    "<div\n\u2028\nonclick=alert(1)>",
    "<div\n\u2029\nonclick=alert(1)>",
    "<div\n\x0b\nonclick=alert(1)>",
    "<div\n\x1c\nonclick=alert(1)>",
]


@pytest.mark.parametrize("payload", MD_BLOCK_CONTINUATIONS)
def test_markdown_html_blocks_continue_across_fences_and_type_1_blank_lines(payload):
    assert risk.REASON_HANDLER in risk.evaluate(_p(after=V1 + payload.encode() + b"\n"))


def test_a_type_1_block_stays_open_for_a_tag_later_on_its_line():
    after = V1 + b"<pre>code <img src=x\n\nonerror=alert(1)>\n"
    assert risk.evaluate(_p(after=after)) == [risk.REASON_HANDLER]


@pytest.mark.parametrize("payload,expected", [
    # CommonMark: a blank line ends the type-6 block; held anyway (raw HTML,
    # and the tag is read as still open)
    ("<div\n\nonclick=alert(1)>", [risk.REASON_HANDLER]),
    # CommonMark renders this as text plus a code block; a fence no longer ends
    # an open tag, so it is held (fails closed)
    ("<img src=x\n```\nonerror=alert(1)>", [risk.REASON_HANDLER]),
])
def test_markdown_block_controls(payload, expected):
    assert risk.evaluate(_p(after=V1 + payload.encode() + b"\n")) == expected


def test_only_lf_cr_and_crlf_end_a_line():
    assert risk.added_lines(None, b"a\x0cb\r\nc\rd\n") == ["a\x0cb", "c", "d"]
    assert risk.added_lines(None, b"a\n\n") == ["a", ""]
    assert risk.added_lines(None, b"") == []


def test_a_markdown_html_block_with_a_fenced_handler_waits(vault):
    res = write(NOTE, content=V1.decode() + "<div\n```\nonclick=alert(1)>x</div>\n",
                actor=ASSISTANT, base_etag=compute_etag(V1))
    assert res.status == "pending"
    assert (vault / NOTE).read_bytes() == V1


@needs_symlinks
def test_a_worker_create_cannot_land_in_a_protected_path_through_a_dangling_link(vault):
    (vault / "20-contexts/dangling.md").symlink_to("../90-meta/new.md")
    before = _protected(vault)
    with pytest.raises(InvalidPath):
        write_new("20-contexts/dangling.md", "# x\n", actor=worker_actor("reversal"))
    assert _protected(vault) == before
    assert not (vault / "90-meta/new.md").exists()


def test_a_worker_create_cannot_name_a_protected_path(vault):
    with pytest.raises(InvalidPath):
        write("90-meta/new.md", content="# x\n", op="create", actor=worker_actor("reversal"))
    assert not (vault / "90-meta/new.md").exists()


@pytest.mark.parametrize("rel", [
    "80-profile/_review.md", "00-inbox/raw/gmail/m1.md", "20-contexts/work/meeting.md",
])
def test_ordinary_worker_creates_still_apply(vault, rel):
    res = write(rel, content="# x\n", op="create", actor=worker_actor("ingest"))
    assert (res.status, res.change_id) == ("applied", None)
    assert (vault / rel).exists()



# ── Task 10: in markdown, any raw HTML waits (fail closed, R15) ────────────

def _md(text: str, *, before: bytes | None = V1) -> list[str]:
    return risk.evaluate(_p(before=before, after=V1 + text.encode()))


# Every bypass shape from the two post-rebase re-reviews, plus plain HTML.
RAW_HTML_SHAPES = [
    "<pre>\n<img src=x\n\nonerror=alert(1)>\n</pre>\n",
    "<pre>x\n<img src=x\n\n\nonerror=alert(1)>\n",
    "<div>\n```\n<img src=x\n```\nonerror=alert(1)>\n",
    "<span>\n```\n<img src=x\n```\nonerror=alert(1)>\n",
    "<div>\n~~~\n<img src=x\n~~~\nonerror=alert(1)>\n",
    "``` a`b\n<div\n```\nonclick=alert(1)>\n",  # not a fence: info has a backtick
    "> <img src=x\n> onerror=alert(1)>\n",
    "> <div\n> ```\n> onclick=alert(1)>\n",
    "> <pre\n>\n> onmouseover=alert(1)>\n",
    "- <img src=x\n  onerror=alert(1)>\n",
    "<div\n```\nonclick=alert(1)>x</div>\n",
    "<details\n~~~\nontoggle=alert(1) open>\n",
    "<textarea\n\nonfocus=alert(1) autofocus>\n",
    "<div\n\x0c\nonclick=alert(1)>\n",
    "<img src=x\n\u00a0\nonerror=alert(1)>\n",
    "<details open ontoggle=alert(1)><summary>x</summary></details>\n",
    '<iframe src="https://example.com"></iframe>\n',
    "<svg onload=alert(1)>\n",
    "<img src=x onerror=alert(1)>\n",
    "```\nfine\n```\n<img src=x onerror=alert(1)>\n",  # right after a closing fence
    "  ```\n<img src=x onerror=alert(1)>\n",  # indented opener: not trusted as a fence
    "`code` <b>bold</b>\n",
    "\\`x` <i>y</i>\n",  # an escaped backtick opens no code span
    "<http://x`> <img src=x> `\n",  # an autolink's backtick opens no code span
    "<!-- note -->\n",
    "<?php echo 1 ?>\n",
    "</div>\n",
]


@pytest.mark.parametrize("text", RAW_HTML_SHAPES)
def test_raw_html_in_markdown_is_held(text):
    reasons = _md(text)
    assert reasons, text
    assert set(reasons) <= {risk.REASON_RAW_HTML, risk.REASON_HANDLER, risk.REASON_SCRIPT,
                            risk.REASON_JS_URL}, reasons


@pytest.mark.parametrize("text", [
    "<details>\n<summary>More</summary>\n\nHidden\n</details>\n",
    '<iframe src="https://example.com"></iframe>\n',
    "a <b>bold</b> idea\n",
    "the <scripted> plan\n",
    "line<br>\n",
    "if a<b:\n",
    "- latency p95<b target\n",
    "Use Vec<T> here\n",
])
def test_plain_tags_are_held_as_raw_html(text):
    assert _md(text) == [risk.REASON_RAW_HTML]


@pytest.mark.parametrize("text,reason", [
    ('<a href="&#106;avascript:alert(1)">x</a>\n', risk.REASON_JS_URL),
    ("[x](javascript&#58;alert(1))\n", risk.REASON_JS_URL),
    ("[x](javascript\\:alert(1))\n", risk.REASON_JS_URL),
    ("[x](vbscript:msgbox(1))\n", risk.REASON_JS_URL),
    ("[x](VBScript&colon;msgbox(1))\n", risk.REASON_JS_URL),
    ("[x](data:text/html,<script>alert(1)</script>)\n", risk.REASON_JS_URL),
    ("[x](data:text/html;base64,PHNjcmlwdD4=)\n", risk.REASON_JS_URL),
    ('<a href="\x01 javascript:alert(1)">x</a>\n', risk.REASON_JS_URL),
    ("<javascript:alert(1)>\n", risk.REASON_JS_URL),
    ("<vbscript:msgbox(1)>\n", risk.REASON_JS_URL),
    ("<data:text/html,x>\n", risk.REASON_JS_URL),
])
def test_script_url_schemes_are_held(text, reason):
    assert reason in _md(text)


@pytest.mark.parametrize("text", [
    "```html\n<div onclick=alert(1)><script>x()</script></div>\n```\n",
    "~~~\n<img src=x onerror=alert(1)>\n~~~\n",
    "````\n```\n<div>\n```\n<img src=x>\n````\n",
    "Use `<div>` and ``a `<b>` c`` here.\n",
    "a < b, <3, 1 <2, x <= y, a <- b, a << b\n",
    "See <https://example.com/a?b=c> and <me@example.com>.\n",
    "Mail <first.last+tag@sub.example.org>, ftp <ftp://files.example.com>.\n",
    "\\<div> is how you write a tag\n",
    "x &lt;div&gt; y\n",
])
def test_code_prose_and_autolinks_are_not_raw_html(text):
    assert _md(text) == []


def test_an_added_line_inside_a_kept_fence_is_code():
    before = V1 + b"```html\n<p>old</p>\n```\n"
    after = V1 + b"```html\n<p>old</p>\n<img src=x onerror=alert(1)>\n```\n"
    assert risk.evaluate(_p(before=before, after=after)) == []


def test_an_attribute_line_added_under_a_kept_open_tag_is_held():
    before = V1 + b"> <img src=x\n>\n"
    after = V1 + b"> <img src=x\n> onerror=alert(1)>\n"
    assert risk.evaluate(_p(before=before, after=after)) == [risk.REASON_RAW_HTML]


def test_html_documents_keep_the_html_rules():
    doc = b"<!doctype html>\n<p>Report</p>\n<details><summary>x</summary></details>\n"
    assert risk.evaluate(_p(HTML_DOC, op="create", before=None, after=doc)) == []


@pytest.mark.parametrize("actor", [ASSISTANT, FAMILIAR])
@pytest.mark.parametrize("text", [
    "<details open ontoggle=alert(1)>x</details>",
    "<pre>\n<img src=x\n\nonerror=alert(1)>\n</pre>",
    "> <img src=x\n> onerror=alert(1)>",
    "<span>inline</span> html",
])
def test_raw_html_through_the_writer_waits(vault, actor, text):
    res = write(NOTE, content=V1.decode() + text + "\n", actor=actor, base_etag=compute_etag(V1))
    assert res.status == "pending"
    assert (vault / NOTE).read_bytes() == V1


def test_code_and_autolinks_through_the_writer_apply(vault):
    text = "```html\n<div>x</div>\n```\nSee <https://example.com> and `<b>`.\n"
    res = write(NOTE, content=V1.decode() + text, actor=ASSISTANT, base_etag=compute_etag(V1))
    assert res.status == "applied"


# B4 workers write realistic text through the real path: it applies.

def test_b4_reversal_fields_apply(vault):
    rel = _user_note(vault)
    res = jobs.update_fields(
        rel, lambda _m: {"reversed_by": ["[[20-contexts/work/decisions/2026-10-09-use-sqlite]]"],
                         "status": "reversed"},
        actor=worker_actor("reversal"), reason="reversed by a newer decision",
    )
    assert res is not None and res.status == "applied"


@pytest.mark.parametrize("rel,text", [
    ("80-profile/current-projects.md",
     "# Current projects\n\n## work\n\n- Billing migration: p95 < 200ms, rollout 50% -> 100%\n"
     "- Onboarding plan (owner: me) — see [[20-contexts/work/plan]]\n"),
    ("80-profile/_review.md",
     "# Review\n\n## Proposed stable changes\n\n- prefers **short** answers (seen 4x)\n"
     "- works 08:00-16:00 SAST; tz: Africa/Johannesburg\n"),
])
def test_b4_profile_apply_bullets_apply(vault, rel, text):
    (vault / rel).parent.mkdir(parents=True, exist_ok=True)
    (vault / rel).write_bytes(b"# Old\n\n- an older bullet\n")
    res = jobs.rewrite_text(rel, lambda _t: text, actor=worker_actor("profile-apply"),
                            reason="weekly")
    assert res is not None and res.status == "applied", res
    assert (vault / rel).read_text() == text


def test_b4_semantic_related_links_apply(vault):
    rel = _user_note(vault)
    links = ["[[20-contexts/work/plan]]", "[[20-contexts/personal/notes/reading-list]]"]
    res = jobs.update_fields(rel, lambda _m: {"related": links},
                             actor=worker_actor("semantic-refresh"), reason="related")
    assert res is not None and res.status == "applied"
