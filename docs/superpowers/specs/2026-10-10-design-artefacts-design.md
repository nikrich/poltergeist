# Design artefacts — existing codebases + Artefacts tab

**Date:** 2026-10-10
**Builds on:** `2026-10-10-live-design-session-design.md`
**Status:** design agreed in conversation; spec awaiting review.

## Goal

Everything a live design session produces is an **artefact**: a working demo
linked back to the meeting it came from. An artefact is one of:

- **Scratch prototype** — a standalone folder in the vault, bundled by the
  built-in esbuild bundler (today's behaviour). Used when no codebase is named,
  or when the named one can't be found.
- **Worktree** — a git worktree of an existing frontend ("today we're working
  on Orbit, use our existing frontend and let's extend it"), running that app's
  own dev server with the backend mocked out.
- **Board** — the event-storming board (+ architecture view) of the session.

A new **Artefacts** tab lists them, linked to their meetings, with a live
preview.

## What the user said

- Find the repo by searching a code folder; repos can be nested (no per-project
  setup required).
- Preview runs the repo's own dev server; the agent must make it run **without
  the backend** (no spinning up services).
- Sibling git worktree on a local branch, never pushed.
- Working against no repo at all must keep working (scratch).

## 1. Picking the codebase

**Command detection.** `commands.detect` gains a `codebase` field:
`{"command", "canvas", "text", "codebase": str|null}`. `codebase` is the spoken
hint ("Orbit frontend", "the claims portal") when the speaker asks to build on an
existing solution, else null. Applies to `start_ui` only.

**Repo discovery (`ghostbrain/design/codebases.py`).**
- Setting `design.code_roots` (list, default `["~/development"]`), editable in
  Settings → Design.
- `scan(roots)` walks up to depth 5, recording directories that contain a
  `.git` **directory** (main checkouts; `.git` files = worktrees are skipped).
  Prunes `node_modules`, `.git`, `dist`, `build`, `.next`, `target`, `.venv`,
  hidden dirs, and anything named `*-poltergeist-*`. Does not descend into a
  found repo. Results cached for 10 min.
- Each candidate gets cheap facts: relative path, `package.json` name, whether
  it has a frontend dependency (react, next, vue, svelte, angular, vite).
- `resolve(hint, candidates)`: score by token overlap of the hint against path
  segments / package name (case-insensitive, `fe`↔`frontend` synonyms); when
  more than one candidate scores, a `fast`-tier LLM call picks one given the
  hint + the top 15 candidates (or "none"). Frontend repos win ties when the
  hint mentions frontend/UI. Returns `{path, name, confidence}` or None.

**Outcome.**
- Match → the UI canvas starts in **worktree mode** with toast
  "Using orbit-web · Undo · Change".
- No match → scratch with toast "Couldn't find 'Orbit' — using a scratch
  prototype · Choose repo".
- The panel header gets a **Codebase** picker (Scratch | search repos), usable
  before the first rev; switching after rev 0 asks for confirmation and starts a
  fresh artefact.

## 2. Worktree artefacts

**Create (`ghostbrain/design/worktree.py`).**
- Default branch: `git symbolic-ref refs/remotes/origin/HEAD`, else `main`/`master`,
  else current HEAD. Base = `origin/<default>` when it exists (after a
  `git fetch origin <default>` with 20 s timeout, failure tolerated), else local.
- Path: sibling of the repo, `<repo>-poltergeist-<YYYY-MM-DD>-<slug>`; branch
  `poltergeist/<YYYY-MM-DD>-<slug>`; `-2`, `-3`… on collision.
- `git worktree add -b <branch> <path> <base>`. Never pushes.
- Each rev = one commit on that branch (`rev N: <summary>`); revert = new
  commit restoring rev N's tree, same as scratch.

**Install.** Package manager from lockfile (`pnpm-lock.yaml` → pnpm,
`yarn.lock` → yarn, else npm). `npm ci`/`pnpm install --frozen-lockfile`/
`yarn install --frozen-lockfile` in the worktree root (or the app subfolder,
see below), streamed to `.poltergeist/install.log`, 10 min timeout. Canvas shows
"Installing dependencies…". Failure → canvas `unavailable` with the log tail.
Nested apps: the app dir is the repo root, or the single workspace package with
a frontend dependency + `dev` script when the root has none.

**Bootstrap run (offline mode).** The first agent run in a worktree has a fixed
task before any meeting content: make the app start and render its main screens
with **no backend**:
- mock network calls (MSW if the app already uses it or it fits, else the app's
  own API/fetch layer) with plausible mock data;
- stub auth so screens behind login render;
- gate all of it behind `POLTERGEIST_OFFLINE=1` / `VITE_POLTERGEIST_OFFLINE` /
  `NEXT_PUBLIC_POLTERGEIST_OFFLINE` (whichever the stack reads) so the real app
  is unchanged without the flag;
- write `.poltergeist/run.json`:
  `{"cwd": ".", "command": ["npm","run","dev"], "env": {...}, "port_env": "PORT",
  "url_path": "/"}`.
The agent may edit any file in the worktree except `.git`; still no Bash. It
may add a dev dependency only by editing `package.json` — Poltergeist re-runs
install when `package.json`/lockfile changed after a rev.

**Dev server (desktop main, `design-devserver.ts`).**
- Starts `run.json`'s command with a free port (passed via `port_env` and
  `--port` when the script is vite), env + offline flags, cwd in the worktree.
- Ready when the URL answers HTTP (poll 500 ms, 120 s timeout) or stdout prints
  a `http://localhost:<port>` URL (port taken from it).
- One server per worktree, kept alive while the panel, pop-out or Artefacts
  preview shows it; stopped 60 s after the last viewer, and on app quit
  (process-group kill).
- After each rev: the server's HMR picks it up; the frame reloads only when the
  server reports a full reload is needed (we just reload the hidden buffer
  iframe and swap on load — same double-buffer as scratch).
- Compile errors (stderr lines matching error patterns, or the page posting
  `gb-proto:error`) and server exit → `/session/build-error` → fix run (max 2),
  same loop as scratch bundle errors. Server exit restarts it once.
- The frame is `http://localhost:<port>`: renderer CSP `frame-src` adds
  `http://localhost:*` `http://127.0.0.1:*`; the navigation guard allows frames
  on localhost and blocks navigation from them to anything else; permission
  handler denies media/etc. to localhost frames.
- Scroll/route restore uses the same `gb-proto:*` postMessage protocol through
  a tiny script the bootstrap run adds to the app's entry (gated by the offline
  flag); without it, swaps still work, just without scroll restore.

## 3. Artefacts in the vault + meeting links

**Artefact note.** Every session's artefact has a note with frontmatter
`type: artefact`, `kind: prototype|worktree|board`, `meeting`, `meeting_path`,
`date`, `context`, `project`, `design_system`, `revs`, and for worktrees `repo`,
`worktree`, `branch`, `base`.
- Scratch / board: the folder's `README.md` (today's index note, extended).
- Worktree: `20-contexts/<ctx>/[projects/<slug>/]artefacts/<date>-<slug>.md`
  (the session's `board.json`, `session.jsonl` live beside it in
  `…/artefacts/<date>-<slug>/`; the code lives in the worktree).
- A session with both a UI artefact and a board writes one note covering both
  (kind = the UI kind; `board: true`).

**Naming.** When the recording has no title at start, the folder/branch slug
uses `meeting-<HHMM>`; once the meeting note exists, the note title (and
`meeting:`) is updated to the real meeting title. Folders/branches are not
renamed after creation.

**Meeting link (both ways).** A recorder hook `on_transcribed(wav, note_path)`
fires after the meeting note is written (manual and calendar recordings). The
design module then:
- sets `meeting: "[[<note>]]"`, `meeting_path`, and the title on the artefact note;
- appends an `## Artefacts` section to the meeting note (or a line to it) with
  `- [[<artefact note>|<title>]] — <kind>, rev N` and adds
  `artefacts: [<artefact note path>]` to its frontmatter.
Idempotent; failures are logged, never raised into transcription.

## 4. Artefacts tab

New sidebar entry **artefacts** (icon `layers`) → `screens/artefacts.tsx`.

- **List** (left): grouped by date, newest first; row = title, kind icon,
  context/project, repo + branch (worktree), latest rev, meeting link. Filter by
  context and kind. Source: `GET /v1/design/artefacts` (scans `type: artefact`
  notes under `20-contexts/**/{prototypes,artefacts}/`).
- **Detail** (right): header with meeting link (opens the meeting note), actions
  **Open in editor** (`code`/default app on the folder or worktree), **Reveal in
  Finder**, **Pop out**, **Eject** (scratch), **Remove worktree** (confirm;
  `git worktree remove` + delete branch only if merged, else keep the branch and
  say so).
- **Preview**: scratch → `gbproto://` bundle (protocol now serves any artefact
  folder under the vault's prototype/artefact dirs, still path-checked);
  worktree → starts its dev server on demand ("Starting…"); board → the board
  view + architecture toggle. Rev list with ◀ ▶ (read-only checkout of old revs
  for scratch; for worktrees, shows the rev summary and diffstat — no checkout).
- Meeting notes opened in the app show their Artefacts section as normal links.

## REST additions (`/v1/design`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/codebases?q=` | scanned repos (for the picker), filtered by query |
| POST | `/session/codebase` | `{path \| null}` switch UI canvas to a repo / scratch |
| GET | `/artefacts` | list artefact notes |
| GET | `/artefacts/{id}` | one artefact (note fields + revs + board) |
| POST | `/artefacts/{id}/remove-worktree` | remove the worktree |
| POST | `/artefacts/{id}/eject` | eject a scratch prototype |

Snapshot (`DesignSessionSnapshot`) gains `ui_kind: 'scratch' | 'worktree'`,
`codebase: {path, name, branch, worktree} | null`, `install: 'idle' | 'running' |
'failed'`. Main IPC gains `gb:design:devserver:{ensure,release}` returning
`{ok, url} | {ok:false, error}` and `gb:design:open-path`.

## Error handling

- Discovery, worktree creation, install and dev-server failures never affect
  recording; they put the UI canvas in `unavailable` with a reason and a
  "Use scratch instead" action.
- A dirty main checkout is irrelevant (worktree is off the base ref).
- The agent never runs commands; installs and servers are run by Poltergeist
  with fixed argv (no shell), cwd confined to the worktree.

## Testing

- Python: scan (nesting, pruning, worktree-skip, cache), resolve (scoring,
  LLM tie-break via fake, none), detect `codebase` field, worktree create/commit/
  revert/remove on a real temp git repo with a fake origin, install command
  selection, bootstrap-run prompt, artefact note write + meeting link hook
  (idempotent), artefacts routes.
- Desktop: devserver (fake script printing a URL; ready detection; idle stop;
  restart once; error forwarding), protocol serving any artefact dir + guard,
  nav guard for localhost frames, Artefacts screen (list, detail, actions),
  panel codebase picker + toasts.
- Live smoke: scratch session end-to-end again; worktree session against a small
  local Vite fixture repo with a fake backend call; then a real try against
  `orbit-web` (report what the offline bootstrap did).

## Out of scope (v1)

Continuing an artefact in a later meeting, backend repos as artefacts, pushing
or PRs from the app, non-JS frontends, Windows QA of worktree dev servers.
