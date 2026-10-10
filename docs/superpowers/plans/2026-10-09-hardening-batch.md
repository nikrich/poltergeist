# Hardening Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five hardening items: the flaky Linux release smoke test, orphaned sidecars, the misleading whisper-model hint, conflict-text loss on navigation, and stale backlinks.

**Architecture:** Independent fixes across the Python sidecar (`ghostbrain/`), the release smoke script (`scripts/`), and the Electron/React desktop (`desktop/`). Each task is self-contained with its own tests and commit(s).

**Tech Stack:** Python 3.11, FastAPI/uvicorn, mcp 1.x, pytest; Electron, React, TanStack Query, vitest + RTL.

**Spec:** The controller's task brief (5 items) — reproduced in each task's "Requirement" line. No separate spec document.

## Global Constraints

- EVERY shell command starts with `cd <repo> && `. Verify `git branch --show-current` == `fix/hardening-batch` and `git rev-parse --show-toplevel` == `<repo>` before every commit. Never touch `<main checkout>` or any other `ghost-brain-*` worktree.
- Never push, open PRs or merge.
- Never read/write `~/ghostbrain`, `~/.ghostbrain` or the vault; never launch the app. Tests must sandbox HOME / `GHOSTBRAIN_STATE_DIR` / `VAULT_PATH` (tmp_path).
- Before ANY pytest run: `pgrep -x ghostbrain-capture` — if it prints a pid, wait 5 min and re-check.
- Python gate: `.venv/bin/python -m pytest -p no:cacheprovider --timeout 120 <paths>`. Desktop gates (in `desktop/`): `npm run typecheck`, `npx vitest run <files>`, `npm run lint`. Capture exit codes by redirecting output to a file and echoing `$?` — never pipe to tail.
- Desktop tests run on windows-2022 in release builds: any POSIX-only assertion goes under `describe.skipIf(process.platform === 'win32')`. Python POSIX-only tests use `pytest.mark.skipif(sys.platform == "win32", ...)`.
- No real people's or employer names in any committed text.
- Conventional commits ending with the line `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Pre-existing failures to ignore: test_agent_stream unknown_tool, test_calendar jxa, test_joplin_connector (2), test_mcp_integration bad_token, test_mcp_tools (2 search), test_recorder_api_platform_guard win32, test_weekly_digest wikilinks; openai_http_chat cancel test is flaky.

## Review Focus

- Task 1: the fix must hold for both the frozen binary and `python -m ghostbrain.api mcp`; a smoke failure must print the binary's stderr so the next flake is diagnosable.
- Task 2: a sidecar whose parent died mid-recording must stop capture via the normal recorder stop path (SIGINT to capture, manual.state updated) — not be hard-killed before shutdown hooks run.
- Task 2: running `python -m ghostbrain.api` from a terminal (no Electron parent, stdin a TTY or /dev/null) must NOT self-terminate.
- Task 5: the discard confirm must not fire when no conflict is pending (plain navigation stays frictionless), and cancelling the confirm must keep both the route and the paused text.
- Task 6: invalidation must cover the backlinks of every affected note (prefix key `['vault','backlinks']`), not just the path of the mutated note.

---

### Task 1: Release smoke-test flake — MCP tools/list returns `[]` on Linux

**Requirement:** v1.11.0 rescue build (run 37971895211, job build-linux) failed `scripts/smoke-sidecar.py` with "mcp tools/list missing tools: got []" while the first build (run 37964652055) passed. Find the root cause, fix it (pins with justification and/or code), test if code.

**Controller pre-investigation (verify, don't trust):** Both runs checked out tag `v1.11.0` and their `Successfully installed …` pip lines are byte-identical (mcp 1.30.0, pydantic 2.14.0, anyio 4.15.1, starlette 1.7.0 …). So dependency drift is NOT the cause. Hypothesis: `check_mcp_handshake` writes initialize + initialized + tools/list and then closes stdin immediately (`communicate(input=…)`). On stdin EOF the mcp stdio server's read stream closes and the server task group is torn down, cancelling the still-in-flight tools/list handler — so the id=2 response is never written and `tools` stays `[]`. Timing-dependent → flaky.

**Files:**
- Modify: `scripts/smoke-sidecar.py`
- Possibly modify: `ghostbrain/mcp/__main__.py` (only if the investigation shows the server itself should drain in-flight requests on EOF)
- Test: `tests/test_smoke_sidecar.py` (new) if any code changes

- [ ] **Step 1: Confirm the deps finding.** `gh run view 37964652055 --log --job 113936719777` vs `gh run view 37971895211 --log --job 113960351269`; diff the `Successfully installed` lines. Record the result in the report.
- [ ] **Step 2: Reproduce the race.** Loop the exact smoke handshake (write all three messages then close stdin) against `.venv/bin/python -m ghostbrain.api mcp` with sandboxed env (HOME/GHOSTBRAIN_STATE_DIR/VAULT_PATH in a tmp dir), ~200 iterations, count runs with no id=2 response. If it doesn't reproduce locally, try in Docker `python:3.11` (install `.[api]`, Linux like CI), optionally with CPU constraint (`--cpus 0.5`). Record counts.
- [ ] **Step 3: Write failing test** in `tests/test_smoke_sidecar.py`: import the smoke module via `importlib` (it's a script), run `check_mcp_handshake` against a stub "binary" (a small Python script written to tmp_path, made executable, POSIX-only skip on win32) that answers initialize immediately but answers tools/list only after a short delay AND exits on stdin EOF without answering pending requests — mimicking the race. Current script fails it; fixed script passes.
- [ ] **Step 4: Fix `check_mcp_handshake`:** send initialize, read stdout line-by-line until the id=1 response, send `notifications/initialized` + tools/list, read until the id=2 response (with an overall deadline, e.g. 120s, using a reader thread or `select`-free approach portable to Windows — e.g. a background thread draining stdout into a `queue.Queue`), THEN close stdin and wait. On any failure include the binary's stderr tail in the message (the CI failure printed none). Keep the "initialize got no result" / "missing tools" messages.
- [ ] **Step 5: Verify:** re-run the Step 2 loop with the new handshake logic (0 failures expected) and run the new test + `tests/` paths touching mcp.
- [ ] **Step 6: Pins:** only add upper bounds in `pyproject.toml` if Step 1/2 show a version-dependent behaviour; otherwise add none and say so in the report.
- [ ] **Step 7: Commit** `fix(release): make sidecar MCP smoke handshake wait for responses before closing stdin`.

---

### Task 2: Sidecar exits when its parent goes away (Python side)

**Requirement:** The dev sidecar outlives the Electron app (orphaned, ppid 1); once it ignored SIGTERM and only exited on SIGINT. Make the sidecar shut down when its parent disappears however the app dies, while a live recording still stops cleanly (SIGINT to capture, manual.state consistent for next-start recovery). Test parent-death detection with a subprocess test.

**Files:**
- Modify: `ghostbrain/api/__main__.py` (`_run_api_server`, `_uvicorn_kwargs`)
- Create: `ghostbrain/api/parent_watch.py`
- Test: `ghostbrain/api/tests/test_parent_watch.py` (new) — follow existing test locations

**Interfaces:**
- Produces: env var contract `GHOSTBRAIN_PARENT_WATCH=1` — when set, the sidecar treats stdin EOF (and, on POSIX, `os.getppid()` changing from its startup value) as "parent gone". Task 3 sets this env var and keeps stdin as a pipe.
- Produces: `parent_watch.start(on_parent_gone: Callable[[], None], *, poll_s: float = 1.0) -> threading.Thread | None` — daemon thread; returns None when the env var is unset.

- [ ] **Step 1: Root-cause the "ignored SIGTERM".** Read `_run_api_server` and the shutdown hooks (`_stop_scheduler`, `_reap_chat_turns`, `live.stop_all`), scheduler `stop()` and the recorder's stop path. Determine why SIGTERM would not exit (candidates: uvicorn graceful shutdown waiting forever on open streaming/SSE/keep-alive connections because `timeout_graceful_shutdown` is unset; a shutdown hook blocking; a non-daemon thread). Reproduce if feasible with a sandboxed sidecar + an open streaming request, then SIGTERM. Record findings.
- [ ] **Step 2: Write failing subprocess tests** (`skipif win32` where POSIX signals are used): spawn an intermediate "parent" Python process that spawns `python -m ghostbrain.api` with sandboxed HOME/GHOSTBRAIN_STATE_DIR/VAULT_PATH, `GHOSTBRAIN_SCHEDULER_ENABLED=0`, `GHOSTBRAIN_PARENT_WATCH=1`, stdin=PIPE, waits for READY, prints the child pid, then the test SIGKILLs the parent → assert the child exits within ~15s. Second test: without `GHOSTBRAIN_PARENT_WATCH`, stdin=DEVNULL → child still alive after a few seconds (then cleaned up). Third (unit): `parent_watch.start` calls the callback once when stdin hits EOF (feed a pipe, close it).
- [ ] **Step 3: Implement `parent_watch.py`** and wire it in `_run_api_server`: switch `uvicorn.run(...)` to `server = uvicorn.Server(uvicorn.Config(**kwargs)); server.run()` and have the callback set `server.should_exit = True` (graceful: shutdown hooks run, so `live.stop_all()` / scheduler stop end any recording through their normal path). Add a bounded `timeout_graceful_shutdown` (justify value in a comment) so open connections can't stall exit forever. Add a last-resort watchdog: if the process is still alive N seconds after parent-gone (N comfortably longer than the recorder's capture-stop timeout — find that value), `os._exit(1)`. Log each stage.
- [ ] **Step 4: Recording safety test:** unit-test (with monkeypatched recorder/live stop functions) that the parent-gone path invokes the normal shutdown hooks (i.e. goes through `should_exit`, not `os._exit`) — or document in the report precisely which existing tests cover recorder stop on shutdown.
- [ ] **Step 5: Run** the new tests + `ghostbrain/api/tests` + recorder tests.
- [ ] **Step 6: Commit** `fix(sidecar): shut down gracefully when the parent app goes away`.

---

### Task 3: Desktop stop() signals correctly and escalates

**Requirement:** main's stop sends the right signal and escalates; the sidecar is told to watch its parent.

**Files:**
- Modify: `desktop/src/main/sidecar.ts`
- Test: `desktop/src/main/__tests__/sidecar.test.ts` (extend or create, mocking `node:child_process` + `electron`)

**Interfaces:**
- Consumes: `GHOSTBRAIN_PARENT_WATCH=1` env contract and stdin-EOF semantics from Task 2.

Known defect to verify: `stop()` escalates only `if (proc && !proc.killed)`, but `ChildProcess.killed` becomes true as soon as `kill('SIGTERM')` *sends* the signal, so the SIGKILL escalation is dead code.

- [ ] **Step 1: Failing tests:** (a) `buildSidecarEnv` (or the spawn env) includes `GHOSTBRAIN_PARENT_WATCH: '1'`; (b) spawn keeps stdin as a pipe; (c) `stop()` sends SIGTERM, and if no exit after the grace period, escalates (use fake timers) — the escalation must check `proc.exitCode === null && proc.signalCode === null`, not `proc.killed`. Choose the escalation ladder from Task 2's findings: SIGTERM → (grace ≥ sidecar's graceful-shutdown budget so a recording can stop) → SIGINT (uvicorn force-exit on second signal) → SIGKILL. Document chosen timings in a comment. On win32 `kill()` signals are all hard-terminate — keep behaviour sane there (skip POSIX-specific assertions on win32).
- [ ] **Step 2: Implement**, then also close the child's stdin in `stop()` after sending SIGTERM (belt-and-braces with the parent watch).
- [ ] **Step 3: Gates:** `npm run typecheck`, `npx vitest run src/main/__tests__/sidecar.test.ts`, `npm run lint` (exit codes to files).
- [ ] **Step 4: Commit** `fix(desktop): escalate sidecar stop and enable parent watch`.

---

### Task 4: Name a pinned whisper model in settings and doctor

**Requirement:** `GHOSTBRAIN_WHISPER_MODEL` (from env / `~/.ghostbrain/.env` loaded in `ghostbrain/__init__.py`) overrides the model; when it pins an English-only `.en` model the settings hint says "run poltergeist setup fetch-model", which does nothing. Expose the source (`env` vs `default`) and make both the settings hint and doctor `whisper-model` say the model is pinned by `GHOSTBRAIN_WHISPER_MODEL` and how to change it.

**Files:**
- Modify: `ghostbrain/api/models/settings.py` (`RecorderSettings`: add `transcription_model_source: Literal["env", "default"] = "default"`)
- Modify: `ghostbrain/api/repo/settings.py` (`_transcription_model` → also return source)
- Modify: `ghostbrain/doctor/checks_recorder.py` (`whisper-model` check)
- Modify: desktop API types for RecorderSettings (find with grep `multilingual_model` in `desktop/src`), `desktop/src/renderer/screens/settings.tsx` (transcription language row hint)
- Tests: existing settings repo/API tests, doctor recorder tests, `desktop/src/renderer/__tests__/` settings test (grep for an existing settings-screen test touching `multilingual_model`)

- [ ] **Step 1:** Read how the model path is resolved (grep `GHOSTBRAIN_WHISPER_MODEL`) — source is `env` iff that variable is set non-empty and is what resolution used.
- [ ] **Step 2: Failing Python tests:** with `monkeypatch.setenv("GHOSTBRAIN_WHISPER_MODEL", <tmp>/ggml-base.en.bin)` the recorder settings report `transcription_model_source == "env"` and `multilingual_model is False`; unset → `"default"`. Doctor check with the env pin to an `.en` model: message names `GHOSTBRAIN_WHISPER_MODEL`, says to unset it or point it at a multilingual model (and where it may be set: environment or `~/.ghostbrain/.env`), and does NOT suggest `setup fetch-model` as the fix.
- [ ] **Step 3: Implement** Python side.
- [ ] **Step 4: Failing desktop test:** settings screen with `transcription_model_source: 'env'` and an English-only model shows a hint mentioning `GHOSTBRAIN_WHISPER_MODEL` and not `fetch-model`; with `'default'` the existing fetch-model hint is unchanged.
- [ ] **Step 5: Implement** desktop side (type + hint copy).
- [ ] **Step 6: Gates** (pytest on touched test files, typecheck, vitest touched files, lint).
- [ ] **Step 7: Commit** `fix(settings): say when the whisper model is pinned by GHOSTBRAIN_WHISPER_MODEL`.

---

### Task 5: Guard conflict text against navigation away from Jots

**Requirement:** With the "changed elsewhere" conflict banner pending (GuardedNoteEditor / useGuardedSave from B1), leaving Jots via sidebar navigation, or opening a note from outside NoteView, drops the paused text. Guard those paths with a confirm before discarding, consistent with the existing jot-switch confirm.

**Files:**
- Read first: `desktop/src/renderer/components/GuardedNoteEditor*`, `useGuardedSave` (grep), `desktop/src/renderer/screens/jots.tsx` (existing jot-switch confirm), the app navigation store / sidebar (grep how screens change, e.g. a `useNavigation`/`setScreen` store) and any "open note" entry points outside NoteView (search results, backlinks, chat links, command palette).
- Modify: whatever owns navigation (add a single guard hook, e.g. a registry `registerNavigationGuard(fn: () => boolean)` in the navigation store consulted before every screen change / note open), and the guarded editor registers a guard while a conflict is pending.
- Tests: `desktop/src/renderer/__tests__/` (extend jots / guarded editor tests)

- [ ] **Step 1:** Map every navigation path (sidebar, note-open from outside NoteView) and how the existing jot-switch confirm is implemented (copy, `window.confirm` vs dialog). Reuse the same mechanism and wording.
- [ ] **Step 2: Failing tests:** (a) conflict pending → sidebar nav to another screen prompts; cancel keeps the Jots screen and paused text; confirm navigates. (b) conflict pending → opening a note from outside NoteView prompts with the same semantics. (c) no conflict pending → navigation does not prompt. (d) guard is unregistered on unmount (no stale prompts).
- [ ] **Step 3: Implement** with one central guard point rather than per-call-site checks.
- [ ] **Step 4: Gates** (typecheck, vitest touched files, lint).
- [ ] **Step 5: Commit** `fix(jots): confirm before navigation discards a pending conflict`.

---

### Task 6: Invalidate backlinks after jot re-route, delete and extract-photo

**Requirement:** After jot re-route, delete and extract-photo mutations in `desktop/src/renderer/lib/api/hooks.ts`, invalidate the backlinks query like create/update already do.

**Files:**
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (the mutations around lines 615-695 — identify re-route, delete, extract-photo by their endpoints)
- Test: the existing hooks/jots test that asserts create/update backlinks invalidation (grep `'backlinks'` in `desktop/src/renderer/__tests__`)

- [ ] **Step 1: Failing tests:** for each of re-route, delete, extract-photo: spy on `queryClient.invalidateQueries` and assert a call with `{ queryKey: ['vault', 'backlinks'] }` after success — mirror the existing create/update test.
- [ ] **Step 2: Implement:** add `qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] });` to each mutation's success handler, next to the existing invalidations.
- [ ] **Step 3: Gates** (typecheck, vitest touched files, lint).
- [ ] **Step 4: Commit** `fix(jots): refresh backlinks after re-route, delete and photo extract`.
