"""POST /v1/templates/generate (C4): AI drafts are validated and only ever saved as pending."""
from __future__ import annotations

import pytest

from ghostbrain.api.repo.settings import ProviderUnavailable
from ghostbrain.changes import log as change_log

GOOD = """---
template:
  name: Standup
  prompts:
    - id: team
      ask: Which team?
      type: text
  file:
    folder: "20-contexts/{{context}}/standups"
    name: "{{date | format: YYYY-MM-DD}} {{team}} standup"
---
# {{team}} standup
"""
BAD = GOOD.replace("# {{team}} standup", "<script>alert(1)</script>")


@pytest.fixture(autouse=True)
def _provider_ok(monkeypatch):
    monkeypatch.setattr("ghostbrain.api.routes.templates.require_provider", lambda: None)


def _model(monkeypatch, *answers: str) -> list[str]:
    prompts: list[str] = []
    it = iter(answers)

    def turn(prompt, *, turn_key):
        prompts.append(prompt)
        return next(it)

    monkeypatch.setattr("ghostbrain.templates.generate.run_turn", turn)
    return prompts


def _post(client, auth_headers, description="a daily standup"):
    return client.post("/v1/templates/generate", headers=auth_headers, json={"description": description})


def test_a_valid_draft_is_saved_as_a_pending_assistant_change(client, auth_headers, tmp_vault, monkeypatch):
    _model(monkeypatch, GOOD)
    r = _post(client, auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending" and body["id"] == "standup" and body["name"] == "Standup"
    assert body["path"] == "90-meta/templates/standup.md" and body["changeId"]
    assert not (tmp_vault / body["path"]).exists()
    [row] = change_log.list_changes(status="pending")
    assert (row.actor, row.rel_path, row.op) == ("assistant", body["path"], "create")
    assert row.reason == "AI template: a daily standup"
    names = [t["name"] for t in client.get("/v1/templates", headers=auth_headers).json()["templates"]]
    assert "Standup" not in names


def test_an_invalid_draft_is_repaired_once(client, auth_headers, tmp_vault, monkeypatch):
    prompts = _model(monkeypatch, BAD, GOOD)
    assert _post(client, auth_headers).json()["status"] == "pending"
    assert len(prompts) == 2 and "<script> tags are not allowed" in prompts[1]


def test_invalid_twice_returns_the_draft_and_saves_nothing(client, auth_headers, tmp_vault, monkeypatch):
    _model(monkeypatch, BAD, BAD)
    r = _post(client, auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "invalid" and body["draft"] == BAD
    assert body["diagnostics"][0]["code"] == "forbidden"
    assert body["message"].startswith("the draft is not a valid template")
    assert change_log.list_changes() == []
    assert not list((tmp_vault / "90-meta").rglob("standup*.md"))


def test_provider_unavailable_is_412(client, auth_headers, monkeypatch):
    def unavailable():
        raise ProviderUnavailable("no AI provider is set up")

    monkeypatch.setattr("ghostbrain.api.routes.templates.require_provider", unavailable)
    r = _post(client, auth_headers)
    assert r.status_code == 412 and r.json()["detail"] == "no AI provider is set up"


def test_model_failure_is_502(client, auth_headers, monkeypatch):
    from ghostbrain.templates.generate import GenerateError

    def turn(prompt, *, turn_key):
        raise GenerateError("rate limited")

    monkeypatch.setattr("ghostbrain.templates.generate.run_turn", turn)
    r = _post(client, auth_headers)
    assert r.status_code == 502 and "rate limited" in r.json()["detail"]


class _Broken:
    supports_tool_allowlist = True

    def chat(self, req):
        yield {"type": "delta", "text": "---"}
        raise OSError("connection reset")


def _no_provider(cfg=None):
    raise RuntimeError("provider config is broken")


class _ErrorEvent:
    supports_tool_allowlist = True

    def chat(self, req):
        yield {"type": "error", "message": "claude: cannot read /Users/alex/.claude/settings.json"}


def _error_event(cfg=None):
    return _ErrorEvent()


@pytest.mark.parametrize(("get_provider", "message"), [
    (_error_event, "/Users/alex/.claude/settings.json"),
    (_no_provider, "provider config is broken"),
    (lambda cfg=None: _Broken(), "connection reset"),
])
def test_any_provider_failure_is_502(client, auth_headers, monkeypatch, get_provider, message):
    monkeypatch.setattr("ghostbrain.llm.providers.get_provider", get_provider)
    r = _post(client, auth_headers)
    assert r.status_code == 502
    assert r.json()["detail"] == "template generation failed — check the AI provider in settings"
    assert message not in r.json()["detail"]
    assert change_log.list_changes() == []


@pytest.mark.parametrize("description", ["", "   ", "x" * 2001], ids=["empty", "blank", "too-long"])
def test_bad_descriptions_are_422(client, auth_headers, description):
    assert _post(client, auth_headers, description).status_code == 422


def _save_raises(monkeypatch, exc: Exception) -> None:
    def save(source, template, *, reason):
        raise exc

    monkeypatch.setattr("ghostbrain.templates.ai_save.save_ai_template", save)


def _save_errors():
    from ghostbrain.changes.log import ChangeLogError
    from ghostbrain.history import HistoryUnavailable
    from ghostbrain.templates.ai_save import NotHeld
    from ghostbrain.templates.generate import DraftInvalid
    from ghostbrain.templates.parse import Diagnostic
    from ghostbrain.vault_write import InvalidPath, NotHeldError, WriteConflict

    changed = DraftInvalid(GOOD, (Diagnostic(1, 1, "error", "the template changed after it was checked",
                                             "changed"),))
    return [
        (changed, 500, "the template changed after it was checked"),
        (NotHeld("the approval rules would not hold this template; nothing was saved"), 500,
         "would not hold"),
        (NotHeldError("not held"), 500, "not held for approval"),
        (WriteConflict(None, "no free template id near 'standup'"), 409, "no free template name"),
        (InvalidPath("90-meta/templates/standup.md resolves outside the vault"), 409,
         "templates folder"),
        (HistoryUnavailable("snapshot failed"), 503, "history"),
        (ChangeLogError("database is locked"), 503, "change log"),
    ]


@pytest.mark.parametrize(("exc", "status", "detail"), _save_errors())
def test_save_failures_map_to_clear_errors(client, auth_headers, monkeypatch, exc, status, detail):
    _model(monkeypatch, GOOD)
    _save_raises(monkeypatch, exc)
    r = _post(client, auth_headers)
    assert r.status_code == status, r.text
    assert detail in r.json()["detail"]


def test_an_invalid_path_detail_names_no_path(client, auth_headers, monkeypatch, caplog):
    from ghostbrain.vault_write import InvalidPath

    _model(monkeypatch, GOOD)
    _save_raises(monkeypatch, InvalidPath("/Users/alex/elsewhere/standup.md resolves outside the vault"))
    with caplog.at_level("WARNING"):
        r = _post(client, auth_headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "the templates folder cannot be written (is it outside the vault?)"
    assert "/Users/alex/elsewhere" in caplog.text


def test_only_the_user_can_ask_for_a_draft(client, auth_headers, tmp_vault, monkeypatch):
    prompts = _model(monkeypatch, GOOD)
    r = client.post("/v1/templates/generate", json={"description": "a daily standup"},
                    headers={**auth_headers, "X-Poltergeist-Actor": "plugin:familiar"})
    assert r.status_code == 403
    assert r.json()["detail"] == "only you can ask the assistant to draft a template"
    assert prompts == [] and change_log.list_changes() == []


def test_control_and_format_characters_are_stripped_from_the_request(client, auth_headers, tmp_vault,
                                                                      monkeypatch):
    prompts = _model(monkeypatch, GOOD)
    r = _post(client, auth_headers, "a daily\u202e stand\u200bup\x07\nfor the team")
    assert r.status_code == 200, r.text
    [row] = change_log.list_changes(status="pending")
    assert row.reason == "AI template: a daily standup for the team"
    assert "a daily standup\nfor the team" in prompts[0]
    for ch in ("\u202e", "\u200b", "\x07"):
        assert ch not in prompts[0]


def test_only_format_characters_is_a_bad_description(client, auth_headers):
    assert _post(client, auth_headers, "\u202e\u200b").status_code == 422


def test_approving_the_change_on_the_changes_screen_makes_it_usable(client, auth_headers, tmp_vault, monkeypatch):
    _model(monkeypatch, GOOD)
    body = _post(client, auth_headers).json()
    pending = client.get("/v1/changes?status=pending", headers=auth_headers).json()["items"]
    assert [(c["actor"], c["path"]) for c in pending] == [("assistant", body["path"])]
    r = client.post(f"/v1/changes/{body['changeId']}/approve", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    assert (tmp_vault / body["path"]).read_text(encoding="utf-8") == GOOD
    names = [t["name"] for t in client.get("/v1/templates", headers=auth_headers).json()["templates"]]
    assert "Standup" in names


class _CannotDraft:
    supports_tool_allowlist = False

    def chat(self, req):
        raise AssertionError("a turn ran on a provider that cannot limit its tools")


def test_a_provider_that_cannot_limit_its_tools_is_412(client, auth_headers, monkeypatch):
    prompts = _model(monkeypatch, GOOD)
    monkeypatch.setattr("ghostbrain.llm.providers.get_provider", lambda cfg=None: _CannotDraft())
    r = _post(client, auth_headers)
    assert r.status_code == 412
    assert r.json()["detail"] == ("AI templates need a provider that can run without tools: switch to "
                                  "claude or a local/OpenAI-compatible model in settings")
    assert prompts == [] and change_log.list_changes() == []
