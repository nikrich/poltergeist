# One-Click Install — Design

**Date:** 2026-07-14
**Status:** Approved (pending spec review)

## Problem

Installing Poltergeist on a machine that isn't Jannik's currently requires, beyond the
desktop installer: a Python 3.11 venv, `pip install` of the `ghostbrain` package,
running `ghostbrain-bootstrap`, and using per-connector `ghostbrain-*` CLIs. The
desktop artifact (DMG/exe/AppImage) already bundles a PyInstaller sidecar containing
nearly the whole Python package, but:

1. Nothing creates the vault on first launch — the packaged app points at a vault
   that doesn't exist.
2. The frozen binary exposes only the HTTP server and an `mcp` subcommand — none of
   the `ghostbrain-*` CLI entry points, so connector setup still requires pip.
3. The user's four personal contexts (`sanlam`, `codeship`, `reducedrecipes`,
   `personal`) are hardcoded in six modules, so another user's vault is seeded with
   them and — worse — the LLM router's JSON-schema enum makes any other context
   unroutable, and the notes API rejects other contexts outright.

**Goal:** download installer → open app → backend fully works. No pip, no venv, no
terminal required for core use. Vault shape belongs to the user, not to Jannik.

**Out of scope (explicitly):** in-app connector auth UI (connectors stay CLI-driven,
now via the bundled binary); hosted OAuth broker; auto-installing the `claude` CLI
(detection/guidance already exists); Windows/Linux PATH shim.

## Design

### 1. First-run vault bootstrap (in the sidecar)

In `ghostbrain/api/__main__.py::main()`, after the `mcp` argv dispatch and before the
lazy app-stack import:

- Resolve `ghostbrain.paths.vault_path()` (same resolution the API and bootstrap
  already share: `$VAULT_PATH` or `~/ghostbrain/vault`).
- If `<vault>/90-meta/routing.yaml` does not exist, call
  `ghostbrain.bootstrap.bootstrap()` (already idempotent) and log one line.
- Wrap in try/except that logs the failure and continues serving. Rationale: the
  Electron `sidecar.ts` auto-respawns on exit, so a hard failure here would
  crash-loop; a degraded-but-up API surfaces the error visibly in the app instead.

Extract the check into an `ensure_vault()` helper so it is unit-testable without
booting uvicorn. Same code path in dev (`python -m ghostbrain.api`) and frozen
builds; all three platforms get it for free.

### 2. CLI multiplexer (the bundled binary becomes the CLI)

Extend the existing `argv[0] == "mcp"` dispatch in `ghostbrain/api/__main__.py` into
a busybox-style table mapping every `[project.scripts]` entry in `pyproject.toml` to
its `main()`, minus the `ghostbrain-` prefix:

```
ghostbrain-api bootstrap
ghostbrain-api gmail-auth <email>
ghostbrain-api slack-token-add <slug> <xoxp>
ghostbrain-api github-fetch --dry-run
ghostbrain-api worker
...
```

- All imports lazy (inside the dispatch branch) so server startup cost is unchanged.
- Remaining argv is passed through by shifting `sys.argv` before calling the target
  `main()` (the entry points read `sys.argv` themselves today).
- Unknown subcommand → print the available subcommand list, exit non-zero.
- **Drift guard:** a unit test parses `pyproject.toml` and asserts every
  `ghostbrain-*` console script has a dispatch entry (and vice versa).

### 3. PyInstaller spec: bundle the whole package

Replace the piecemeal `collect_submodules('ghostbrain.connectors' / .worker /
.recorder / .profile / .mcp)` lines in `packaging/sidecar.spec` with
`collect_submodules('ghostbrain')` so `bootstrap`, `metrics`, `semantic`, and any
future module ship automatically. Keep the third-party collect lines as they are.

### 4. macOS PATH shim (optional, last slice)

A Settings action "Install command line tool" (VS Code-style) in the desktop app:

- Writes a tiny `poltergeist` wrapper script that `exec`s the bundled
  `<resourcesPath>/sidecar/ghostbrain-api "$@"`.
- Symlinks it into `/usr/local/bin` if writable, else `~/.local/bin` (telling the
  user which, and whether it's on their PATH).
- macOS only for this iteration. Windows/Linux: documented as invoking the binary in
  the install directory directly.

### 5. Contexts as configuration

The context *list* becomes data with a single source of truth in `routing.yaml`:

- New top-level key in `routing.yaml`:

  ```yaml
  contexts:
    - personal
    - work
  ```

- One accessor — `contexts()` in a new `ghostbrain/routing_config.py` — returns the
  configured list. A new neutral module because the two existing routing.yaml
  loaders are scope-local duplicates (`connectors/_runner.py:load_routing()` and the
  worker's private `_load_yaml`); both API routes and worker/metrics modules can
  import the new one without dependency cycles. (Consolidating the duplicate loaders
  themselves is out of scope.)
- All six hardcoded sites switch to it:

  | Site | Change |
  |---|---|
  | `bootstrap.py:16 CONTEXTS` | seeds folders from configured/default list |
  | `worker/router.py:38` router JSON-schema enum | built at runtime: configured list + `needs_review` |
  | `api/routes/notes.py:37 _KNOWN_CONTEXTS` | validates against configured list |
  | `worker/digest.py:35` | iterates configured list |
  | `worker/weekly_digest.py:41` | iterates configured list |
  | `metrics/anticipation.py:37` | iterates configured list |

- **New vaults:** bootstrap seeds a neutral default — `personal`, `work` — writing
  both the `contexts:` key and the matching `20-contexts/<ctx>/` folders.
- **Back-compat (existing vault):** if `contexts:` is absent from `routing.yaml`,
  the accessor falls back to the legacy four (`sanlam`, `codeship`,
  `reducedrecipes`, `personal`) and logs a hint once. The startup path never
  rewrites an existing routing.yaml (first-run bootstrap only fires when the file
  is missing), so the fallback persists until the user adds the key — or runs
  `ghostbrain-bootstrap` / `ghostbrain-api bootstrap` manually, which (being
  idempotent) writes the in-effect list into `routing.yaml` without touching
  anything else. Behavior for the existing vault is unchanged until the list is
  edited.
- The legacy tuple lives in exactly one place (the accessor's fallback). A unit test
  asserts the literal context names appear nowhere else in `ghostbrain/` (grep-style
  over the package source, excluding tests/fixtures).
- Editing `contexts:` takes effect the way other routing.yaml edits do (read at
  load; no live-reload work in this iteration).

## Resulting first-run experience

1. Download `Poltergeist-<v>.dmg` (or exe/AppImage) from GitHub Releases; install; open.
2. Sidecar starts → vault missing → bootstrap runs → vault exists with neutral
   contexts. Notes, search, jots, recorder, scheduler all live.
3. Claude CLI missing → existing guided detection points the user at installing
   Claude Code; everything non-LLM already works.
4. Connectors, whenever wanted: run the bundled `ghostbrain-api <connector>-auth` /
   edit `routing.yaml` — via the PATH shim on macOS, no Python install ever.

## Error handling

- Bootstrap failure at startup: logged, server still comes up; app shows its normal
  "vault unavailable/empty" surfaces rather than a crash-looping sidecar.
- CLI subcommand failures behave exactly as the pip-installed CLIs do today (they
  own their argv parsing and exit codes).
- Empty or invalid `contexts:` (not a list / empty list): accessor treats it as
  absent → legacy fallback, with a logged warning naming the file.

## Testing

- **Unit:** `ensure_vault()` against a tmp `VAULT_PATH` (creates when missing, no-op
  when present, survives bootstrap raising); dispatch-table ↔ `pyproject.toml`
  parity; `contexts()` accessor (configured / absent / invalid); router schema enum
  reflects configured contexts; notes API accepts configured + rejects unknown;
  hardcoded-name grep test.
- **Integration (dev):** `python -m ghostbrain.api bootstrap` and a couple of
  representative subcommands (`github-fetch --dry-run`) round-trip through the
  multiplexer.
- **Manual (packaged):** `npm run pack:unsigned`, launch with a clean temp
  `VAULT_PATH`, confirm first-launch bootstrap, neutral contexts, and
  `ghostbrain-api bootstrap`/`--help` from the bundled binary. Existing vault on
  this machine boots unchanged.

## Slices (implementation order)

1. Contexts as configuration (§5) — pure Python, unblocks everything user-shaped.
2. `ensure_vault()` first-run bootstrap (§1) + spec-wide `collect_submodules` (§3).
3. CLI multiplexer + parity test (§2).
4. macOS PATH shim in desktop Settings (§4) — optional, last.
