"""dry_run(): render template source with sample answers; never write."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ghostbrain.templates.render import RenderEnv
from ghostbrain.templates.starters import ONE_ON_ONE
from ghostbrain.templates.testrun import SAMPLE_PERSON, dry_run, would_be_path
from ghostbrain.templates.values import ProjectValue

ENV = RenderEnv(
    now=datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2))),
    default_context="work",
    contexts=("work", "personal"),
    projects={"work/alpha": ProjectValue("work/alpha", "Alpha", "alpha", "work")},
    user_name="Sam",
)
CHOICE = """---
template:
  name: Review
  prompts:
    - id: kind
      ask: Kind?
      type: choice
      options: [weekly, monthly]
    - id: proj
      ask: Project?
      type: project
    - id: note
      ask: Note?
      type: text
    - id: extra
      ask: Extra?
      type: text
      optional: true
  file:
    folder: "20-contexts/{{context}}/reviews"
    name: "{{date | format: YYYY-MM-DD}} {{kind}} review"
---
# {{kind}} for {{proj.name}}: {{note}} {{extra | default: none}}
"""


@pytest.fixture
def vault(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(root))
    return root


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def test_renders_one_on_one_with_a_sample_person_and_writes_nothing(vault):
    before = _files(vault)
    res = dry_run(ONE_ON_ONE, {}, template_id="one-on-one", env=ENV)
    assert res.ok and res.error is None
    assert res.answers == {"person": SAMPLE_PERSON}
    assert res.would_be_filed_at == "20-contexts/work/one-on-ones/2026-10-09-sample-person-1-1.md"
    assert res.note.body.startswith("# 1-1 with [[Sample Person]] — 9 Oct 2026\n")
    assert 'mentions: "[[Sample Person]]"' in res.note.body
    assert _files(vault) == before


def test_given_answers_win_and_stale_keys_are_dropped(vault):
    res = dry_run(ONE_ON_ONE, {"person": "Alex", "gone": "x", "focus": " "}, env=ENV)
    assert res.answers == {"person": "Alex"}
    assert "# 1-1 with [[Alex]]" in res.note.body


def test_samples_by_prompt_type(vault):
    res = dry_run(CHOICE, {}, env=ENV)
    assert res.ok, res.error
    assert res.answers == {"kind": "weekly", "proj": "work/alpha", "note": "[note]"}
    assert res.note.body == "# weekly for Alpha: [note] none\n"
    assert [p.id for p in res.prompts] == ["kind", "proj", "note", "extra"]


def test_would_be_path_skips_taken_names(vault):
    folder = vault / "20-contexts/work/one-on-ones"
    folder.mkdir(parents=True)
    (folder / "2026-10-09-alex-1-1.md").write_text("x", encoding="utf-8")
    (folder / "2026-10-09-alex-1-1-2.md").write_text("x", encoding="utf-8")
    res = dry_run(ONE_ON_ONE, {"person": "Alex"}, env=ENV)
    assert res.would_be_filed_at == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1-3.md"
    assert would_be_path("20-contexts/work/new.md") == "20-contexts/work/new.md"


def test_broken_source_reports_the_first_error(vault):
    res = dry_run("---\ntemplate:\n  name: [x\n---\n", {}, env=ENV)
    assert not res.ok and res.note is None
    assert res.error.startswith("template has errors: line 4: frontmatter is not valid YAML")
    assert res.diagnostics and res.prompts == ()


def test_bad_answer_is_reported_inline(vault):
    res = dry_run(CHOICE, {"kind": "daily"}, env=ENV)
    assert not res.ok and res.error == "kind: pick one of: weekly, monthly"
    assert [p.id for p in res.prompts] == ["kind", "proj", "note", "extra"]


def test_escaping_folder_is_reported_and_nothing_written(vault):
    src = '---\ntemplate:\n  name: Evil\n  file:\n    folder: "../../outside"\n---\nx\n'
    before = _files(vault.parent)
    res = dry_run(src, {}, env=ENV)
    assert not res.ok and "not allowed" in res.error
    assert _files(vault.parent) == before


def test_symlinked_folder_out_of_the_vault_is_reported(vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "20-contexts").mkdir()
    try:
        (vault / "20-contexts" / "work").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    res = dry_run(ONE_ON_ONE, {"person": "Alex"}, env=ENV)
    assert not res.ok and "escapes the vault" in res.error


def test_json_shape(vault):
    data = dry_run(ONE_ON_ONE, {"person": "Alex"}, env=ENV).to_json()
    assert set(data) == {"ok", "prompts", "answers", "rendered", "wouldBeFiledAt", "diagnostics", "error"}
    assert set(data["rendered"]) == {"path", "folder", "filename", "title", "frontmatter", "body", "markdown"}
    assert data["rendered"]["markdown"].startswith("---\ntitle: 2026-10-09 Alex 1-1\n")
    assert data["prompts"][0] == {"id": "person", "ask": "Who's this 1-1 with?", "type": "person",
                                  "optional": False, "default": None, "options": []}
