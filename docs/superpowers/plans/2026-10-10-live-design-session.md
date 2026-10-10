# Live design session — implementation plan

Spec: `docs/superpowers/specs/2026-10-10-live-design-session-design.md`
Wire contract (source of truth for shapes): `desktop/src/shared/design-types.ts`
Worktree: `/Users/jannik/development/nikrich/ghost-brain-live-design` (branch `feat/live-design-session`)

Four parallel workstreams with disjoint file ownership. Every workstream is
test-first (write the failing test, see it fail, implement, see it pass).
Workstreams do **not** commit; the coordinator commits.

## Python interfaces shared between workstreams A and B

```python
# ghostbrain/design/packs.py   (owned by A)
BUILTIN_PACK_ID = "poltergeist-neutral"
def library_dir() -> Path                       # <vault>/90-meta/design-systems
def list_packs() -> list[dict]                  # DesignPack dicts, builtin first
def get_pack(pack_id: str) -> dict | None
def pack_dir(pack_id: str) -> Path              # raises KeyError when unknown
def copy_into(pack_id: str, dest: Path) -> None # replaces dest/ with the pack files
def delete_pack(pack_id: str) -> None           # ValueError for builtin
def start_import(source: str, name: str | None = None) -> dict   # job dict, runs in a thread
def get_import(job_id: str) -> dict | None

# ghostbrain/design/scaffold.py (owned by A)
def create(prototype_dir: Path, pack_id: str, *, title: str) -> None  # src/ + design-pack/ + git init + rev 0 commit
def commit(prototype_dir: Path, message: str) -> str                  # returns short sha
def revert_to(prototype_dir: Path, rev: int) -> None                  # restores the files of "rev N" commit as a new commit
def eject(prototype_dir: Path) -> Path                                # writes package.json, vite.config.ts, index.html; returns dir

# ghostbrain/design/settings.py (owned by A)
def load() -> dict           # {"listen": True, "budget_usd": 2.0, "default_pack": BUILTIN_PACK_ID}, from config.yaml `design:`
def update(**fields) -> dict
```

Project registry (A): `design_system: str | None` on `Project`,
`UpdateProjectRequest`, `update_project(...)` persists it.

## Workstream A — sidecar: packs, scaffold, settings, project field, pack routes

Files: `ghostbrain/design/{__init__,packs,scaffold,settings}.py`,
`ghostbrain/design/builtin/poltergeist-neutral/{pack.json,tokens.css,README.md}`,
`ghostbrain/design/scaffold_template/src/{main.tsx,App.tsx,router.tsx,data.ts,styles.css}`,
`ghostbrain/api/routes/design_packs.py` (`/v1/design/packs*`, `/v1/design/settings`),
`ghostbrain/api/models/project.py`, `ghostbrain/api/repo/projects.py`,
`ghostbrain/api/routes/projects.py`, register router in `ghostbrain/api/main.py`
(only add the `design_packs` include line; B adds its own line), packaging data
files (`pyproject.toml` package-data / PyInstaller spec if templates need it),
tests `tests/test_design_packs.py`, `tests/test_design_scaffold.py`,
`ghostbrain/api/tests/test_design_packs_routes.py`, project route test additions.

## Workstream B — sidecar: session loop, commands, relevance, agents, live routes

Files: `ghostbrain/design/{commands,relevance,session,ui_agent,board_agent,listener}.py`,
`ghostbrain/api/models/design.py`, `ghostbrain/api/routes/design.py`
(`/v1/design/live`, `/v1/design/session*`), one include line in `api/main.py`,
hook to start the listener when live transcription begins (recorder/live.py
`begin` or the `/v1/recorder/live` route — must never raise into recording),
tests `tests/test_design_{commands,relevance,session,agents}.py`,
`ghostbrain/api/tests/test_design_routes.py`.

## Workstream C — desktop main: bundler, gbproto://, IPC, pop-out

Files: `desktop/src/main/design-bundler.ts`, `desktop/src/main/design-protocol.ts`,
`desktop/src/main/design-popout.ts`, IPC wiring in `desktop/src/main/index.ts`
(`gb:design:live:subscribe|unsubscribe` via `startRecorderStream` on
`/v1/design/live` forwarding to `gb:design:live:event`, `gb:design:build`,
`gb:design:popout`), `esbuild-wasm` dependency + electron-builder asarUnpack if
needed, tests under `desktop/src/main/__tests__/design-*.test.ts`.
Preload + `GbBridge` typing are already done.

## Workstream D — renderer: store, panel, board, pop-out route, settings

Files: `desktop/src/renderer/stores/design-session.ts`,
`desktop/src/renderer/components/design/*` (DesignPanel, PrototypeFrame,
EventStormBoard, ArchitectureView, DesignToast, PackPicker),
`desktop/src/renderer/screens/design-popout.tsx` + route wiring in `App.tsx`,
mount `DesignPanel` in `screens/meetings.tsx` next to `LiveTranscriptPanel`,
Design section in `screens/settings.tsx` (+ project design-system select),
api hooks in `lib/api/hooks.ts`, tests in `desktop/src/renderer/__tests__/`.

## Final integration (coordinator)

1. `pytest` (full), `cd desktop && npm run typecheck && npm test && npm run lint`.
2. Live smoke in dev app with a scripted transcript (see spec Testing).
3. Commit per workstream, push branch, open PR.
