"""Design artefacts: artefact.json + README note, listing, detail, folder
guard, worktree removal, eject, and the meeting link both ways."""
from __future__ import annotations

import json
import os
import shutil
import sys
import types
from pathlib import Path

import pytest

from ghostbrain.design import artefacts, scaffold
from ghostbrain.design import session as ds
from ghostbrain.recorder import hooks
from ghostbrain.vault_index.parse import split_frontmatter

DATA = {
    "version": 1, "title": "Login screen review", "kind": "prototype", "board": False,
    "date": "2026-10-10", "context": "personal", "project": None,
    "design_system": "poltergeist-neutral", "meeting": None, "meeting_path": None,
    "ui_rev": 2, "board_rev": 0,
    "revs": [{"rev": 1, "at": "2026-10-10T10:00:00+00:00", "summary": "Login form"},
             {"rev": 2, "at": "2026-10-10T10:05:00+00:00", "summary": "Error states"}],
    "codebase": None, "wav": "/rec/meeting.wav",
}


@pytest.fixture()
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "20-contexts" / "personal").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(v))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "nogitconfig"))
    return v


def _folder(vault: Path, rel: str) -> Path:
    d = vault / rel
    d.mkdir(parents=True, exist_ok=True)
    return d


def _codebase(tmp_path: Path, *, exists: bool = True) -> dict:
    wt = tmp_path / "code" / "web-poltergeist-2026-10-10-login"
    if exists:
        wt.mkdir(parents=True)
    return {"repo": str(tmp_path / "code" / "web"), "name": "web", "app_dir": str(wt),
            "worktree": str(wt), "branch": "poltergeist/2026-10-10-login", "base": "origin/main"}


class FakeWorktreeModule(types.ModuleType):
    """Stands in for ghostbrain.design.worktree (workstream A)."""

    def __init__(self) -> None:
        super().__init__("ghostbrain.design.worktree")
        self.removed: list = []
        self.revs = [{"rev": 1, "at": "2026-10-10T10:00:00+00:00", "summary": "from branch"}]
        self.remove_result = {"removed": True, "branch_kept": True,
                              "reason": "unmerged commits on poltergeist/2026-10-10-login"}
        self.remove_error: Exception | None = None

        outer = self

        class Worktree:
            def __init__(self, d: dict) -> None:
                self.d = d
                self.path = Path(d["worktree"])

            @classmethod
            def from_dict(cls, d: dict) -> Worktree:
                return cls(d)

        self.Worktree = Worktree

        def revisions(wt):
            return list(outer.revs)

        def remove(wt):
            outer.removed.append(wt.d["worktree"])
            if outer.remove_error is not None:
                raise outer.remove_error
            return dict(outer.remove_result)

        self.revisions = revisions
        self.remove = remove


@pytest.fixture()
def fake_wt(monkeypatch: pytest.MonkeyPatch) -> FakeWorktreeModule:
    mod = FakeWorktreeModule()
    monkeypatch.setitem(sys.modules, "ghostbrain.design.worktree", mod)
    return mod


# -- C1: artefact.json + README ------------------------------------------------------


def test_write_creates_json_and_note(vault: Path) -> None:
    folder = _folder(vault, "20-contexts/personal/prototypes/2026-10-10-login")
    artefacts.write(folder, DATA)
    assert artefacts.load(folder)["ui_rev"] == 2
    note = (folder / "README.md").read_text()
    assert note.startswith("---\ntype: artefact\nkind: prototype\n")
    assert "# Login screen review" in note and "rev 2: Error states" in note
    assert "Built live during a meeting on 2026-10-10." in note
    assert "Prototype: `src/`" in note
    meta, _ = split_frontmatter(note)
    assert meta["title"] == "Login screen review" and meta["ui_rev"] == 2
    assert "meeting" not in meta and "repo" not in meta  # None values omitted
    assert not [p for p in folder.iterdir() if p.name.endswith(".tmp")]


def test_frontmatter_key_order(vault: Path) -> None:
    folder = _folder(vault, "20-contexts/personal/artefacts/2026-10-10-login")
    data = DATA | {"kind": "worktree", "project": "personal/app", "meeting": "Login review",
                   "meeting_path": "20-contexts/personal/calendar/transcripts/x.md",
                   "codebase": _codebase(folder.parent)}
    artefacts.write(folder, data)
    meta, _ = split_frontmatter((folder / "README.md").read_text())
    assert list(meta) == ["type", "kind", "title", "date", "context", "project", "design_system",
                          "meeting", "meeting_path", "ui_rev", "board_rev", "repo", "worktree", "branch"]


def test_note_links_meeting_when_known(vault: Path) -> None:
    folder = _folder(vault, "20-contexts/personal/prototypes/2026-10-10-login")
    artefacts.write(folder, DATA | {"meeting": "Login review",
                                    "meeting_path": "20-contexts/personal/calendar/transcripts/x.md"})
    note = (folder / "README.md").read_text()
    assert 'meeting: "[[20-contexts/personal/calendar/transcripts/x|Login review]]"' in note
    assert "Built live during **[[20-contexts/personal/calendar/transcripts/x|Login review]]** on 2026-10-10." in note
    meta, _ = split_frontmatter(note)
    assert meta["meeting_path"] == "20-contexts/personal/calendar/transcripts/x.md"


def test_worktree_note_lists_repo_branch(vault: Path, tmp_path: Path) -> None:
    folder = _folder(vault, "20-contexts/personal/artefacts/2026-10-10-login")
    cb = _codebase(tmp_path)
    artefacts.write(folder, DATA | {"kind": "worktree", "codebase": cb})
    note = (folder / "README.md").read_text()
    assert (f"- Code: `{cb['worktree']}` on branch `poltergeist/2026-10-10-login` "
            f"(from {cb['repo']})") in note
    meta, _ = split_frontmatter(note)
    assert meta["repo"] == cb["repo"] and meta["branch"] == "poltergeist/2026-10-10-login"


def test_board_line_and_odd_titles_survive_yaml(vault: Path) -> None:
    folder = _folder(vault, "20-contexts/personal/prototypes/2026-10-10-x")
    artefacts.write(folder, DATA | {"title": 'Claims: "v2" #1', "kind": "board", "board": True,
                                    "ui_rev": 0, "board_rev": 3, "revs": []})
    note = (folder / "README.md").read_text()
    assert "- Event-storming board: `board.json` (rev 3)" in note
    assert split_frontmatter(note)[0]["title"] == 'Claims: "v2" #1'


def test_write_keeps_meeting_link_when_session_rewrites_without_it(vault: Path) -> None:
    folder = _folder(vault, "20-contexts/personal/prototypes/2026-10-10-login")
    artefacts.write(folder, DATA | {"meeting": "Login review", "meeting_path": "a/b.md"})
    artefacts.write(folder, DATA | {"ui_rev": 3})  # the live session knows nothing of the link
    data = artefacts.load(folder)
    assert data["ui_rev"] == 3 and data["meeting"] == "Login review" and data["meeting_path"] == "a/b.md"


def test_load_missing_or_garbage_is_none(vault: Path) -> None:
    folder = _folder(vault, "20-contexts/personal/prototypes/2026-10-10-x")
    assert artefacts.load(folder) is None
    (folder / "artefact.json").write_text("{nope")
    assert artefacts.load(folder) is None


# -- C2: listing, detail, folder guard, remove, eject ------------------------------------


def test_list_scans_prototypes_and_artefacts_newest_first(vault: Path, tmp_path: Path) -> None:
    old = _folder(vault, "20-contexts/personal/prototypes/2026-10-08-old")
    artefacts.write(old, DATA | {"title": "Old", "date": "2026-10-08"})
    new = _folder(vault, "20-contexts/personal/projects/app/artefacts/2026-10-10-new")
    artefacts.write(new, DATA | {"title": "New", "kind": "worktree", "project": "personal/app",
                                 "codebase": _codebase(tmp_path)})
    _folder(vault, "20-contexts/personal/notes/2026-10-10-not-an-artefact")
    _folder(vault, "20-contexts/personal/prototypes/2026-10-09-empty")  # no note: skipped

    items = artefacts.list_artefacts()
    assert [i["title"] for i in items] == ["New", "Old"]
    first = items[0]
    assert first["id"] == "20-contexts/personal/projects/app/artefacts/2026-10-10-new"
    assert first["kind"] == "worktree" and first["project"] == "personal/app"
    assert first["codebase"]["missing"] is False and first["codebase"]["branch"].startswith("poltergeist/")
    assert set(first) == {"id", "title", "kind", "board", "date", "context", "project", "meeting",
                          "meeting_path", "ui_rev", "board_rev", "codebase"}
    assert items[1]["codebase"] is None


def test_list_reads_legacy_readme_without_json(vault: Path) -> None:
    folder = _folder(vault, "20-contexts/personal/prototypes/2026-10-09-legacy")
    (folder / "README.md").write_text(
        "---\ntype: prototype\ncontext: personal\ndate: 2026-10-09\nmeeting: \"Old meeting\"\n"
        "design_system: poltergeist-neutral\n---\n\n# Prototype: Old meeting\n\n"
        "Built live during the meeting **Old meeting** on 2026-10-09.\n\n"
        "- Frontend prototype: `src/` (rev 2, design system `poltergeist-neutral`)\n"
        "  - rev 1: First\n  - rev 2: Second\n"
        "- Event-storming board: `board.json` (rev 4)\n"
    )
    [item] = artefacts.list_artefacts()
    assert item["kind"] == "prototype" and item["ui_rev"] == 2 and item["board_rev"] == 4
    assert item["board"] is True and item["title"] == "Old meeting" and item["date"] == "2026-10-09"
    assert item["meeting"] is None


def test_folder_for_rejects_escape(vault: Path) -> None:
    _folder(vault, "20-contexts/personal/notes/x")
    ok = _folder(vault, "20-contexts/personal/prototypes/2026-10-10-a")
    with pytest.raises(ValueError):
        artefacts.folder_for("../../etc")
    with pytest.raises(ValueError):
        artefacts.folder_for("20-contexts/personal/notes/x")
    with pytest.raises(ValueError):
        artefacts.folder_for("20-contexts/personal/prototypes/../prototypes/2026-10-10-a")
    with pytest.raises(ValueError):
        artefacts.folder_for("/20-contexts/personal/prototypes/2026-10-10-a")
    with pytest.raises(ValueError):
        artefacts.folder_for("20-contexts/personal/prototypes/missing")
    assert artefacts.folder_for("20-contexts/personal/prototypes/2026-10-10-a") == ok


def test_folder_for_rejects_symlink_out_of_vault(vault: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "20-contexts/personal/prototypes").mkdir(parents=True)
    os.symlink(outside, vault / "20-contexts/personal/prototypes/link")
    with pytest.raises(ValueError):
        artefacts.folder_for("20-contexts/personal/prototypes/link")


def test_detail_marks_missing_worktree(vault: Path, tmp_path: Path, fake_wt) -> None:
    folder = _folder(vault, "20-contexts/personal/artefacts/2026-10-10-login")
    artefacts.write(folder, DATA | {"kind": "worktree", "codebase": _codebase(tmp_path, exists=False)})
    d = artefacts.detail("20-contexts/personal/artefacts/2026-10-10-login")
    assert d["codebase"]["missing"] is True
    assert [r["summary"] for r in d["revs"]] == ["Login form", "Error states"]  # json, not git
    assert d["folder"] == str(folder) and d["design_system"] == "poltergeist-neutral"
    assert d["board_model"] is None
    assert artefacts.list_artefacts()[0]["codebase"]["missing"] is True


def test_detail_unknown_or_bad_id_is_none(vault: Path) -> None:
    assert artefacts.detail("../../etc") is None
    _folder(vault, "20-contexts/personal/prototypes/2026-10-10-empty")
    assert artefacts.detail("20-contexts/personal/prototypes/2026-10-10-empty") is None


def test_detail_revs_scratch_from_git_and_worktree_from_branch(vault: Path, tmp_path: Path, fake_wt) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    from ghostbrain.design import packs

    scratch = vault / "20-contexts/personal/prototypes/2026-10-10-scratch"
    scaffold.create(scratch, packs.BUILTIN_PACK_ID, title="Scratch")
    (scratch / "src" / "App.tsx").write_text("// v1\n")
    scaffold.commit(scratch, "rev 1: from git")
    (scratch / "board.json").write_text(json.dumps({"contexts": [], "items": [], "links": []}))
    artefacts.write(scratch, DATA | {"revs": [], "ui_rev": 1, "board_rev": 1, "board": True})
    d = artefacts.detail("20-contexts/personal/prototypes/2026-10-10-scratch")
    assert [(r["rev"], r["summary"]) for r in d["revs"]] == [(1, "from git")]
    assert d["board_model"] == {"contexts": [], "items": [], "links": []}

    wt = _folder(vault, "20-contexts/personal/artefacts/2026-10-10-wt")
    artefacts.write(wt, DATA | {"kind": "worktree", "codebase": _codebase(tmp_path)})
    d = artefacts.detail("20-contexts/personal/artefacts/2026-10-10-wt")
    assert [r["summary"] for r in d["revs"]] == ["from branch"]


def test_remove_worktree_calls_worktree_remove(vault: Path, tmp_path: Path, fake_wt) -> None:
    folder = _folder(vault, "20-contexts/personal/artefacts/2026-10-10-login")
    cb = _codebase(tmp_path)
    artefacts.write(folder, DATA | {"kind": "worktree", "codebase": cb})
    out = artefacts.remove_worktree("20-contexts/personal/artefacts/2026-10-10-login")
    assert out == fake_wt.remove_result and fake_wt.removed == [cb["worktree"]]


def test_remove_worktree_missing_is_success(vault: Path, tmp_path: Path, fake_wt) -> None:
    folder = _folder(vault, "20-contexts/personal/artefacts/2026-10-10-login")
    artefacts.write(folder, DATA | {"kind": "worktree", "codebase": _codebase(tmp_path, exists=False)})
    fake_wt.remove_error = RuntimeError("not a git repository")  # the repo went too
    out = artefacts.remove_worktree("20-contexts/personal/artefacts/2026-10-10-login")
    assert out["removed"] is True


def test_remove_worktree_refuses_scratch(vault: Path, fake_wt) -> None:
    folder = _folder(vault, "20-contexts/personal/prototypes/2026-10-10-login")
    artefacts.write(folder, DATA)
    with pytest.raises(artefacts.ArtefactError):
        artefacts.remove_worktree("20-contexts/personal/prototypes/2026-10-10-login")
    assert fake_wt.removed == []


def test_eject_scratch_only(vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(scaffold, "eject", lambda d: calls.append(d) or d)
    folder = _folder(vault, "20-contexts/personal/prototypes/2026-10-10-login")
    artefacts.write(folder, DATA)
    assert artefacts.eject("20-contexts/personal/prototypes/2026-10-10-login") == folder
    assert calls == [folder]
    wt = _folder(vault, "20-contexts/personal/artefacts/2026-10-10-wt")
    artefacts.write(wt, DATA | {"kind": "worktree", "codebase": _codebase(tmp_path)})
    with pytest.raises(artefacts.ArtefactError):
        artefacts.eject("20-contexts/personal/artefacts/2026-10-10-wt")


# -- C3: meeting link ----------------------------------------------------------------------


MEETING = (
    "---\n"
    "artifactType: transcript\n"
    "context: personal\n"
    "created: '2026-10-10T10:30:00+00:00'\n"
    "title: 'Transcript: Login review'\n"
    "type: artifact\n"
    "---\n\n"
    "# Transcript — Login review\n\nwe talked\n"
)


def _session_artefact(vault: Path, wav: Path, *, title: str = "Meeting") -> Path:
    folder = _folder(vault, "20-contexts/personal/prototypes/2026-10-10-meeting-1015")
    artefacts.write(folder, DATA | {"title": title})
    ptr = ds.pointer_path(wav)
    ptr.parent.mkdir(parents=True, exist_ok=True)
    ptr.write_text(json.dumps({"wav": str(wav), "prototype_dir": str(folder)}))
    return folder


def _meeting(vault: Path, text: str = MEETING) -> Path:
    note = vault / "20-contexts/personal/calendar/transcripts/login-review-ab12.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(text)
    return note


def test_link_meeting_updates_both_sides(vault: Path, tmp_path: Path) -> None:
    wav = tmp_path / "rec" / "meeting.wav"
    folder = _session_artefact(vault, wav)
    note = _meeting(vault)

    assert artefacts.link_meeting(wav, note) is True

    data = artefacts.load(folder)
    assert data["meeting"] == "Login review"
    assert data["meeting_path"] == "20-contexts/personal/calendar/transcripts/login-review-ab12.md"
    assert data["title"] == "Login review"  # placeholder title replaced
    readme = (folder / "README.md").read_text()
    assert "[[20-contexts/personal/calendar/transcripts/login-review-ab12|Login review]]" in readme

    text = note.read_text()
    meta, body = split_frontmatter(text)
    aid = "20-contexts/personal/prototypes/2026-10-10-meeting-1015"
    assert meta["artefacts"] == [f"{aid}/README"]
    assert meta["title"] == "Transcript: Login review"
    assert meta["created"] == "2026-10-10T10:30:00+00:00"  # other fields untouched
    assert text.startswith("---\nartifactType: transcript\ncontext: personal\n")
    assert body.endswith(f"\n## Artefacts\n\n- [[{aid}/README|Login review]] — prototype, rev 2\n")
    assert "we talked" in body


def test_link_meeting_keeps_a_real_title(vault: Path, tmp_path: Path) -> None:
    wav = tmp_path / "meeting.wav"
    folder = _session_artefact(vault, wav, title="Checkout redesign")
    artefacts.link_meeting(wav, _meeting(vault))
    assert artefacts.load(folder)["title"] == "Checkout redesign"


def test_link_meeting_idempotent(vault: Path, tmp_path: Path) -> None:
    wav = tmp_path / "meeting.wav"
    _session_artefact(vault, wav)
    note = _meeting(vault)
    assert artefacts.link_meeting(wav, note) is True
    once = note.read_text()
    assert artefacts.link_meeting(wav, note) is True
    assert note.read_text() == once
    assert once.count("## Artefacts") == 1 and once.count("/README|") == 1


def test_link_meeting_adds_line_to_existing_section_and_list(vault: Path, tmp_path: Path) -> None:
    wav = tmp_path / "meeting.wav"
    _session_artefact(vault, wav)
    note = _meeting(vault, MEETING.replace("type: artifact\n", "type: artifact\nartefacts:\n- other/README\n")
                    + "\n## Artefacts\n\n- [[other/README|Other]] — board, rev 1\n")
    artefacts.link_meeting(wav, note)
    meta, body = split_frontmatter(note.read_text())
    aid = "20-contexts/personal/prototypes/2026-10-10-meeting-1015"
    assert meta["artefacts"] == ["other/README", f"{aid}/README"]
    assert body.count("## Artefacts") == 1
    assert body.endswith(f"- [[other/README|Other]] — board, rev 1\n- [[{aid}/README|Login review]] — prototype, rev 2\n")


def test_link_meeting_note_without_frontmatter(vault: Path, tmp_path: Path) -> None:
    wav = tmp_path / "meeting.wav"
    _session_artefact(vault, wav)
    note = _meeting(vault, "# Standup\n\nnotes\n")
    assert artefacts.link_meeting(wav, note) is True
    meta, body = split_frontmatter(note.read_text())
    assert meta["artefacts"] and body.lstrip().startswith("# Standup\n")
    assert "|Standup]] — prototype, rev 2" in body  # title from the H1


def test_link_meeting_without_session_is_noop(vault: Path, tmp_path: Path) -> None:
    note = _meeting(vault)
    assert artefacts.link_meeting(tmp_path / "x.wav", note) is False
    assert note.read_text() == MEETING


def test_link_meeting_pointer_without_artefact_is_noop(vault: Path, tmp_path: Path) -> None:
    wav = tmp_path / "meeting.wav"
    ptr = ds.pointer_path(wav)
    ptr.parent.mkdir(parents=True, exist_ok=True)
    ptr.write_text(json.dumps({"wav": str(wav), "prototype_dir": str(tmp_path / "gone")}))
    note = _meeting(vault)
    assert artefacts.link_meeting(wav, note) is False
    assert note.read_text() == MEETING


def test_link_meeting_never_raises(vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = tmp_path / "meeting.wav"
    _session_artefact(vault, wav)
    monkeypatch.setattr(artefacts, "write", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert artefacts.link_meeting(wav, _meeting(vault)) is False


def test_link_meeting_updates_live_session_title(vault: Path, tmp_path: Path, monkeypatch) -> None:
    wav = tmp_path / "meeting.wav"
    _session_artefact(vault, wav)
    live = types.SimpleNamespace(recording_title=None)
    monkeypatch.setattr(ds, "get", lambda w: live if Path(w) == wav else None)
    artefacts.link_meeting(wav, _meeting(vault))
    assert live.recording_title == "Login review"


def test_link_meeting_is_registered_on_the_recorder_hook() -> None:
    assert artefacts.link_meeting in hooks._on_transcribed


# -- against the real worktree module ---------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                    *args], cwd=cwd, check=True, capture_output=True)


def test_real_worktree_detail_and_remove_after_manual_delete(vault: Path, tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    from datetime import date

    from ghostbrain.design import worktree

    repo = tmp_path / "code" / "web"
    (repo / "src").mkdir(parents=True)
    (repo / "package.json").write_text('{"name":"web","scripts":{"dev":"vite"},"dependencies":{"react":"18"}}')
    (repo / "src" / "App.tsx").write_text("v0")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="login")
    (wt.path / "src" / "App.tsx").write_text("v1")
    worktree.commit(wt, "rev 1: login form")

    folder = _folder(vault, "20-contexts/personal/artefacts/2026-10-10-login")
    artefacts.write(folder, DATA | {"kind": "worktree", "codebase": wt.to_dict(), "revs": []})
    aid = "20-contexts/personal/artefacts/2026-10-10-login"
    d = artefacts.detail(aid)
    assert d["codebase"]["missing"] is False
    assert [(r["rev"], r["summary"]) for r in d["revs"]] == [(1, "login form")]

    shutil.rmtree(wt.path)  # deleted by hand
    assert artefacts.detail(aid)["codebase"]["missing"] is True
    out = artefacts.remove_worktree(aid)
    assert out["removed"] is True and out["branch_kept"] is True  # unmerged rev 1 kept
