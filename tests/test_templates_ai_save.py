"""AI templates are proposed as pending changes and never applied on their own (C4 + B3)."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from ghostbrain.changes import log as change_log
from ghostbrain.templates import ai_save
from ghostbrain.templates.ai_save import NotHeld, save_ai_template
from ghostbrain.templates.generate import DraftInvalid, check_draft
from ghostbrain.templates.registry import list_templates
from ghostbrain.vault_write import risk, set_hold_policy

SOURCE = "---\ntemplate:\n  name: Standup\n---\n# Standup {{date | format: D MMM}}\n"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(root))
    return root


@pytest.fixture
def risk_rules():
    set_hold_policy(risk.evaluate)
    yield
    set_hold_policy(risk.evaluate)


@pytest.fixture
def template():
    check = check_draft(SOURCE)
    assert check.ok
    return check.template


def _templates(vault: Path) -> list[str]:
    return sorted(p.name for p in (vault / "90-meta/templates").glob("*.md"))


def test_ai_template_is_pending_and_writes_nothing(vault, risk_rules, template):
    saved = save_ai_template(SOURCE, template, reason="AI template: standup")
    assert (saved.id, saved.path) == ("standup", "90-meta/templates/standup.md")
    assert not (vault / saved.path).exists()
    [row] = change_log.list_changes(status="pending")
    assert (row.actor, row.rel_path, row.op) == ("assistant", saved.path, "create")
    assert row.risk_reasons and str(row.id) == saved.change_id
    assert saved.to_json() == {"status": "pending", "id": "standup", "path": saved.path,
                               "name": "Standup", "changeId": saved.change_id}


def test_starters_are_seeded_before_the_proposal(vault, risk_rules, template):
    save_ai_template(SOURCE, template, reason="r")
    assert _templates(vault) == ["decision-record.md", "meeting-notes.md", "one-on-one.md"]
    assert sorted(i.id for i in list_templates()) == ["decision-record", "meeting-notes", "one-on-one"]


def test_ids_skip_existing_files_and_other_pending_proposals(vault, risk_rules, template):
    (vault / "90-meta/templates").mkdir(parents=True)
    (vault / "90-meta/templates/standup.md").write_text(SOURCE, encoding="utf-8")
    first = save_ai_template(SOURCE, template, reason="r")
    second = save_ai_template(SOURCE, template, reason="r")
    assert (first.id, second.id) == ("standup-2", "standup-3")


def test_the_pre_check_sees_the_exact_proposal(vault, risk_rules, template, monkeypatch):
    seen = []
    real = risk.evaluate

    def spy(proposal):
        seen.append(proposal)
        return real(proposal)

    monkeypatch.setattr(ai_save.risk, "evaluate", spy)
    saved = save_ai_template(SOURCE, template, reason="r")
    first = seen[0]
    assert (first.actor, first.op, first.rel_path, first.before, first.after, first.requested) == (
        "assistant", "create", saved.path, None, SOURCE.encode("utf-8"), (saved.path,))


def test_refuses_when_the_rules_would_not_hold_it(vault, risk_rules, template, monkeypatch):
    monkeypatch.setattr(ai_save.risk, "evaluate", lambda _proposal: [])
    with pytest.raises(NotHeld):
        save_ai_template(SOURCE, template, reason="r")
    assert change_log.list_changes() == []
    assert not (vault / "90-meta/templates/standup.md").exists()


def test_a_hook_that_holds_nothing_writes_nothing(vault, risk_rules, template):
    set_hold_policy(lambda _proposal: [])  # a broken install: the hook holds nothing
    with pytest.raises(NotHeld):
        save_ai_template(SOURCE, template, reason="r")
    assert not (vault / "90-meta/templates/standup.md").exists()
    assert change_log.list_changes() == []


@pytest.mark.parametrize(
    "source",
    [
        SOURCE + "Trailing text\n",
        SOURCE.replace("\n", "\r\n"),
        SOURCE.replace("# Standup", "# Standup <b>x</b>"),
    ],
)
def test_a_source_other_than_the_validated_template_is_refused(vault, risk_rules, template, source):
    with pytest.raises(DraftInvalid):
        save_ai_template(source, template, reason="r")
    assert change_log.list_changes() == []
    assert not (vault / "90-meta/templates").exists()


def test_concurrent_saves_get_distinct_ids(vault, risk_rules, template):
    barrier = threading.Barrier(4)
    ids: list[str] = []

    def save() -> None:
        barrier.wait()
        ids.append(save_ai_template(SOURCE, template, reason="r").id)

    threads = [threading.Thread(target=save) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(ids) == ["standup", "standup-2", "standup-3", "standup-4"]
    assert len(change_log.list_changes(status="pending")) == 4


def test_approving_the_proposal_makes_a_usable_template(vault, risk_rules, template):
    from ghostbrain.changes import approve
    from ghostbrain.templates.registry import load_template

    saved = save_ai_template(SOURCE, template, reason="r")
    approve.approve(int(saved.change_id))
    assert (vault / saved.path).read_text(encoding="utf-8") == SOURCE
    assert load_template("standup").name == "Standup"
    assert sorted(i.id for i in list_templates()) == [
        "decision-record", "meeting-notes", "one-on-one", "standup"]


def test_a_rejected_proposal_frees_its_id(vault, risk_rules, template):
    from ghostbrain.changes import approve

    first = save_ai_template(SOURCE, template, reason="r")
    approve.reject(int(first.change_id))
    assert not (vault / first.path).exists()
    assert save_ai_template(SOURCE, template, reason="r").id == "standup"
