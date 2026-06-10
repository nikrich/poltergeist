# Dynamic Projects + Chat-Summary Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** User-defined projects nested under the four fixed contexts, routable by the LLM auto-router and manual re-route, plus an "export to jots" action that LLM-summarizes a chat conversation into an auto-routed jot.

**Architecture:** A synced registry at `<vault>/90-meta/projects.json` (repo module + `/v1/projects` API) feeds a dynamic destination enum into the existing router (`worker/router.py`); `move_jot` learns project folders (`20-contexts/<ctx>/projects/<slug>/`) and frontmatter; a new `chat_export` repo turns a conversation into an inbox jot via one `llm/client.py` call and routes it through the existing `route_existing_jot`. Desktop: projects section in Settings, project-aware jots tree/re-route, export button in chat.

**Tech Stack:** Python 3.11 / FastAPI / python-frontmatter / pytest; Electron + React + React Query + zustand + Vitest.

**Spec:** `docs/superpowers/specs/2026-06-10-projects-and-chat-export-design.md`

---

## Task 0: worktree setup

All work happens on a worktree so the main checkout stays free.

- [ ] **Step 1: Create the worktree + branch**

```bash
cd /Users/jannik/development/nikrich/ghost-brain
git pull
git worktree add .claude/worktrees/projects-export -b feat/projects-and-chat-export main
```

- [ ] **Step 2: Python env in the worktree** (the main checkout's `.venv` is an editable install pointing at the MAIN checkout's code — tests run there would import the wrong tree)

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/projects-export
python3.11 -m venv .venv && .venv/bin/pip install -q -e ".[dev,mcp]"
.venv/bin/pytest ghostbrain/api/tests -q 2>&1 | tail -2   # sanity: same pass/fail profile as main
```

- [ ] **Step 3: Desktop deps**

```bash
cd desktop && npm install --no-audit --no-fund 2>&1 | tail -1 && npm test -- --run 2>&1 | grep "Tests" && npm run typecheck
```

ALL subsequent tasks run inside `/Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/projects-export` (referred to as `$WT`). Backend tests: `$WT/.venv/bin/pytest`. Known pre-existing env failures (calendar/joplin/weekly-digest/confluence) are NOT regressions.

---

## Task 1: project registry repo

**Files:**
- Create: `ghostbrain/api/repo/projects.py`
- Test: `tests/test_projects_repo.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_projects_repo.py`:

```python
"""Project registry: vault-synced JSON file CRUD."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.api.repo import projects


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    monkeypatch.setenv("VAULT_PATH", str(v))
    return v


def test_create_writes_registry_and_folder(vault: Path):
    p = projects.create_project("codeship", "Poltergeist", "second brain product")
    assert p == {
        "id": "codeship/poltergeist",
        "context": "codeship",
        "slug": "poltergeist",
        "name": "Poltergeist",
        "description": "second brain product",
        "archived": False,
        "created_at": p["created_at"],
    }
    assert (vault / "20-contexts/codeship/projects/poltergeist").is_dir()
    on_disk = json.loads((vault / "90-meta/projects.json").read_text())
    assert on_disk == [p]


def test_create_rejects_unknown_context_and_duplicate(vault: Path):
    with pytest.raises(projects.UnknownContext):
        projects.create_project("nope", "X")
    projects.create_project("personal", "Home Lab")
    with pytest.raises(projects.ProjectExists):
        projects.create_project("personal", "home-lab")  # same slug


def test_list_filters_archived_by_default(vault: Path):
    projects.create_project("personal", "A")
    projects.create_project("personal", "B")
    projects.update_project("personal", "b", archived=True)
    assert [p["slug"] for p in projects.list_projects()] == ["a"]
    assert [p["slug"] for p in projects.list_projects(include_archived=True)] == ["a", "b"]


def test_update_edits_and_returns_none_for_missing(vault: Path):
    projects.create_project("sanlam", "Capstone", "old")
    p = projects.update_project("sanlam", "capstone", name="Capstone v2", description="new")
    assert p["name"] == "Capstone v2" and p["description"] == "new"
    assert projects.update_project("sanlam", "missing", name="x") is None


def test_get_project_active_only_flag(vault: Path):
    projects.create_project("codeship", "Ship")
    assert projects.get_project("codeship", "ship")["name"] == "Ship"
    projects.update_project("codeship", "ship", archived=True)
    assert projects.get_project("codeship", "ship", active_only=True) is None
    assert projects.get_project("codeship", "ship") is not None


def test_corrupt_registry_reads_as_empty(vault: Path):
    (vault / "90-meta/projects.json").write_text("{nope")
    assert projects.list_projects() == []


def test_active_destinations_and_prompt_lines(vault: Path):
    projects.create_project("codeship", "Poltergeist", "the second brain")
    projects.create_project("codeship", "Archived One")
    projects.update_project("codeship", "archived-one", archived=True)
    dests = projects.active_destinations()
    assert "codeship/poltergeist" in dests
    assert "codeship/archived-one" not in dests
    assert {"sanlam", "codeship", "reducedrecipes", "personal"} <= set(dests)
    lines = projects.project_prompt_lines()
    assert lines == ["codeship/poltergeist — Poltergeist: the second brain"]
```

- [ ] **Step 2: Run** `$WT/.venv/bin/pytest tests/test_projects_repo.py -v` → ImportError.

- [ ] **Step 3: Implement** — `ghostbrain/api/repo/projects.py`:

```python
"""Project registry: user-defined routing destinations nested under contexts.

Stored at <vault>/90-meta/projects.json so it syncs with the vault. Atomic
writes (tmp+rename); a corrupt registry reads as empty — routing then degrades
to context-only rather than failing.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ghostbrain.api.repo.notes_manual import make_slug
from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.projects")

KNOWN_CONTEXTS = ("sanlam", "codeship", "reducedrecipes", "personal")
REGISTRY_REL = "90-meta/projects.json"
PROJECT_DIR_TEMPLATE = "20-contexts/{context}/projects/{slug}"


class UnknownContext(ValueError):
    pass


class ProjectExists(ValueError):
    pass


def _registry_path() -> Path:
    return vault_path() / REGISTRY_REL


def _read() -> list[dict]:
    path = _registry_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("unreadable projects registry %s: %s", path, exc)
        return []
    return data if isinstance(data, list) else []


def _write(items: list[dict]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_projects(*, include_archived: bool = False) -> list[dict]:
    items = _read()
    if not include_archived:
        items = [p for p in items if not p.get("archived")]
    return items


def get_project(context: str, slug: str, *, active_only: bool = False) -> dict | None:
    for p in _read():
        if p["context"] == context and p["slug"] == slug:
            if active_only and p.get("archived"):
                return None
            return p
    return None


def create_project(context: str, name: str, description: str = "") -> dict:
    if context not in KNOWN_CONTEXTS:
        raise UnknownContext(context)
    slug = make_slug(name)
    if not slug:
        raise ValueError("project name produces an empty slug")
    if get_project(context, slug) is not None:
        raise ProjectExists(f"{context}/{slug}")
    project = {
        "id": f"{context}/{slug}",
        "context": context,
        "slug": slug,
        "name": name.strip(),
        "description": description.strip(),
        "archived": False,
        "created_at": time.time(),
    }
    items = _read()
    items.append(project)
    _write(items)
    folder = vault_path() / PROJECT_DIR_TEMPLATE.format(context=context, slug=slug)
    folder.mkdir(parents=True, exist_ok=True)
    return project


def update_project(
    context: str,
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    archived: bool | None = None,
) -> dict | None:
    items = _read()
    for p in items:
        if p["context"] == context and p["slug"] == slug:
            if name is not None:
                p["name"] = name.strip()
            if description is not None:
                p["description"] = description.strip()
            if archived is not None:
                p["archived"] = bool(archived)
            _write(items)
            return p
    return None


def active_destinations() -> list[str]:
    """Routing destinations: bare contexts + 'context/slug' for active projects."""
    dests = list(KNOWN_CONTEXTS)
    dests.extend(p["id"] for p in list_projects())
    return dests


def project_prompt_lines() -> list[str]:
    """'context/slug — Name: description' lines for the router prompt."""
    out = []
    for p in list_projects():
        desc = f": {p['description']}" if p["description"] else ""
        out.append(f"{p['id']} — {p['name']}{desc}")
    return out
```

NOTE: check that `make_slug` in `ghostbrain/api/repo/notes_manual.py:21` produces kebab-case filesystem-safe slugs (read it). If it lowercases/strips to hyphens, use it as-is; do not write a duplicate slugifier.

- [ ] **Step 4: Run** → 7 passed.
- [ ] **Step 5: Commit** `git add ghostbrain/api/repo/projects.py tests/test_projects_repo.py && git commit -m "feat(projects): vault-synced project registry"`

---

## Task 2: `/v1/projects` API

**Files:**
- Create: `ghostbrain/api/models/project.py`, `ghostbrain/api/routes/projects.py`
- Modify: `ghostbrain/api/main.py`
- Test: `ghostbrain/api/tests/test_projects_routes.py`

- [ ] **Step 1: Write the failing tests** — `ghostbrain/api/tests/test_projects_routes.py` (the existing `client`/`auth_headers`/`tmp_vault` fixtures in `ghostbrain/api/tests/conftest.py` already point VAULT_PATH at a temp vault):

```python
"""/v1/projects CRUD routes."""
from __future__ import annotations


def test_create_list_roundtrip(client, auth_headers):
    created = client.post(
        "/v1/projects",
        json={"context": "codeship", "name": "Poltergeist", "description": "brain"},
        headers=auth_headers,
    )
    assert created.status_code == 200
    body = created.json()
    assert body["id"] == "codeship/poltergeist"
    listed = client.get("/v1/projects", headers=auth_headers).json()
    assert [p["id"] for p in listed] == ["codeship/poltergeist"]


def test_create_validation(client, auth_headers):
    r = client.post("/v1/projects", json={"context": "nope", "name": "X"}, headers=auth_headers)
    assert r.status_code == 422
    client.post("/v1/projects", json={"context": "personal", "name": "Lab"}, headers=auth_headers)
    dup = client.post("/v1/projects", json={"context": "personal", "name": "lab"}, headers=auth_headers)
    assert dup.status_code == 409


def test_patch_edit_and_archive(client, auth_headers):
    client.post("/v1/projects", json={"context": "sanlam", "name": "Capstone"}, headers=auth_headers)
    r = client.patch(
        "/v1/projects/sanlam/capstone",
        json={"description": "the big one", "archived": True},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["archived"] is True
    assert client.get("/v1/projects", headers=auth_headers).json() == []
    full = client.get("/v1/projects?includeArchived=true", headers=auth_headers).json()
    assert full[0]["description"] == "the big one"
    missing = client.patch("/v1/projects/sanlam/none", json={"name": "x"}, headers=auth_headers)
    assert missing.status_code == 404
```

- [ ] **Step 2: Run** `$WT/.venv/bin/pytest ghostbrain/api/tests/test_projects_routes.py -v` → 404s.

- [ ] **Step 3: Implement.** `ghostbrain/api/models/project.py`:

```python
"""Project registry schemas."""
from pydantic import BaseModel, Field


class Project(BaseModel):
    id: str
    context: str
    slug: str
    name: str
    description: str = ""
    archived: bool = False
    created_at: float


class CreateProjectRequest(BaseModel):
    context: str
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field("", max_length=400)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = Field(None, max_length=400)
    archived: bool | None = None
```

`ghostbrain/api/routes/projects.py`:

```python
"""Project registry CRUD. No DELETE — archive only (notes reference projects)."""
from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.project import (
    CreateProjectRequest,
    Project,
    UpdateProjectRequest,
)
from ghostbrain.api.repo import projects as repo

router = APIRouter(prefix="/v1/projects", tags=["projects"])


@router.get("", response_model=list[Project])
def list_projects(includeArchived: bool = Query(False)) -> list[dict]:
    return repo.list_projects(include_archived=includeArchived)


@router.post("", response_model=Project)
def create_project(payload: CreateProjectRequest) -> dict:
    try:
        return repo.create_project(payload.context, payload.name, payload.description)
    except repo.UnknownContext:
        raise HTTPException(
            status_code=422,
            detail=f"unknown context: {payload.context!r}; valid: {sorted(repo.KNOWN_CONTEXTS)}",
        )
    except repo.ProjectExists as e:
        raise HTTPException(status_code=409, detail=f"project already exists: {e}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.patch("/{context}/{slug}", response_model=Project)
def update_project(context: str, slug: str, payload: UpdateProjectRequest) -> dict:
    p = repo.update_project(
        context,
        slug,
        name=payload.name,
        description=payload.description,
        archived=payload.archived,
    )
    if p is None:
        raise HTTPException(status_code=404, detail=f"project not found: {context}/{slug}")
    return p
```

`ghostbrain/api/main.py`: add `from ghostbrain.api.routes import projects as projects_routes` and `app.include_router(projects_routes.router)` next to the other routers.

- [ ] **Step 4: Run** → 3 passed. **Step 5: Commit** `git add ghostbrain/api/models/project.py ghostbrain/api/routes/projects.py ghostbrain/api/main.py ghostbrain/api/tests/test_projects_routes.py && git commit -m "feat(projects): /v1/projects CRUD API"`

---

## Task 3: router picks destinations (context/project)

**Files:**
- Modify: `ghostbrain/worker/router.py`
- Test: `tests/test_router_projects.py`

The static `ROUTER_JSON_SCHEMA` context enum becomes a per-call destination enum; the LLM may answer `"codeship/poltergeist"`. `RoutingDecision` gains `project`. Unknown/archived project in the answer degrades to context-only.

- [ ] **Step 1: Write the failing tests** — `tests/test_router_projects.py`:

```python
"""Router destination enum + project parsing/validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.worker.router import build_router_schema, parse_destination


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(v))
    return v


def test_build_router_schema_includes_destinations(vault):
    projects.create_project("codeship", "Poltergeist")
    schema = build_router_schema()
    enum = schema["properties"]["context"]["enum"]
    assert "codeship/poltergeist" in enum
    assert "needs_review" in enum
    assert "sanlam" in enum


def test_parse_destination_bare_context(vault):
    assert parse_destination("sanlam") == ("sanlam", None)
    assert parse_destination("needs_review") == ("needs_review", None)


def test_parse_destination_valid_project(vault):
    projects.create_project("codeship", "Poltergeist")
    assert parse_destination("codeship/poltergeist") == ("codeship", "poltergeist")


def test_parse_destination_unknown_or_archived_project_degrades(vault):
    projects.create_project("codeship", "Poltergeist")
    projects.update_project("codeship", "poltergeist", archived=True)
    assert parse_destination("codeship/poltergeist") == ("codeship", None)
    assert parse_destination("codeship/never-existed") == ("codeship", None)
    # garbage context in a pair degrades to needs_review
    assert parse_destination("nope/x") == ("needs_review", None)
```

- [ ] **Step 2: Run** → ImportError on `build_router_schema`.

- [ ] **Step 3: Implement** in `ghostbrain/worker/router.py`:

1. Add `project: str | None = None` field to `RoutingDecision` (after `method`, keep `secondary_contexts` default last as dataclass rules require defaults ordering — both have defaults, fine).
2. Add imports `import copy` and `from ghostbrain.api.repo import projects as projects_repo` (no import cycle: `projects` imports only `notes_manual.make_slug` + paths — verify `notes_manual` top-of-file imports don't import `router` at module top; the router import there is mid-file (`notes_manual.py:313`), which DOES execute at import time. If `ghostbrain.api.repo.projects` → `notes_manual` → `router` → `projects` cycles, BREAK it by moving `make_slug` usage: import inside `create_project` body (`from ghostbrain.api.repo.notes_manual import make_slug` at function level) — adjust Task 1's file accordingly and note it.)
3. Add after `ROUTER_JSON_SCHEMA`:

```python
def build_router_schema() -> dict:
    """ROUTER_JSON_SCHEMA with the context enum replaced by the live
    destination list (contexts + active 'context/slug' projects)."""
    schema = copy.deepcopy(ROUTER_JSON_SCHEMA)
    schema["properties"]["context"]["enum"] = (
        projects_repo.active_destinations() + ["needs_review"]
    )
    return schema


def parse_destination(value: str) -> tuple[str, str | None]:
    """'codeship/poltergeist' → ('codeship', 'poltergeist'); bare context
    passes through. Unknown/archived project degrades to context-only;
    unknown context degrades to needs_review."""
    if "/" not in value:
        return value, None
    context, slug = value.split("/", 1)
    if context not in projects_repo.KNOWN_CONTEXTS:
        return "needs_review", None
    if projects_repo.get_project(context, slug, active_only=True) is None:
        return context, None
    return context, slug
```

4. In `_route_via_llm` (router.py:249): use the dynamic schema, inject project lines into the prompt, and parse the destination:

```python
    prompt_template = _read_prompt("router.md")
    prompt = prompt_template.replace("{{content}}", excerpt)
    project_lines = projects_repo.project_prompt_lines()
    if project_lines:
        # Appended rather than templated so existing router.md files in user
        # vaults keep working without regeneration.
        prompt += (
            "\n\n## Projects\n"
            "If the content clearly belongs to one of these projects, answer "
            "with its full 'context/slug' id instead of the bare context:\n- "
            + "\n- ".join(project_lines)
        )
```

```python
        result = llm.run(
            prompt,
            model=(config.get("llm") or {}).get("router_model", "haiku"),
            json_schema=build_router_schema(),
        )
```

and where the payload is unpacked (`ctx = payload.get("context", ...)`):

```python
    raw_dest = payload.get("context", "needs_review")
    ctx, project = parse_destination(str(raw_dest))
```

then include `project=project` in the returned `RoutingDecision`. Read the rest of `_route_via_llm` (lines 272-300) for the confidence/validation tail and keep its behavior; anywhere it validates `ctx` against a hardcoded set, validate against `projects_repo.KNOWN_CONTEXTS | {"needs_review"}` instead.

- [ ] **Step 4: Run** `$WT/.venv/bin/pytest tests/test_router_projects.py tests/test_router.py -v` → new tests pass, existing router tests still pass (they use the static schema only via route_event with fast-path/fallback — if any asserts on `ROUTER_JSON_SCHEMA` enum exist, they still hold because the static constant is unchanged).
- [ ] **Step 5: Commit** `git add ghostbrain/worker/router.py tests/test_router_projects.py && git commit -m "feat(projects): router routes to dynamic context/project destinations"`

---

## Task 4: notes storage knows projects

**Files:**
- Modify: `ghostbrain/api/repo/notes_manual.py`
- Test: `tests/test_notes_projects.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_notes_projects.py`:

```python
"""move_jot/list_jots/write_inbox_jot with projects."""
from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.notes_manual import (
    list_jots,
    move_jot,
    write_inbox_jot,
)


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "00-inbox/raw/manual").mkdir(parents=True)
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    monkeypatch.setenv("VAULT_PATH", str(v))
    return v


def test_move_jot_into_project_folder_and_frontmatter(vault: Path):
    projects.create_project("codeship", "Poltergeist")
    jot = write_inbox_jot("ship the chat feature")
    moved = move_jot(
        jot["id"], to_context="codeship", to_project="poltergeist",
        confidence=0.9, method="llm", reasoning="r",
    )
    assert moved["context"] == "codeship"
    assert moved["project"] == "poltergeist"
    assert moved["path"].startswith("20-contexts/codeship/projects/poltergeist/")
    post = frontmatter.load(vault / moved["path"])
    assert post["project"] == "poltergeist"


def test_move_jot_without_project_unchanged(vault: Path):
    jot = write_inbox_jot("plain note")
    moved = move_jot(
        jot["id"], to_context="personal",
        confidence=1.0, method="user", reasoning="r",
    )
    assert moved["path"].startswith("20-contexts/personal/notes/")
    assert moved.get("project") is None


def test_reroute_out_of_project_clears_frontmatter(vault: Path):
    projects.create_project("codeship", "Poltergeist")
    jot = write_inbox_jot("note")
    move_jot(jot["id"], to_context="codeship", to_project="poltergeist",
             confidence=0.9, method="llm", reasoning="r")
    moved = move_jot(jot["id"], to_context="codeship",
                     confidence=1.0, method="user", reasoning="r")
    assert moved["path"].startswith("20-contexts/codeship/notes/")
    post = frontmatter.load(vault / moved["path"])
    assert post.get("project") is None


def test_list_jots_scans_project_folders_and_filters(vault: Path):
    projects.create_project("codeship", "Poltergeist")
    a = write_inbox_jot("in project")
    move_jot(a["id"], to_context="codeship", to_project="poltergeist",
             confidence=0.9, method="llm", reasoning="r")
    b = write_inbox_jot("loose note")
    move_jot(b["id"], to_context="codeship",
             confidence=1.0, method="user", reasoning="r")
    page = list_jots()
    by_id = {i["id"]: i for i in page["items"]}
    assert by_id[a["id"]]["project"] == "poltergeist"
    assert by_id[b["id"]]["project"] is None
    only = list_jots(project="poltergeist")
    assert [i["id"] for i in only["items"]] == [a["id"]]


def test_write_inbox_jot_extra_frontmatter(vault: Path):
    jot = write_inbox_jot("summary body", extra={"source": "chat-summary", "chat_id": "c1"})
    post = frontmatter.load(vault / jot["path"])
    assert post["source"] == "chat-summary"
    assert post["chat_id"] == "c1"
```

- [ ] **Step 2: Run** → TypeError (unexpected kwargs).

- [ ] **Step 3: Implement** in `ghostbrain/api/repo/notes_manual.py` (read each function first; minimal diffs):

1. Next to `CONTEXT_NOTES_TEMPLATE` (line 71):

```python
PROJECT_NOTES_TEMPLATE = "20-contexts/{context}/projects/{project}"
```

2. `write_inbox_jot(body, *, captured_at=None, extra: dict | None = None)` — after building the `frontmatter.Post(...)` kwargs, apply overrides/additions:

```python
    if extra:
        for k, v in extra.items():
            post[k] = v
```

(`source` override to `chat-summary` is intentional — `list_jots` filtering is adjusted in step 4 below.)

3. `move_jot` gains `to_project: str | None = None`:
   - destination: `_guard_inside_vault((_vault() / PROJECT_NOTES_TEMPLATE.format(context=to_context, project=to_project)) / f"{jot_id}.md")` when `to_project` else the existing `_context_dir(to_context) / ...`; `dst.parent.mkdir(parents=True, exist_ok=True)` before write (project folder may not exist if created outside the app).
   - frontmatter: `post["project"] = to_project` when set, else remove a stale key:

```python
    if to_project:
        post["project"] = to_project
    elif "project" in post.metadata:
        del post.metadata["project"]
```

   - return dict gains `"project": to_project`.
4. `_iter_manual_files`: also scan project folders:

```python
            projects_dir = ctx_dir / "projects"
            if projects_dir.is_dir():
                for proj_dir in projects_dir.iterdir():
                    if proj_dir.is_dir():
                        yield from proj_dir.glob("manual-*.md")
```

5. `list_jots`: signature gains `project: str | None = None`; the `source` filter becomes `if post.get("source") not in ("manual", "chat-summary"): continue` (chat-summary jots are reviewable jots); item dict gains `"project": post.get("project")`; filter `if project is not None and item["project"] != project: continue`.

- [ ] **Step 4: Run** `$WT/.venv/bin/pytest tests/test_notes_projects.py ghostbrain/api/tests/test_routes_notes_list.py ghostbrain/api/tests/test_notes_manual_io.py -v` → all pass.
- [ ] **Step 5: Commit** `git add ghostbrain/api/repo/notes_manual.py tests/test_notes_projects.py && git commit -m "feat(projects): jot storage — project folders, frontmatter, list filter"`

---

## Task 5: routing plumbing + manual route endpoint

**Files:**
- Modify: `ghostbrain/api/repo/notes_manual.py` (`_route_jot_core`), `ghostbrain/api/models/note.py`, `ghostbrain/api/routes/notes.py`
- Test: `tests/test_notes_projects.py` (append), `ghostbrain/api/tests/test_routes_notes_mutate.py` (append)

- [ ] **Step 1: Failing tests.** Append to `tests/test_notes_projects.py`:

```python
def test_route_jot_core_passes_project(vault, monkeypatch):
    import ghostbrain.api.repo.notes_manual as nm
    from ghostbrain.worker.router import RoutingDecision

    projects.create_project("codeship", "Poltergeist")
    jot = write_inbox_jot("note about the brain")
    monkeypatch.setattr(
        nm, "route_event",
        lambda event, **kw: RoutingDecision(
            context="codeship", confidence=0.9, reasoning="r",
            method="llm", project="poltergeist",
        ),
    )
    from ghostbrain.api.repo.notes_manual import route_existing_jot
    result = route_existing_jot(jot["id"])
    assert result["routingStatus"] == "routed"
    assert result["context"] == "codeship"
    assert result["project"] == "poltergeist"
    assert result["path"].startswith("20-contexts/codeship/projects/poltergeist/")
```

Append to `ghostbrain/api/tests/test_routes_notes_mutate.py` (match its existing fixture/style — read the file first; it has client fixtures creating jots via POST /v1/notes):

```python
def test_manual_route_with_project(client, auth_headers):
    from ghostbrain.api.repo import projects
    projects.create_project("codeship", "Poltergeist")
    created = client.post(
        "/v1/notes", json={"body": "note", "route": False}, headers=auth_headers
    ).json()
    r = client.post(
        f"/v1/notes/{created['id']}/route",
        json={"context": "codeship", "project": "poltergeist"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["project"] == "poltergeist"
    bad = client.post(
        f"/v1/notes/{created['id']}/route",
        json={"context": "codeship", "project": "ghost-project"},
        headers=auth_headers,
    )
    assert bad.status_code == 400
```

(If `POST /v1/notes` has no `route: False` mode, read `CreateNoteRequest` — it does: `route=True` field — and the create endpoint; adapt the fixture to however the existing mutate tests create an unrouted jot.)

- [ ] **Step 2: Run** → failures.

- [ ] **Step 3: Implement.**

1. `_route_jot_core` (notes_manual.py:336): pass project through and return it —

```python
        moved = move_jot(
            jot_id,
            to_context=decision.context,
            to_project=decision.project,
            confidence=decision.confidence,
            method=decision.method,
            reasoning=decision.reasoning,
        )
```

and in the success return dict add `"project": decision.project`.

2. `ghostbrain/api/models/note.py`: `RouteNoteRequest` gains `project: str | None = None`; `NoteListItem` gains `project: str | None = None`.

3. `ghostbrain/api/routes/notes.py`:
   - `get_notes` gains `project: str | None = Query(None)` passed to `list_jots`.
   - `route_note`: after the context check, validate the project and pass it:

```python
    if req.project is not None:
        from ghostbrain.api.repo import projects as projects_repo
        if projects_repo.get_project(req.context, req.project, active_only=True) is None:
            raise HTTPException(
                status_code=400,
                detail=f"unknown or archived project: {req.context}/{req.project}",
            )
    try:
        return move_jot(
            jot_id,
            to_context=req.context,
            to_project=req.project,
            confidence=1.0,
            method="user",
            reasoning="manual re-route by user",
        )
```

(Module-level import is fine too — match the file's import style. Spec said 422 for bad project; use 400 to match the endpoint's existing unknown-context behavior — note this as an intentional spec deviation in the commit body.)

- [ ] **Step 4: Run** `$WT/.venv/bin/pytest tests/test_notes_projects.py ghostbrain/api/tests/test_routes_notes_mutate.py ghostbrain/api/tests/test_routes_notes_route_auto.py -v` → all pass.
- [ ] **Step 5: Commit** `git add -u && git add tests/test_notes_projects.py && git commit -m "feat(projects): route pipeline + manual re-route carry projects"`

---

## Task 6: chat-summary export

**Files:**
- Create: `ghostbrain/api/repo/chat_export.py`
- Modify: `ghostbrain/api/routes/chat.py`, `ghostbrain/api/models/chat.py`
- Test: `tests/test_chat_export.py`, `ghostbrain/api/tests/test_chat.py` (append)

- [ ] **Step 1: Failing tests** — `tests/test_chat_export.py`:

```python
"""Chat conversation → LLM summary → routed jot."""
from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from ghostbrain.api.repo import chat_export, chat_store


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "00-inbox/raw/manual").mkdir(parents=True)
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    monkeypatch.setenv("VAULT_PATH", str(v))
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(tmp_path / "chats"))
    return v


def _conv_with_messages() -> dict:
    conv = chat_store.create()
    chat_store.append_user_message(conv, "what did we decide about the rebrand?")
    chat_store.append_assistant_message(
        conv,
        "You renamed ghost-brain to Poltergeist. See [[20-contexts/codeship/decision]].",
        [{"name": "search", "summary": "searched vault: rebrand"}],
    )
    return conv


class FakeLLMResult:
    text = "## Rebrand summary\n\n- renamed to Poltergeist [[20-contexts/codeship/decision]]\n"


def test_export_writes_summary_jot_and_routes(env, monkeypatch):
    conv = _conv_with_messages()
    captured: dict = {}

    def fake_run(prompt, **kw):
        captured["prompt"] = prompt
        return FakeLLMResult()

    monkeypatch.setattr(chat_export.llm, "run", fake_run)
    monkeypatch.setattr(
        chat_export,
        "route_existing_jot",
        lambda jot_id: {"id": jot_id, "path": f"20-contexts/codeship/notes/{jot_id}.md",
                        "routingStatus": "routed", "context": "codeship", "project": None},
    )
    result = chat_export.export_conversation(conv["id"])
    assert result["routingStatus"] == "routed"
    assert result["context"] == "codeship"
    # the transcript and the citation made it into the prompt
    assert "rebrand" in captured["prompt"]
    assert "[[20-contexts/codeship/decision]]" in captured["prompt"]
    # frontmatter marks provenance (file may have been "moved" by the fake router;
    # read via the inbox path captured before routing)
    assert result["jot_id"]


def test_export_empty_conversation_rejected(env):
    conv = chat_store.create()
    with pytest.raises(chat_export.NothingToExport):
        chat_export.export_conversation(conv["id"])


def test_export_unknown_conversation(env):
    with pytest.raises(chat_export.ConversationNotFound):
        chat_export.export_conversation("nope")


def test_llm_failure_writes_nothing(env, monkeypatch):
    conv = _conv_with_messages()

    def boom(prompt, **kw):
        raise chat_export.llm.LLMError("over budget")

    monkeypatch.setattr(chat_export.llm, "run", boom)
    with pytest.raises(chat_export.llm.LLMError):
        chat_export.export_conversation(conv["id"])
    inbox = env / "00-inbox/raw/manual"
    assert list(inbox.glob("*.md")) == []
```

Append to `ghostbrain/api/tests/test_chat.py`:

```python
def test_export_route(client, tmp_chats_dir, auth_headers, monkeypatch):
    conv = client.post("/v1/chat", headers=auth_headers).json()
    monkeypatch.setattr(
        "ghostbrain.api.routes.chat.repo_chat_export.export_conversation",
        lambda conv_id: {"jot_id": "j1", "path": "p", "routingStatus": "routed",
                         "context": "codeship", "project": None, "title": "t"},
    )
    r = client.post(f"/v1/chat/{conv['id']}/export-jot", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["jot_id"] == "j1"


def test_export_route_maps_errors(client, tmp_chats_dir, auth_headers):
    assert (
        client.post("/v1/chat/nope/export-jot", headers=auth_headers).status_code == 404
    )
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement.** `ghostbrain/api/repo/chat_export.py`:

```python
"""Export a chat conversation as an LLM-summarized, auto-routed jot.

Order matters: the LLM call completes BEFORE any file is written, so a failed
export leaves no half-jot behind.
"""
from __future__ import annotations

import logging

from ghostbrain.api.repo import chat_store
from ghostbrain.api.repo.notes_manual import route_existing_jot, write_inbox_jot
from ghostbrain.llm import client as llm

log = logging.getLogger("ghostbrain.chat.export")

EXPORT_MODEL = "sonnet"
TRANSCRIPT_CHAR_CAP = 60_000  # keep the prompt bounded for marathon chats


class ConversationNotFound(LookupError):
    pass


class NothingToExport(ValueError):
    pass


PROMPT_TEMPLATE = """Summarize this chat conversation between the user and \
Poltergeist (their second-brain assistant) into a reviewable note.

Rules:
1. Markdown only. Start with a single `#` title naming the topic.
2. Sections (omit empty ones): **Summary** (2-4 sentences), **Decisions**, \
**Findings**, **Open questions**.
3. Preserve every Obsidian wikilink (`[[...]]`) from the conversation verbatim \
where relevant — they link the note back to its sources.
4. Be concrete and specific; use the user's own terminology. No filler.

Conversation transcript:

{transcript}

Note:"""


def _transcript(conv: dict) -> str:
    lines = []
    for m in conv["messages"]:
        who = "user" if m["role"] == "user" else "poltergeist"
        lines.append(f"{who}: {m['text']}")
    text = "\n\n".join(lines)
    return text[-TRANSCRIPT_CHAR_CAP:]


def export_conversation(conv_id: str) -> dict:
    conv = chat_store.get(conv_id)
    if conv is None:
        raise ConversationNotFound(conv_id)
    if not any(m["role"] == "assistant" and m["text"] for m in conv["messages"]):
        raise NothingToExport(conv_id)

    prompt = PROMPT_TEMPLATE.format(transcript=_transcript(conv))
    result = llm.run(prompt, model=EXPORT_MODEL)  # raises LLMError on failure

    jot = write_inbox_jot(
        result.text.strip() + "\n",
        extra={
            "source": "chat-summary",
            "chat_id": conv_id,
            "chat_title": conv["title"],
        },
    )
    routed = route_existing_jot(jot["id"])
    return {
        "jot_id": jot["id"],
        "path": routed.get("path", jot["path"]),
        "routingStatus": routed.get("routingStatus", "manual_review"),
        "context": routed.get("context"),
        "project": routed.get("project"),
        "title": conv["title"],
    }
```

`ghostbrain/api/models/chat.py` — add:

```python
class ChatExportResponse(BaseModel):
    jot_id: str
    path: str
    routingStatus: str
    context: str | None = None
    project: str | None = None
    title: str
```

`ghostbrain/api/routes/chat.py` — add imports (`from ghostbrain.api.repo import chat_export as repo_chat_export`, `ChatExportResponse`, and `from ghostbrain.llm.client import LLMError`) and the route:

```python
@router.post("/{conv_id}/export-jot", response_model=ChatExportResponse)
def export_jot(conv_id: str) -> dict:
    try:
        return repo_chat_export.export_conversation(conv_id)
    except repo_chat_export.ConversationNotFound:
        raise HTTPException(status_code=404, detail="conversation not found")
    except repo_chat_export.NothingToExport:
        raise HTTPException(status_code=400, detail="conversation has no answers to summarize")
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"summary failed: {e}")
```

- [ ] **Step 4: Run** `$WT/.venv/bin/pytest tests/test_chat_export.py ghostbrain/api/tests/test_chat.py -v` → all pass.
- [ ] **Step 5: Full backend suite** `$WT/.venv/bin/pytest tests ghostbrain/api/tests -q` → no new failures.
- [ ] **Step 6: Commit** `git add ghostbrain/api/repo/chat_export.py ghostbrain/api/models/chat.py ghostbrain/api/routes/chat.py tests/test_chat_export.py ghostbrain/api/tests/test_chat.py && git commit -m "feat(chat): export conversation as LLM-summarized, auto-routed jot"`

---

## Task 7: desktop types + hooks

**Files:**
- Modify: `desktop/src/shared/api-types.ts`, `desktop/src/renderer/lib/api/hooks.ts`

- [ ] **Step 1: api-types.ts** — append a Projects block, and extend the jot types:

```ts
// ── Projects ──────────────────────────────────────────────────────────────

export interface Project {
  id: string;
  context: string;
  slug: string;
  name: string;
  description: string;
  archived: boolean;
  created_at: number;
}

export interface CreateProjectRequest {
  context: string;
  name: string;
  description?: string;
}

export interface UpdateProjectRequest {
  name?: string;
  description?: string;
  archived?: boolean;
}

export interface ChatExportResponse {
  jot_id: string;
  path: string;
  routingStatus: string;
  context: string | null;
  project: string | null;
  title: string;
}
```

Find the jot list item type (`JotListItem` in api-types.ts) and add `project?: string | null;`.

- [ ] **Step 2: hooks.ts** — extend the type import with `ChatExportResponse, CreateProjectRequest, Project, UpdateProjectRequest`, then append:

```ts
// ── Projects ──────────────────────────────────────────────────────────────

export function useProjects(opts?: { includeArchived?: boolean }) {
  return useQuery({
    queryKey: ['projects', opts ?? {}],
    queryFn: () =>
      get<Project[]>(`/v1/projects${opts?.includeArchived ? '?includeArchived=true' : ''}`),
    staleTime: 30_000,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: CreateProjectRequest) => post<Project>('/v1/projects', req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  });
}

export function useUpdateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { context: string; slug: string } & UpdateProjectRequest) =>
      patch<Project>(`/v1/projects/${vars.context}/${vars.slug}`, {
        name: vars.name,
        description: vars.description,
        archived: vars.archived,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  });
}

export function useExportChatToJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (convId: string) =>
      post<ChatExportResponse>(`/v1/chat/${encodeURIComponent(convId)}/export-jot`),
    onSuccess: () => qc.invalidateQueries({ queryKey: JOTS_KEY }),
  });
}
```

Also extend `useRouteJot`'s vars with `project?: string | null` and pass it in the body (read the existing hook; it posts `{context}` to `/v1/notes/{id}/route` — add `project: vars.project ?? undefined`). Extend `useJots` params with `project?: string` appended to the query string like the others.

- [ ] **Step 3: Verify** `cd $WT/desktop && npm test -- --run && npm run typecheck` → green.
- [ ] **Step 4: Commit** `git add src/shared/api-types.ts src/renderer/lib/api/hooks.ts && git commit -m "feat(projects): desktop types + project/export hooks"`

---

## Task 8: projects section in Settings

**Files:**
- Modify: `desktop/src/renderer/screens/settings.tsx`
- Test: `desktop/src/renderer/__tests__/ProjectsSettings.test.tsx`

- [ ] **Step 1: Read `settings.tsx`** — note the `SectionId` union, `SECTIONS` nav array, `SectionHeader`/`SettingRow` primitives, and how sections render.

- [ ] **Step 2: Failing test** — `desktop/src/renderer/__tests__/ProjectsSettings.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ProjectsSettings } from '../screens/settings';
import type { Project } from '../../shared/api-types';

const projects: Project[] = [
  {
    id: 'codeship/poltergeist',
    context: 'codeship',
    slug: 'poltergeist',
    name: 'Poltergeist',
    description: 'second brain',
    archived: false,
    created_at: 1,
  },
];

const post = vi.fn(() => Promise.resolve(projects[0]));
vi.mock('../lib/api/client', () => ({
  get: vi.fn(() => Promise.resolve(projects)),
  post: (...args: unknown[]) => post(...args),
  patch: vi.fn(() => Promise.resolve(projects[0])),
  del: vi.fn(),
}));

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ProjectsSettings />
    </QueryClientProvider>,
  );
}

describe('ProjectsSettings', () => {
  it('lists projects grouped under their context', async () => {
    renderSection();
    expect(await screen.findByText('Poltergeist')).toBeTruthy();
    expect(screen.getByText('codeship')).toBeTruthy();
    expect(screen.getByText('second brain')).toBeTruthy();
  });

  it('creates a project from the form', async () => {
    renderSection();
    await screen.findByText('Poltergeist');
    fireEvent.change(screen.getByPlaceholderText(/project name/i), {
      target: { value: 'Hive IDE' },
    });
    fireEvent.click(screen.getByRole('button', { name: /add project/i }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/v1/projects', {
        context: expect.any(String),
        name: 'Hive IDE',
        description: '',
      }),
    );
  });
});
```

- [ ] **Step 3: Implement.** In `settings.tsx`: add `'projects'` to the `SectionId` union and a `{ id: 'projects', label: 'projects', … }` entry to `SECTIONS` (match the existing entry shape — read it), render `{section === 'projects' && <ProjectsSettings />}`, and add an **exported** section component (export needed for the test):

```tsx
const PROJECT_CONTEXTS = ['sanlam', 'codeship', 'reducedrecipes', 'personal'];

export function ProjectsSettings() {
  const projects = useProjects({ includeArchived: true });
  const createProject = useCreateProject();
  const updateProject = useUpdateProject();
  const [ctx, setCtx] = useState(PROJECT_CONTEXTS[0]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  const submit = () => {
    const trimmed = name.trim();
    if (!trimmed || createProject.isPending) return;
    createProject.mutate(
      { context: ctx, name: trimmed, description: description.trim() },
      {
        onSuccess: () => {
          setName('');
          setDescription('');
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : 'create failed'),
      },
    );
  };

  const byContext = PROJECT_CONTEXTS.map((c) => ({
    context: c,
    items: (projects.data ?? []).filter((p) => p.context === c),
  })).filter((g) => g.items.length > 0);

  return (
    <div>
      <SectionHeader
        title="projects"
        sub="routing destinations nested under your contexts. jots, notes, and chat exports can route into them."
      />

      <div className="mb-6 flex flex-col gap-2 rounded-md border border-hairline bg-vellum p-4">
        <div className="flex gap-2">
          <select
            value={ctx}
            onChange={(e) => setCtx(e.target.value)}
            className="rounded-sm border border-hairline-2 bg-paper px-2 py-[6px] text-12 text-ink-0"
          >
            {PROJECT_CONTEXTS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="project name…"
            className="flex-1 rounded-sm border border-hairline-2 bg-paper px-2 py-[6px] text-12 text-ink-0 placeholder:text-ink-3 focus:outline-none"
          />
        </div>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="description (helps the router pick it)…"
          className="rounded-sm border border-hairline-2 bg-paper px-2 py-[6px] text-12 text-ink-0 placeholder:text-ink-3 focus:outline-none"
        />
        <div>
          <Btn
            variant="primary"
            size="sm"
            disabled={!name.trim() || createProject.isPending}
            onClick={submit}
          >
            add project
          </Btn>
        </div>
      </div>

      {projects.isError && (
        <div className="mb-4 rounded-md border border-oxblood/30 bg-oxblood/10 p-3 text-12 text-oxblood">
          couldn't read the project registry:{' '}
          {projects.error instanceof Error ? projects.error.message : 'unknown error'}
        </div>
      )}

      {byContext.map((group) => (
        <div key={group.context} className="mb-5">
          <Eyebrow className="mb-2">{group.context}</Eyebrow>
          {group.items.map((p) => (
            <ProjectRow key={p.id} project={p} onUpdate={updateProject.mutate} />
          ))}
        </div>
      ))}
      {(projects.data ?? []).length === 0 && !projects.isError && (
        <div className="text-12 text-ink-3">no projects yet — add one above.</div>
      )}
    </div>
  );
}

function ProjectRow({
  project,
  onUpdate,
}: {
  project: Project;
  onUpdate: (vars: { context: string; slug: string } & UpdateProjectRequest) => void;
}) {
  return (
    <div
      className={`flex items-center gap-3 rounded-sm px-3 py-2 hover:bg-vellum ${
        project.archived ? 'opacity-50' : ''
      }`}
    >
      <div className="min-w-0 flex-1">
        <div className="text-13 text-ink-0">{project.name}</div>
        {project.description && (
          <div className="truncate text-11 text-ink-2">{project.description}</div>
        )}
      </div>
      <span className="font-mono text-10 text-ink-3">{project.slug}</span>
      <button
        type="button"
        className="text-11 text-ink-2 hover:text-ink-0"
        onClick={() =>
          onUpdate({
            context: project.context,
            slug: project.slug,
            archived: !project.archived,
          })
        }
      >
        {project.archived ? 'unarchive' : 'archive'}
      </button>
    </div>
  );
}
```

Imports needed at the top of settings.tsx: `useProjects, useCreateProject, useUpdateProject` from `../lib/api/hooks`; `Project, UpdateProjectRequest` types; `Btn`, `Eyebrow`, `toast` if not already imported; `useState` is already there. Inline edit of name/description is v1-deferred to keep the section small — archive toggle + create is the spec's core. (Deviation note: spec said "inline edit"; implement name/description editing ONLY if trivial with existing primitives — a double-click-to-edit input like the chat conversation list rows is the pattern to copy if you do.)

- [ ] **Step 4: Run** `npm test -- --run src/renderer/__tests__/ProjectsSettings.test.tsx` then the full suite + typecheck.
- [ ] **Step 5: Commit** `git add -A src/renderer && git commit -m "feat(projects): settings section — create/archive projects"`

---

## Task 9: jots tree groups by project

**Files:**
- Modify: `desktop/src/renderer/components/JotTree.tsx`
- Test: `desktop/src/renderer/__tests__/JotTree.test.tsx` (append)

- [ ] **Step 1: Read** `JotTree.tsx` fully and its existing test for fixture shape.

- [ ] **Step 2: Failing test** — append to `JotTree.test.tsx` (adapt fixture fields to the real `JotListItem`):

```tsx
it('groups project jots under context → project', () => {
  const items = [
    makeItem({ id: 'a', context: 'codeship', project: 'poltergeist', created: '2026-06-01T00:00:00Z' }),
    makeItem({ id: 'b', context: 'codeship', project: null, created: '2026-06-02T00:00:00Z' }),
  ];
  render(<JotTree items={items} selectedId={null} onSelect={() => {}} />);
  expect(screen.getByText('poltergeist')).toBeTruthy();   // project node
  expect(screen.getByText('codeship')).toBeTruthy();      // context node
});
```

(`makeItem` = whatever fixture helper the existing tests use; create one mirroring their literal objects if none exists.)

- [ ] **Step 3: Implement.** Change the grouping so project jots get an intermediate level; project-less jots keep today's context → month shape. Concretely, extend `groupItems` to a per-context structure:

```typescript
interface ContextGroup {
  /** project slug → month → items */
  projects: Record<string, Record<string, JotListItem[]>>;
  /** month → items (project-less, today's behavior) */
  months: Record<string, JotListItem[]>;
}

function groupItems(items: JotListItem[]): Record<string, ContextGroup> {
  const tree: Record<string, ContextGroup> = {};
  for (const item of items) {
    const ctx =
      item.routingStatus === 'manual_review'
        ? 'unrouted'
        : item.routingStatus === 'pending'
          ? 'inbox (pending)'
          : item.context ?? 'unrouted';
    const month = (item.created || '').slice(0, 7) || 'unknown';
    tree[ctx] ??= { projects: {}, months: {} };
    if (item.project) {
      tree[ctx].projects[item.project] ??= {};
      tree[ctx].projects[item.project][month] ??= [];
      tree[ctx].projects[item.project][month].push(item);
    } else {
      tree[ctx].months[month] ??= [];
      tree[ctx].months[month].push(item);
    }
  }
  return tree;
}
```

Render project nodes (sorted alphabetically) above the loose months inside each context, reusing the existing month/leaf rendering for both branches (extract the month-list rendering into a small local component so it isn't duplicated). Keep existing sorting: months descending, leaves by `created` descending.

- [ ] **Step 4: Run** JotTree + jots tests + full suite + typecheck.
- [ ] **Step 5: Commit** `git add src/renderer/components/JotTree.tsx src/renderer/__tests__/JotTree.test.tsx && git commit -m "feat(projects): jots tree groups context → project → month"`

---

## Task 10: jots re-route picker with projects

**Files:**
- Modify: `desktop/src/renderer/screens/jots.tsx`
- Test: `desktop/src/renderer/__tests__/jots.test.tsx` (append)

- [ ] **Step 1: Read** `jots.tsx` (the re-route `<select>` at ~line 272 and `handleReroute` at ~line 172) and its test file.

- [ ] **Step 2: Failing test** — append to `jots.test.tsx` (mirror its existing mock/client setup; add `/v1/projects` to the mocked GET routes returning one project `codeship/poltergeist`):

```tsx
it('re-route select offers project destinations', async () => {
  renderJots(); // existing helper; select a jot per existing test flow
  // ... follow the file's established way of opening a jot detail ...
  const select = await screen.findByDisplayValue('re-route…');
  const options = Array.from(select.querySelectorAll('option')).map((o) => o.getAttribute('value'));
  expect(options).toContain('codeship');
  expect(options).toContain('codeship/poltergeist');
});
```

- [ ] **Step 3: Implement.** In `jots.tsx`:
- `const projects = useProjects();`
- Replace the `KNOWN_CONTEXTS.map` options with grouped destinations:

```tsx
{KNOWN_CONTEXTS.map((c) => (
  <optgroup key={c} label={c}>
    <option value={c}>{c}</option>
    {(projects.data ?? [])
      .filter((p) => p.context === c)
      .map((p) => (
        <option key={p.id} value={p.id}>
          {c} / {p.name}
        </option>
      ))}
  </optgroup>
))}
```

- `handleReroute(value)` splits: `const [context, project] = value.includes('/') ? value.split('/', 2) : [value, undefined]; routeJot.mutate({ id: selectedId, context, project });`
- If the detail pane shows the jot's context, also show ` / <project>` when present (read how context renders there and match).

- [ ] **Step 4: Run** jots tests + full suite + typecheck. **Step 5: Commit** `git add src/renderer/screens/jots.tsx src/renderer/__tests__/jots.test.tsx && git commit -m "feat(projects): jots re-route picker offers context/project destinations"`

---

## Task 11: chat export button

**Files:**
- Modify: `desktop/src/renderer/screens/chat.tsx`
- Test: `desktop/src/renderer/__tests__/ChatScreen.test.tsx` (append)

- [ ] **Step 1: Failing test** — append to `ChatScreen.test.tsx` (its mock client + store seeding already exist; add `post` handling for the export path):

```tsx
it('exports the conversation to a jot', async () => {
  renderScreen();
  await screen.findByText('what did we decide?');
  fireEvent.click(screen.getByRole('button', { name: /export to jots/i }));
  await waitFor(() => {
    // mocked post resolves with a routed export response
    expect(vi.mocked(post)).toHaveBeenCalledWith('/v1/chat/c1/export-jot');
  });
});
```

(Adjust to the file's actual mock variables — the `vi.mock('../lib/api/client', ...)` factory must expose the `post` spy; follow the pattern used in `ProjectsSettings.test.tsx` from Task 8.)

- [ ] **Step 2: Implement.** In `chat.tsx`:
- `const exportJot = useExportChatToJot();`
- In the `TopBar` `right` prop (add one if the chat TopBar has none — `today.tsx` shows the `right={<div className="flex gap-2">…}` pattern), add:

```tsx
<Btn
  variant="ghost"
  size="sm"
  icon={<Lucide name="file-output" size={13} />}
  disabled={activeId === null || exportJot.isPending || conversationEmpty}
  onClick={() => {
    if (!activeId) return;
    exportJot.mutate(activeId, {
      onSuccess: (res) => {
        const dest =
          res.routingStatus === 'routed'
            ? [res.context, res.project].filter(Boolean).join(' / ')
            : 'inbox (needs review)';
        toast.success(`exported to jots → ${dest}`);
      },
      onError: (e) =>
        toast.error(e instanceof Error ? e.message : 'export failed'),
    });
  }}
>
  {exportJot.isPending ? 'exporting…' : 'export to jots'}
</Btn>
```

where `conversationEmpty` is `(conversation.data?.messages ?? []).every((m) => m.role !== 'assistant')`. The export takes ~5-15s (sonnet) — the pending label + disabled state covers it. (Deviation note: spec mentioned an "open the jot" affordance on the toast; the toast store is string-only, so the destination text + the jots screen is v1. Don't extend the toast store for this.)

- [ ] **Step 3: Run** ChatScreen tests + full suite + typecheck. **Step 4: Commit** `git add src/renderer/screens/chat.tsx src/renderer/__tests__/ChatScreen.test.tsx && git commit -m "feat(chat): export-to-jots button with routed-destination toast"`

---

## Task 12: full verification + PR

- [ ] **Step 1:** `$WT/.venv/bin/pytest tests ghostbrain/api/tests -q` → no new failures vs the Task 0 baseline.
- [ ] **Step 2:** `cd $WT/desktop && npm test -- --run && npm run typecheck` → green.
- [ ] **Step 3: Live smoke** (sidecar from the worktree):

```bash
cd $WT && GHOSTBRAIN_SCHEDULER_ENABLED=0 .venv/bin/python -m ghostbrain.api  # note READY port/token
```

1. `POST /v1/projects {"context":"codeship","name":"Smoke Project","description":"smoke testing destination"}` → 200.
2. `POST /v1/notes {"body":"smoke note about the Smoke Project","route":true}` → expect it routed (LLM may or may not pick the project — both fine; assert no 500).
3. `POST /v1/notes/{id}/route {"context":"codeship","project":"smoke-project"}` → 200, path under `projects/smoke-project/`.
4. Create a chat conversation, send one real message, then `POST /v1/chat/{id}/export-jot` → 200 with a jot id; `GET /v1/notes?source=manual` shows it with `source: chat-summary` filtering intact.
5. Archive the project via PATCH; `GET /v1/projects` no longer lists it; re-route to it now 400s.
   Clean up: delete the smoke jots via `DELETE /v1/notes/{id}`, archive the smoke project.
- [ ] **Step 4:** Push branch, `gh pr create` to main (use the established PR body format), report for review. Do NOT merge without the user's go-ahead.

---

## Self-review

1. **Spec coverage:** registry+folders (T1), API (T2), dynamic router enum + prompt + degradation (T3), folders/frontmatter/list (T4), pipeline + manual route (T5), export endpoint + no-half-jot ordering (T6), hooks/types (T7), settings UI (T8), tree (T9), re-route picker (T10), export button (T11), verification (T12). Spec deviations flagged inline: 400 vs 422 on bad manual-route project; inline name-edit optional; toast has no open-jot affordance.
2. **Type consistency:** `RoutingDecision.project`, `move_jot(to_project=)`, `list_jots(project=)`, `useRouteJot({project})`, `Project`/`CreateProjectRequest`/`UpdateProjectRequest`/`ChatExportResponse` used consistently across tasks.
3. **Known judgment calls for the executor:** exact `SECTIONS`/`SectionId` shape in settings.tsx; `JotListItem` fixture fields in JotTree tests; the existing `_route_via_llm` validation tail; the potential `projects → notes_manual → router` import cycle (Task 3 step 3.2 gives the fix: function-level import of `make_slug` in projects.py).
