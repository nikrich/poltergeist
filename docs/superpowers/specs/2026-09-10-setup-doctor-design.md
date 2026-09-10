# Setup Doctor + Claude Code Setup Skill — Design

**Status:** Approved in conversation 2026-09-10 (pending spec review)
**Origin:** External first-run audit (`poltergeist-first-run-audit.md`, 14 findings), verified
against `main` @ `eff6bce` on 2026-09-10.

## Problem

A user taking Poltergeist from a downloaded `.dmg` to a working meeting recorder on a
clean Mac hit fourteen defects. Six of them are the same defect: a required dependency
(ffmpeg, whisper-cli, a ggml model, BlackHole, the "Ghost Brain" multi-output device,
the Claude Code hook script) is discovered at the worst possible moment, and the
remediation string that already exists in the code never reaches the user. Two
defaults (`routing_mode: review_only`, scheduler off) make a correctly working install
look empty. The docs still tell packaged-app users to run `ghostbrain-*` commands that
only exist on a pip install.

The verification found the situation is slightly worse than reported: several
connectors can show **"on"** while doing nothing (the Claude Code hook is written
pointing at a developer-machine path; GitHub/Gmail/Google Calendar connect without
writing their routing block), and a failed transcription is recorded as **"done"** with
no error.

Nearly every check the auditor wanted already exists somewhere in the sidecar, with a
good remediation message. What is missing is one place that runs them all, before the
user needs them, and a guided way to act on the results.

## Goals

1. A single `doctor` command that runs every first-run check and reports status,
   remediation, and whether the fix is automatable.
2. Automated fixes for everything that does not need an admin password, including
   Homebrew installs.
3. A Claude Code skill, installable by any `.dmg` user, that drives the user from a
   fresh install to a verified test recording and configured connectors.
4. The skill is the first thing the README shows.
5. The checks are reusable by the desktop app later (`GET /v1/doctor`).

## Non-goals

- An in-app setup wizard or prerequisite panel (P-08 UI). The endpoint makes that
  possible later; this work does not build it.
- Windows dependency automation. Windows `doctor` reports; fixes stay manual, matching
  the existing `docs/install/windows.md` guidance about corporate proxies.
- Calendar identity keying (P-12) and a connector context-mapping UI (P-14 UI). Both
  are real and are tracked separately.
- Changing what transcription model the desktop setting refers to (P-09).

## Design

### 1. `ghostbrain/doctor/` — checks

A new package in the sidecar. `run_checks() -> list[CheckResult]` runs the catalog
below in order and never raises: a check that blows up reports `fail` with the
exception text.

```python
@dataclass
class Fix:
    kind: Literal["automated", "interactive", "manual"]
    command: str          # e.g. "setup deps --only ffmpeg", "brew install --cask blackhole-2ch"
    note: str = ""        # why it's interactive/manual, or what to expect

@dataclass
class CheckResult:
    id: str               # stable, kebab-case, part of the JSON contract
    status: Literal["ok", "warn", "fail", "skip"]
    summary: str          # one line, shown in the table
    detail: str = ""      # paragraph, shown when expanded
    fix: Fix | None = None
    data: dict = field(default_factory=dict)   # machine-readable extras (counts, paths)
```

- `automated`: a `setup` subcommand the skill runs directly.
- `interactive`: a command that works in a terminal but prompts for a password, so the
  skill hands it to the user.
- `manual`: a Settings path the app owns, or an action outside our control.

`skip` is used for checks that do not apply on the current platform (audio on Linux).

**Output.** `ghostbrain-api doctor` prints a table in the shape the audit mocked up
(✔ / ✘ / ! with the fix command indented under failures) and exits 1 if any check is
`fail`. `doctor --json` prints `{"platform": ..., "version": ..., "checks": [...]}`.
The JSON shape is the contract the skill depends on and is covered by a test.

**Catalog** (macOS unless noted; each names the existing code it reuses):

| id | fail condition | fix |
|---|---|---|
| `app` | `Poltergeist.app` not in `/Applications`; or the descriptor at `~/ghostbrain/run/sidecar.json` is absent, its pid is dead, or `/health` on its port does not answer. Distinguishes "app not running" (no Poltergeist process) from "app running but its sidecar is unpublished" (Poltergeist process alive, descriptor dead or unreachable), which is the read-only relaunch race; the summary for the latter says to quit, wait ten seconds, and reopen. | manual: open / restart the app |
| `vault` | `vault_path()/90-meta/routing.yaml` missing (`ensure_vault` logic); warn if desktop `config.json` `vaultPath` differs from the sidecar's `vault_path()` (P-10) | automated: `setup bootstrap`; mismatch is manual until the companion fix ships |
| `contexts` | `routing_config.contexts()` empty | manual: edit `contexts:` |
| `claude-cli` | `claude` not on PATH, or `claude --version` fails | manual: install Claude Code, `claude login` |
| `ffmpeg` | `DarwinBackend.preflight()` reports it missing (reuses `ghostbrain/recorder/audio/darwin.py`) | automated: `setup deps --only ffmpeg` |
| `whisper-cli` | not on PATH (reuses the resolver in `ghostbrain/recorder/transcribe.py`) | automated: `setup deps --only whisper-cpp` |
| `whisper-model` | no `ggml-*.bin` in `~/ghostbrain/recorder/models/` and `GHOSTBRAIN_WHISPER_MODEL` unset (reuses `transcribe.py` model resolution) | automated: `setup fetch-model` |
| `switchaudio` | `SwitchAudioSource` not on PATH (reuses `audio_switcher`) | automated: `setup deps --only switchaudio-osx` |
| `blackhole` | "BlackHole 2ch" not in `SwitchAudioSource -a -t output` | interactive: `setup deps --only blackhole` |
| `audio-device` | no output device named `recorder.audio_device` from `config.yaml` (default "Ghost Brain") | automated: `setup audio-device` |
| `audio-routing` | current default output is not that device (`warn` only: the daemon switches it itself; the manual Record button requires it) | manual: Sound menu |
| `scheduler` | desktop `config.json` `schedulerEnabled` is false | manual: Settings → background → "Run scheduler in-app" |
| `routing-mode` | `worker.routing_mode == review_only` (`warn`, with count of `00-inbox/raw/*.md` in `data`) | automated: `setup go-live` |
| `connectors` | per connector with a routing block: `fail` if the probe says `on` but the block is empty (`github.orgs`, `gmail.accounts`, `calendar.*.accounts`), `warn` if configured but never run. Uses `connector_probe.probe()` and `routing.yaml`. | manual: the app's connector cards, then a fetch |
| `claude-hook` | `~/.claude/settings.json` has no `SessionEnd` hook, or its command path does not exist (P-06 amplifier) | automated: `setup install-hook` |
| `cli-shim` | `poltergeist` not on PATH | automated: `setup cli-shim` |

Windows runs `app`, `vault`, `contexts`, `claude-cli`, `scheduler`, `routing-mode`,
`connectors`, `claude-hook`, plus a single `recorder-backend` check that surfaces
`WasapiBackend.preflight()` with manual fixes pointing at `docs/install/windows.md`.
Linux runs the non-recorder checks only.

**`GET /v1/doctor`** returns the same JSON. It is one route over `run_checks()`,
registered in `create_app()` like every other router. No consumer in this release.

### 2. `ghostbrain-api setup <fix>` — fixes

`ghostbrain/doctor/setup.py` dispatches to one module per fix. Every fix is
idempotent, prints what it did or why it did nothing, and exits non-zero with a
one-line reason on failure. None of them prompt; anything that needs a password is
`interactive` in the catalog and simply runs the underlying command so a terminal can
prompt.

- **`setup deps [--only NAME ...]`** (`deps.py`). Resolves `brew` via `shutil.which`
  then `/opt/homebrew/bin/brew` then `/usr/local/bin/brew`. If absent, exits with the
  Homebrew install instruction (its installer also needs sudo, so it stays manual).
  Installs, in order, whichever of `ffmpeg`, `whisper-cpp`, `switchaudio-osx`,
  `blackhole-2ch` (cask) are missing or named in `--only`, streaming brew's output.
  Skips what is already installed by re-running the corresponding doctor check first.
- **`setup fetch-model [base.en|small.en|medium.en]`** (`models.py`). Default
  `medium.en`, matching `DEFAULT_MODEL` in `transcribe.py`. Downloads
  `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-<name>.bin` to
  `<models dir>/.ggml-<name>.bin.part` with a progress line (bytes / total / %), prints
  the expected size before starting (base.en ≈ 142 MB, small.en ≈ 466 MB,
  medium.en ≈ 1.5 GB), verifies `Content-Length` matched, then renames into place.
  Honors `HTTPS_PROXY`. Respects an existing `GHOSTBRAIN_WHISPER_MODEL` by reporting it
  and doing nothing. Uses `httpx`, already a hard dependency.
- **`setup audio-device`** (`audio_device.py`). Creates the multi-output device via
  `AudioHardwareCreateAggregateDevice` from `pyobjc-framework-CoreAudio` (new
  darwin-only dependency, added to `pyproject.toml` and collected in
  `packaging/sidecar.spec`). Description dictionary: name from
  `recorder.audio_device`, uid `tech.codeship.ghostbrain.multioutput`, `stacked: 1`
  (multi-output rather than aggregate), `private: 0` (persists, visible in Audio MIDI
  Setup), master = built-in output UID, subdevices = built-in output and BlackHole with
  `drift: 1` on BlackHole. Finds device UIDs by enumerating `kAudioHardwarePropertyDevices`
  and matching names "BlackHole 2ch" and the built-in output (`kAudioDeviceTransportTypeBuiltIn`).
  If BlackHole is missing, exits with the blackhole fix. If a device with the target
  name already exists, reports it and exits 0.
- **`setup install-hook`** (`hook.py`). Atomic deep-merge into `~/.claude/settings.json`
  (reuses the merge in `ghostbrain/api/auth/providers/local_grant.py`, extracted into a
  shared helper). Command is `"<absolute path of the running binary> session-end"`,
  resolved from `sys.executable` when frozen. Removes an existing Poltergeist
  `SessionEnd` entry whose command path no longer exists before adding the new one.
  Windows writes the same entry (the binary path differs; no `.ps1` needed anymore).
- **`setup cli-shim`** (`cli_shim.py`). Writes the same two-line `exec` shim the desktop
  writes (`desktop/src/main/cli-shim.ts`) to `/usr/local/bin/poltergeist` if that
  directory is writable, else `~/.local/bin/poltergeist` with a note to add it to PATH.
- **`setup go-live`** (`go_live.py`). Sets `worker.routing_mode: live` in
  `90-meta/config.yaml` via a comment-preserving edit (a line-level replace of the
  existing key, not a YAML dump), and prints how many `00-inbox/raw` notes the next
  worker pass will file.
- **`setup bootstrap`**. Alias for the existing `bootstrap` subcommand, kept so the
  catalog can point at one namespace.

### 3. `session-end` subcommand

`ghostbrain/hooks/session_end.py` is a direct port of `orchestration/hooks/session-end.sh`:
read the SessionEnd JSON from stdin; skip when `session_id` is empty or
`reason == "resume"`; snapshot the transcript to
`90-meta/queue/transcripts/<session_id>.jsonl` (Claude Code prunes the original);
write the same event JSON to `90-meta/queue/pending/<UTC ts>-claude-code-<session_id>.json`
with `transcript_snapshot` preferred. It uses only the standard library and honors
`VAULT_PATH` the same way. The shell and PowerShell scripts stay in the repo for
source installs but the docs and the connector card stop pointing at them.

The Claude Code `local_grant` provider (`ghostbrain/api/auth/providers/local_grant.py`)
switches its default command to the `session-end` subcommand so the app's own connect
button stops writing a developer path. `_claude_code_probe` in
`ghostbrain/api/repo/connector_probe.py` reports `on` only if the hook's command path
exists.

Subcommand registration: `doctor`, `setup`, `session-end` are added to `SUBCOMMANDS` in
`ghostbrain/api/__main__.py` and to `[project.scripts]` in `pyproject.toml` as
`ghostbrain-doctor`, `ghostbrain-setup`, `ghostbrain-session-end`, keeping
`tests/test_api_main_dispatch.py`'s parity check green.

### 4. The skill — `.claude/skills/poltergeist-setup/`

Files: `SKILL.md` (the flow, under 150 lines) and `checks.md` (one paragraph per
check id: what it means in plain words, the fix, what to say if it fails twice).
`.claude/skills/onboarding-poltergeist/` is deleted; its still-accurate connector
notes move into `checks.md`.

Flow the skill drives, one step per user turn:

1. **Find the binary.** `poltergeist` on PATH; else
   `/Applications/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api`;
   else `%LOCALAPPDATA%\Programs\Poltergeist\resources\sidecar\ghostbrain-api\ghostbrain-api.exe`.
   If none exist: link the latest GitHub release and stop.
2. **Run `doctor --json`.** Render the table. If everything is `ok`, jump to step 4.
3. **Walk failures in catalog order, one at a time.** For each: one sentence on what
   it is and why the recorder needs it, the exact command, run it on consent for
   `automated` fixes, hand over a Terminal one-liner for `interactive` ones and wait,
   give the Settings path for `manual` ones. Re-run only that check before moving on.
   Never batch installs; never run `sudo`.
4. **Prove it.** With the app running: `POST /v1/recorder/start` with an explicit
   context, ask the user to talk for fifteen seconds, `POST /v1/recorder/stop`, poll
   `/v1/recorder/status` until `done`, then open the transcript note. This is the step
   the auditor never reached; the skill does not report success without it.
5. **Connectors.** Ask which of gmail, calendar, slack, github, jira, confluence,
   microsoft, joplin, claude code matter. For each: point at the app's connector card
   for credentials (they work; the README's "placeholders" note is wrong and gets
   fixed), then verify with `poltergeist <x>-fetch` and confirm the routing block is
   non-empty. Surface any "on but empty" block doctor found.
6. **Go live.** Once `00-inbox/raw` has items, explain review mode in two sentences and
   offer `setup go-live`.
7. **Final `doctor`.** All green or the remaining warns explained. Done.

The skill authenticates API calls with the token from `~/ghostbrain/run/sidecar.json`
and tells the user to restart the app if the descriptor is stale (the `app` check
already says so).

### 5. Distribution and README

- The skill lives in the repo. Users install it with
  `npx skills add nikrich/poltergeist` (Vercel's `skills` CLI discovers `SKILL.md`
  directories). Fallback that needs no Node:
  ```
  curl -fsSL https://github.com/nikrich/poltergeist/archive/main.tar.gz | tar -xz --strip-components=3 -C ~/.claude/skills poltergeist-main/.claude/skills/poltergeist-setup
  ```
  Both commands are verified against a fresh `~/.claude/skills` during implementation.
- `README.md` opens with a new first section, **"Set up in five minutes with Claude
  Code"**: download the app, install the skill, open Claude Code anywhere, say
  "set up Poltergeist". Four lines and the two commands. The existing quick-start
  moves below it unchanged.
- `README.md` line 152 ("connect buttons are placeholders") is deleted.

### 6. Companion fixes in the same release

All size S, each its own PR, all verified against `main` on 2026-09-10. They exist so
the doctor rarely has to flag the corresponding check on a fresh install and so the
skill's test recording can actually surface errors.

| Audit | Fix |
|---|---|
| P-01 | `repo/recorder.start()` runs `recorder_prereqs_ok()` first and raises a `RecorderPrereqsMissing` mapped to 412 with the preflight text; `routes/recorder.py` also maps `OSError` to 500 with detail. |
| P-02 | `recover_one` re-raises `TranscribeError` (and treats an empty transcript as one) so `_transcribe_in_background` writes `error`; the renderer's existing red pill then shows it. |
| P-03 | `bootstrap.py` seeds `routing_mode: live` for new vaults. Existing vaults keep whatever they have; doctor's `routing-mode` check plus `setup go-live` covers them. |
| P-04 | `schedulerEnabled` defaults to `true`; the two `stub(3)` toasts in `connectors.tsx` become the real "scheduler is off" message. |
| P-06 | Covered by section 3. |
| P-10 | `sidecar.ts` passes `VAULT_PATH` from settings; `index.ts` restarts the sidecar when `vaultPath` changes. |
| P-11 | `connector_probe.probe("calendar")` returns `on` on darwin when EventKit is authorized and `calendar.macos.accounts` is non-empty (reuses `_macos_calendar_authorized`). |
| P-13 | `runtime.setup_file_logging()` sets `httpx`, `httpcore`, `huggingface_hub`, `transformers`, `sentence_transformers`, `filelock`, `urllib3` to WARNING; `create_app()` registers an `Exception` handler that logs the traceback with a request id and returns `{"detail": "Internal error", "requestId": ...}`; `uvicorn.run` gets a `log_config` whose `uvicorn` logger propagates to root. |
| P-05, P-07 | Docs: `docs/connectors.md` adopts the README's three-spellings note and rewrites its fences as `poltergeist <sub>`; new `docs/install/macos.md` covering BlackHole, the multi-output device, models, `GHOSTBRAIN_ALLOWED_AUDIO_OUTPUTS`, and "or just run the skill"; the two false Meetings-tab claims in `docs/install/windows.md` are corrected. |

## Error handling

- `doctor` never exits non-zero because a *check* crashed; the crash becomes that
  check's `fail` with the exception text in `detail`. The JSON is always complete.
- `setup deps` stops at the first brew failure and prints brew's last twenty lines;
  the skill reports that verbatim rather than retrying.
- `setup fetch-model` resumes nothing: a partial `.part` file is deleted on failure and
  the next run starts over. A size mismatch is a failure, not a warning.
- `setup audio-device` treats any CoreAudio `OSStatus != 0` as failure and prints the
  status code plus the recipe for doing it by hand in Audio MIDI Setup.
- `setup install-hook` refuses to write if `~/.claude/settings.json` is not valid JSON,
  and never touches keys other than `hooks.SessionEnd`.
- The skill never runs `sudo`, never batches fixes, and stops after the same check
  fails twice with the same output, telling the user what to paste into an issue.

## Testing

- **Unit (pytest):** one test module per check, monkeypatching `shutil.which`,
  `subprocess.run`, the descriptor file, `config.json`, and `settings.json` via
  `tmp_path` and `GHOSTBRAIN_STATE_DIR` / `VAULT_PATH`. A contract test asserts every
  `fail` result carries a `fix` and that the JSON shape is stable. `setup fetch-model`
  is tested against a local `http.server` fixture serving a small file, including the
  size-mismatch path. `setup install-hook` is tested for idempotency and stale-path
  removal on a tmp `settings.json`. `session-end` is tested with the same payloads the
  shell script's docstring describes, including `reason=resume` and a missing
  transcript. The subcommand parity test covers the three new entries.
- **Guarded local runs:** the recorder state tests already showed that a local pytest
  can clobber the live sidecar's state. An autouse fixture in `tests/conftest.py`
  sets `GHOSTBRAIN_STATE_DIR`, `VAULT_PATH`, and `HOME` to `tmp_path` for every test.
  That lands first, in its own PR.
- **`audio-device` on darwin:** a `--dry-run` flag prints the description dictionary
  it would submit; the unit test asserts the dictionary. Real creation is verified
  manually on a machine with BlackHole and recorded in the PR.
- **Desktop (vitest):** the P-04 and P-10 companion fixes get tests in the existing
  `__tests__` pattern.
- **Acceptance:** a fresh macOS user account on a Mac with nothing but the `.dmg` and
  Claude Code. Install the skill with each of the two commands, say "set up
  Poltergeist", and follow it to a transcript. Both the Terminal handoff for BlackHole
  and the test recording must work. Result recorded in the release PR.

## Slices (implementation order)

1. Test isolation fixture (`conftest.py`).
2. `ghostbrain/doctor/` checks + `doctor` subcommand + `GET /v1/doctor` (macOS catalog
   first, Windows and Linux subsets).
3. `setup deps`, `setup fetch-model`, `setup cli-shim`, `setup go-live`, `setup bootstrap`.
4. `session-end` subcommand + `setup install-hook` + provider/probe changes (P-06).
5. `setup audio-device` (CoreAudio dependency + spec change).
6. Companion fixes P-01, P-02, P-03, P-04, P-10, P-11, P-13 (separate small PRs).
7. Docs: `docs/install/macos.md`, `docs/connectors.md`, `windows.md` corrections.
8. The skill + README section + delete the old skill; verify both install commands.
9. Release as 1.5.0 (the setup surface is a feature); acceptance run on a clean account.
