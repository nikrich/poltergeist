# Project Editing (full rename + unarchive) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users can fix a project's name (including a typo baked into its slug and vault folder), edit its description, and unarchive it — from Settings → projects and from the docs tree — without breaking jots, docs, links, history or chats that point into the project.

**Architecture:** A new `rename_project` in `ghostbrain/api/repo/projects.py`. A name whose slug is unchanged only updates the registry. A new slug runs a reversible pipeline:
1. Collision checks.
2. Move every file from `projects/<old>/` to `projects/<new>/`. Markdown notes move through `vault_write` (`op="move"` with `fields`), so history logs the move and the link index stays fresh. Other files (library originals, `.keep`, assets) move with `os.replace`.
3. Re-stamp `project: <new>` on notes whose `project` was the old slug.
4. Rewrite links elsewhere in the vault that point into the old folder.
5. Re-point chat conversations whose `project` is `ctx/<old>`.
6. Update the registry.

Any failure undoes the completed steps in reverse, then re-raises. The existing `PATCH /v1/projects/{context}/{slug}` route calls it and returns the updated project, with the new slug. The renderer adds inline edit + unarchive in Settings → projects and a rename action on project rows in the docs tree.

**Tech Stack:** Python 3.11 / FastAPI / PyYAML / `ghostbrain.vault_write`; Electron renderer React 18 / TanStack Query / Vitest + RTL.

**Spec:** the design approved in conversation on 2026-10-10:
- Full rename: the slug changes with the name.
- The folder moves, jot and doc notes are re-stamped, and inbound links are rewritten.
- Writes go through `vault_write`.
- A failure rolls back.
- Unarchive is included.
- UI: Settings → projects inline edit, and docs tree project rename.
- Out of scope: moving a project to another context, deleting projects, and rewriting paths inside past chat transcripts.

## Global Constraints

- The slug comes from `notes_manual.make_slug(name)`. A rename whose slug equals the current slug never touches the filesystem.
- New slug already registered in that context, or a folder already at `projects/<new>`: raise `ProjectExists`, which the route maps to **409**. Nothing changes.
- Markdown notes (suffix in `vault_write.WRITABLE_SUFFIXES`) move only through `vault_write.write(rel, op="move", dest=..., fields=..., actor=USER, reason="rename project <old> → <new>")`. History and the link index rely on it.
- Link rewrite targets the path prefix `20-contexts/<ctx>/projects/<old>`, followed by `/`, `]`, `|`, `#`, `)` or end of string. It applies in every vault `.md` outside dot-directories, through `vault_write.write(rel, op="modify", content=...)`.
- Re-stamp only notes whose frontmatter `project` equals the old slug. Notes without a `project` key are moved and left as they are.
- After a successful rename, `doc_library.index.invalidate()` is called.
- On any exception mid-rename, undo what was done in reverse order, then re-raise. The registry is written **last**, so it never points at a half-moved folder.
- Python tests use the existing temp-vault fixture pattern (`VAULT_PATH`, sandboxed `GHOSTBRAIN_STATE_DIR`). New test files go into `.github/workflows/ci.yml`'s backend list.
- UI copy is lowercase. Desktop: `npm run typecheck` (tsc -b), `npm run lint` (`--max-warnings 0`), vitest pristine, Node 20 green (`npx -y node@20 node_modules/vitest/vitest.mjs run`). Node 25 locally shadows jsdom `localStorage`, so stub it with `vi.stubGlobal`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Never use real context names in docs or tests. Use `work` / `personal`; `tests/test_no_hardcoded_contexts.py` guards this.

## Review Focus

1. **A project folder containing a library doc**: an original binary plus its companion `.md`. Expect both to move, the companion note's `project:` to be re-stamped, and the docs tree to list the doc under the renamed project. Pinned in Task 1.
2. **Links from outside the project**: a jot in another context links `[[20-contexts/work/projects/paymnets/x.md|X]]`. Expect the link rewritten to `payments` and the alias kept. A note that only mentions the word `paymnets` in prose is untouched. Pinned in Task 1.
3. **A failure halfway**, e.g. the 3rd file's move raising. Expect every already-moved file back in place, no registry change, and no rewritten links. Pinned in Task 1.
4. **A prefix-sharing sibling**: renaming `pay` must not touch `projects/payments/...` links or files. Pinned in Task 1.
5. **The renderer after a slug change**: the selected docs folder, the jots project filter and any open note path that pointed at the old slug must not crash. Expect the tree and lists to refetch, and a stale selection to fall back to the default view. Pinned in Task 3.

---

### Task 1: `rename_project` core

**Files:**
- Modify: `ghostbrain/api/repo/projects.py`
- Test: `tests/test_project_rename.py`
- Modify: `.github/workflows/ci.yml` (add `tests/test_project_rename.py`)

**Interfaces:**
- Consumes:
  - `notes_manual.make_slug(text)`
  - `vault_write.write(rel, *, actor, content=None, fields=None, op, dest=None, reason)`
  - `vault_write.WRITABLE_SUFFIXES`
  - `vault_write.USER`
  - `chat_store`: read its API. It stores `conv["project"]` as `"ctx/slug"`. There is a setter near `chat_store.py:135` and a listing function. Use them; don't write chat files by hand.
  - `ghostbrain.api.repo.doc_library.index.invalidate()`
- Produces:
  - `projects.rename_project(context: str, slug: str, *, name: str | None = None, description: str | None = None, archived: bool | None = None) -> dict | None`. Returns the updated project dict (new `slug`/`id` when the slug changed), or `None` when the project is unknown. Raises `ProjectExists` on collision and `ValueError` when the new name produces an empty slug.
  - `update_project` stays as is, for existing callers.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_project_rename.py
"""Full project rename: folder move, re-stamp, link rewrite, chats, rollback."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ghostbrain.api.repo import projects


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    (v / "90-meta" / "routing.yaml").write_text("contexts:\n  - work\n  - personal\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(v))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    projects.create_project("work", "Paymnets")
    projects.create_project("work", "Pay")
    return v


def _note(path: Path, front: dict, body: str = "body") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{yaml.safe_dump(front, sort_keys=False)}---\n\n{body}\n", encoding="utf-8")


def _front(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---\n")[1])


OLD = "20-contexts/work/projects/paymnets"
NEW = "20-contexts/work/projects/payments"


def test_same_slug_rename_only_updates_registry(vault: Path):
    p = projects.rename_project("work", "paymnets", name="PAYMNETS", description="d")
    assert p["slug"] == "paymnets" and p["name"] == "PAYMNETS" and p["description"] == "d"
    assert (vault / OLD).is_dir()


def test_full_rename_moves_restamps_and_rewrites(vault: Path):
    _note(vault / OLD / "manual-1-jot.md", {"id": "j1", "project": "paymnets", "context": "work"})
    _note(vault / OLD / "docs/specs/spec-aaaaaa.md", {"doc_id": "aaaaaaaaaaaa", "source": "doc-library",
          "original": "Spec.pdf", "project": "paymnets", "context": "work"})
    (vault / OLD / "docs/specs/Spec.pdf").write_bytes(b"%PDF")
    _note(vault / "20-contexts/personal/elsewhere.md", {"id": "e"},
          f"see [[{OLD}/manual-1-jot.md|the jot]] and [[{OLD}]] but not paymnets prose "
          f"or [[20-contexts/work/projects/pay/x.md]]")
    p = projects.rename_project("work", "paymnets", name="Payments")
    assert p["slug"] == "payments" and p["id"] == "work/payments" and p["name"] == "Payments"
    assert not (vault / OLD).exists()
    assert (vault / NEW / "docs/specs/Spec.pdf").read_bytes() == b"%PDF"
    assert _front(vault / NEW / "manual-1-jot.md")["project"] == "payments"
    assert _front(vault / NEW / "docs/specs/spec-aaaaaa.md")["project"] == "payments"
    other = (vault / "20-contexts/personal/elsewhere.md").read_text()
    assert f"[[{NEW}/manual-1-jot.md|the jot]]" in other and f"[[{NEW}]]" in other
    assert "paymnets prose" in other
    assert "[[20-contexts/work/projects/pay/x.md]]" in other
    assert projects.get_project("work", "paymnets") is None
    assert projects.get_project("work", "payments")["name"] == "Payments"


def test_collision_is_rejected_without_changes(vault: Path):
    _note(vault / OLD / "a.md", {"project": "paymnets"})
    with pytest.raises(projects.ProjectExists):
        projects.rename_project("work", "paymnets", name="Pay")
    assert (vault / OLD / "a.md").exists()
    (vault / NEW).mkdir(parents=True)  # stray unregistered folder also blocks
    with pytest.raises(projects.ProjectExists):
        projects.rename_project("work", "paymnets", name="Payments")


def test_failure_midway_rolls_back(vault: Path, monkeypatch):
    for i in range(4):
        _note(vault / OLD / f"n{i}.md", {"project": "paymnets"})
    _note(vault / "20-contexts/personal/l.md", {}, f"[[{OLD}/n0.md]]")
    from ghostbrain import vault_write
    real = vault_write.write
    calls = {"n": 0}

    def flaky(rel, **kw):
        if kw.get("op") == "move":
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("disk full")
        return real(rel, **kw)

    monkeypatch.setattr(projects.vault_write, "write", flaky)
    with pytest.raises(OSError):
        projects.rename_project("work", "paymnets", name="Payments")
    assert sorted(p.name for p in (vault / OLD).glob("*.md")) == ["n0.md", "n1.md", "n2.md", "n3.md"]
    assert all(_front(vault / OLD / f"n{i}.md")["project"] == "paymnets" for i in range(4))
    assert not (vault / NEW).exists() or not any((vault / NEW).rglob("*.md"))
    assert f"[[{OLD}/n0.md]]" in (vault / "20-contexts/personal/l.md").read_text()
    assert projects.get_project("work", "paymnets") is not None


def test_chat_conversations_are_repointed(vault: Path):
    from ghostbrain.api.repo import chat_store
    conv = chat_store.create()  # adjust to the real chat_store API if named differently
    chat_store.set_project(conv["id"], "work/paymnets")  # adjust likewise
    projects.rename_project("work", "paymnets", name="Payments")
    assert chat_store.get(conv["id"])["project"] == "work/payments"


def test_unarchive_and_unknown(vault: Path):
    projects.update_project("work", "pay", archived=True)
    assert projects.rename_project("work", "pay", archived=False)["archived"] is False
    assert projects.rename_project("work", "ghost", name="X") is None
```

(Read `chat_store` and adapt the two marked calls to its real function names. Keep the assertion: the conversation's stored project becomes `work/payments`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra api pytest tests/test_project_rename.py -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'rename_project'`

- [ ] **Step 3: Implement `rename_project`**

Add the code below to `ghostbrain/api/repo/projects.py`, keeping its existing style. It covers module imports (`os`, `re`, `yaml`, `from ghostbrain import vault_write`, `from ghostbrain.vault_write import USER`) and a function-level import of `chat_store` and `doc_library.index` to avoid cycles.

```python
_HIDDEN = re.compile(r"(^|/)\.")


def _rel(p: Path) -> str:
    return p.relative_to(vault_path()).as_posix()


def _front_project(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    try:
        front = yaml.safe_load(text[4:end]) if end != -1 else None
    except yaml.YAMLError:
        return None
    return front.get("project") if isinstance(front, dict) else None


def _link_pattern(context: str, slug: str) -> re.Pattern[str]:
    prefix = re.escape(PROJECT_DIR_TEMPLATE.format(context=context, slug=slug))
    return re.compile(prefix + r"(?=[/\]|#)]|$)", re.MULTILINE)


def rename_project(
    context: str,
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    archived: bool | None = None,
) -> dict | None:
    current = get_project(context, slug)
    if current is None:
        return None
    from ghostbrain.api.repo.notes_manual import make_slug  # noqa: PLC0415

    new_name = name.strip() if name is not None else current["name"]
    new_slug = make_slug(new_name) if name is not None else slug
    if not new_slug:
        raise ValueError("project name produces an empty slug")
    if new_slug == slug:
        return update_project(context, slug, name=name, description=description, archived=archived)

    root = vault_path()
    old_dir = root / PROJECT_DIR_TEMPLATE.format(context=context, slug=slug)
    new_dir = root / PROJECT_DIR_TEMPLATE.format(context=context, slug=new_slug)
    if get_project(context, new_slug) is not None or new_dir.exists():
        raise ProjectExists(f"{context}/{new_slug}")

    reason = f"rename project {slug} → {new_slug}"
    undo: list = []  # callables, run in reverse on failure
    try:
        # 1. move every file (notes through vault_write, the rest with os.replace)
        files = sorted(p for p in old_dir.rglob("*") if p.is_file()) if old_dir.is_dir() else []
        new_dir.mkdir(parents=True, exist_ok=True)
        undo.append(lambda: _rmdir_tree_if_empty(new_dir))
        for src in files:
            src_rel = _rel(src)
            dst = new_dir / src.relative_to(old_dir)
            dst_rel = _rel(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix in vault_write.WRITABLE_SUFFIXES:
                stamp = {"project": new_slug} if _front_project(src) == slug else None
                vault_write.write(src_rel, op="move", dest=dst_rel, fields=stamp, actor=USER, reason=reason)
                back = {"project": slug} if stamp else None
                undo.append(lambda a=dst_rel, b=src_rel, f=back: vault_write.write(
                    a, op="move", dest=b, fields=f, actor=USER, reason=f"undo {reason}"))
            else:
                os.replace(src, dst)
                undo.append(lambda a=dst, b=src: os.replace(a, b))

        # 2. rewrite inbound links elsewhere in the vault
        pattern = _link_pattern(context, slug)
        replacement = PROJECT_DIR_TEMPLATE.format(context=context, slug=new_slug)
        for note in sorted(root.rglob("*.md")):
            rel = _rel(note)
            if _HIDDEN.search(rel):  # notes already moved into the new folder are rewritten too (self-links)
                continue
            try:
                text = note.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            updated = pattern.sub(replacement, text)
            if updated != text:
                vault_write.write(rel, op="modify", content=updated, actor=USER, reason=reason)
                undo.append(lambda r=rel, t=text: vault_write.write(
                    r, op="modify", content=t, actor=USER, reason=f"undo {reason}"))

        # 3. chats scoped to the project
        from ghostbrain.api.repo import chat_store  # noqa: PLC0415
        # Use chat_store's real list/set API: every conversation whose project == f"{context}/{slug}"
        # gets f"{context}/{new_slug}"; push an undo that sets it back.

        # 4. registry last
        items = _read()
        for p in items:
            if p["context"] == context and p["slug"] == slug:
                p.update(slug=new_slug, id=f"{context}/{new_slug}", name=new_name)
                if description is not None:
                    p["description"] = description.strip()
                if archived is not None:
                    p["archived"] = bool(archived)
                result = dict(p)
        _write(items)
    except Exception:
        for fn in reversed(undo):
            try:
                fn()
            except Exception:  # noqa: BLE001 — best-effort rollback; the original error wins
                log.exception("project rename rollback step failed")
        raise

    _rmdir_tree_if_empty(old_dir)
    from ghostbrain.api.repo.doc_library import index as library_index  # noqa: PLC0415

    library_index.invalidate()
    return result


def _rmdir_tree_if_empty(d: Path) -> None:
    if not d.is_dir() or any(p.is_file() for p in d.rglob("*")):
        return
    for sub in sorted((p for p in d.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        sub.rmdir()
    d.rmdir()
```

Implementer notes:
- **Step 3 (chats):** read `ghostbrain/api/repo/chat_store.py` and implement it with its real functions. Never edit chat JSON by hand.
- **The `vault_write.write` lambdas:** `rel_path` is positional and the rest are keywords. Check the signature in `ghostbrain/vault_write/writer.py`.
- **If a move to a path that already exists raises in `vault_write`:** the pre-checks prevent that for project folders.
- **Link scan scope:** keep `rglob` over the vault but skip dot-directories. The history store and `.obsidian` must not be rewritten.

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev --extra api pytest tests/test_project_rename.py tests/test_projects_repo.py tests/test_vault_write_*.py tests/test_doc_library_*.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/projects.py tests/test_project_rename.py .github/workflows/ci.yml
git commit -m "feat(projects): full rename — move folder, re-stamp notes, rewrite links, repoint chats, rollback

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: PATCH route uses rename

**Files:**
- Modify: `ghostbrain/api/routes/projects.py` (`update_project` route)
- Test: `tests/test_projects_routes_rename.py` (or extend the existing projects route test file. `ghostbrain/api/tests/test_projects_routes.py` exists; prefer extending it.)

**Interfaces:**
- Consumes: `projects.rename_project`, `ProjectExists`.
- Produces:
  - `PATCH /v1/projects/{context}/{slug}` with `{name?, description?, archived?}` returns `Project`, with the **new** slug/id after a slug-changing rename.
  - Unknown project: 404. Collision: 409. Empty slug: 422.

- [ ] **Step 1: Write the failing test** (in the existing projects route test file, using its client/fixture helpers):

```python
def test_patch_renames_slug_and_maps_errors(client_and_vault):  # adapt to the file's fixture
    client, vault = client_and_vault
    client.post("/v1/projects", json={"context": "work", "name": "Paymnets"}, headers=H)
    client.post("/v1/projects", json={"context": "work", "name": "Claims"}, headers=H)
    r = client.patch("/v1/projects/work/paymnets", json={"name": "Payments"}, headers=H)
    assert r.status_code == 200 and r.json()["slug"] == "payments" and r.json()["id"] == "work/payments"
    assert client.patch("/v1/projects/work/payments", json={"name": "Claims"}, headers=H).status_code == 409
    assert client.patch("/v1/projects/work/ghost", json={"name": "X"}, headers=H).status_code == 404
    assert client.patch("/v1/projects/work/payments", json={"name": "!!!"}, headers=H).status_code == 422
    r = client.patch("/v1/projects/work/payments", json={"archived": True}, headers=H)
    assert r.json()["archived"] is True
    assert client.patch("/v1/projects/work/payments", json={"archived": False}, headers=H).json()["archived"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev --extra api pytest ghostbrain/api/tests/test_projects_routes.py -q`
Expected: FAIL. The slug stays `paymnets`.

- [ ] **Step 3: Implement**

```python
@router.patch("/{context}/{slug}", response_model=Project)
def update_project(context: str, slug: str, payload: UpdateProjectRequest) -> dict:
    try:
        p = repo.rename_project(
            context, slug, name=payload.name, description=payload.description, archived=payload.archived
        )
    except repo.ProjectExists as e:
        raise HTTPException(status_code=409, detail=f"a project with that name already exists: {e}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if p is None:
        raise HTTPException(status_code=404, detail=f"project not found: {context}/{slug}")
    return p
```

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev --extra api pytest ghostbrain/api/tests/test_projects_routes.py tests/test_project_rename.py tests/test_projects_repo.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/routes/projects.py ghostbrain/api/tests/test_projects_routes.py
git commit -m "feat(api): PATCH /v1/projects renames slug-safely; 409 on collision

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Edit + unarchive in Settings, rename in the docs tree

**Files:**
- Modify: `desktop/src/renderer/screens/settings.tsx` (`ProjectsSettings`)
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (`useUpdateProject`: also invalidate `['library']`, `['jots']`/notes and `['chat']` query keys; check the real keys in the file)
- Modify: `desktop/src/renderer/components/docs/DocTree.tsx` (project-row rename action) and `desktop/src/renderer/screens/docs.tsx` (wire it)
- Test: `desktop/src/renderer/__tests__/ProjectsSettings.test.tsx` (extend if present, else create), `DocTree.test.tsx`, `DocsScreen.test.tsx`

**Interfaces:**
- Consumes: `useUpdateProject()`. Vars are `{context, slug, name?, description?, archived?}` and it returns `Project`, carrying the new slug.
- Produces:
  - `DocTree` prop `onRenameProject(ref: { context: string; project: string }, name: string)`.
  - Settings rows: an **edit** action (inline name + description inputs, **save** / **cancel**, Enter saves, Esc cancels). When `make-slug(name)` would differ from the current slug, show the hint `renames the folder too`. Archived rows get **unarchive**. A 409 shows a toast with the server's detail.

- [ ] **Step 1: Write the failing tests**
  - **Settings:** clicking **edit** on `Paymnets`, typing `Payments` and saving calls `patch('/v1/projects/work/paymnets', { name: 'Payments', description: … })`. The hint appears while the typed name changes the slug. **unarchive** on an archived row patches `{ archived: false }`.
  - **DocTree:** the project row hover action `rename work/paymnets` shows an inline input. Enter with `Payments` calls `onRenameProject({context:'work', project:'paymnets'}, 'Payments')`. Esc cancels. Archived projects have no rename action.
  - **DocsScreen:** a rename resolving to slug `payments` while the selection was a folder in `paymnets` doesn't crash. The selection falls back (the existing stale-selection reset) and the tree refetches.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/ProjectsSettings.test.tsx src/renderer/__tests__/DocTree.test.tsx src/renderer/__tests__/DocsScreen.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**
  - **`ProjectsSettings`:** a per-row `editing` state with inputs. The slug-change hint uses a local `slugify` mirroring Python's `make_slug`: lowercase, non-alphanumerics to `-`, trimmed.
  - **`DocTree`:** a scope-row pencil (aria-label `rename ${context}/${project}`) using the existing module-level `FolderInput`, initial value the project name.
  - **`docs.tsx`:** `onRenameProject` → `run(updateProject.mutateAsync({ context, slug: project, name }))`.
  - **`useUpdateProject`** invalidates `projects`, `library`, the jots/notes keys, and `chat` on success.

- [ ] **Step 4: Run all desktop checks**

Run: `cd desktop && npx vitest run && npm run typecheck && npm run lint && npx -y node@20 node_modules/vitest/vitest.mjs run`
Expected: PASS. Output pristine.

- [ ] **Step 5: Commit**

```bash
git add desktop/src
git commit -m "feat(projects): edit name/description and unarchive in settings; rename from the docs tree

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

## Self-review notes

- **Design coverage:**
  - Rename with slug change, folder move, re-stamp, link rewrite and rollback: Task 1.
  - Chats: Task 1.
  - API and 409: Task 2.
  - Unarchive: Tasks 1, 2 and 3.
  - Settings edit and docs tree rename: Task 3.
- **Review Focus coverage:**
  - Library doc folder: Task 1, full-rename test.
  - Outside links: Task 1.
  - Rollback: Task 1.
  - Prefix sibling `pay`: Task 1, full-rename test.
  - Renderer after a slug change: Task 3, DocsScreen test.
- **Known limitation:** paths inside past chat transcripts (attachment chips) and semantic-index embeddings keep old paths until the next refresh. This is stated out of scope.
