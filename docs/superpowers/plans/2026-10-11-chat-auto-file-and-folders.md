# Chat Auto-Filing and Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New chats file themselves under the right context/project after the first reply, and the chat sidebar becomes a context → project → folder tree with create/rename/delete/drag-move, sharing one tree component with docs.

**Architecture:** Chat location (`context`, `project` slug, `folder`) lives in each chat's JSON file; empty folders live in `chats/folders.json`. A new `chat_folders` repo module validates locations, owns the registry, builds the tree and moves folders. Auto-filing is a background thread after the first assistant reply that calls the existing `router.route_event`. On the renderer, `DocTree`'s guts move into a generic `ScopeTree<L>`; `DocTree` and a new `ChatTree` are thin wrappers.

**Tech Stack:** Python 3.11+ / FastAPI / pydantic / pytest (backend); Electron + React + TypeScript + TanStack Query + Vitest/RTL (desktop).

**Spec:** `docs/superpowers/specs/2026-10-11-chat-auto-file-and-folders-design.md`

**Worktree:** `/Users/jannik/development/nikrich/ghost-brain-chatfile` (branch `feat/chat-auto-file`). Every shell command MUST start with `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && …`. Never run bare `git`/`npm` from another cwd — subagent shells start in a different checkout.

## Global Constraints

- Public repo: never mention employer/client names in code, tests, commits or PR text. Use neutral stand-ins (`work`, `personal`, `Site Rebuild`, `Atlas`).
- Backend CI is Python 3.11; local may be newer. No 3.12+ syntax (no `type X = …`, no PEP 695 generics).
- API tests that exercise chat turns must patch `ghostbrain.api.repo.chat.require_provider` (see `ghostbrain/api/tests/test_chat.py` autouse fixture).
- Desktop typecheck is `npm run typecheck --prefix desktop` (NOT `tsc --noEmit`, which checks nothing). Desktop lint is `npm run lint --prefix desktop` with `--max-warnings 0` semantics — run it; release builds fail on warnings.
- `window.gb` test mocks: per-field `window.gb.api.request = vi.fn(...) as unknown as typeof window.gb.api.request;`.
- Platform-specific tests: gate with `describe.skipIf(process.platform === 'win32')`.
- Location fields on disk: `context: str|null`, `project: str|null` (bare slug), `folder: str|null` (no leading/trailing `/`; null = location root), `auto_filed: "pending"|"done"|"skipped"`.
- API `FolderRef` = `{context, project: str|null, path}`; `path == ""` is the location root.
- Auto-filing runs once per chat, after the first assistant reply, only when `auto_filed == "pending"`. Never retried. Manual moves always win.
- Commit after each task; messages `feat(chat): …` / `test(chat): …` / `refactor(tree): …`, ending with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Turn writes clobbering a concurrent move.** The stream handler holds a stale conv dict and writes it on every event; an auto-file (or a drag) landing mid-turn must survive. Pinned in Task 1 (`test_turn_write_preserves_location_moved_on_disk`).
2. **Legacy chats** with `project: "ctx/slug"` and no `context`/`auto_filed` keys must read, list, tree and export correctly, and must never be auto-filed. Pinned in Task 1 and Task 4.
3. **Folder move into itself / onto an existing name / into an archived project** must be rejected without touching any chat. Pinned in Task 2.
4. **Route shadowing**: `GET /v1/chat/tree` and `PATCH|DELETE /v1/chat/folders` must not be swallowed by `/{conv_id}` routes. Pinned in Task 3 (`test_tree_route_not_shadowed`, folder route tests).
5. **Chats under a context removed from routing.yaml or a deleted project** must still appear (in Unfiled, flagged) rather than vanish. Pinned in Task 2 (`test_tree_orphaned_chat_lands_in_unfiled`).

---

## File Map

Backend:
- Modify `ghostbrain/api/repo/chat_store.py` — normalization, new fields, shared lock, location-preserving turn writes, `move`, `apply_auto_file`, `rewrite_all`.
- Create `ghostbrain/api/repo/chat_folders.py` — location validation, folder registry, tree, folder create/move/delete, chat move, project repoint.
- Create `ghostbrain/api/repo/chat_autofile.py` — first-reply auto-filing.
- Modify `ghostbrain/api/repo/chat.py` — trigger auto-file after first reply.
- Modify `ghostbrain/api/repo/chat_export.py` — use `context`/`project` fields.
- Modify `ghostbrain/api/repo/projects.py` — `rename_project` step 3 uses `chat_folders.repoint_project`.
- Modify `ghostbrain/api/models/chat.py` — new fields, tree models, request model.
- Modify `ghostbrain/api/routes/chat.py` — tree + folder routes, PATCH move.
- Tests: `tests/test_chat_store.py`, create `tests/test_chat_folders.py`, create `tests/test_chat_autofile.py`, `tests/test_chat_export.py`, `tests/test_project_rename.py`, `ghostbrain/api/tests/test_routes_chat_update.py`, create `ghostbrain/api/tests/test_routes_chat_folders.py`.

Desktop (`desktop/src/…`):
- Modify `shared/api-types.ts` — conversation fields, `ChatTree` types.
- Create `renderer/components/tree/ScopeTree.tsx`, `renderer/components/tree/tree-types.ts`.
- Modify `renderer/components/docs/DocTree.tsx` — thin wrapper over `ScopeTree`.
- Create `renderer/components/chat/ChatTree.tsx`, `renderer/components/chat/MoveToMenu.tsx`, `renderer/components/chat/FiledNotice.tsx`.
- Create `renderer/lib/chat-autofile.ts` — poll until auto-filing settles.
- Modify `renderer/lib/api/hooks.ts` — chat tree/move/folder hooks.
- Modify `renderer/stores/chat.ts` — `filed` notices.
- Modify `renderer/screens/chat.tsx` — use `ChatTree`, trigger polling, show notice; remove `groupConversations`, `FileMenu`.
- Tests: `renderer/__tests__/ScopeTree.test.tsx` (new), `renderer/__tests__/ChatTree.test.tsx` (new), `renderer/__tests__/chat-autofile.test.ts` (new), rewrite `renderer/__tests__/ConversationFolders.test.tsx`, keep `renderer/__tests__/DocTree.test.tsx` **unchanged** and green.

---

### Task 1: chat_store — location fields, shared lock, safe turn writes

**Files:**
- Modify: `ghostbrain/api/repo/chat_store.py`
- Test: `tests/test_chat_store.py`

**Interfaces:**
- Produces:
  - `chat_store.lock: threading.RLock` — guards every read-modify-write of chat files and `folders.json`.
  - `chat_store.normalize(conv: dict) -> dict` (mutates + returns).
  - `chat_store.get(conv_id) -> dict | None` (normalized).
  - `chat_store.list_all() -> list[dict]` — summaries now include `context`, `project`, `folder`, `auto_filed`.
  - `chat_store.update(conv_id, *, title) -> dict | None` (the `project` kwarg is REMOVED).
  - `chat_store.move(conv_id, *, context: str|None, project: str|None, folder: str|None) -> dict | None` — no validation; sets `auto_filed="done"`; does not bump `updated_at`. `context=None` clears all three.
  - `chat_store.apply_auto_file(conv_id, context: str|None, project: str|None) -> dict | None` — returns the conv only if it was still `pending` (then sets location if `context`, `folder=None`, `auto_filed="done"`); returns None if missing or not pending.
  - `chat_store.rewrite_all(fn: Callable[[dict], bool]) -> int` — under lock, for every readable chat: normalize, call `fn(conv)`; if it returns True, write. Returns count written.
  - `chat_store.iter_all() -> list[dict]` — all normalized full convs (used by tree/folders).

- [ ] **Step 1: Write failing tests** (append to `tests/test_chat_store.py`; use the existing chats-dir fixture in that file — read its top first and match it):

```python
import json

from ghostbrain.api.repo import chat_store


def _raw_write(chats_dir, conv):
    chats_dir.mkdir(parents=True, exist_ok=True)
    (chats_dir / f"{conv['id']}.json").write_text(json.dumps(conv))


def _legacy(conv_id="legacy1", project="work/atlas"):
    return {
        "id": conv_id, "title": "old", "created_at": 1.0, "updated_at": 2.0,
        "claude_session_id": None, "project": project, "messages": [],
    }


def test_legacy_project_is_split_on_read(chats):
    _raw_write(chats, _legacy())
    conv = chat_store.get("legacy1")
    assert (conv["context"], conv["project"], conv["folder"]) == ("work", "atlas", None)
    assert conv["auto_filed"] == "skipped"


def test_legacy_unfiled_reads_clean(chats):
    _raw_write(chats, _legacy(project=None))
    conv = chat_store.get("legacy1")
    assert conv["context"] is None and conv["project"] is None and conv["folder"] is None


def test_legacy_project_without_slash_is_dropped(chats):
    _raw_write(chats, _legacy(project="nonsense"))
    conv = chat_store.get("legacy1")
    assert conv["context"] is None and conv["project"] is None


def test_list_all_includes_location(chats):
    _raw_write(chats, _legacy())
    [s] = chat_store.list_all()
    assert s["context"] == "work" and s["project"] == "atlas"
    assert s["folder"] is None and s["auto_filed"] == "skipped"


def test_create_starts_pending_and_unfiled(chats):
    conv = chat_store.create()
    assert conv["auto_filed"] == "pending"
    assert conv["context"] is None and conv["project"] is None and conv["folder"] is None


def test_move_sets_location_and_done(chats):
    conv = chat_store.create()
    before = conv["updated_at"]
    moved = chat_store.move(conv["id"], context="work", project="atlas", folder="q4")
    assert (moved["context"], moved["project"], moved["folder"]) == ("work", "atlas", "q4")
    assert moved["auto_filed"] == "done"
    assert chat_store.get(conv["id"])["updated_at"] == before


def test_move_context_none_clears_everything(chats):
    conv = chat_store.create()
    chat_store.move(conv["id"], context="work", project="atlas", folder="q4")
    moved = chat_store.move(conv["id"], context=None, project="ignored", folder="ignored")
    assert moved["context"] is None and moved["project"] is None and moved["folder"] is None


def test_move_missing_returns_none(chats):
    assert chat_store.move("nope", context=None, project=None, folder=None) is None


def test_apply_auto_file_only_when_pending(chats):
    conv = chat_store.create()
    filed = chat_store.apply_auto_file(conv["id"], "work", "atlas")
    assert filed["context"] == "work" and filed["auto_filed"] == "done"
    assert chat_store.apply_auto_file(conv["id"], "personal", None) is None
    assert chat_store.get(conv["id"])["context"] == "work"


def test_apply_auto_file_none_marks_done_unfiled(chats):
    conv = chat_store.create()
    out = chat_store.apply_auto_file(conv["id"], None, None)
    assert out["context"] is None and out["auto_filed"] == "done"


def test_apply_auto_file_loses_to_manual_move(chats):
    conv = chat_store.create()
    chat_store.move(conv["id"], context="personal", project=None, folder=None)
    assert chat_store.apply_auto_file(conv["id"], "work", "atlas") is None
    assert chat_store.get(conv["id"])["context"] == "personal"


def test_turn_write_preserves_location_moved_on_disk(chats):
    conv = chat_store.create()
    stale = chat_store.get(conv["id"])          # what the stream handler holds
    chat_store.move(conv["id"], context="work", project="atlas", folder="q4")
    chat_store.append_user_message(stale, "hello")
    chat_store.append_assistant_message(stale, "hi", [])
    chat_store.set_session_id(stale, "sess-1", "claude")
    disk = chat_store.get(conv["id"])
    assert (disk["context"], disk["project"], disk["folder"]) == ("work", "atlas", "q4")
    assert disk["auto_filed"] == "done"
    assert [m["text"] for m in disk["messages"]] == ["hello", "hi"]
    assert stale["context"] == "work"            # caller's dict is refreshed too


def test_rewrite_all_writes_only_changed(chats):
    a = chat_store.create()
    chat_store.append_user_message(a, "x")       # so create() doesn't reuse it
    b = chat_store.create()

    def fn(conv):
        if conv["id"] == a["id"]:
            conv["folder"] = "z"
            conv["context"] = "work"
            return True
        return False

    assert chat_store.rewrite_all(fn) == 1
    assert chat_store.get(a["id"])["folder"] == "z"
    assert chat_store.get(b["id"])["folder"] is None


def test_update_title_only(chats):
    conv = chat_store.create()
    out = chat_store.update(conv["id"], title="renamed")
    assert out["title"] == "renamed"
```

If the file has no `chats` fixture, add one at the top:

```python
import pytest

@pytest.fixture
def chats(tmp_path, monkeypatch):
    d = tmp_path / "chats"
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(d))
    return d
```

- [ ] **Step 2: Run to confirm failures**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && python -m pytest tests/test_chat_store.py -q`
Expected: the new tests FAIL (KeyError `context`, missing `move`, etc.); pre-existing tests pass.

- [ ] **Step 3: Implement in `chat_store.py`**

Replace `_create_lock` with a shared re-entrant lock and add the helpers. Key code:

```python
from typing import Callable

lock = threading.RLock()  # every read-modify-write of chat files + folders.json

LOCATION_FIELDS = ("context", "project", "folder", "auto_filed")
AUTO_FILE_STATES = ("pending", "done", "skipped")


def normalize(conv: dict) -> dict:
    """Bring any stored shape up to the current one (mutates + returns).

    Legacy files hold ``project: "ctx/slug"`` and no context/folder/auto_filed.
    They predate auto-filing, so they read as ``skipped`` and are never routed.
    """
    project = conv.get("project")
    if project and not conv.get("context"):
        ctx, sep, slug = str(project).partition("/")
        if sep and ctx:
            conv["context"], conv["project"] = ctx, (slug or None)
        else:
            conv["project"] = None
    if not conv.get("context"):
        conv["context"] = None
        conv["project"] = None
        conv["folder"] = None
    conv.setdefault("project", None)
    conv["folder"] = conv.get("folder") or None
    if conv.get("auto_filed") not in AUTO_FILE_STATES:
        conv["auto_filed"] = "skipped"
    return conv


def _read_raw(conv_id: str) -> dict | None:
    path = _conv_path(conv_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        log.warning("unreadable conversation file: %s", path)
        return None


def get(conv_id: str) -> dict | None:
    conv = _read_raw(conv_id)
    return normalize(conv) if conv is not None else None


def _write_turn(conv: dict) -> None:
    """Persist a turn-path write without clobbering a concurrent move.

    The stream handler holds its own dict for the whole turn; location fields
    are owned by move()/apply_auto_file(), so they're re-read from disk here.
    A conversation deleted mid-turn is re-created (pre-existing behaviour).
    """
    with lock:
        disk = _read_raw(conv["id"])
        if disk is not None:
            normalize(disk)
            for f in LOCATION_FIELDS:
                conv[f] = disk[f]
        _write(conv)
```

- `create()`: use `with lock:`; new conv dict gets `"context": None, "project": None, "folder": None, "auto_filed": "pending"`. When reusing `_newest_empty()`, normalize it; if it has no `context` and `auto_filed != "pending"`, set `"pending"` and `_write` it. `_newest_empty` should normalize what it returns.
- `list_all()`: normalize each conv; summary adds `"context"`, `"project"`, `"folder"`, `"auto_filed"`.
- `iter_all()`: like `list_all` but returns the normalized full dicts (skip unreadable).
- `update(conv_id, *, title=_UNSET)`: drop the `project` parameter; wrap in `with lock:`.
- `move(...)`:

```python
def move(conv_id: str, *, context: str | None, project: str | None, folder: str | None) -> dict | None:
    """Set a chat's location. No validation (chat_folders does that). A manual
    move always ends auto-filing, and doesn't count as activity (updated_at)."""
    with lock:
        conv = get(conv_id)
        if conv is None:
            return None
        if context is None:
            project = folder = None
        conv.update(context=context, project=project, folder=folder or None, auto_filed="done")
        _write(conv)
        return conv
```

- `apply_auto_file(...)`:

```python
def apply_auto_file(conv_id: str, context: str | None, project: str | None) -> dict | None:
    """Land a router decision — only if the chat is still waiting for one."""
    with lock:
        conv = get(conv_id)
        if conv is None or conv["auto_filed"] != "pending":
            return None
        if context:
            conv.update(context=context, project=project, folder=None)
        conv["auto_filed"] = "done"
        _write(conv)
        return conv
```

- `rewrite_all(fn)`: `with lock:` loop `chats_dir().glob("*.json")`, `_read_raw` by stem, skip None, `normalize`, `if fn(conv): _write(conv); n += 1`.
- `append_user_message`, `append_assistant_message`, `set_session_id`: replace their `_write(conv)` with `_write_turn(conv)`.
- `delete()`: wrap in `with lock:`.

Then fix the one in-repo caller of the removed `update(project=…)`: `ghostbrain/api/repo/projects.py` step 3 (Task 2 replaces it properly; for now change it to `chat_store.move(conv["id"], context=context, project=new_slug, folder=conv.get("folder"))` and the undo to move back to `slug`, comparing `conv.get("context") == context and conv.get("project") == slug` — read the surrounding variables first to use the right names). The `PATCH` route still calls `update(project=…)` — leave the route alone in this task; Task 3 rewrites it. To keep the API suite importable meanwhile, nothing else is needed (the route only breaks at call time).

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && python -m pytest tests/test_chat_store.py tests/test_chat_repo.py tests/test_project_rename.py -q`
Expected: all PASS except project-rename tests that assert the legacy `"ctx/slug"` chat `project` value — update those assertions to the new split fields (`context`, bare `project`).

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-chatfile && git add -A ghostbrain/api/repo/chat_store.py ghostbrain/api/repo/projects.py tests/ && git commit -m "feat(chat): chat location fields, shared store lock, move-safe turn writes"
```

---

### Task 2: chat_folders — validation, registry, tree, folder ops

**Files:**
- Create: `ghostbrain/api/repo/chat_folders.py`
- Modify: `ghostbrain/api/repo/projects.py` (rename_project step 3)
- Test: `tests/test_chat_folders.py`, `tests/test_project_rename.py`

**Interfaces:**
- Consumes: Task 1's `chat_store.lock`, `get`, `move`, `rewrite_all`, `iter_all`, `list_all`.
- Produces:
  - Exceptions (all subclass `ChatFolderError(Exception)` with class attr `status: int`): `InvalidLocation` (422), `FolderNotFound` (404), `FolderExists` (409), `FolderNotEmpty` (409), `ChatNotFound` (404).
  - `Loc = tuple[str, str | None]` (context, project).
  - `clean_path(path: str | None) -> str` — `""` for root.
  - `check_location(context: str, project: str | None, *, for_write: bool = True) -> None`.
  - `folder_exists(context, project, path) -> bool`.
  - `create(context, project, path) -> dict` → `{"context","project","path"}`.
  - `move(src: tuple[str, str|None, str], dst: tuple[str, str|None, str]) -> dict` → dst FolderRef.
  - `delete(context, project, path) -> None`.
  - `move_chat(conv_id, *, context: str|None, project: str|None, folder: str|None) -> dict` → normalized conv.
  - `tree() -> dict` → `{"unfiled": [summary...], "scopes": [{"context","project","name","archived","folders":[node...],"chats":[summary...]}]}`; node = `{"name","path","folders":[...],"chats":[...]}`; summary = `chat_store.list_all()` item plus `"unknown_location": bool` (only meaningful in `unfiled`; always present).
  - `repoint_project(context, old_slug, new_slug) -> None` — rewrites chats and registry entries.

- [ ] **Step 1: Write failing tests** `tests/test_chat_folders.py`. Use the repo's vault fixtures (read `tests/conftest.py` for the fixture that creates a temp vault with `routing.yaml` contexts — e.g. how `tests/test_project_rename.py` sets up `work`/`personal` contexts and creates projects with `projects.create_project`). Tests to write:

```python
import json
import pytest

from ghostbrain.api.repo import chat_folders as cf, chat_store, projects


@pytest.fixture
def chats(tmp_path, monkeypatch):
    d = tmp_path / "chats"
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(d))
    return d


@pytest.fixture
def env(tmp_path, monkeypatch, chats):
    # Same minimal vault as tests/test_project_rename.py: contexts work + personal.
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    (v / "90-meta" / "routing.yaml").write_text("contexts:\n  - work\n  - personal\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(v))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    atlas = projects.create_project("work", "Atlas")
    return {"atlas": atlas["slug"]}


def _chat(title="t"):
    c = chat_store.create()
    chat_store.append_user_message(c, title)   # non-empty so create() won't reuse it
    return c


def test_clean_path_rejects_traversal():
    for bad in ("../x", "a/../b", "/abs", ".hidden", "a/.b"):
        with pytest.raises(cf.InvalidLocation):
            cf.clean_path(bad)
    assert cf.clean_path("a//b/") == "a/b"
    assert cf.clean_path("") == ""


def test_check_location(env):
    cf.check_location("work", None)
    cf.check_location("work", env["atlas"])
    with pytest.raises(cf.InvalidLocation):
        cf.check_location("nope", None)
    with pytest.raises(cf.InvalidLocation):
        cf.check_location("work", "missing")


def test_archived_project_rejects_writes(env):
    projects.update_project("work", env["atlas"], archived=True)
    with pytest.raises(cf.InvalidLocation):
        cf.check_location("work", env["atlas"])
    cf.check_location("work", env["atlas"], for_write=False)


def test_create_and_duplicate(env):
    assert cf.create("work", None, "q4/plans") == {"context": "work", "project": None, "path": "q4/plans"}
    assert cf.folder_exists("work", None, "q4")          # implied parent
    with pytest.raises(cf.FolderExists):
        cf.create("work", None, "q4/plans")
    with pytest.raises(cf.InvalidLocation):
        cf.create("work", None, "")


def test_registry_survives_reload_and_corruption(env, chats):
    cf.create("work", None, "empty")
    assert cf.folder_exists("work", None, "empty")
    (chats / "folders.json").write_text("{not json")
    assert not cf.folder_exists("work", None, "empty")   # lost, but no crash
    c = _chat()
    cf.move_chat(c["id"], context="work", project=None, folder="kept")
    (chats / "folders.json").unlink()
    assert cf.folder_exists("work", None, "kept")        # implied by the chat


def test_move_chat_validates_and_creates_folder(env):
    c = _chat()
    out = cf.move_chat(c["id"], context="work", project=env["atlas"], folder="a/b")
    assert (out["context"], out["project"], out["folder"]) == ("work", env["atlas"], "a/b")
    assert cf.folder_exists("work", env["atlas"], "a/b")
    with pytest.raises(cf.InvalidLocation):
        cf.move_chat(c["id"], context="nope", project=None, folder=None)
    with pytest.raises(cf.ChatNotFound):
        cf.move_chat("missing", context="work", project=None, folder=None)
    out = cf.move_chat(c["id"], context=None, project=None, folder=None)
    assert out["context"] is None


def test_move_folder_rewrites_chats_and_subfolders(env):
    cf.create("work", None, "q4/empty-child")
    c = _chat()
    cf.move_chat(c["id"], context="work", project=None, folder="q4/deep")
    other = _chat()
    cf.move_chat(other["id"], context="work", project=None, folder="q40")   # prefix trap
    cf.move(("work", None, "q4"), ("work", env["atlas"], "archive/q4"))
    moved = chat_store.get(c["id"])
    assert (moved["context"], moved["project"], moved["folder"]) == ("work", env["atlas"], "archive/q4/deep")
    assert chat_store.get(other["id"])["folder"] == "q40"
    assert cf.folder_exists("work", env["atlas"], "archive/q4/empty-child")
    assert not cf.folder_exists("work", None, "q4")


def test_move_folder_rejections_leave_chats_alone(env):
    cf.create("work", None, "a")
    cf.create("work", None, "b")
    c = _chat()
    cf.move_chat(c["id"], context="work", project=None, folder="a")
    with pytest.raises(cf.InvalidLocation):
        cf.move(("work", None, "a"), ("work", None, "a/inner"))
    with pytest.raises(cf.FolderExists):
        cf.move(("work", None, "a"), ("work", None, "b"))
    with pytest.raises(cf.FolderNotFound):
        cf.move(("work", None, "zzz"), ("work", None, "y"))
    projects.update_project("work", env["atlas"], archived=True)
    with pytest.raises(cf.InvalidLocation):
        cf.move(("work", None, "a"), ("work", env["atlas"], "a"))
    assert chat_store.get(c["id"])["folder"] == "a"


def test_delete_only_empty(env):
    cf.create("work", None, "x/y")
    with pytest.raises(cf.FolderNotEmpty):
        cf.delete("work", None, "x")
    cf.delete("work", None, "x/y")
    cf.delete("work", None, "x")
    assert not cf.folder_exists("work", None, "x")
    c = _chat()
    cf.move_chat(c["id"], context="work", project=None, folder="busy")
    with pytest.raises(cf.FolderNotEmpty):
        cf.delete("work", None, "busy")
    with pytest.raises(cf.FolderNotFound):
        cf.delete("work", None, "never")


def test_tree_shape(env):
    cf.create("work", env["atlas"], "plans")
    c = _chat("in plans")
    cf.move_chat(c["id"], context="work", project=env["atlas"], folder="plans")
    loose = _chat("loose")
    t = cf.tree()
    assert [x["id"] for x in t["unfiled"]] == [loose["id"]]
    scopes = {(s["context"], s["project"]): s for s in t["scopes"]}
    assert ("work", None) in scopes and ("personal", None) in scopes
    atlas = scopes[("work", env["atlas"])]
    assert atlas["name"] == "Atlas" and atlas["archived"] is False
    [plans] = atlas["folders"]
    assert plans["name"] == "plans" and plans["path"] == "plans"
    assert [x["id"] for x in plans["chats"]] == [c["id"]]


def test_tree_orphaned_chat_lands_in_unfiled(env, chats):
    raw = {"id": "orph", "title": "o", "created_at": 1, "updated_at": 1, "messages": [],
           "context": "gone", "project": None, "folder": None, "auto_filed": "done"}
    (chats / "orph.json").write_text(json.dumps(raw))
    ghost = _chat()
    chat_store.move(ghost["id"], context="work", project="deleted-proj", folder=None)
    t = cf.tree()
    flagged = {x["id"]: x["unknown_location"] for x in t["unfiled"]}
    assert flagged == {"orph": True, ghost["id"]: True}


def test_tree_hides_empty_archived_projects(env):
    empty = projects.create_project("work", "Old")
    projects.update_project("work", empty["slug"], archived=True)
    keys = {(s["context"], s["project"]) for s in cf.tree()["scopes"]}
    assert ("work", empty["slug"]) not in keys


def test_repoint_project(env):
    cf.create("work", env["atlas"], "plans")
    c = _chat()
    cf.move_chat(c["id"], context="work", project=env["atlas"], folder="plans")
    cf.repoint_project("work", env["atlas"], "atlas-2")
    assert chat_store.get(c["id"])["project"] == "atlas-2"
    assert ("work", "atlas-2", "plans") in cf._registry()   # registry entry moved too
```

Also add to `tests/test_project_rename.py` one test: a chat filed under the project with a folder follows the rename (context, new slug, same folder) and a registry folder follows too. Mirror that file's existing chat-repoint test.

- [ ] **Step 2: Run to confirm failures**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && python -m pytest tests/test_chat_folders.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `ghostbrain/api/repo/chat_folders.py`**

```python
"""Chat folders and locations (chat auto-filing spec §1, §3).

A chat's location is (context, project slug | None, folder | None) stored on
the chat itself. ``folders.json`` next to the chats only keeps EMPTY folders
alive: the folder set is registry ∪ every folder a chat references ∪ their
parents, so losing the registry only loses empty folders.
"""
from __future__ import annotations

import json
import logging

from ghostbrain import routing_config
from ghostbrain.api.repo import chat_store
from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.api.repo.doc_library.scope import InvalidPath, clean_rel
from ghostbrain.paths import chats_dir

log = logging.getLogger("ghostbrain.chat.folders")

Entry = tuple[str, "str | None", str]  # (context, project, path)


class ChatFolderError(Exception):
    status = 422


class InvalidLocation(ChatFolderError):
    status = 422


class FolderNotFound(ChatFolderError):
    status = 404


class FolderExists(ChatFolderError):
    status = 409


class FolderNotEmpty(ChatFolderError):
    status = 409


class ChatNotFound(ChatFolderError):
    status = 404


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


def _registry_path():
    return chats_dir() / "folders.json"


def _registry() -> set[Entry]:
    try:
        raw = json.loads(_registry_path().read_text(encoding="utf-8"))
        return {(f["context"], f.get("project"), f["path"]) for f in raw.get("folders", [])}
    except FileNotFoundError:
        return set()
    except (json.JSONDecodeError, OSError, KeyError, TypeError, AttributeError):
        log.warning("unreadable chat folder registry %s; treating as empty", _registry_path())
        return set()


def _save_registry(entries: set[Entry]) -> None:
    d = chats_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = _registry_path()
    tmp = target.with_name(target.name + ".tmp")
    rows = [{"context": c, "project": p, "path": path} for c, p, path in sorted(entries, key=lambda e: (e[0], e[1] or "", e[2]))]
    tmp.write_text(json.dumps({"folders": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def _with_parents(entries) -> set[Entry]:
    out: set[Entry] = set()
    for c, p, path in entries:
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            out.add((c, p, "/".join(parts[:i])))
    return out


def _all_folders(convs: list[dict] | None = None) -> set[Entry]:
    convs = chat_store.iter_all() if convs is None else convs
    used = {(c["context"], c["project"], c["folder"]) for c in convs if c["context"] and c["folder"]}
    return _with_parents(_registry() | used)


def folder_exists(context: str, project: str | None, path: str) -> bool:
    return (context, project, clean_path(path)) in _all_folders()


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def create(context: str, project: str | None, path: str) -> dict:
    cleaned = clean_path(path)
    if not cleaned:
        raise InvalidLocation("folder path is required")
    with chat_store.lock:
        check_location(context, project)
        if (context, project, cleaned) in _all_folders():
            raise FolderExists(f"folder already exists: {cleaned}")
        _save_registry(_registry() | {(context, project, cleaned)})
    return {"context": context, "project": project, "path": cleaned}


def move(src: tuple, dst: tuple) -> dict:
    s_ctx, s_proj, s_raw = src
    d_ctx, d_proj, d_raw = dst
    s_path, d_path = clean_path(s_raw), clean_path(d_raw)
    if not s_path or not d_path:
        raise InvalidLocation("folder path is required")
    with chat_store.lock:
        existing = _all_folders()
        if (s_ctx, s_proj, s_path) not in existing:
            raise FolderNotFound(f"folder not found: {s_path}")
        check_location(d_ctx, d_proj)
        if (s_ctx, s_proj) == (d_ctx, d_proj) and _under(d_path, s_path):
            raise InvalidLocation("cannot move a folder into itself")
        if (d_ctx, d_proj, d_path) in existing:
            raise FolderExists(f"folder already exists: {d_path}")

        def remap(path: str) -> str:
            return d_path + path[len(s_path):]

        reg = set()
        for c, p, path in _registry():
            if (c, p) == (s_ctx, s_proj) and _under(path, s_path):
                reg.add((d_ctx, d_proj, remap(path)))
            else:
                reg.add((c, p, path))
        reg.add((d_ctx, d_proj, d_path))  # keep the moved folder even if it was only implied

        def fn(conv: dict) -> bool:
            if (conv["context"], conv["project"]) == (s_ctx, s_proj) and conv["folder"] and _under(conv["folder"], s_path):
                conv.update(context=d_ctx, project=d_proj, folder=remap(conv["folder"]))
                return True
            return False

        chat_store.rewrite_all(fn)
        _save_registry(reg)
    return {"context": d_ctx, "project": d_proj, "path": d_path}


def delete(context: str, project: str | None, path: str) -> None:
    cleaned = clean_path(path)
    with chat_store.lock:
        convs = chat_store.iter_all()
        folders = _all_folders(convs)
        if (context, project, cleaned) not in folders:
            raise FolderNotFound(f"folder not found: {cleaned}")
        if any((c, p) == (context, project) and path_ != cleaned and _under(path_, cleaned) for c, p, path_ in folders):
            raise FolderNotEmpty(f"folder is not empty: {cleaned}")
        if any((c["context"], c["project"]) == (context, project) and c["folder"] and _under(c["folder"], cleaned) for c in convs):
            raise FolderNotEmpty(f"folder is not empty: {cleaned}")
        _save_registry(_registry() - {(context, project, cleaned)})


def move_chat(conv_id: str, *, context: str | None, project: str | None, folder: str | None) -> dict:
    with chat_store.lock:
        if chat_store.get(conv_id) is None:
            raise ChatNotFound(conv_id)
        if context is None:
            return chat_store.move(conv_id, context=None, project=None, folder=None)
        check_location(context, project)
        cleaned = clean_path(folder) or None
        if cleaned and (context, project, cleaned) not in _all_folders():
            _save_registry(_registry() | {(context, project, cleaned)})
        return chat_store.move(conv_id, context=context, project=project, folder=cleaned)


def repoint_project(context: str, old_slug: str, new_slug: str) -> None:
    with chat_store.lock:
        def fn(conv: dict) -> bool:
            if conv["context"] == context and conv["project"] == old_slug:
                conv["project"] = new_slug
                return True
            return False

        chat_store.rewrite_all(fn)
        _save_registry({(c, new_slug if (c == context and p == old_slug) else p, path) for c, p, path in _registry()})
```

`tree()`:

```python
def _summary(conv: dict, unknown: bool = False) -> dict:
    return {
        "id": conv["id"], "title": conv["title"], "created_at": conv["created_at"],
        "updated_at": conv["updated_at"], "message_count": len(conv.get("messages", [])),
        "context": conv["context"], "project": conv["project"], "folder": conv["folder"],
        "auto_filed": conv["auto_filed"], "unknown_location": unknown,
    }


def _node(name: str, path: str, entries: set[str], chats_by_folder: dict[str, list[dict]]) -> dict:
    prefix = f"{path}/" if path else ""
    child_names = sorted({e[len(prefix):].split("/", 1)[0] for e in entries if e.startswith(prefix) and e != path and e})
    return {
        "name": name,
        "path": path,
        "folders": [_node(n, f"{prefix}{n}", entries, chats_by_folder) for n in child_names],
        "chats": sorted(chats_by_folder.get(path, []), key=lambda s: s["updated_at"], reverse=True),
    }


def tree() -> dict:
    with chat_store.lock:
        convs = chat_store.iter_all()
        folders = _all_folders(convs)
    contexts = routing_config.contexts()
    projs = projects_repo.list_projects(include_archived=True)
    known = {(p["context"], p["slug"]): p for p in projs}
    unfiled: list[dict] = []
    by_loc: dict[tuple, dict[str, list[dict]]] = {}
    for c in convs:
        ctx, proj = c["context"], c["project"]
        if ctx is None:
            unfiled.append(_summary(c))
        elif ctx not in contexts or (proj is not None and (ctx, proj) not in known):
            unfiled.append(_summary(c, unknown=True))
        else:
            by_loc.setdefault((ctx, proj), {}).setdefault(c["folder"] or "", []).append(_summary(c))
    unfiled.sort(key=lambda s: s["updated_at"], reverse=True)

    def scope(ctx: str, proj: str | None, name: str, archived: bool) -> dict:
        entries = {path for c, p, path in folders if (c, p) == (ctx, proj)}
        root = _node(name, "", entries, by_loc.get((ctx, proj), {}))
        return {"context": ctx, "project": proj, "name": name, "archived": archived,
                "folders": root["folders"], "chats": root["chats"]}

    scopes = []
    for ctx in contexts:
        scopes.append(scope(ctx, None, ctx, False))
        for p in sorted((p for p in projs if p["context"] == ctx), key=lambda p: p["name"].lower()):
            s = scope(ctx, p["slug"], p["name"], bool(p.get("archived")))
            if s["archived"] and not s["chats"] and not s["folders"]:
                continue
            scopes.append(s)
    return {"unfiled": unfiled, "scopes": scopes}
```

Then in `projects.py` `rename_project` step 3, replace the chat loop (and its undo) with:

```python
        # 3. Chats (and their folders) scoped to the project.
        from ghostbrain.api.repo import chat_folders

        chat_folders.repoint_project(context, slug, new_slug)
        undo.append(lambda: chat_folders.repoint_project(context, new_slug, slug))
```

(Read the function first: use its real names for the old/new slug variables.)

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && python -m pytest tests/test_chat_folders.py tests/test_project_rename.py tests/test_chat_store.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-chatfile && git add -A ghostbrain/api/repo/chat_folders.py ghostbrain/api/repo/projects.py tests/ && git commit -m "feat(chat): chat folders — registry, locations, tree, folder moves"
```

---

### Task 3: API — models, tree + folder routes, PATCH move

**Files:**
- Modify: `ghostbrain/api/models/chat.py`, `ghostbrain/api/routes/chat.py`
- Test: `ghostbrain/api/tests/test_routes_chat_update.py` (update), create `ghostbrain/api/tests/test_routes_chat_folders.py`

**Interfaces:**
- Consumes: Task 2's `chat_folders.*` and `ChatFolderError.status`.
- Produces (HTTP):
  - `GET /v1/chat/tree` → `ChatTree` (shape from Task 2 `tree()`).
  - `POST /v1/chat/folders` body `FolderRef` → `FolderRef`.
  - `PATCH /v1/chat/folders` body `{"from": FolderRef, "to": FolderRef}` → `FolderRef`.
  - `DELETE /v1/chat/folders?context=&path=&project=` → `{"deleted": true}`.
  - `PATCH /v1/chat/{id}` body `{title?, context?, project?, folder?}` → `Conversation`.
  - `ConversationSummary`/`Conversation` gain `context: str|None`, `folder: str|None`, `auto_filed: str = "skipped"`; `project` is the bare slug.

- [ ] **Step 1: Models** (`ghostbrain/api/models/chat.py`): add fields to `ConversationSummary` and `Conversation`:

```python
    context: str | None = None
    project: str | None = None
    folder: str | None = None
    auto_filed: Literal["pending", "done", "skipped"] = "skipped"
```

Add:

```python
class ChatTreeChat(ConversationSummary):
    unknown_location: bool = False


class ChatFolderNode(BaseModel):
    name: str
    path: str
    folders: list["ChatFolderNode"] = []
    chats: list[ChatTreeChat] = []


class ChatScope(BaseModel):
    context: str
    project: str | None = None
    name: str
    archived: bool = False
    folders: list[ChatFolderNode] = []
    chats: list[ChatTreeChat] = []


class ChatTree(BaseModel):
    unfiled: list[ChatTreeChat] = []
    scopes: list[ChatScope] = []
```

Replace `UpdateConversationRequest`:

```python
class UpdateConversationRequest(BaseModel):
    """Partial update; absent fields stay untouched (model_fields_set).

    Location: send ``context`` (null unfiles) with optional ``project`` slug
    and ``folder``. Legacy clients send only ``project`` as ``context/slug``
    (null unfiles) — still accepted.
    """

    title: str | None = Field(None, min_length=1, max_length=200)
    context: str | None = Field(None, max_length=200)
    project: str | None = Field(None, max_length=200)
    folder: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _something_to_update(self) -> "UpdateConversationRequest":
        if not self.model_fields_set:
            raise ValueError("nothing to update — pass title and/or a location")
        return self
```

- [ ] **Step 2: Write failing route tests.** `ghostbrain/api/tests/test_routes_chat_folders.py` (use the same fixtures as `test_routes_chat_update.py`: `client`, `auth_headers`, `tmp_chats_dir`, `tmp_vault`; contexts in that vault include `personal` — check `conftest.py` for which contexts exist and use them):

```python
import pytest

from ghostbrain.api.repo import chat_store, projects


@pytest.fixture
def proj(tmp_vault):
    return projects.create_project("personal", "Site Rebuild")


@pytest.fixture
def conv(client, auth_headers, tmp_chats_dir):
    c = client.post("/v1/chat", headers=auth_headers).json()
    chat_store.append_user_message(chat_store.get(c["id"]), "hello")
    return c


def test_tree_route_not_shadowed(client, auth_headers, tmp_chats_dir, tmp_vault):
    r = client.get("/v1/chat/tree", headers=auth_headers)
    assert r.status_code == 200
    assert set(r.json()) == {"unfiled", "scopes"}


def test_folder_crud(client, auth_headers, tmp_chats_dir, proj):
    ref = {"context": "personal", "project": proj["slug"], "path": "plans"}
    assert client.post("/v1/chat/folders", headers=auth_headers, json=ref).status_code == 200
    assert client.post("/v1/chat/folders", headers=auth_headers, json=ref).status_code == 409
    r = client.patch("/v1/chat/folders", headers=auth_headers,
                     json={"from": ref, "to": {**ref, "path": "renamed"}})
    assert r.status_code == 200 and r.json()["path"] == "renamed"
    r = client.delete("/v1/chat/folders", headers=auth_headers,
                      params={"context": "personal", "project": proj["slug"], "path": "renamed"})
    assert r.status_code == 200 and r.json() == {"deleted": True}


def test_folder_errors(client, auth_headers, tmp_chats_dir, tmp_vault):
    bad = {"context": "nope", "project": None, "path": "x"}
    assert client.post("/v1/chat/folders", headers=auth_headers, json=bad).status_code == 422
    trav = {"context": "personal", "project": None, "path": "../x"}
    assert client.post("/v1/chat/folders", headers=auth_headers, json=trav).status_code == 422
    r = client.delete("/v1/chat/folders", headers=auth_headers, params={"context": "personal", "path": "never"})
    assert r.status_code == 404


def test_patch_moves_into_folder(client, auth_headers, conv, proj):
    r = client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers,
                     json={"context": "personal", "project": proj["slug"], "folder": "plans"})
    assert r.status_code == 200
    body = r.json()
    assert (body["context"], body["project"], body["folder"]) == ("personal", proj["slug"], "plans")
    assert body["auto_filed"] == "done"
    tree = client.get("/v1/chat/tree", headers=auth_headers).json()
    scope = next(s for s in tree["scopes"] if s["project"] == proj["slug"])
    assert scope["folders"][0]["chats"][0]["id"] == conv["id"]


def test_patch_context_null_unfiles(client, auth_headers, conv, proj):
    client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"context": "personal"})
    r = client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"context": None})
    assert r.status_code == 200 and r.json()["context"] is None


def test_patch_folder_without_context_422(client, auth_headers, conv):
    r = client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"folder": "x"})
    assert r.status_code == 422


def test_patch_unknown_context_422(client, auth_headers, conv):
    r = client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"context": "nope"})
    assert r.status_code == 422


def test_patch_missing_chat_404(client, auth_headers, tmp_chats_dir, tmp_vault):
    r = client.patch("/v1/chat/deadbeef", headers=auth_headers, json={"context": None})
    assert r.status_code == 404
```

Update `test_routes_chat_update.py`: the legacy `{"project": "ctx/slug"}` requests stay, but assertions change — response `project` is now the bare slug and `context` is the context (e.g. `assert r.json()["context"] == project["context"] and r.json()["project"] == project["slug"]`; store checks likewise). Keep the 422 cases for `nope/missing` and `no-slash`, and `{"project": None}` unfiles.

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && python -m pytest ghostbrain/api/tests/test_routes_chat_folders.py ghostbrain/api/tests/test_routes_chat_update.py -q` → FAIL.

- [ ] **Step 3: Routes** (`ghostbrain/api/routes/chat.py`). Import `chat_folders`, `ChatTree`, and reuse `FolderRef`, `MoveFolderRequest` from `ghostbrain.api.models.library`. **Declare the new routes ABOVE `@router.get("/{conv_id}")`** so they are not shadowed:

```python
def _folder_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except chat_folders.ChatFolderError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.get("/tree", response_model=ChatTree)
def chat_tree() -> dict:
    return chat_folders.tree()


@router.post("/folders", response_model=FolderRef)
def create_chat_folder(payload: FolderRef) -> dict:
    return _folder_call(chat_folders.create, payload.context, payload.project, payload.path)


@router.patch("/folders", response_model=FolderRef)
def move_chat_folder(payload: MoveFolderRequest) -> dict:
    src, dst = payload.from_, payload.to
    return _folder_call(
        chat_folders.move, (src.context, src.project, src.path), (dst.context, dst.project, dst.path)
    )


@router.delete("/folders")
def delete_chat_folder(context: str, path: str, project: str | None = Query(None)) -> dict:
    _folder_call(chat_folders.delete, context, project, path)
    return {"deleted": True}
```

Replace `update_conversation`:

```python
@router.patch("/{conv_id}", response_model=Conversation)
def update_conversation(conv_id: str, payload: UpdateConversationRequest) -> dict:
    fields = payload.model_fields_set
    if chat_store.get(conv_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    conv = None
    if "context" in fields:
        conv = _folder_call(
            chat_folders.move_chat, conv_id,
            context=payload.context, project=payload.project, folder=payload.folder,
        )
    elif "project" in fields:  # legacy: project = "context/slug" | null
        if payload.project is None:
            conv = _folder_call(chat_folders.move_chat, conv_id, context=None, project=None, folder=None)
        else:
            context, _, slug = payload.project.partition("/")
            if not context or not slug:
                raise HTTPException(status_code=422, detail=f"unknown project: {payload.project}")
            conv = _folder_call(chat_folders.move_chat, conv_id, context=context, project=slug, folder=None)
    elif "folder" in fields:
        raise HTTPException(status_code=422, detail="context is required to move a conversation")
    if "title" in fields:
        conv = chat_store.update(conv_id, title=payload.title)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv
```

Note: the legacy-path "unknown project" message must contain the raw value (`nope/missing`) — `check_location` raises `unknown project: nope/missing` which already does. Remove the now-unused `projects_repo` import if nothing else uses it. Add `Query` to the fastapi import.

- [ ] **Step 4: Run backend suite**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && python -m pytest ghostbrain/api/tests -q -x -k "chat or project" && python -m pytest tests -q -k "chat or project"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-chatfile && git add -A ghostbrain/api tests && git commit -m "feat(chat): chat tree + folder routes, PATCH moves chats between locations"
```

---

### Task 4: Auto-filing + export reuse

**Files:**
- Create: `ghostbrain/api/repo/chat_autofile.py`
- Modify: `ghostbrain/api/repo/chat.py` (`_stream_turn` "done" branch), `ghostbrain/api/repo/chat_export.py`
- Test: create `tests/test_chat_autofile.py`; update `tests/test_chat_export.py`; add one test to `tests/test_chat_repo.py`

**Interfaces:**
- Consumes: `chat_store.get`, `chat_store.apply_auto_file`; `ghostbrain.worker.router.route_event`, `RoutingDecision`, `router._load_yaml`.
- Produces: `chat_autofile.maybe_schedule(conv: dict) -> bool`; `chat_autofile.run(conv_id: str) -> None`; module attr `_spawn(fn, *args)` (tests monkeypatch it to run inline); `EXCERPT_CAP = 4000`.

- [ ] **Step 1: Failing tests** `tests/test_chat_autofile.py`:

```python
import pytest

from ghostbrain.api.repo import chat_autofile, chat_store
from ghostbrain.worker.router import RoutingDecision


@pytest.fixture
def chats(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(tmp_path / "chats"))
    monkeypatch.setattr(chat_autofile, "_spawn", lambda fn, *a: fn(*a))
    monkeypatch.setattr(chat_autofile, "_reject_below", lambda: 0.5)


def _first_turn():
    conv = chat_store.create()
    chat_store.append_user_message(conv, "how do we deploy atlas?")
    chat_store.append_assistant_message(conv, "atlas deploys via ...", [])
    return conv


def _router(monkeypatch, decision=None, exc=None):
    seen = {}

    def fake(event, *, content_excerpt=None, **_):
        seen["event"], seen["excerpt"] = event, content_excerpt
        if exc:
            raise exc
        return decision

    monkeypatch.setattr(chat_autofile, "_route", fake)
    return seen


def test_files_after_first_reply(chats, monkeypatch):
    seen = _router(monkeypatch, RoutingDecision("work", 0.9, "r", "llm", project="atlas"))
    conv = _first_turn()
    assert chat_autofile.maybe_schedule(conv) is True
    disk = chat_store.get(conv["id"])
    assert (disk["context"], disk["project"], disk["auto_filed"]) == ("work", "atlas", "done")
    assert seen["event"]["source"] == "chat"
    assert "how do we deploy atlas?" in seen["excerpt"] and "atlas deploys" in seen["excerpt"]


def test_excerpt_is_capped(chats, monkeypatch):
    seen = _router(monkeypatch, RoutingDecision("work", 0.9, "r", "llm"))
    conv = chat_store.create()
    chat_store.append_user_message(conv, "x" * 10_000)
    chat_store.append_assistant_message(conv, "y" * 10_000, [])
    chat_autofile.maybe_schedule(conv)
    assert len(seen["excerpt"]) <= chat_autofile.EXCERPT_CAP


@pytest.mark.parametrize("decision", [
    RoutingDecision("needs_review", 0.9, "r", "llm"),
    RoutingDecision("work", 0.3, "r", "llm"),
    RoutingDecision("needs_review", 0.0, "err", "fallback"),
])
def test_unsure_leaves_unfiled_but_done(chats, monkeypatch, decision):
    _router(monkeypatch, decision)
    conv = _first_turn()
    chat_autofile.maybe_schedule(conv)
    disk = chat_store.get(conv["id"])
    assert disk["context"] is None and disk["auto_filed"] == "done"


def test_router_exception_leaves_unfiled_but_done(chats, monkeypatch):
    _router(monkeypatch, exc=RuntimeError("boom"))
    conv = _first_turn()
    chat_autofile.maybe_schedule(conv)
    disk = chat_store.get(conv["id"])
    assert disk["context"] is None and disk["auto_filed"] == "done"


def test_not_scheduled_for_skipped_or_later_turns(chats, monkeypatch):
    seen = _router(monkeypatch, RoutingDecision("work", 0.9, "r", "llm"))
    conv = _first_turn()
    chat_store.move(conv["id"], context="personal", project=None, folder=None)
    assert chat_autofile.maybe_schedule(chat_store.get(conv["id"])) is False
    legacy = _first_turn()
    legacy["auto_filed"] = "skipped"
    assert chat_autofile.maybe_schedule(legacy) is False
    two = _first_turn()
    chat_store.append_user_message(two, "more")
    chat_store.append_assistant_message(two, "more reply", [])
    assert chat_autofile.maybe_schedule(two) is False
    assert "event" not in seen


def test_manual_move_during_routing_wins(chats, monkeypatch):
    conv = _first_turn()

    def slow(event, *, content_excerpt=None, **_):
        chat_store.move(conv["id"], context="personal", project=None, folder=None)  # user drags mid-call
        return RoutingDecision("work", 0.9, "r", "llm", project="atlas")

    monkeypatch.setattr(chat_autofile, "_route", slow)
    chat_autofile.maybe_schedule(conv)
    assert chat_store.get(conv["id"])["context"] == "personal"
```

In `tests/test_chat_repo.py` add a test that a fake `agent.run_chat_turn` yielding `{"type": "done", "text": "hi", "session_id": None}` causes `chat_autofile.maybe_schedule` to be called once with the conv (monkeypatch `ghostbrain.api.repo.chat.chat_autofile.maybe_schedule` with a recorder; follow that file's existing fake-agent pattern and its `require_provider` patching).

In `tests/test_chat_export.py`: update any test that sets a chat's `project` to `"ctx/slug"` to set `context`+`project` via `chat_store.move(...)`, and add one test: a chat with `context="work", project=None` exports via `move_jot(to_context="work", to_project=None, method="chat-project")` without calling `route_existing_jot` (follow the file's existing monkeypatch style).

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && python -m pytest tests/test_chat_autofile.py -q` → FAIL.

- [ ] **Step 2: Implement `ghostbrain/api/repo/chat_autofile.py`**

```python
"""File a new chat under its context/project after the first reply (spec §2).

Runs once per chat, off the reply stream, using the same router that files
every other inbound item. Unsure or failed → the chat stays unfiled. A
manual move before the router answers always wins (apply_auto_file checks
the chat is still pending under the store lock).
"""
from __future__ import annotations

import logging
import threading

from ghostbrain.api.repo import chat_store

log = logging.getLogger("ghostbrain.chat.autofile")

EXCERPT_CAP = 4000


def _spawn(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True, name="chat-autofile").start()


def _route(event: dict, *, content_excerpt: str):
    from ghostbrain.worker import router  # lazy: router pulls in the llm stack

    return router.route_event(event, content_excerpt=content_excerpt)


def _reject_below() -> float:
    from ghostbrain.worker import router

    try:
        thresholds = (router._load_yaml("config.yaml") or {}).get("thresholds") or {}
        return float(thresholds.get("reject_below", 0.5))
    except Exception:
        return 0.5


def maybe_schedule(conv: dict) -> bool:
    """Kick off auto-filing if this conv just got its first reply and is pending."""
    if conv.get("auto_filed") != "pending":
        return False
    if sum(1 for m in conv.get("messages", []) if m["role"] == "assistant") != 1:
        return False
    _spawn(run, conv["id"])
    return True


def _excerpt(conv: dict) -> str:
    user = next((m["text"] for m in conv["messages"] if m["role"] == "user"), "")
    reply = next((m["text"] for m in conv["messages"] if m["role"] == "assistant"), "")
    half = EXCERPT_CAP // 2 - 20
    return f"User: {user[:half]}\n\nAssistant: {reply[:half]}"[:EXCERPT_CAP]


def run(conv_id: str) -> None:
    conv = chat_store.get(conv_id)
    if conv is None or conv["auto_filed"] != "pending":
        return
    context = project = None
    try:
        d = _route({"source": "chat", "title": conv["title"]}, content_excerpt=_excerpt(conv))
        if d.method != "fallback" and d.context != "needs_review" and d.confidence >= _reject_below():
            context, project = d.context, d.project
        log.info("chat %s auto-file → %s/%s (conf=%.2f, %s)", conv_id, d.context, d.project, d.confidence, d.method)
    except Exception:
        log.warning("auto-filing failed for chat %s", conv_id, exc_info=True)
    chat_store.apply_auto_file(conv_id, context, project)
```

In `ghostbrain/api/repo/chat.py`: `from ghostbrain.api.repo import chat_attachments, chat_autofile, chat_store`; in `_stream_turn`'s `"done"` branch, right after `chat_store.append_assistant_message(...)`, add:

```python
            chat_autofile.maybe_schedule(conv)
```

In `chat_export.py`, replace the `if conv.get("project"):` block's condition and `partition` with the new fields:

```python
        # A filed conversation routes straight to its location — the router
        # only decides for unfiled ones.
        if conv.get("context"):
            moved = move_jot(
                jot["id"],
                to_context=conv["context"],
                to_project=conv.get("project"),
                confidence=1.0,
                method="chat-project",
                reasoning="conversation is filed here",
            )
```

(keep the rest of the block's return as-is).

- [ ] **Step 3: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && python -m pytest tests/test_chat_autofile.py tests/test_chat_repo.py tests/test_chat_export.py -q && python -m pytest ghostbrain/api/tests/test_chat.py -q`
Expected: PASS.

- [ ] **Step 4: Full backend suite, CI-like PATH**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && PATH=/usr/bin:/bin:$(dirname $(which python)) python -m pytest -q -x 2>&1 | tail -15`
Expected: no new failures vs `origin/main` (if anything unrelated fails, check it fails on main too and note it).

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-chatfile && git add -A ghostbrain tests && git commit -m "feat(chat): auto-file new chats after the first reply; export reuses location"
```

---

### Task 5: Generic ScopeTree extracted from DocTree

**Files:**
- Create: `desktop/src/renderer/components/tree/tree-types.ts`, `desktop/src/renderer/components/tree/ScopeTree.tsx`
- Modify: `desktop/src/renderer/components/docs/DocTree.tsx`
- Test: create `desktop/src/renderer/__tests__/ScopeTree.test.tsx`; `desktop/src/renderer/__tests__/DocTree.test.tsx` must pass **unmodified**.

**Interfaces:**
- Produces:

```ts
// tree-types.ts
import type { FolderRef } from '../../../shared/api-types';

export interface TreeFolderNode<L> { name: string; path: string; folders: TreeFolderNode<L>[]; leaves: L[] }
export interface TreeScope<L> {
  context: string; project: string | null; name: string; archived: boolean;
  folders: TreeFolderNode<L>[]; leaves: L[];
}
export type TreeDrop = { kind: 'leaf'; id: string } | { kind: 'folder'; ref: FolderRef };
export interface TreeDragCodec {
  mime: string;
  encodeLeaf: (id: string) => string;
  encodeFolder: (ref: FolderRef) => string;
  decode: (raw: string) => TreeDrop | null;
}
/** Props ScopeTree hands a leaf row so the caller renders its own element. */
export interface LeafRowProps {
  key: string;
  draggable: boolean;
  onDragStart: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
  className: string;
  style: React.CSSProperties;
}
export function folderKey(ref: FolderRef): string; // `${context}/${project ?? '_'}/${path}` — move from docs/kinds.ts and re-export there
export function joinPath(parent: string, name: string): string;
export function isInside(child: FolderRef, parent: FolderRef): boolean; // move from docs/tree-model.ts, re-export there
export function countLeaves<L>(n: { leaves: L[]; folders: TreeFolderNode<L>[] }): number;
export function groupByContext<S extends { context: string; project: string | null }>(scopes: S[]): Array<{ context: string; scopes: S[] }>;
```

```ts
// ScopeTree.tsx
export interface ScopeTreeProps<L> {
  scopes: TreeScope<L>[];
  ariaLabel: string;                         // 'docs tree' for docs
  codec: TreeDragCodec;
  leafId: (l: L) => string;
  leafRef: (l: L) => FolderRef;              // dropping onto a leaf drops into its folder
  renderLeaf: (l: L, row: LeafRowProps, ctx: { depth: number; archived: boolean }) => React.ReactNode;
  selectedFolderKey: string | null;
  onSelectFolder?: (ref: FolderRef) => void; // absent → clicking a folder name toggles it
  onMoveLeaf: (id: string, to: FolderRef) => void;
  onMoveFolder: (from: FolderRef, to: FolderRef) => void;
  onCreateFolder: (ref: FolderRef) => void;
  onRenameFolder: (from: FolderRef, to: FolderRef) => void;
  onDeleteFolder: (ref: FolderRef) => void;
  onUploadFiles?: (files: File[], to: FolderRef) => void;
  onRenameProject?: (ref: { context: string; project: string }, name: string) => void;
  header?: React.ReactNode;                  // rendered first inside the <nav>
  revealKeys?: string[];                     // folder keys / `ctx:<context>` to force-expand
  rootIcon?: string;                         // Lucide name for bare-context scope rows; default 'inbox'
}
export function ScopeTree<L>(props: ScopeTreeProps<L>): JSX.Element;
```

- [ ] **Step 1: Write `ScopeTree.test.tsx`** with a fake leaf type `{ id: string; title: string; ref: FolderRef }` and a JSON codec (`mime 'application/x-test'`). Build `dt()` the same way `DocTree.test.tsx` does (read it and copy its helper). Cases:
  1. renders context header, project name, folder, leaf title (via `renderLeaf` returning `<button {...row}>{l.title}</button>`).
  2. dropping a leaf payload on `folder-work/p/specs` calls `onMoveLeaf('a', {context:'work',project:'p',path:'specs'})`.
  3. dropping folder `specs` on its own child calls nothing; on a sibling calls `onMoveFolder(specs, {...sibling, path: 'diagrams/specs'})`.
  4. "new folder in work/p/specs" → type `x` + Enter → `onCreateFolder({...,path:'specs/x'})`; name with `/` → not called.
  5. no `onSelectFolder`: clicking folder name hides its leaves (toggle).
  6. archived scope: no create button, rows `draggable="false"`, drop ignored.
  7. `revealKeys` re-expands a collapsed folder when it changes.
  8. no `onUploadFiles`: dropping files does nothing (no throw).

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile/desktop && npx vitest run src/renderer/__tests__/ScopeTree.test.tsx` → FAIL.

- [ ] **Step 2: Implement.** Move the body of `DocTree` into `ScopeTree`, generalizing:
  - `docs` → `leaves`; `docRow` → calls `renderLeaf(l, rowProps, {depth, archived})` where `rowProps` carries the exact drag/drop handlers, `className = rowCls(isActive?, key)` — NOTE the caller decides active styling: pass `className` built with `active=false`; callers prepend their own active classes. Keep the `draggable={!archived}` and `onDragStart` (calls `e.preventDefault()` if archived, else `setData(codec.mime, codec.encodeLeaf(id))`, `effectAllowed='move'`).
  - drop handler: files → `onUploadFiles?.(files, ref)` (return early only if handler exists **and** files present); otherwise `codec.decode(getData(codec.mime))`; leaf → `onMoveLeaf`; folder → `isInside` guard then `onMoveFolder(payload.ref, {...ref, path: joinPath(ref.path, name)})`.
  - folder row: if `onSelectFolder` provided, name click selects (current behaviour); otherwise toggles.
  - project rename button only when `onRenameProject` is provided **and** `scope.project`.
  - `header` replaces the docs-only "needs attention" button (DocTree passes it as `header`).
  - `revealKeys`: `useEffect(() => setCollapsed(c => { const n = {...c}; for (const k of revealKeys ?? []) delete n[k]; return n; }), [revealKeys?.join('|')])`.
  - Keep every `data-testid`, `aria-label` and placeholder string identical (`folder-${key}`, `count-${context}/${project ?? '_'}/`, `new folder in ${key}`, `rename ${key}`, `delete ${key}`, `rename ${context}/${project}`, `folder name`, `project name`, `collapse`/`expand`).
  - `FolderInput`, `PROJECT_DOTS`, `validName` move into `ScopeTree.tsx` at module scope.

Then rewrite `DocTree.tsx` as a wrapper (keep its exported `Props` unchanged):

```tsx
export function DocTree(props: Props) {
  const { tree, selection, onSelect } = props;
  const scopes = useMemo(() => tree.scopes.map(toTreeScope), [tree.scopes]);
  return (
    <ScopeTree<DocSummary>
      scopes={scopes}
      ariaLabel="docs tree"
      codec={DOC_CODEC}
      leafId={(d) => d.doc_id}
      leafRef={(d) => ({ context: d.context, project: d.project, path: d.folder })}
      selectedFolderKey={selection?.type === 'folder' ? folderKey(selection.ref) : null}
      onSelectFolder={(ref) => onSelect({ type: 'folder', ref })}
      onMoveLeaf={props.onMoveDoc}
      onMoveFolder={props.onMoveFolder}
      onCreateFolder={props.onCreateFolder}
      onRenameFolder={props.onRenameFolder}
      onDeleteFolder={props.onDeleteFolder}
      onUploadFiles={props.onUploadFiles}
      onRenameProject={props.onRenameProject}
      header={tree.attention.length > 0 ? <AttentionButton … /> : null}
      renderLeaf={(d, row) => {
        const active = selection?.type === 'doc' && selection.docId === d.doc_id;
        return (
          <button type="button" {...row} key={row.key} onClick={() => onSelect({ type: 'doc', docId: d.doc_id })}
            className={`${row.className} ${active ? 'bg-neon-mist text-neon' : ''}`}>
            <KindChip doc={d} />
            <span className="truncate">{d.title}</span>
            {d.index_status === 'failed' && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-[#F2C14E]" title="indexing failed" />}
          </button>
        );
      }}
    />
  );
}
```

where `toTreeScope` maps `docs → leaves` recursively, and `DOC_CODEC` wraps the existing `encodeDrag`/`decodeDrag`/`DRAG_MIME` from `tree-model.ts` (`decode`: `{type:'doc'}` → `{kind:'leaf', id: docId}`, `{type:'folder'}` → `{kind:'folder', ref}`). The non-active base class must not fight the active class: build `rowCls` in ScopeTree so the base includes `text-ink-1 hover:bg-vellum` only via a `leafActive` arg — simplest: `LeafRowProps.className` is the shared layout + drop-highlight classes only; the caller adds `active ? 'bg-neon-mist text-neon' : 'text-ink-1 hover:bg-vellum'`. Folder/scope rows keep using `selectedFolderKey` internally.

`folderKey` and `isInside` move to `tree-types.ts`; keep `export { folderKey } from '../tree/tree-types'` in `docs/kinds.ts` and `export { isInside } from '../tree/tree-types'` in `docs/tree-model.ts` so other importers keep working.

- [ ] **Step 3: Verify**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile/desktop && npx vitest run src/renderer/__tests__/ScopeTree.test.tsx src/renderer/__tests__/DocTree.test.tsx src/renderer/__tests__/DocsScreen.test.tsx src/renderer/__tests__/docs-tree-model.test.ts && npm run typecheck && npm run lint`
Expected: all PASS, `git diff --stat origin/main -- src/renderer/__tests__/DocTree.test.tsx` empty.

- [ ] **Step 4: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-chatfile && git add -A desktop/src && git commit -m "refactor(tree): extract generic ScopeTree from DocTree"
```

---

### Task 6: Chat types, hooks, auto-file polling, notice store

**Files:**
- Modify: `desktop/src/shared/api-types.ts`, `desktop/src/renderer/lib/api/hooks.ts`, `desktop/src/renderer/stores/chat.ts`
- Create: `desktop/src/renderer/lib/chat-autofile.ts`
- Test: create `desktop/src/renderer/__tests__/chat-autofile.test.ts`; extend `desktop/src/renderer/__tests__/chat-store.test.ts`

**Interfaces:**
- Consumes: Task 3 HTTP API.
- Produces:

```ts
// api-types.ts
export type AutoFiled = 'pending' | 'done' | 'skipped';
export interface ConversationSummary {
  id: string; title: string; created_at: number; updated_at: number; message_count: number;
  context: string | null;
  /** bare project slug within `context`, or null. */
  project: string | null;
  folder: string | null;
  auto_filed: AutoFiled;
}
export interface Conversation { /* existing fields */ context: string | null; project: string | null; folder: string | null; auto_filed: AutoFiled; }
export interface ChatTreeChat extends ConversationSummary { unknown_location: boolean }
export interface ChatFolderNode { name: string; path: string; folders: ChatFolderNode[]; chats: ChatTreeChat[] }
export interface ChatScope { context: string; project: string | null; name: string; archived: boolean; folders: ChatFolderNode[]; chats: ChatTreeChat[] }
export interface ChatTree { unfiled: ChatTreeChat[]; scopes: ChatScope[] }
export interface ChatLocation { context: string | null; project: string | null; folder: string | null }

// hooks.ts
export function useChatTree(): UseQueryResult<ChatTree>;          // key ['chat','tree'], staleTime 5_000
export function useMoveChat(): UseMutationResult<Conversation, Error, { id: string } & ChatLocation>;
export function useCreateChatFolder(): UseMutationResult<FolderRef, Error, FolderRef>;
export function useMoveChatFolder(): UseMutationResult<FolderRef, Error, { from: FolderRef; to: FolderRef }>;
export function useDeleteChatFolder(): UseMutationResult<unknown, Error, FolderRef>;
// all onSuccess: qc.invalidateQueries({ queryKey: ['chat'] })

// chat-autofile.ts
export async function waitForAutoFile(
  convId: string,
  fetchConv: (id: string) => Promise<Conversation>,
  opts?: { intervalMs?: number; maxTries?: number; sleep?: (ms: number) => Promise<void> },
): Promise<Conversation | null>; // resolves the conv once auto_filed !== 'pending'; null on timeout/error. defaults 1500ms × 20

// stores/chat.ts additions
filed: Record<string, ChatLocation>;            // convId → where auto-filing put it
setFiled: (convId: string, loc: ChatLocation) => void;
clearFiled: (convId: string) => void;
```

- [ ] **Step 1: Tests.** `chat-autofile.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest';
import { waitForAutoFile } from '../lib/chat-autofile';
import type { Conversation } from '../../shared/api-types';

const conv = (auto_filed: Conversation['auto_filed'], context: string | null = null) =>
  ({ id: 'c1', title: 't', created_at: 0, updated_at: 0, claude_session_id: null, messages: [],
     context, project: null, folder: null, auto_filed }) as Conversation;
const sleep = () => Promise.resolve();

describe('waitForAutoFile', () => {
  it('polls until auto-filing settles', async () => {
    const fetchConv = vi.fn()
      .mockResolvedValueOnce(conv('pending'))
      .mockResolvedValueOnce(conv('done', 'work'));
    const out = await waitForAutoFile('c1', fetchConv, { sleep });
    expect(out?.context).toBe('work');
    expect(fetchConv).toHaveBeenCalledTimes(2);
  });
  it('gives up after maxTries', async () => {
    const fetchConv = vi.fn().mockResolvedValue(conv('pending'));
    expect(await waitForAutoFile('c1', fetchConv, { sleep, maxTries: 3 })).toBeNull();
    expect(fetchConv).toHaveBeenCalledTimes(3);
  });
  it('returns null when the fetch fails', async () => {
    const fetchConv = vi.fn().mockRejectedValue(new Error('gone'));
    expect(await waitForAutoFile('c1', fetchConv, { sleep })).toBeNull();
  });
});
```

In `chat-store.test.ts` add: `setFiled('c1', loc)` stores it; `clearFiled('c1')` removes it.

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile/desktop && npx vitest run src/renderer/__tests__/chat-autofile.test.ts src/renderer/__tests__/chat-store.test.ts` → FAIL.

- [ ] **Step 2: Implement** the types, hooks (mirror the docs library hooks' style; `useDeleteChatFolder` builds `URLSearchParams({context, path})` + `project` when set, `del('/v1/chat/folders?…')`), `waitForAutoFile`:

```ts
import type { Conversation } from '../../shared/api-types';

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Auto-filing runs in the background after the first reply; poll the chat
 *  until it settles so the sidebar can move it and show the notice. */
export async function waitForAutoFile(
  convId: string,
  fetchConv: (id: string) => Promise<Conversation>,
  { intervalMs = 1500, maxTries = 20, sleep = defaultSleep }: { intervalMs?: number; maxTries?: number; sleep?: (ms: number) => Promise<void> } = {},
): Promise<Conversation | null> {
  for (let i = 0; i < maxTries; i++) {
    try {
      const conv = await fetchConv(convId);
      if (conv.auto_filed !== 'pending') return conv;
    } catch {
      return null;
    }
    if (i < maxTries - 1) await sleep(intervalMs);
  }
  return null;
}
```

and the store fields. Fix any type errors the `project` semantic change causes (grep `\.project` under `desktop/src/renderer` for chat usages; the old `FileMenu`/`groupConversations` are replaced in Task 7 — if they fail typecheck now, leave them compiling by keeping their usage valid; they're deleted next task).

- [ ] **Step 3: Verify**: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile/desktop && npx vitest run src/renderer/__tests__/chat-autofile.test.ts src/renderer/__tests__/chat-store.test.ts && npm run typecheck`
- [ ] **Step 4: Commit**: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && git add -A desktop/src && git commit -m "feat(chat): chat tree types, hooks, auto-file polling"`

---

### Task 7: ChatTree sidebar, Move-to menu, filed notice

**Files:**
- Create: `desktop/src/renderer/components/chat/ChatTree.tsx`, `desktop/src/renderer/components/chat/MoveToMenu.tsx`, `desktop/src/renderer/components/chat/FiledNotice.tsx`
- Modify: `desktop/src/renderer/screens/chat.tsx` (remove `groupConversations`, the grouped list and `FileMenu`; mount `ChatTree`; trigger polling; render notice)
- Test: create `desktop/src/renderer/__tests__/ChatTree.test.tsx`; rewrite `desktop/src/renderer/__tests__/ConversationFolders.test.tsx`; keep `ChatScreen.test.tsx` green (update its mocks so `GET /v1/chat/tree` returns a tree).

**Interfaces:**
- Consumes: Task 5 `ScopeTree`, `folderKey`; Task 6 hooks/types/store/`waitForAutoFile`; existing `useRenameConversation`, `useDeleteConversation`, `useCreateConversation`, `useProjects`.
- Produces:

```ts
export const CHAT_DRAG_MIME = 'application/x-gb-chat';
export function ChatTree(props: { activeId: string | null; onSelect: (id: string | null) => void }): JSX.Element;
export function MoveToMenu(props: { chat: ConversationSummary; tree: ChatTree; onMove: (loc: ChatLocation) => void }): JSX.Element;
export function FiledNotice(props: { convId: string }): JSX.Element | null;
```

Behaviour:
- `ChatTree` keeps the existing sidebar chrome from `ConversationList` (aside 240px, "conversations" eyebrow, "new chat" + button with `aria-label="new chat"`, skeleton while loading, "no conversations yet" when tree has zero chats anywhere).
- **Unfiled section** at top: header row `data-testid="chat-unfiled"` labelled `unfiled` with count; it is a drop target (decode `CHAT_DRAG_MIME`; leaf → `moveChat({id, context:null, project:null, folder:null})`; folders can't be dropped there — ignore). Chats with `unknown_location` show a small `Lucide name="circle-help"` with `title="its project or context no longer exists"`.
- Below: `<ScopeTree<ChatTreeChat>>` with scopes mapped `chats → leaves`, `codec` = JSON `{kind:'leaf',id}|{kind:'folder',ref}` on `CHAT_DRAG_MIME`, `leafRef = (c) => ({context: c.context!, project: c.project, path: c.folder ?? ''})`, no `onSelectFolder` (folder click toggles), no `onUploadFiles`, no `onRenameProject`, `selectedFolderKey={null}`, `rootIcon="message-square"`, `ariaLabel="chat tree"`, `revealKeys` = ancestors of the active chat (`ctx:<context>`, the scope root key and each folder prefix key via `folderKey`).
- Folder callbacks → `useCreateChatFolder` / `useMoveChatFolder` / `useDeleteChatFolder`, `onMoveLeaf(id, to)` → `useMoveChat({id, context: to.context, project: to.project, folder: to.path || null})`. All `onError: (e) => toast.error(e.message)`.
- **Chat row** (`renderLeaf` and unfiled rows share one `ChatRow` component): a `div role="button" tabIndex={0}` spreading `row` props (unfiled rows get their own drag start with the same codec), click → `onSelect(id)`, double-click → inline rename input (reuse the current `ConversationRow` rename logic + `useRenameConversation`; the input must `stopPropagation` on keydown/click), hover actions: `MoveToMenu` button (`aria-label={\`move ${title}\`}`) and delete button (`aria-label="delete conversation"`, deleting the active chat calls `onSelect(null)`). Active row: `bg-neon/12 font-medium text-ink-0`.
- **MoveToMenu**: `role="menu"`; first item `unfiled`; then for every scope (skip archived) an item with the scope name (indent projects), and under it each folder path (indent by depth, label = last segment). Choosing the chat's current location is a no-op. Each item `role="menuitem"`.
- **Polling** in `ChatScreen.sendMessage` finalizer: after `endStream`, if the conversation was `auto_filed === 'pending'` (read `qc.getQueryData<Conversation>(['chat', convId])` before sending), call `waitForAutoFile(convId, (id) => window.gb.api.request(...)` — use the same `get` helper hooks use; export it from `lib/api/client` if not already exported — then if the result has `context`, `useChat.getState().setFiled(convId, {context, project, folder})`, and `qc.invalidateQueries({queryKey:['chat']})` in all settled cases.
- **FiledNotice** (render above the thread, below the top bar, only for the active chat): when `filed[convId]` exists: text `Filed under <Context> / <Project name>` (project name from `useProjects({includeArchived:true})`, fallback slug; context-only → just the context) + `Undo` button (`moveChat({id, context:null, project:null, folder:null})`, then `clearFiled`) + dismiss `×` (`aria-label="dismiss"`, `clearFiled`). Muted mono 11px styling consistent with the screen.

- [ ] **Step 1: Tests.** `ChatTree.test.tsx` — mock `window.gb.api.request` per-field (see Global Constraints) to answer `GET /v1/chat/tree` with a fixture tree (unfiled: `loose thread`; scope `work/_` with a folder `plans` containing `filed thread`; scope `work/atlas` named `Atlas`; scope `personal/_`), `GET /v1/projects…` with `[]`/the Atlas project, and record PATCH/POST/DELETE. Render inside a fresh `QueryClientProvider`. Cases:
  1. renders `unfiled`, `loose thread`, `work`, `Atlas`, `plans`, `filed thread`.
  2. drop `loose thread` payload (`CHAT_DRAG_MIME`, `{kind:'leaf',id}`) on `folder-work/atlas/` → `PATCH /v1/chat/<id>` body `{context:'work', project:'atlas', folder:null}`.
  3. drop `filed thread` on `chat-unfiled` → body `{context:null, project:null, folder:null}`.
  4. drop folder `plans` on `folder-work/atlas/` → `PATCH /v1/chat/folders` body `{from:{context:'work',project:null,path:'plans'}, to:{context:'work',project:'atlas',path:'plans'}}`.
  5. "new folder in work/_/" → type `q4` Enter → `POST /v1/chat/folders` `{context:'work', project:null, path:'q4'}`.
  6. "delete work/_/plans" → `DELETE /v1/chat/folders?context=work&path=plans`.
  7. Move-to menu: click `move loose thread` → menuitem `plans` → PATCH `{context:'work', project:null, folder:'plans'}`.
  8. unknown_location chat in unfiled shows the help icon title.
  9. `FiledNotice`: with `useChat.setState({filed:{c1:{context:'work',project:'atlas',folder:null}}})` renders `Filed under work / Atlas`; Undo PATCHes `{context:null,…}` and the notice disappears.

  Rewrite `ConversationFolders.test.tsx` to cover the screen-level integration only: ChatScreen renders the tree from `/v1/chat/tree`, selecting a chat in a folder opens it. Remove the old group/collapse/file-menu tests (replaced by ChatTree tests).

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile/desktop && npx vitest run src/renderer/__tests__/ChatTree.test.tsx` → FAIL.

- [ ] **Step 2: Implement** the three components and wire `chat.tsx` as described. Delete `groupConversations`, `ConversationList`, `ConversationRow` (logic moves to `ChatRow` in `ChatTree.tsx`), `FileMenu`, and the `UNFILED` constant. Keep `useConversations` in `ChatScreen` for the "auto-select newest on mount" effect.

- [ ] **Step 3: Verify**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile/desktop && npx vitest run && npm run typecheck && npm run lint`
Expected: all PASS, zero lint warnings.

- [ ] **Step 4: Commit**: `cd /Users/jannik/development/nikrich/ghost-brain-chatfile && git add -A desktop/src && git commit -m "feat(chat): chat sidebar tree with folders, drag-move, move-to menu, filed notice"`

---

### Task 8: End-to-end verification

- [ ] **Step 1: Full gates**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-chatfile && python -m pytest -q > /tmp/claude-py.out 2>&1; echo "py exit $?"; tail -5 /tmp/claude-py.out
cd /Users/jannik/development/nikrich/ghost-brain-chatfile/desktop && npx vitest run > /tmp/claude-vt.out 2>&1; echo "vitest exit $?"; tail -5 /tmp/claude-vt.out
cd /Users/jannik/development/nikrich/ghost-brain-chatfile/desktop && npm run typecheck; echo "tc $?"; npm run lint; echo "lint $?"
```

Expected: all exit 0 (any pre-existing failure must be shown to also fail on `origin/main`).

- [ ] **Step 2: Live API smoke** — start the sidecar against a sandbox (`HOME`, `VAULT_PATH`, `GHOSTBRAIN_STATE_DIR`, `GHOSTBRAIN_CHATS_DIR` all temp; seed a routing.yaml with two contexts + one project), then via HTTP: create chat, create folder, PATCH chat into it, GET tree shows it, move the folder to the project, delete an empty folder, legacy chat file with `project:"ctx/slug"` appears under its project. Auto-filing with a real LLM call is optional (needs the `claude` CLI); if available, send one message and confirm `auto_filed` becomes `done`.

- [ ] **Step 3: UI smoke** — launch the desktop app in demo mode (`GHOSTBRAIN_DEMO=1`, Playwright `_electron`) and screenshot the chat sidebar tree; drag a chat into a folder. If demo mode can't drive chat, record that and rely on component tests.

- [ ] **Step 4: Commit any fixes**, then open the PR.
