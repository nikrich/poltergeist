# Jot Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Jots sidebar the context → project → folder tree chats and docs have (create / rename / delete folders, drag jots and folders), backed by a `folder` frontmatter field and a registry.

**Architecture:** A jot's folder is a frontmatter field relative to its location; `~/.ghostbrain/state/jot-folders.json` keeps empty folders. The folder plumbing chats already use is lifted into `scoped_folders.py` and shared by `chat_folders.py` and a new `jot_folders.py`. Moves across locations reuse `notes_manual.move_jot`. The desktop `JotTree` is rewritten on the shared `ScopeTree`.

**Tech Stack:** Python 3.11+ / FastAPI / pydantic / python-frontmatter / pytest; Electron + React 18 + TanStack Query + Vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-10-12-jot-folders-design.md`

## Global Constraints

- Work only in the worktree `/Users/jannik/development/nikrich/ghost-brain-jot-folders` on branch `feat/jot-folders`. Every shell command starts with `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders` (subagent git otherwise runs in the main checkout); verify `git rev-parse --abbrev-ref HEAD` prints `feat/jot-folders` before each commit.
- Registry file: `state_dir() / "jot-folders.json"`, shape `{"folders": [{"context", "project", "path"}]}`.
- Folder paths validated by `doc_library.scope.clean_rel` (via `clean_path`).
- Routing (router, manual `/route`, `route-auto`, chat export, `mark_manual_review`) clears `folder`.
- Jot writes go through `vault_write` (never raw file writes).
- `/v1/notes/tree` and `/v1/notes/folders` routes are declared before every `/{jot_id}` route.
- Public repo: no employer/client/product names in code, tests, fixtures or commit messages.
- Desktop typecheck is `npm run typecheck` (tsc -b), never `tsc --noEmit`.
- Never run pytest without `GHOSTBRAIN_STATE_DIR` sandboxed by fixtures (the suite's fixtures already do this; don't add tests that touch `~/.ghostbrain`).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. A jot whose `folder` frontmatter was hand-edited to something invalid (`../x`, `/abs`, `a//b`) — expected: shown at its location root, never crashes the tree or creates a `..` node. (Task 3 test `test_invalid_folder_field_shows_at_root`.)
2. Moving a folder that contains a jot which fails to move (file vanished mid-operation) — expected: the others move, 409 names the failed jot, the folder still shows the stuck jot at its old path. (Task 4 test `test_move_folder_partial_failure_reports_ids`.)
3. Dragging a pending inbox jot into a folder — expected: it gets filed (routed, file moved out of the inbox) with the folder set, and it leaves the Inbox section. (Task 3 test `test_move_pending_jot_into_folder_files_it`.)
4. Re-routing a jot that sits in a folder to the same context it is already in — expected: folder cleared, no file move. (Task 2 test `test_route_same_location_clears_folder`.)
5. Search query present while a jot is selected — expected: selection and editor stay, the pane shows the flat results; clearing search returns to the tree with the jot revealed. (Task 9 test `keeps the selected jot when searching`.)

---

## File Structure

| File | Responsibility |
|---|---|
| `ghostbrain/api/repo/scoped_folders.py` (new) | Shared folder plumbing: errors, `clean_path`, `check_location`, `with_parents`, `under`, `Registry`, `build_scopes`. |
| `ghostbrain/api/repo/chat_folders.py` | Re-pointed onto `scoped_folders`; same public names. |
| `ghostbrain/api/repo/notes_manual.py` | `move_jot(folder=)`, folder cleared on routing / manual review, `folder` in list rows. |
| `ghostbrain/api/repo/jot_folders.py` (new) | Jot folder registry, create / move / delete folder, `move_jot_to`, `repoint_project`, `tree`. |
| `ghostbrain/api/repo/projects.py` | Rename hook calls `jot_folders.repoint_project`. |
| `ghostbrain/api/models/note.py` | `folder` on `NoteListItem`; `JotTreeItem`, `JotFolderNode`, `JotScope`, `JotTree`, `MoveJotRequest`. |
| `ghostbrain/api/routes/notes.py` | `GET /tree`, `/folders` CRUD, `PATCH /{id}/location`. |
| `desktop/src/shared/api-types.ts` | Jot tree types. |
| `desktop/src/renderer/lib/api/hooks.ts` | `useJotTree`, `useMoveJot`, jot folder hooks. |
| `desktop/src/renderer/components/JotTree.tsx` | Rewritten on `ScopeTree`; also exports `JotList`, `flattenJotTree`, `shortDate`. |
| `desktop/src/renderer/screens/jots.tsx` | Uses the tree; flat list while searching. |
| `desktop/src/main/demo/fixtures.ts` | Demo `/v1/notes/tree`. |

---

### Task 1: Extract shared folder plumbing into `scoped_folders.py`

Pure refactor. Chat behaviour must not change; `tests/test_chat_folders.py`, `tests/test_project_rename.py` and `ghostbrain/api/tests/test_routes_chat_folders.py` keep passing untouched.

**Files:**
- Create: `ghostbrain/api/repo/scoped_folders.py`
- Modify: `ghostbrain/api/repo/chat_folders.py`
- Test: `tests/test_scoped_folders.py` (new)

**Interfaces:**
- Produces (all in `ghostbrain.api.repo.scoped_folders`):
  - `Entry = tuple[str, str | None, str]`
  - exceptions `FolderError(status=422)`, `InvalidLocation(FolderError, 422)`, `FolderNotFound(404)`, `FolderExists(409)`, `FolderNotEmpty(409)`
  - `clean_path(path: str | None) -> str` (raises `InvalidLocation`)
  - `check_location(context: str, project: str | None, *, for_write: bool = True) -> None`
  - `with_parents(entries) -> set[Entry]`, `under(path: str, root: str) -> bool`
  - `class Registry(path_fn: Callable[[], Path], label: str)` with `.load() -> set[Entry]`, `.save(entries: set[Entry]) -> None`, `.repoint(context, old_slug, new_slug) -> None`
  - `build_scopes(folders: set[Entry], by_loc: dict[tuple[str, str | None], dict[str, list[dict]]], *, leaf_key: str, sort_key: str) -> list[dict]` — each scope `{"context","project","name","archived","folders":[node], leaf_key: [...]}`, each node `{"name","path","folders":[...], leaf_key: [...]}`, leaves sorted by `sort_key` descending.

- [ ] **Step 1: Write the failing tests**

`tests/test_scoped_folders.py`:

```python
import json

import pytest

from ghostbrain.api.repo import projects, scoped_folders as sf


@pytest.fixture
def env(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    (v / "90-meta" / "routing.yaml").write_text("contexts:\n  - work\n  - personal\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(v))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


def test_registry_round_trip_and_corrupt(tmp_path):
    reg = sf.Registry(lambda: tmp_path / "r" / "f.json", "test")
    assert reg.load() == set()
    reg.save({("work", None, "a"), ("work", "atlas", "b/c")})
    assert reg.load() == {("work", None, "a"), ("work", "atlas", "b/c")}
    (tmp_path / "r" / "f.json").write_text("{not json", encoding="utf-8")
    assert reg.load() == set()


def test_registry_repoint(tmp_path):
    reg = sf.Registry(lambda: tmp_path / "f.json", "test")
    reg.save({("work", "old", "a"), ("work", None, "b"), ("personal", "old", "c")})
    reg.repoint("work", "old", "new")
    assert reg.load() == {("work", "new", "a"), ("work", None, "b"), ("personal", "old", "c")}


def test_with_parents_and_under():
    assert sf.with_parents({("w", None, "a/b/c")}) == {("w", None, "a"), ("w", None, "a/b"), ("w", None, "a/b/c")}
    assert sf.under("a/b", "a") and sf.under("a", "a") and not sf.under("ab", "a")


def test_build_scopes_shapes_and_sorts(env):
    atlas = projects.create_project("work", "Atlas")["slug"]
    folders = {("work", None, "q4"), ("work", None, "q4/plans")}
    by_loc = {
        ("work", None): {"": [{"id": "x", "t": 1}, {"id": "y", "t": 3}], "q4/plans": [{"id": "z", "t": 2}]},
    }
    scopes = sf.build_scopes(folders, by_loc, leaf_key="jots", sort_key="t")
    assert [(s["context"], s["project"]) for s in scopes] == [("work", None), ("work", atlas), ("personal", None)]
    work = scopes[0]
    assert [j["id"] for j in work["jots"]] == ["y", "x"]
    assert work["folders"][0]["name"] == "q4"
    assert work["folders"][0]["folders"][0]["jots"][0]["id"] == "z"


def test_build_scopes_hides_empty_archived_project(env):
    slug = projects.create_project("work", "Old")["slug"]
    projects.update_project("work", slug, archived=True)
    scopes = sf.build_scopes(set(), {}, leaf_key="jots", sort_key="t")
    assert ("work", slug) not in [(s["context"], s["project"]) for s in scopes]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest tests/test_scoped_folders.py -q`
Expected: FAIL — `ImportError: cannot import name 'scoped_folders'`.

- [ ] **Step 3: Create `scoped_folders.py`**

Move the bodies verbatim from `chat_folders.py` (`clean_path`, `check_location`, `_with_parents`, `_under`, `_registry`/`_save_registry`, `_node`, the scope loop in `tree`) and parameterize:

```python
"""Folder plumbing shared by chat and jot folders (jot folders spec §1).

A folder lives at a location — (context, project slug | None) — and is a
slash path relative to it. A registry file only keeps EMPTY folders alive;
callers union it with the folders their items reference.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from ghostbrain import routing_config
from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.api.repo.doc_library.scope import InvalidPath, clean_rel

log = logging.getLogger("ghostbrain.folders")

Entry = tuple[str, "str | None", str]  # (context, project, path)


class FolderError(Exception):
    status = 422


class InvalidLocation(FolderError):
    status = 422


class FolderNotFound(FolderError):
    status = 404


class FolderExists(FolderError):
    status = 409


class FolderNotEmpty(FolderError):
    status = 409


def clean_path(path: str | None) -> str:
    try:
        return clean_rel(path or "")
    except InvalidPath as e:
        raise InvalidLocation(str(e)) from None


def check_location(context: str, project: str | None, *, for_write: bool = True) -> None:
    if context not in routing_config.contexts():
        raise InvalidLocation(f"unknown context: {context}")
    if project is None:
        return
    p = projects_repo.get_project(context, project)
    if p is None:
        raise InvalidLocation(f"unknown project: {context}/{project}")
    if for_write and p.get("archived"):
        raise InvalidLocation(f"project is archived: {context}/{project}")


def with_parents(entries) -> set[Entry]:
    out: set[Entry] = set()
    for c, p, path in entries:
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            out.add((c, p, "/".join(parts[:i])))
    return out


def under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


class Registry:
    def __init__(self, path_fn: Callable[[], Path], label: str) -> None:
        self._path_fn = path_fn
        self._label = label

    def load(self) -> set[Entry]:
        path = self._path_fn()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {(f["context"], f.get("project"), f["path"]) for f in raw.get("folders", [])}
        except FileNotFoundError:
            return set()
        except (json.JSONDecodeError, OSError, KeyError, TypeError, AttributeError):
            log.warning("unreadable %s folder registry %s; treating as empty", self._label, path)
            return set()

    def save(self, entries: set[Entry]) -> None:
        target = self._path_fn()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        rows = [{"context": c, "project": p, "path": path}
                for c, p, path in sorted(entries, key=lambda e: (e[0], e[1] or "", e[2]))]
        tmp.write_text(json.dumps({"folders": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)

    def repoint(self, context: str, old_slug: str, new_slug: str) -> None:
        self.save({(c, new_slug if (c == context and p == old_slug) else p, path) for c, p, path in self.load()})


def _node(name: str, path: str, entries: set[str], by_folder: dict[str, list[dict]], leaf_key: str, sort_key: str) -> dict:
    prefix = f"{path}/" if path else ""
    child_names = sorted({e[len(prefix):].split("/", 1)[0] for e in entries if e.startswith(prefix) and e != path and e})
    return {
        "name": name,
        "path": path,
        "folders": [_node(n, f"{prefix}{n}", entries, by_folder, leaf_key, sort_key) for n in child_names],
        leaf_key: sorted(by_folder.get(path, []), key=lambda s: s[sort_key], reverse=True),
    }


def build_scopes(folders: set[Entry], by_loc: dict, *, leaf_key: str, sort_key: str) -> list[dict]:
    """Contexts in routing order; each bare context then its projects by name.
    Archived projects with nothing in them are left out."""
    contexts = routing_config.contexts()
    projs = projects_repo.list_projects(include_archived=True)

    def scope(ctx: str, proj: str | None, name: str, archived: bool) -> dict:
        entries = {path for c, p, path in folders if (c, p) == (ctx, proj)}
        root = _node(name, "", entries, by_loc.get((ctx, proj), {}), leaf_key, sort_key)
        return {"context": ctx, "project": proj, "name": name, "archived": archived,
                "folders": root["folders"], leaf_key: root[leaf_key]}

    scopes = []
    for ctx in contexts:
        scopes.append(scope(ctx, None, ctx, False))
        for p in sorted((p for p in projs if p["context"] == ctx), key=lambda p: p["name"].lower()):
            s = scope(ctx, p["slug"], p["name"], bool(p.get("archived")))
            if s["archived"] and not s[leaf_key] and not s["folders"]:
                continue
            scopes.append(s)
    return scopes


def known_locations() -> tuple[list[str], set[tuple[str, str]]]:
    """(contexts, {(context, slug)} of every project incl. archived)."""
    projs = projects_repo.list_projects(include_archived=True)
    return routing_config.contexts(), {(p["context"], p["slug"]) for p in projs}
```

- [ ] **Step 4: Re-point `chat_folders.py`**

Replace the moved definitions with imports/aliases so every existing name keeps working (tests use `cf.clean_path`, `cf.InvalidLocation`, `cf.check_location`, `chat_folders._registry`):

```python
from ghostbrain.api.repo import scoped_folders as sf
from ghostbrain.api.repo.scoped_folders import (  # re-exported: callers import these from here
    Entry, FolderExists, FolderNotEmpty, FolderNotFound, InvalidLocation, check_location, clean_path,
)

ChatFolderError = sf.FolderError


class ChatNotFound(ChatFolderError):
    status = 404


_REGISTRY = sf.Registry(lambda: chats_dir() / "folders.json", "chat")
_registry = _REGISTRY.load
_save_registry = _REGISTRY.save
_with_parents = sf.with_parents
_under = sf.under
```

Delete the now-duplicate local definitions (`clean_path`, `check_location`, `_registry_path`, `_registry`, `_save_registry`, `_with_parents`, `_under`, `_node`, error classes other than `ChatNotFound`). In `repoint_project` replace the `_save_registry({...})` line with `_REGISTRY.repoint(context, old_slug, new_slug)`. In `tree()` replace the `contexts = …` / `projs = …` / `known = …` lines with `contexts, known = sf.known_locations()` (and `known` membership tests stay `(ctx, proj) not in known`), and replace the `scope()` helper and loop with:

```python
    return {"unfiled": unfiled, "scopes": sf.build_scopes(folders, by_loc, leaf_key="chats", sort_key="updated_at")}
```

Remove now-unused imports (`json`, `routing_config`, `projects_repo`, `InvalidPath`, `clean_rel`) only if nothing else in the file uses them.

- [ ] **Step 5: Run the new and the existing chat tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest tests/test_scoped_folders.py tests/test_chat_folders.py tests/test_project_rename.py ghostbrain/api/tests/test_routes_chat_folders.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && git add ghostbrain/api/repo/scoped_folders.py ghostbrain/api/repo/chat_folders.py tests/test_scoped_folders.py && git commit -m "refactor(folders): share chat folder plumbing in scoped_folders

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `folder` on jots — `move_jot`, manual review, list rows

**Files:**
- Modify: `ghostbrain/api/repo/notes_manual.py` (`move_jot` ~269-323, `mark_manual_review` ~326, `list_jots` ~448)
- Modify: `ghostbrain/api/models/note.py` (`NoteListItem`)
- Test: `ghostbrain/api/tests/test_notes_manual_folder.py` (new)

**Interfaces:**
- Produces: `move_jot(jot_id, *, to_context, to_project=None, confidence, method, reasoning, actor=USER, base_etag=None, folder: str | None = None) -> dict` — writes `folder` (or deletes it when `None`). Same-location call: if `folder` differs from the stored one, a fields-only write of `folder` + `updated`; otherwise no write. `list_jots` rows gain `"folder": str | None`.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_notes_manual_folder.py`:

```python
from datetime import datetime, timezone

import frontmatter

from ghostbrain.api.repo import notes_manual as nm


def _routed(vault, ctx="work", folder=None):
    (vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    rec = nm.write_inbox_jot("hello there", captured_at=datetime(2026, 5, 14, 9, tzinfo=timezone.utc))
    nm.move_jot(rec["id"], to_context=ctx, confidence=1.0, method="user", reasoning="t", folder=folder)
    return rec["id"]


def _fm(vault, jot_id):
    return frontmatter.load(vault / nm.read_jot(jot_id)["path"])


def test_move_jot_writes_folder(tmp_vault):
    jid = _routed(tmp_vault, folder="q4/plans")
    assert _fm(tmp_vault, jid)["folder"] == "q4/plans"
    assert nm.list_jots()["items"][0]["folder"] == "q4/plans"


def test_same_location_folder_change_writes_without_moving(tmp_vault):
    jid = _routed(tmp_vault)
    before = nm.read_jot(jid)["path"]
    res = nm.move_jot(jid, to_context="work", confidence=1.0, method="user", reasoning="t", folder="ideas")
    assert res["path"] == before
    assert _fm(tmp_vault, jid)["folder"] == "ideas"


def test_route_same_location_clears_folder(tmp_vault):
    jid = _routed(tmp_vault, folder="ideas")
    nm.move_jot(jid, to_context="work", confidence=0.9, method="llm", reasoning="router")
    assert "folder" not in _fm(tmp_vault, jid).metadata


def test_route_other_context_clears_folder(tmp_vault):
    jid = _routed(tmp_vault, folder="ideas")
    nm.move_jot(jid, to_context="personal", confidence=0.9, method="llm", reasoning="router")
    fm = _fm(tmp_vault, jid)
    assert fm["context"] == "personal" and "folder" not in fm.metadata


def test_mark_manual_review_clears_folder(tmp_vault):
    jid = _routed(tmp_vault, folder="ideas")
    nm.mark_manual_review(jid, reasoning="unsure")
    assert "folder" not in _fm(tmp_vault, jid).metadata


def test_list_rows_default_folder_none(tmp_vault):
    _routed(tmp_vault)
    assert nm.list_jots()["items"][0]["folder"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest ghostbrain/api/tests/test_notes_manual_folder.py -q`
Expected: FAIL — `TypeError: move_jot() got an unexpected keyword argument 'folder'`.

- [ ] **Step 3: Implement**

In `move_jot`, add the keyword `folder: str | None = None` after `base_etag`. Replace the `src.resolve() == dst` early return with:

```python
    if src.resolve() == dst:
        current = frontmatter.load(src).get("folder") or None
        if current == folder:
            return {"id": jot_id, "path": _vault_rel(dst), "context": to_context, "project": to_project}
        res = vault_write.write(
            _vault_rel(src), fields={"folder": folder or DELETE_FIELD, "updated": _now_iso()},
            actor=actor, reason="moved jot to a folder" if folder else "moved jot out of its folder",
            base_etag=base_etag,
        )
        return {
            "id": jot_id, "path": res.path, "context": to_context, "project": to_project,
            "etag": res.etag, "status": res.status, "changeId": res.change_id,
        }
```

Add `"folder": folder or DELETE_FIELD,` to the `fields` dict of the move write. (`frontmatter` is already imported in this module — `list_jots` uses it.)

In `mark_manual_review`, add `"folder": DELETE_FIELD` to its `fields`.

In `list_jots`, add `"folder": post.get("folder") or None,` to `item`.

In `models/note.py` `NoteListItem`, add `folder: str | None = None` after `project`.

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest ghostbrain/api/tests/test_notes_manual_folder.py ghostbrain/api/tests/test_notes_manual_io.py ghostbrain/api/tests/test_routes_notes_list.py ghostbrain/api/tests/test_routes_notes_mutate.py ghostbrain/api/tests/test_routes_notes_route_auto.py -q`
Expected: all PASS. If an existing test asserts an exact list-row dict, add `"folder": None` to its expected dict.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && git add ghostbrain/api/repo/notes_manual.py ghostbrain/api/models/note.py ghostbrain/api/tests/test_notes_manual_folder.py && git commit -m "feat(jots): folder frontmatter field, cleared on routing

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `jot_folders.py` — registry, create / delete, move a jot, tree

**Files:**
- Create: `ghostbrain/api/repo/jot_folders.py`
- Test: `ghostbrain/api/tests/test_jot_folders.py` (new)

**Interfaces:**
- Consumes: `scoped_folders` (Task 1), `notes_manual.move_jot(..., folder=)` and `list_jots` rows with `folder` (Task 2).
- Produces (`ghostbrain.api.repo.jot_folders`):
  - `lock: threading.RLock`
  - `JotFolderError = scoped_folders.FolderError`; `JotMissing(JotFolderError, 404)`; `FolderMoveIncomplete(JotFolderError, 409)` (defined here, used in Task 4)
  - `create(context, project, path) -> dict` (FolderRef dict)
  - `delete(context, project, path) -> None`
  - `move_jot_to(jot_id, *, context, project, folder, actor=USER) -> dict` (the `move_jot` result)
  - `tree() -> {"inbox": [...], "unrouted": [...], "scopes": [...]}`; items are list rows + `"unknownLocation": bool`; scopes use `leaf_key="jots"`, `sort_key="created"`.
  - private: `_registry()`, `_save_registry()`, `_jots()`, `_folder_of(row) -> str`, `_all_folders(rows=None)`

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_jot_folders.py`:

```python
from datetime import datetime, timedelta, timezone

import frontmatter
import pytest

from ghostbrain.api.repo import jot_folders as jf, notes_manual as nm, projects


T0 = datetime(2026, 5, 14, 9, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_vault, tmp_state_dir):
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    return {"vault": tmp_vault, "atlas": projects.create_project("work", "Atlas")["slug"]}


def _jot(text="hello", minutes=0):
    return nm.write_inbox_jot(text, captured_at=T0 + timedelta(minutes=minutes))["id"]


def _fm(env, jid):
    return frontmatter.load(env["vault"] / nm.read_jot(jid)["path"])


def _scope(t, ctx, proj=None):
    return next(s for s in t["scopes"] if (s["context"], s["project"]) == (ctx, proj))


def test_create_and_delete_empty_folder(env):
    assert jf.create("work", env["atlas"], "q4/plans") == {"context": "work", "project": env["atlas"], "path": "q4/plans"}
    with pytest.raises(jf.sf.FolderExists):
        jf.create("work", env["atlas"], "q4/plans")
    assert ("work", env["atlas"], "q4") in jf._all_folders()
    with pytest.raises(jf.sf.FolderNotEmpty):
        jf.delete("work", env["atlas"], "q4")
    jf.delete("work", env["atlas"], "q4/plans")
    jf.delete("work", env["atlas"], "q4")
    assert jf._all_folders() == set()


def test_create_rejects_bad_location_and_path(env):
    with pytest.raises(jf.sf.InvalidLocation):
        jf.create("nope", None, "x")
    with pytest.raises(jf.sf.InvalidLocation):
        jf.create("work", None, "../x")
    projects.update_project("work", env["atlas"], archived=True)
    with pytest.raises(jf.sf.InvalidLocation):
        jf.create("work", env["atlas"], "x")


def test_delete_refuses_folder_holding_a_jot(env):
    jid = _jot()
    jf.move_jot_to(jid, context="work", project=None, folder="ideas")
    with pytest.raises(jf.sf.FolderNotEmpty):
        jf.delete("work", None, "ideas")


def test_move_jot_into_new_folder_registers_it(env):
    jid = _jot()
    jf.move_jot_to(jid, context="work", project=env["atlas"], folder="a/b")
    fm = _fm(env, jid)
    assert (fm["context"], fm["project"], fm["folder"]) == ("work", env["atlas"], "a/b")
    assert ("work", env["atlas"], "a/b") in jf._registry()


def test_move_pending_jot_into_folder_files_it(env):
    jid = _jot()
    jf.move_jot_to(jid, context="work", project=None, folder="ideas")
    fm = _fm(env, jid)
    assert fm["routingStatus"] == "routed"
    assert "00-inbox" not in nm.read_jot(jid)["path"]
    t = jf.tree()
    assert t["inbox"] == []
    assert _scope(t, "work")["folders"][0]["jots"][0]["id"] == jid


def test_move_jot_errors(env):
    with pytest.raises(jf.JotMissing):
        jf.move_jot_to("manual-19000101T000000-nope", context="work", project=None, folder=None)
    jid = _jot()
    with pytest.raises(jf.sf.InvalidLocation):
        jf.move_jot_to(jid, context="work", project=None, folder="../x")


def test_tree_sections_and_order(env):
    pending = _jot("pending one", 0)
    review = _jot("review one", 1)
    nm.mark_manual_review(review, reasoning="unsure")
    old = _jot("old", 2)
    new = _jot("new", 3)
    jf.move_jot_to(old, context="work", project=None, folder=None)
    jf.move_jot_to(new, context="work", project=None, folder=None)
    t = jf.tree()
    assert [j["id"] for j in t["inbox"]] == [pending]
    assert [j["id"] for j in t["unrouted"]] == [review]
    assert [j["id"] for j in _scope(t, "work")["jots"]] == [new, old]
    assert _scope(t, "work")["jots"][0]["unknownLocation"] is False


def test_unknown_context_goes_to_unrouted(env):
    jid = _jot()
    jf.move_jot_to(jid, context="personal", project=None, folder=None)
    (env["vault"] / "90-meta" / "routing.yaml").write_text("contexts:\n  - work\n", encoding="utf-8")
    t = jf.tree()
    assert [(j["id"], j["unknownLocation"]) for j in t["unrouted"]] == [(jid, True)]


def test_invalid_folder_field_shows_at_root(env):
    jid = _jot()
    jf.move_jot_to(jid, context="work", project=None, folder=None)
    nm.set_frontmatter_fields(jid, {"folder": "../escape"})
    t = jf.tree()
    work = _scope(t, "work")
    assert [j["id"] for j in work["jots"]] == [jid]
    assert work["folders"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest ghostbrain/api/tests/test_jot_folders.py -q`
Expected: FAIL — `ImportError: cannot import name 'jot_folders'`.

- [ ] **Step 3: Implement `jot_folders.py`**

```python
"""Jot folders (jot folders spec §1–2).

A jot's location is its (context, project) plus a ``folder`` frontmatter path
relative to it. ``jot-folders.json`` in the state dir only keeps EMPTY folders
alive: the folder set is registry ∪ every folder a routed jot references ∪
their parents, so losing the registry only loses empty folders.
"""
from __future__ import annotations

import logging
import threading

from ghostbrain.api.repo import notes_manual
from ghostbrain.api.repo import scoped_folders as sf
from ghostbrain.paths import state_dir
from ghostbrain.vault_write import USER, Actor

log = logging.getLogger("ghostbrain.jot.folders")

lock = threading.RLock()  # every registry read-modify-write + multi-jot folder op

JotFolderError = sf.FolderError


class JotMissing(JotFolderError):
    status = 404


class FolderMoveIncomplete(JotFolderError):
    status = 409


_REGISTRY = sf.Registry(lambda: state_dir() / "jot-folders.json", "jot")
_registry = _REGISTRY.load
_save_registry = _REGISTRY.save


def _jots() -> list[dict]:
    return notes_manual.list_jots(limit=1_000_000)["items"]


def _folder_of(row: dict) -> str:
    """The row's folder, cleaned; a hand-edited invalid value counts as the root."""
    try:
        return sf.clean_path(row.get("folder"))
    except sf.InvalidLocation:
        return ""


def _filed(row: dict) -> bool:
    return row.get("routingStatus") == "routed" and bool(row.get("context"))


def _all_folders(rows: list[dict] | None = None) -> set[sf.Entry]:
    rows = _jots() if rows is None else rows
    used = {(r["context"], r.get("project"), f) for r in rows if _filed(r) and (f := _folder_of(r))}
    return sf.with_parents(_registry() | used)


def create(context: str, project: str | None, path: str) -> dict:
    cleaned = sf.clean_path(path)
    if not cleaned:
        raise sf.InvalidLocation("folder path is required")
    with lock:
        sf.check_location(context, project)
        if (context, project, cleaned) in _all_folders():
            raise sf.FolderExists(f"folder already exists: {cleaned}")
        _save_registry(_registry() | sf.with_parents({(context, project, cleaned)}))
    return {"context": context, "project": project, "path": cleaned}


def delete(context: str, project: str | None, path: str) -> None:
    cleaned = sf.clean_path(path)
    with lock:
        rows = _jots()
        folders = _all_folders(rows)
        if (context, project, cleaned) not in folders:
            raise sf.FolderNotFound(f"folder not found: {cleaned}")
        if any((c, p) == (context, project) and f != cleaned and sf.under(f, cleaned) for c, p, f in folders):
            raise sf.FolderNotEmpty(f"folder is not empty: {cleaned}")
        if any(_filed(r) and (r["context"], r.get("project")) == (context, project)
               and _folder_of(r) and sf.under(_folder_of(r), cleaned) for r in rows):
            raise sf.FolderNotEmpty(f"folder is not empty: {cleaned}")
        _save_registry(_registry() - {(context, project, cleaned)})


def move_jot_to(jot_id: str, *, context: str, project: str | None, folder: str | None, actor: Actor = USER) -> dict:
    """File a jot at (context, project, folder). Files pending / manual-review jots too."""
    with lock:
        sf.check_location(context, project)
        cleaned = sf.clean_path(folder) or None
        if cleaned and (context, project, cleaned) not in _all_folders():
            _save_registry(_registry() | sf.with_parents({(context, project, cleaned)}))
        try:
            return notes_manual.move_jot(
                jot_id, to_context=context, to_project=project, folder=cleaned,
                confidence=1.0, method="user", reasoning="moved by user", actor=actor,
            )
        except notes_manual.JotNotFound:
            raise JotMissing(f"jot not found: {jot_id}") from None


def repoint_project(context: str, old_slug: str, new_slug: str) -> None:
    with lock:
        _REGISTRY.repoint(context, old_slug, new_slug)


def _item(row: dict, unknown: bool = False) -> dict:
    return {**row, "folder": _folder_of(row) or None, "unknownLocation": unknown}


def tree() -> dict:
    with lock:
        rows = _jots()
        folders = _all_folders(rows)
    contexts, known = sf.known_locations()
    inbox: list[dict] = []
    unrouted: list[dict] = []
    by_loc: dict[tuple, dict[str, list[dict]]] = {}
    for r in rows:  # list_jots is already newest-first
        if r["routingStatus"] == "pending":
            inbox.append(_item(r))
        elif not _filed(r):
            unrouted.append(_item(r))
        elif r["context"] not in contexts or (r.get("project") and (r["context"], r["project"]) not in known):
            unrouted.append(_item(r, unknown=True))
        else:
            by_loc.setdefault((r["context"], r.get("project")), {}).setdefault(_folder_of(r), []).append(_item(r))
    return {
        "inbox": inbox,
        "unrouted": unrouted,
        "scopes": sf.build_scopes(folders, by_loc, leaf_key="jots", sort_key="created"),
    }
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest ghostbrain/api/tests/test_jot_folders.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && git add ghostbrain/api/repo/jot_folders.py ghostbrain/api/tests/test_jot_folders.py && git commit -m "feat(jots): jot folder registry, create/delete, move a jot, tree

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Move / rename a jot folder (incl. across locations)

**Files:**
- Modify: `ghostbrain/api/repo/jot_folders.py`
- Test: `ghostbrain/api/tests/test_jot_folders.py` (append)

**Interfaces:**
- Consumes: Task 3 module internals.
- Produces: `move_folder(src: tuple[str, str | None, str], dst: tuple[str, str | None, str], *, actor: Actor = USER) -> dict` (FolderRef dict of `dst`). Raises `FolderNotFound`, `FolderExists`, `InvalidLocation` (into itself / bad location), `FolderMoveIncomplete` (after moving the rest).

- [ ] **Step 1: Write the failing tests** (append to `test_jot_folders.py`)

```python
def test_rename_folder_same_location(env):
    jid = _jot()
    jf.move_jot_to(jid, context="work", project=None, folder="q4/plans")
    jf.create("work", None, "q4/empty")
    path_before = nm.read_jot(jid)["path"]
    assert jf.move_folder(("work", None, "q4"), ("work", None, "2026q4")) == {"context": "work", "project": None, "path": "2026q4"}
    assert _fm(env, jid)["folder"] == "2026q4/plans"
    assert nm.read_jot(jid)["path"] == path_before
    assert ("work", None, "2026q4/empty") in jf._registry()
    assert not any(p.startswith("q4") for c, _, p in jf._all_folders())


def test_move_folder_across_locations_moves_files(env):
    a, b = _jot("a"), _jot("b", 1)
    jf.move_jot_to(a, context="work", project=None, folder="q4")
    jf.move_jot_to(b, context="work", project=None, folder="q4/deep")
    jf.move_folder(("work", None, "q4"), ("work", env["atlas"], "q4"))
    for jid, folder in ((a, "q4"), (b, "q4/deep")):
        fm = _fm(env, jid)
        assert (fm["context"], fm["project"], fm["folder"]) == ("work", env["atlas"], folder)
        assert f"projects/{env['atlas']}/" in nm.read_jot(jid)["path"]


def test_move_folder_errors(env):
    jf.create("work", None, "a/b")
    jf.create("work", None, "c")
    with pytest.raises(jf.sf.FolderNotFound):
        jf.move_folder(("work", None, "zzz"), ("work", None, "y"))
    with pytest.raises(jf.sf.InvalidLocation):
        jf.move_folder(("work", None, "a"), ("work", None, "a/b/x"))
    with pytest.raises(jf.sf.FolderExists):
        jf.move_folder(("work", None, "a"), ("work", None, "c"))
    projects.update_project("work", env["atlas"], archived=True)
    with pytest.raises(jf.sf.InvalidLocation):
        jf.move_folder(("work", None, "a"), ("work", env["atlas"], "a"))


def test_move_folder_partial_failure_reports_ids(env, monkeypatch):
    good, bad = _jot("good"), _jot("bad", 1)
    jf.move_jot_to(good, context="work", project=None, folder="q4")
    jf.move_jot_to(bad, context="work", project=None, folder="q4")
    real = nm.move_jot

    def flaky(jot_id, **kw):
        if jot_id == bad:
            raise nm.JotNotFound(jot_id)
        return real(jot_id, **kw)

    monkeypatch.setattr(nm, "move_jot", flaky)
    with pytest.raises(jf.FolderMoveIncomplete) as ei:
        jf.move_folder(("work", None, "q4"), ("work", env["atlas"], "q4"))
    assert bad in str(ei.value)
    assert _fm(env, good)["project"] == env["atlas"]
    t = jf.tree()
    old = next(f for f in _scope(t, "work")["folders"] if f["path"] == "q4")
    assert [j["id"] for j in old["jots"]] == [bad]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest ghostbrain/api/tests/test_jot_folders.py -q -k 'move_folder or rename_folder'`
Expected: FAIL — `AttributeError: module ... has no attribute 'move_folder'`.

- [ ] **Step 3: Implement** (add after `delete` in `jot_folders.py`)

```python
def move_folder(src: tuple, dst: tuple, *, actor: Actor = USER) -> dict:
    """Rename or move a folder with every jot inside it. Jots that fail to move
    are reported after the rest have moved; each move is its own atomic write."""
    s_ctx, s_proj, s_raw = src
    d_ctx, d_proj, d_raw = dst
    s_path, d_path = sf.clean_path(s_raw), sf.clean_path(d_raw)
    if not s_path or not d_path:
        raise sf.InvalidLocation("folder path is required")
    with lock:
        rows = _jots()
        existing = _all_folders(rows)
        if (s_ctx, s_proj, s_path) not in existing:
            raise sf.FolderNotFound(f"folder not found: {s_path}")
        sf.check_location(d_ctx, d_proj)
        if (s_ctx, s_proj) == (d_ctx, d_proj) and sf.under(d_path, s_path):
            raise sf.InvalidLocation("cannot move a folder into itself")
        if (d_ctx, d_proj, d_path) in existing:
            raise sf.FolderExists(f"folder already exists: {d_path}")

        def remap(path: str) -> str:
            return d_path + path[len(s_path):]

        reg = set()
        for c, p, path in _registry():
            if (c, p) == (s_ctx, s_proj) and sf.under(path, s_path):
                reg.add((d_ctx, d_proj, remap(path)))
            else:
                reg.add((c, p, path))
        reg |= sf.with_parents({(d_ctx, d_proj, d_path)})  # keep the moved folder even if it was only implied
        _save_registry(reg)

        failed: list[str] = []
        for r in rows:
            f = _folder_of(r)
            if not (_filed(r) and (r["context"], r.get("project")) == (s_ctx, s_proj) and f and sf.under(f, s_path)):
                continue
            try:
                notes_manual.move_jot(
                    r["id"], to_context=d_ctx, to_project=d_proj, folder=remap(f),
                    confidence=1.0, method="user", reasoning="moved with its folder", actor=actor,
                )
            except Exception:
                log.exception("jot %s did not move with folder %s", r["id"], s_path)
                failed.append(r["id"])
        if failed:
            raise FolderMoveIncomplete(f"{len(failed)} jot(s) did not move: {', '.join(failed)}")
    return {"context": d_ctx, "project": d_proj, "path": d_path}
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest ghostbrain/api/tests/test_jot_folders.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && git add ghostbrain/api/repo/jot_folders.py ghostbrain/api/tests/test_jot_folders.py && git commit -m "feat(jots): move and rename jot folders, across locations too

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Project rename repoints jot folders

**Files:**
- Modify: `ghostbrain/api/repo/projects.py` (rename step "3. Chats", ~line 469)
- Test: `tests/test_project_rename.py` (append)

**Interfaces:**
- Consumes: `jot_folders.repoint_project(context, old_slug, new_slug)` (Task 3), `jot_folders._registry()`.

- [ ] **Step 1: Write the failing tests** (append; the file's `vault` fixture already sets `GHOSTBRAIN_STATE_DIR`)

```python
def test_jot_folder_registry_follows_rename(vault: Path):
    from ghostbrain.api.repo import jot_folders
    jot_folders.create("work", "paymnets", "empty")
    projects.rename_project("work", "paymnets", name="Payments")
    assert ("work", "payments", "empty") in jot_folders._registry()
    assert ("work", "paymnets", "empty") not in jot_folders._registry()


def test_failed_rename_restores_jot_folder_registry(vault: Path, monkeypatch):
    from ghostbrain.api.repo import jot_folders
    jot_folders.create("work", "paymnets", "empty")

    def boom(items):
        raise OSError("registry write failed")

    monkeypatch.setattr(projects, "_write", boom)
    with pytest.raises(OSError):
        projects.rename_project("work", "paymnets", name="Payments")
    assert ("work", "paymnets", "empty") in jot_folders._registry()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest tests/test_project_rename.py -q -k jot_folder`
Expected: FAIL on the first assertion (registry still holds `paymnets`).

- [ ] **Step 3: Implement** — right after the chat repoint + undo lines in `rename_project`:

```python
        from ghostbrain.api.repo import jot_folders

        jot_folders.repoint_project(context, slug, new_slug)
        undo.append(lambda: jot_folders.repoint_project(context, new_slug, slug))
```

Update the step comment above the chat block to `# 3. Chats and jot folders scoped to the project.`

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest tests/test_project_rename.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && git add ghostbrain/api/repo/projects.py tests/test_project_rename.py && git commit -m "feat(jots): project rename repoints jot folders

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: API models + routes

**Files:**
- Modify: `ghostbrain/api/models/note.py`
- Modify: `ghostbrain/api/routes/notes.py`
- Test: `ghostbrain/api/tests/test_routes_jot_folders.py` (new)

**Interfaces:**
- Consumes: `jot_folders.tree/create/move_folder/delete/move_jot_to`, `JotFolderError` (Tasks 3-4); `FolderRef`, `MoveFolderRequest` from `ghostbrain.api.models.library`.
- Produces HTTP:
  - `GET /v1/notes/tree` → `JotTree {inbox, unrouted, scopes}`
  - `POST /v1/notes/folders` body FolderRef → FolderRef
  - `PATCH /v1/notes/folders` body `{from: FolderRef, to: FolderRef}` → FolderRef
  - `DELETE /v1/notes/folders?context=&project=&path=` → `{"deleted": true}`
  - `PATCH /v1/notes/{jot_id}/location` body `{context, project?, folder?}` → move result (`id, path, context, project, …`)

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_routes_jot_folders.py`:

```python
from datetime import datetime, timezone

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.notes_manual import write_inbox_jot


@pytest.fixture
def jot(tmp_vault):
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    return write_inbox_jot("folder me", captured_at=datetime(2026, 5, 14, 9, tzinfo=timezone.utc))


@pytest.fixture
def proj(tmp_vault):
    return projects.create_project("work", "Atlas")


def test_tree_route(client, auth_headers, jot):
    r = client.get("/v1/notes/tree", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"inbox", "unrouted", "scopes"}
    assert body["inbox"][0]["id"] == jot["id"]
    assert body["inbox"][0]["unknownLocation"] is False


def test_folder_crud(client, auth_headers, proj):
    ref = {"context": "work", "project": proj["slug"], "path": "plans"}
    assert client.post("/v1/notes/folders", headers=auth_headers, json=ref).status_code == 200
    assert client.post("/v1/notes/folders", headers=auth_headers, json=ref).status_code == 409
    r = client.patch("/v1/notes/folders", headers=auth_headers, json={"from": ref, "to": {**ref, "path": "renamed"}})
    assert r.status_code == 200 and r.json()["path"] == "renamed"
    r = client.delete("/v1/notes/folders", headers=auth_headers,
                      params={"context": "work", "project": proj["slug"], "path": "renamed"})
    assert r.status_code == 200 and r.json() == {"deleted": True}


def test_folder_errors(client, auth_headers, tmp_vault):
    assert client.post("/v1/notes/folders", headers=auth_headers,
                       json={"context": "nope", "project": None, "path": "x"}).status_code == 422
    assert client.post("/v1/notes/folders", headers=auth_headers,
                       json={"context": "work", "project": None, "path": "../x"}).status_code == 422
    assert client.delete("/v1/notes/folders", headers=auth_headers,
                         params={"context": "work", "path": "never"}).status_code == 404


def test_move_jot_location(client, auth_headers, jot, proj):
    r = client.patch(f"/v1/notes/{jot['id']}/location", headers=auth_headers,
                     json={"context": "work", "project": proj["slug"], "folder": "plans"})
    assert r.status_code == 200
    tree = client.get("/v1/notes/tree", headers=auth_headers).json()
    scope = next(s for s in tree["scopes"] if s["project"] == proj["slug"])
    assert scope["folders"][0]["jots"][0]["id"] == jot["id"]
    assert scope["folders"][0]["jots"][0]["folder"] == "plans"


def test_move_jot_location_errors(client, auth_headers, jot):
    assert client.patch("/v1/notes/manual-19000101T000000-nope/location", headers=auth_headers,
                        json={"context": "work"}).status_code == 404
    assert client.patch(f"/v1/notes/{jot['id']}/location", headers=auth_headers,
                        json={"context": "nope"}).status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest ghostbrain/api/tests/test_routes_jot_folders.py -q`
Expected: FAIL — 404/405/422 from missing routes.

- [ ] **Step 3: Add models** (`models/note.py`, after `NoteListItem`)

```python
class JotTreeItem(NoteListItem):
    thumbnail: str | None = None
    unknownLocation: bool = False


class JotFolderNode(BaseModel):
    name: str
    path: str
    folders: list["JotFolderNode"] = []
    jots: list[JotTreeItem] = []


class JotScope(BaseModel):
    context: str
    project: str | None = None
    name: str
    archived: bool = False
    folders: list[JotFolderNode] = []
    jots: list[JotTreeItem] = []


class JotTree(BaseModel):
    inbox: list[JotTreeItem] = []
    unrouted: list[JotTreeItem] = []
    scopes: list[JotScope] = []


class MoveJotRequest(BaseModel):
    context: str
    project: str | None = None
    folder: str | None = None
```

- [ ] **Step 4: Add routes** (`routes/notes.py`)

Imports: add `JotTree, MoveJotRequest` to the `models.note` import, `from ghostbrain.api.models.library import FolderRef, MoveFolderRequest`, and `from ghostbrain.api.repo import jot_folders`. Insert this block **directly after `router = APIRouter(...)` and before `@router.get("")`** so no `/{jot_id}` route can capture `tree` or `folders`:

```python
def _folder_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except jot_folders.JotFolderError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.get("/tree", response_model=JotTree)
def jot_tree() -> dict:
    return jot_folders.tree()


@router.post("/folders", response_model=FolderRef)
def create_jot_folder(payload: FolderRef) -> dict:
    return _folder_call(jot_folders.create, payload.context, payload.project, payload.path)


@router.patch("/folders", response_model=FolderRef)
def move_jot_folder(payload: MoveFolderRequest, actor: Actor = Depends(request_actor)) -> dict:
    src, dst = payload.from_, payload.to
    return _folder_call(
        jot_folders.move_folder, (src.context, src.project, src.path), (dst.context, dst.project, dst.path),
        actor=actor,
    )


@router.delete("/folders")
def delete_jot_folder(context: str, path: str, project: str | None = Query(None)) -> dict:
    _folder_call(jot_folders.delete, context, project, path)
    return {"deleted": True}


@router.patch("/{jot_id}/location")
def move_jot_location(
    req: MoveJotRequest,
    jot_id: str = PathParam(..., min_length=8, max_length=128),
    actor: Actor = Depends(request_actor),
) -> dict:
    """File a jot at a context / project / folder (drag in the jot tree)."""
    return _folder_call(
        jot_folders.move_jot_to, jot_id, context=req.context, project=req.project, folder=req.folder, actor=actor,
    )
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest ghostbrain/api/tests/test_routes_jot_folders.py ghostbrain/api/tests/test_routes_notes_mutate.py ghostbrain/api/tests/test_routes_notes_list.py -q`
Expected: all PASS.

- [ ] **Step 6: Full backend suite**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest -q -x`
Expected: PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && git add ghostbrain/api/models/note.py ghostbrain/api/routes/notes.py ghostbrain/api/tests/test_routes_jot_folders.py && git commit -m "feat(jots): tree, folder and location routes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Desktop types + hooks

**Files:**
- Modify: `desktop/src/shared/api-types.ts` (near `JotListItem`, ~557)
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (Jots section, ~645)
- Test: `desktop/src/renderer/__tests__/jot-folder-hooks.test.tsx` (new)

**Interfaces:**
- Produces (types): `JotTreeItem extends JotListItem { folder: string | null; unknownLocation: boolean }`, `JotFolderNode { name; path; folders: JotFolderNode[]; jots: JotTreeItem[] }`, `JotScope { context; project: string | null; name; archived; folders; jots }`, `JotTree { inbox; unrouted; scopes }`, `JotLocation { context: string; project: string | null; folder: string | null }`; `JotListItem.folder?: string | null`.
- Produces (hooks): `useJotTree()` (key `['jots','tree']`, 5 s poll), `useMoveJot()` vars `{ id } & JotLocation`, `useCreateJotFolder()` vars `FolderRef`, `useMoveJotFolder()` vars `{ from: FolderRef; to: FolderRef }`, `useDeleteJotFolder()` vars `FolderRef`. All mutations invalidate `['jots']`, `['note-by-path']`, `['vault','backlinks']`.

- [ ] **Step 1: Write the failing test**

```tsx
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { useCreateJotFolder, useDeleteJotFolder, useJotTree, useMoveJot, useMoveJotFolder } from '../lib/api/hooks';

type Call = { method: string; path: string; body: unknown };
let calls: Call[] = [];

beforeEach(() => {
  calls = [];
  window.gb.api.request = vi.fn(async (method: string, path: string, body?: unknown) => {
    calls.push({ method, path, body });
    if (path === '/v1/notes/tree') return { ok: true, data: { inbox: [], unrouted: [], scopes: [] } };
    return { ok: true, data: {} };
  }) as unknown as typeof window.gb.api.request;
});

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const spy = vi.spyOn(qc, 'invalidateQueries');
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  return { wrapper, spy };
}

describe('jot folder hooks', () => {
  it('loads the tree', async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useJotTree(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual({ inbox: [], unrouted: [], scopes: [] }));
  });

  it('sends each mutation and invalidates jots', async () => {
    const { wrapper, spy } = setup();
    const ref = { context: 'work', project: 'atlas', path: 'q4' };
    const move = renderHook(() => useMoveJot(), { wrapper }).result;
    const create = renderHook(() => useCreateJotFolder(), { wrapper }).result;
    const moveF = renderHook(() => useMoveJotFolder(), { wrapper }).result;
    const delF = renderHook(() => useDeleteJotFolder(), { wrapper }).result;
    await move.current.mutateAsync({ id: 'j1', context: 'work', project: null, folder: 'q4' });
    await create.current.mutateAsync(ref);
    await moveF.current.mutateAsync({ from: ref, to: { ...ref, path: 'q5' } });
    await delF.current.mutateAsync(ref);
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      'PATCH /v1/notes/j1/location',
      'POST /v1/notes/folders',
      'PATCH /v1/notes/folders',
      'DELETE /v1/notes/folders?context=work&path=q4&project=atlas',
    ]);
    expect(calls[0]!.body).toEqual({ context: 'work', project: null, folder: 'q4' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['jots'] });
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders/desktop && npx vitest run src/renderer/__tests__/jot-folder-hooks.test.tsx`
Expected: FAIL — `useJotTree` is not exported.

- [ ] **Step 3: Add types** (`api-types.ts`, after `JotsPage`; and `folder?: string | null;` on `JotListItem` after `project`)

```ts
export interface JotTreeItem extends JotListItem { folder: string | null; unknownLocation: boolean }
export interface JotFolderNode { name: string; path: string; folders: JotFolderNode[]; jots: JotTreeItem[] }
export interface JotScope {
  context: string;
  project: string | null;
  name: string;
  archived: boolean;
  folders: JotFolderNode[];
  jots: JotTreeItem[];
}
export interface JotTree { inbox: JotTreeItem[]; unrouted: JotTreeItem[]; scopes: JotScope[] }
export interface JotLocation { context: string; project: string | null; folder: string | null }
```

- [ ] **Step 4: Add hooks** (`hooks.ts`, after `useDeleteJot`; add the new types to the existing `api-types` import)

```ts
function invalidateJotMoves(qc: QueryClient) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: JOTS_KEY }),
    // A move can change the jot's path — the open detail view's path is stale.
    qc.invalidateQueries({ queryKey: ['note-by-path'] }),
    qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] }),
  ]);
}

export function useJotTree() {
  return useQuery({
    queryKey: [...JOTS_KEY, 'tree'],
    queryFn: () => get<JotTree>('/v1/notes/tree'),
    refetchInterval: 5000, // pick up overlay-captured jots
  });
}

export function useMoveJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...loc }: { id: string } & JotLocation) =>
      patch<{ id: string; path: string }>(`/v1/notes/${encodeURIComponent(id)}/location`, loc),
    onSuccess: () => invalidateJotMoves(qc),
  });
}

export function useCreateJotFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ref: FolderRef) => post<FolderRef>('/v1/notes/folders', ref),
    onSuccess: () => invalidateJotMoves(qc),
  });
}

export function useMoveJotFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { from: FolderRef; to: FolderRef }) => patch<FolderRef>('/v1/notes/folders', vars),
    // A partial move (409) still moved some jots: refresh either way.
    onSettled: () => invalidateJotMoves(qc),
  });
}

export function useDeleteJotFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ref: FolderRef) => {
      const params = new URLSearchParams({ context: ref.context, path: ref.path });
      if (ref.project) params.set('project', ref.project);
      return del(`/v1/notes/folders?${params.toString()}`);
    },
    onSuccess: () => invalidateJotMoves(qc),
  });
}
```

If `QueryClient` is not yet imported as a type in `hooks.ts`, add `type QueryClient` to the `@tanstack/react-query` import.

- [ ] **Step 5: Run test + typecheck**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders/desktop && npx vitest run src/renderer/__tests__/jot-folder-hooks.test.tsx && npm run typecheck`
Expected: PASS, no type errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && git add desktop/src/shared/api-types.ts desktop/src/renderer/lib/api/hooks.ts desktop/src/renderer/__tests__/jot-folder-hooks.test.tsx && git commit -m "feat(desktop): jot tree and folder hooks

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Rewrite `JotTree` on `ScopeTree`

**Files:**
- Modify (rewrite): `desktop/src/renderer/components/JotTree.tsx`
- Modify (rewrite): `desktop/src/renderer/__tests__/JotTree.test.tsx`

**Interfaces:**
- Consumes: Task 7 types and hooks; `ScopeTree`, `countLeaves`, `folderKey` and tree types from `components/tree`.
- Produces:
  - `JotTree({ tree, selectedId, onSelect }: { tree: JotTreeData; selectedId: string | null; onSelect: (id: string) => void })`
  - `JotList({ items, selectedId, onSelect }: { items: JotListItem[]; selectedId: string | null; onSelect: (id: string) => void })` — flat rows for search results
  - `flattenJotTree(tree: JotTreeData): JotTreeItem[]` — every jot (inbox, unrouted, all scopes/folders), newest `created` first
  - `shortDate(iso: string, now?: Date): string` — `"May 14"`, `"May 14, 2025"` when not this year, `""` when unparseable
  - `JOT_DRAG_MIME = 'application/x-gb-jot'`
  - test ids: `jot-inbox`, `jot-unrouted` (section headers)

- [ ] **Step 1: Write the failing tests** (replace the whole file)

```tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { JotTree, JotList, JOT_DRAG_MIME, flattenJotTree, shortDate } from '../components/JotTree';
import type { JotTree as JotTreeData, JotTreeItem } from '../../shared/api-types';

function jot(id: string, title: string, over: Partial<JotTreeItem> = {}): JotTreeItem {
  return {
    id, title, path: `20-contexts/work/notes/${id}.md`, excerpt: '', context: 'work', project: null,
    routingStatus: 'routed', tags: [], created: '2026-05-14T09:00:00Z', updated: '2026-05-14T09:00:00Z',
    folder: null, unknownLocation: false, ...over,
  };
}

const tree: JotTreeData = {
  inbox: [jot('p1', 'pending idea', { context: null, routingStatus: 'pending', created: '2026-05-15T09:00:00Z' })],
  unrouted: [jot('u1', 'ghost jot', { context: 'gone', unknownLocation: true })],
  scopes: [
    {
      context: 'work', project: null, name: 'work', archived: false,
      folders: [{ name: 'plans', path: 'plans', folders: [], jots: [jot('j1', 'filed jot', { folder: 'plans' })] }],
      jots: [jot('j2', 'root jot', { created: '2026-05-13T09:00:00Z' })],
    },
    { context: 'work', project: 'atlas', name: 'Atlas', archived: false, folders: [], jots: [] },
  ],
};

type Call = { method: string; path: string; body: unknown };
let calls: Call[] = [];

beforeEach(() => {
  calls = [];
  window.gb.api.request = vi.fn(async (method: string, path: string, body?: unknown) => {
    calls.push({ method, path, body });
    return { ok: true, data: {} };
  }) as unknown as typeof window.gb.api.request;
});

const mutations = (method: string) => calls.filter((c) => c.method === method);
const leaf = (id: string) => JSON.stringify({ kind: 'leaf', id });
function dt(data: Record<string, string>) {
  return { getData: (k: string) => data[k] ?? '', setData: vi.fn(), types: Object.keys(data), files: [], dropEffect: 'move', effectAllowed: 'all' };
}

function renderTree(selectedId: string | null = null) {
  const onSelect = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><JotTree tree={tree} selectedId={selectedId} onSelect={onSelect} /></QueryClientProvider>);
  return onSelect;
}

describe('JotTree', () => {
  it('renders inbox, unrouted, scopes, folders and jots', () => {
    renderTree();
    expect(screen.getByTestId('jot-inbox')).toHaveTextContent('inbox');
    expect(screen.getByTestId('jot-unrouted')).toHaveTextContent('unrouted');
    expect(screen.getByText('pending idea')).toBeInTheDocument();
    expect(screen.getByText('ghost jot')).toBeInTheDocument();
    expect(screen.getByText('Atlas')).toBeInTheDocument();
    expect(screen.getByText('plans')).toBeInTheDocument();
    expect(screen.getByText('filed jot')).toBeInTheDocument();
    expect(screen.getByText('root jot')).toBeInTheDocument();
    expect(screen.queryByText('2026-05')).not.toBeInTheDocument();
  });

  it('selects a jot on click', () => {
    const onSelect = renderTree();
    fireEvent.click(screen.getByText('filed jot'));
    expect(onSelect).toHaveBeenCalledWith('j1');
  });

  it('drops an inbox jot onto a project', async () => {
    renderTree();
    fireEvent.drop(screen.getByTestId('folder-work/atlas/'), { dataTransfer: dt({ [JOT_DRAG_MIME]: leaf('p1') }) });
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({ path: '/v1/notes/p1/location', body: { context: 'work', project: 'atlas', folder: null } });
  });

  it('drops a jot into a folder', async () => {
    renderTree();
    fireEvent.drop(screen.getByTestId('folder-work/_/plans'), { dataTransfer: dt({ [JOT_DRAG_MIME]: leaf('j2') }) });
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({ path: '/v1/notes/j2/location', body: { context: 'work', project: null, folder: 'plans' } });
  });

  it('moves a folder into a project', async () => {
    renderTree();
    const ref = { context: 'work', project: null, path: 'plans' };
    fireEvent.drop(screen.getByTestId('folder-work/atlas/'), { dataTransfer: dt({ [JOT_DRAG_MIME]: JSON.stringify({ kind: 'folder', ref }) }) });
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({ path: '/v1/notes/folders', body: { from: ref, to: { context: 'work', project: 'atlas', path: 'plans' } } });
  });

  it('creates a folder inline', async () => {
    renderTree();
    fireEvent.click(screen.getByLabelText('new folder in work/_/'));
    const input = screen.getByPlaceholderText('folder name');
    fireEvent.change(input, { target: { value: 'q4' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(mutations('POST')).toHaveLength(1));
    expect(mutations('POST')[0]).toMatchObject({ path: '/v1/notes/folders', body: { context: 'work', project: null, path: 'q4' } });
  });

  it('deletes a folder', async () => {
    renderTree();
    fireEvent.click(screen.getByLabelText('delete work/_/plans'));
    await waitFor(() => expect(mutations('DELETE')).toHaveLength(1));
    expect(mutations('DELETE')[0]?.path).toBe('/v1/notes/folders?context=work&path=plans');
  });

  it('hides empty inbox and unrouted sections', () => {
    const qc = new QueryClient();
    render(<QueryClientProvider client={qc}><JotTree tree={{ ...tree, inbox: [], unrouted: [] }} selectedId={null} onSelect={() => {}} /></QueryClientProvider>);
    expect(screen.queryByTestId('jot-inbox')).not.toBeInTheDocument();
    expect(screen.queryByTestId('jot-unrouted')).not.toBeInTheDocument();
  });

  it('marks the selected jot active', () => {
    renderTree('j1');
    expect(screen.getByText('filed jot').closest('[role="button"]')).toHaveClass('bg-neon/12');
  });
});

describe('JotList', () => {
  it('renders flat rows and selects', () => {
    const onSelect = vi.fn();
    render(<JotList items={[jot('a', 'alpha'), jot('b', 'beta')]} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText('beta'));
    expect(onSelect).toHaveBeenCalledWith('b');
  });
});

describe('helpers', () => {
  it('flattens newest first', () => {
    expect(flattenJotTree(tree).map((j) => j.id)).toEqual(['p1', 'u1', 'j1', 'j2']);
  });

  it('formats short dates', () => {
    const now = new Date('2026-10-13T12:00:00Z');
    expect(shortDate('2026-05-14T09:00:00Z', now)).toBe('May 14');
    expect(shortDate('2025-05-14T09:00:00Z', now)).toBe('May 14, 2025');
    expect(shortDate('', now)).toBe('');
  });
});
```

Note on `flattenJotTree` order: `u1` and `j1` share a timestamp; the sort must be stable so ties keep collection order (inbox, unrouted, scopes depth-first, folders before root jots). `Array.prototype.sort` is stable.

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders/desktop && npx vitest run src/renderer/__tests__/JotTree.test.tsx`
Expected: FAIL — `JotList` / `JOT_DRAG_MIME` not exported.

- [ ] **Step 3: Implement** (replace the whole file)

```tsx
import { useMemo, useState } from 'react';
import type { FolderRef, JotFolderNode, JotListItem, JotScope, JotTree as JotTreeData, JotTreeItem } from '../../shared/api-types';
import { useCreateJotFolder, useDeleteJotFolder, useMoveJot, useMoveJotFolder } from '../lib/api/hooks';
import { toast } from '../stores/toast';
import { Lucide } from './Lucide';
import { ScopeTree } from './tree/ScopeTree';
import { folderKey } from './tree/tree-types';
import type { LeafRowProps, TreeDragCodec, TreeDrop, TreeFolderNode, TreeScope } from './tree/tree-types';

export const JOT_DRAG_MIME = 'application/x-gb-jot';

const JOT_CODEC: TreeDragCodec = {
  mime: JOT_DRAG_MIME,
  encodeLeaf: (id) => JSON.stringify({ kind: 'leaf', id }),
  encodeFolder: (ref) => JSON.stringify({ kind: 'folder', ref }),
  decode: (raw) => {
    try {
      const p = JSON.parse(raw) as TreeDrop;
      if (p?.kind === 'leaf' && typeof p.id === 'string') return p;
      if (p?.kind === 'folder' && p.ref && typeof p.ref.context === 'string') return p;
    } catch {
      /* not ours */
    }
    return null;
  },
};

const onError = (e: Error) => toast.error(e.message);

export function shortDate(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    ...(d.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}),
  });
}

function collect(nodes: JotFolderNode[], out: JotTreeItem[]) {
  for (const f of nodes) {
    collect(f.folders, out);
    out.push(...f.jots);
  }
}

export function flattenJotTree(tree: JotTreeData): JotTreeItem[] {
  const out: JotTreeItem[] = [...tree.inbox, ...tree.unrouted];
  for (const s of tree.scopes) {
    collect(s.folders, out);
    out.push(...s.jots);
  }
  return out.sort((a, b) => b.created.localeCompare(a.created));
}

function toTreeFolder(n: JotFolderNode): TreeFolderNode<JotTreeItem> {
  return { name: n.name, path: n.path, folders: n.folders.map(toTreeFolder), leaves: n.jots };
}

function toTreeScope(s: JotScope): TreeScope<JotTreeItem> {
  return { context: s.context, project: s.project, name: s.name, archived: s.archived, folders: s.folders.map(toTreeFolder), leaves: s.jots };
}

/** Keys ScopeTree must expand so the selected jot is visible. */
function revealKeysFor(j: JotTreeItem | undefined): string[] {
  if (!j?.context || j.routingStatus !== 'routed') return [];
  const base = { context: j.context, project: j.project ?? null };
  const keys = [`ctx:${j.context}`, folderKey({ ...base, path: '' })];
  const parts = (j.folder ?? '').split('/').filter(Boolean);
  parts.forEach((_, i) => keys.push(folderKey({ ...base, path: parts.slice(0, i + 1).join('/') })));
  return keys;
}

type RowChrome = Pick<LeafRowProps, 'draggable' | 'onDragStart' | 'className' | 'style'> & Partial<LeafRowProps>;

function JotRow({ jot, row, active, onSelect }: { jot: JotListItem & { unknownLocation?: boolean }; row: RowChrome; active: boolean; onSelect: (id: string) => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      {...row}
      onClick={() => onSelect(jot.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(jot.id);
        }
      }}
      className={`${row.className} cursor-pointer transition-colors duration-[120ms] ${
        active ? 'bg-neon/12 font-medium text-ink-0' : 'font-normal text-ink-1 hover:bg-fog'
      }`}
    >
      <span className="min-w-0 flex-1 truncate">{jot.title}</span>
      {jot.unknownLocation && (
        <span title="its project or context no longer exists" className="flex-shrink-0 text-ink-3">
          <Lucide name="circle-help" size={11} />
        </span>
      )}
      <span className="flex-shrink-0 font-mono text-10 text-ink-3">{shortDate(jot.created)}</span>
    </div>
  );
}

const FLAT_ROW = 'group flex w-full items-center gap-[7px] rounded-md px-1.5 py-[5px] text-left text-13';

function dragRow(id: string, paddingLeft: number): RowChrome {
  return {
    draggable: true,
    onDragStart: (e) => {
      e.dataTransfer.setData(JOT_DRAG_MIME, JOT_CODEC.encodeLeaf(id));
      e.dataTransfer.effectAllowed = 'move';
    },
    className: FLAT_ROW,
    style: { paddingLeft },
  };
}

function Section({ testId, icon, label, items, selectedId, onSelect }: {
  testId: string; icon: string; label: string; items: JotTreeItem[]; selectedId: string | null; onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(true);
  if (items.length === 0) return null;
  return (
    <div className="mb-1">
      <button
        type="button"
        data-testid={testId}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-[7px] rounded-md px-1.5 py-1 font-mono text-[10.5px] uppercase tracking-[0.1em] text-ink-2 hover:bg-fog"
      >
        <Lucide name={open ? 'chevron-down' : 'chevron-right'} size={11} />
        <Lucide name={icon} size={12} className="opacity-70" />
        <span>{label}</span>
        <span className="ml-auto text-10 text-ink-3">{items.length}</span>
      </button>
      {open && items.map((j) => (
        <JotRow key={j.id} jot={j} row={dragRow(j.id, 24)} active={j.id === selectedId} onSelect={onSelect} />
      ))}
    </div>
  );
}

export function JotList({ items, selectedId, onSelect }: { items: JotListItem[]; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <div className="flex flex-col px-2 py-2">
      {items.map((j) => (
        <JotRow key={j.id} jot={j} row={dragRow(j.id, 8)} active={j.id === selectedId} onSelect={onSelect} />
      ))}
    </div>
  );
}

export function JotTree({ tree, selectedId, onSelect }: { tree: JotTreeData; selectedId: string | null; onSelect: (id: string) => void }) {
  const moveJot = useMoveJot();
  const createFolder = useCreateJotFolder();
  const moveFolder = useMoveJotFolder();
  const deleteFolder = useDeleteJotFolder();

  const scopes = useMemo(() => tree.scopes.map(toTreeScope), [tree]);
  const revealKeys = useMemo(
    () => (selectedId ? revealKeysFor(flattenJotTree(tree).find((j) => j.id === selectedId)) : []),
    [tree, selectedId],
  );
  const moveFolderTo = (from: FolderRef, to: FolderRef) => moveFolder.mutate({ from, to }, { onError });

  return (
    <ScopeTree<JotTreeItem>
      scopes={scopes}
      ariaLabel="jot tree"
      codec={JOT_CODEC}
      leafId={(j) => j.id}
      leafRef={(j) => ({ context: j.context!, project: j.project ?? null, path: j.folder ?? '' })}
      selectedFolderKey={null}
      rootIcon="notebook-pen"
      revealKeys={revealKeys}
      onMoveLeaf={(id, to) => moveJot.mutate({ id, context: to.context, project: to.project, folder: to.path || null }, { onError })}
      onMoveFolder={moveFolderTo}
      onCreateFolder={(ref) => createFolder.mutate(ref, { onError })}
      onRenameFolder={moveFolderTo}
      onDeleteFolder={(ref) => deleteFolder.mutate(ref, { onError })}
      header={
        <>
          <Section testId="jot-inbox" icon="inbox" label="inbox" items={tree.inbox} selectedId={selectedId} onSelect={onSelect} />
          <Section testId="jot-unrouted" icon="circle-help" label="unrouted" items={tree.unrouted} selectedId={selectedId} onSelect={onSelect} />
        </>
      }
      renderLeaf={(j, row) => <JotRow jot={j} row={row} active={j.id === selectedId} onSelect={onSelect} />}
    />
  );
}
```

Check `notebook-pen` exists in the `Lucide` component's icon map (`grep -n "notebook-pen\|'notebook'" desktop/src/renderer/components/Lucide.tsx`); if not, use `'file-text'`.

- [ ] **Step 4: Run tests + typecheck**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders/desktop && npx vitest run src/renderer/__tests__/JotTree.test.tsx`
Expected: PASS. Do not run `npm run typecheck` here: `screens/jots.tsx` still passes the old `items` prop and only typechecks after Task 9, which runs the full typecheck.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && git add desktop/src/renderer/components/JotTree.tsx desktop/src/renderer/__tests__/JotTree.test.tsx && git commit -m "feat(desktop): jot tree with folders on the shared ScopeTree

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Wire the Jots screen + demo fixture

**Files:**
- Modify: `desktop/src/renderer/screens/jots.tsx`
- Modify: `desktop/src/renderer/__tests__/jots.test.tsx`
- Modify: `desktop/src/main/demo/fixtures.ts`

**Interfaces:**
- Consumes: `useJotTree` (Task 7); `JotTree`, `JotList`, `flattenJotTree` (Task 8).

- [ ] **Step 1: Make the screen test stubs serve the tree**

In `jots.test.tsx` add near the top:

```tsx
import type { JotTree as JotTreeData, JotTreeItem } from '../../shared/api-types';

/** Shape a flat jots page the way GET /v1/notes/tree would. */
function treeOf(page: { items: JotListItem[] }): JotTreeData {
  const tree: JotTreeData = { inbox: [], unrouted: [], scopes: [] };
  for (const raw of page.items) {
    const j: JotTreeItem = { folder: null, unknownLocation: false, ...raw, folder: raw.folder ?? null };
    if (j.routingStatus === 'pending') tree.inbox.push(j);
    else if (j.routingStatus !== 'routed' || !j.context) tree.unrouted.push(j);
    else {
      let s = tree.scopes.find((x) => x.context === j.context && x.project === (j.project ?? null));
      if (!s) tree.scopes.push((s = { context: j.context, project: j.project ?? null, name: j.project ?? j.context, archived: false, folders: [], jots: [] }));
      s.jots.push(j);
    }
  }
  return tree;
}
```

(Import `JotListItem` too if the file doesn't already.) Then in **every** `api.request` stub in the file, add a line before the `source=manual` line that returns the same page shaped as a tree, e.g. where the stub has `if (path.includes('source=manual')) return { ok: true, status: 200, data: page };` add directly above it:

```tsx
      if (path === '/v1/notes/tree') return { ok: true, status: 200, data: treeOf(page) };
```

using the same variable the `source=manual` line returns in that stub (`page`, `twoJotPage`, `pendingPage`, or `{ items: [], total: 0 }`). The tree line must come first: several stubs end in a catch-all that returns `detailA`, which would otherwise answer the tree request. Add `JotListItem` to the existing `api-types` type import.

Then add these two tests next to the auto-route tests (they use the file's existing `apiRequest`, `withConnectors`, `withQuery`, `twoJotPage`, `detailA`, `detailB`):

```tsx
  function stubTwoJots() {
    apiRequest.mockImplementation(withConnectors(async (_m, path) => {
      if (path === '/v1/notes/tree') return { ok: true, status: 200, data: treeOf(twoJotPage) };
      if (path.includes('source=manual')) return { ok: true, status: 200, data: twoJotPage };
      if (path.includes('manual-20260514T093015-a')) return { ok: true, status: 200, data: detailA };
      if (path.includes('manual-20260514T120000-b')) return { ok: true, status: 200, data: detailB };
      return { ok: true, status: 200, data: detailA };
    }));
  }

  it('shows a flat result list while searching', async () => {
    stubTwoJots();
    render(withQuery(<JotsScreen />));
    await waitFor(() => expect(screen.getByLabelText('jot tree')).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText('search jots…'), { target: { value: 'first' } });
    await waitFor(() => expect(screen.queryByLabelText('jot tree')).not.toBeInTheDocument());
    expect(apiRequest.mock.calls.some((a: unknown[]) => typeof a[1] === 'string' && a[1].includes('q=first'))).toBe(true);
    expect(screen.getAllByText('first jot').length).toBeGreaterThan(0);
  });

  it('keeps the selected jot when searching', async () => {
    stubTwoJots();
    render(withQuery(<JotsScreen />));
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());
    const search = screen.getByPlaceholderText('search jots…');
    fireEvent.change(search, { target: { value: 'first' } });
    await waitFor(() => expect(screen.queryByLabelText('jot tree')).not.toBeInTheDocument());
    expect(screen.getByText(/full body here/)).toBeInTheDocument();
    fireEvent.change(search, { target: { value: '' } });
    await waitFor(() => expect(screen.getByLabelText('jot tree')).toBeInTheDocument());
    expect(screen.getByText(/full body here/)).toBeInTheDocument();
  });
```

If `ScopeTree` does not expose `ariaLabel` as an accessible name (`grep -n ariaLabel desktop/src/renderer/components/tree/ScopeTree.tsx`), query `screen.getByRole('tree')` instead of `getByLabelText('jot tree')` in both tests.

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders/desktop && npx vitest run src/renderer/__tests__/jots.test.tsx`
Expected: FAIL — the screen still passes `items` to `JotTree` / doesn't call `/v1/notes/tree`.

- [ ] **Step 3: Wire `jots.tsx`**

- Imports: `import { JotList, JotTree, flattenJotTree } from '../components/JotTree';`, add `useJotTree` to the hooks import.
- After `const list = useJots({ q: q || undefined });` add:

```tsx
  const treeQ = useJotTree();
  const searching = q.trim() !== '';
  // Every jot the screen knows about, newest first — the tree is the source of
  // truth; search results only add rows while a query is typed.
  const allItems = useMemo(() => (treeQ.data ? flattenJotTree(treeQ.data) : []), [treeQ.data]);
```

- `selectedItem`: `allItems.find((i) => i.id === selectedId) ?? list.data?.items.find((i) => i.id === selectedId) ?? null` with deps `[allItems, list.data, selectedId]`.
- Auto-select effect: use `allItems` instead of `list.data?.items` (`if (selectedId === null && allItems.length) setSelectedId(allItems[0]!.id);`, deps `[allItems, selectedId]`).
- Auto-route-on-leave effect: `const prevItem = allItems.find((i) => i.id === prevId);`.
- TopBar subtitle: `treeQ.data ? \`${allItems.length} total\` : '…'`.
- Empty states (`list.data?.items.length === 0` at ~366 and ~558): use `treeQ.data && allItems.length === 0 && !searching`.
- Replace the `<JotTree items=… />` element with:

```tsx
            {searching ? (
              <JotList items={list.data?.items ?? []} selectedId={selectedId} onSelect={selectJot} />
            ) : (
              treeQ.data && <JotTree tree={treeQ.data} selectedId={selectedId} onSelect={selectJot} />
            )}
```

Leave every other use of `list` alone; grep `list.data` afterwards to confirm the only remaining uses are the search list and the `selectedItem` fallback.

- [ ] **Step 4: Demo fixture**

In `desktop/src/main/demo/fixtures.ts`, before the `if (rawPath === '/v1/notes')` block:

```ts
  if (method === 'GET' && rawPath === '/v1/notes/tree') {
    const item = (j: (typeof JOTS)[number], folder: string | null = null) => ({ ...j, project: null, folder, unknownLocation: false });
    const byCtx = new Map<string, ReturnType<typeof item>[]>();
    for (const j of JOTS) byCtx.set(j.context!, [...(byCtx.get(j.context!) ?? []), item(j)]);
    return ok({
      inbox: [],
      unrouted: [],
      scopes: [...byCtx].map(([context, jots]) => ({
        context, project: null, name: context, archived: false,
        folders: context === 'aurora'
          ? [{ name: 'launch', path: 'launch', folders: [], jots: jots.map((j) => ({ ...j, folder: 'launch' })) }]
          : [],
        jots: context === 'aurora' ? [] : jots,
      })),
    });
  }
```

- [ ] **Step 5: Run the desktop suite + typecheck**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders/desktop && npm run typecheck && npx vitest run`
Expected: PASS everywhere.

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && git add desktop/src/renderer/screens/jots.tsx desktop/src/renderer/__tests__/jots.test.tsx desktop/src/main/demo/fixtures.ts && git commit -m "feat(desktop): jots screen uses the folder tree, flat list while searching

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Verification + screenshot

**Files:** none (verification only).

- [ ] **Step 1: Full suites**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-jot-folders && python -m pytest -q && cd desktop && npm run typecheck && npx vitest run && npm run lint`
Expected: all green. Report failures verbatim; do not mark done otherwise.

- [ ] **Step 2: Demo-mode screenshot**

Launch the desktop app with `GHOSTBRAIN_DEMO=1` (Playwright `_electron`, as in the UI-screenshot workflow), open the Jots screen, and capture the sidebar showing the `aurora` context with the `launch` folder expanded. Save to the session scratchpad and show it to the user.

- [ ] **Step 3: Live smoke (manual, with the user's consent)**

Against the user's real sidecar: create a folder under a context, drag a jot into it, rename the folder, drag the folder into a project, confirm the jot's file moved under `projects/<slug>/` and its frontmatter has `folder`. Then delete the now-empty original folder. Report what was done.
