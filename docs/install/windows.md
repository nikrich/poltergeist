# Installing Poltergeist on Windows

> The desktop app is self-contained — it auto-bootstraps the vault on first
> launch and bundles the whole CLI as `ghostbrain-api <subcommand>` (no
> Python install needed). This page covers the headless/pip setup only:
> everything below is for running Poltergeist from source instead of the
> packaged app, where `ghostbrain-api <subcommand>` is replaced by the
> pip-installed `ghostbrain-<subcommand>` scripts.

This guide walks you through a working installation of Poltergeist on Windows. The desktop app with the built-in scheduler is the recommended path; `ghostbrain-worker` can also run under Task Scheduler if you prefer.

## Prerequisites

- **Python 3.11+** from [python.org](https://www.python.org/downloads/) — **not** the Microsoft Store build (it has sandbox restrictions that break subprocess calls and vault paths).
- **Git for Windows** — provides bash if you need to run the SessionEnd hook script.
- **Obsidian** — download from [obsidian.md](https://obsidian.md/download).
- **Claude Code CLI** — required for the LLM backend. See [installing Claude Code](https://claude.ai/docs/download).

## Clone and install

In PowerShell or cmd:

```powershell
git clone <repository-url> ghost-brain
cd ghost-brain
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,api]"
```

The `[api]` extra is needed if you want the desktop app to spawn the sidecar from your venv during development.

## Bootstrap the vault

```powershell
ghostbrain-bootstrap
```

This creates the directory tree and seed files. By default, the vault lives at `%USERPROFILE%\ghostbrain\vault`. To use a different location:

```powershell
$env:VAULT_PATH = "C:\path\to\vault"
ghostbrain-bootstrap
```

To set it permanently, use System Properties → Environment Variables, or:

```powershell
[Environment]::SetEnvironmentVariable("VAULT_PATH", "C:\path\to\vault", "User")
```

## Install Obsidian plugins

Open the vault in Obsidian, then go to **Settings → Community plugins** and install:

- Dataview
- Templater
- Periodic Notes
- Local REST API

These must be installed through the in-app browser.

## Configure routing

Edit `<vault>\90-meta\routing.yaml` to map your sources (GitHub orgs, Jira sites, Claude Code project paths, etc.) to context names. Refer back to the README for the full routing details rather than redoing them here.

## Always-on scheduler

### Option A: Desktop app (recommended)

Once Windows installer artifacts ship from the planned `build-win` CI release job (not built today), download the installer from the latest release. Launch it, then enable the scheduler in **Settings → Background** by toggling the "run scheduler in-app" switch to run connectors and the worker on a schedule.

### Option B: Task Scheduler

Run `ghostbrain-worker` at logon via Task Scheduler:

```cmd
schtasks /Create /TN "Ghostbrain Worker" ^
  /TR "C:\path\to\ghost-brain\.venv\Scripts\ghostbrain-worker.exe" ^
  /SC ONLOGON /RL HIGHEST /F
```

Replace `C:\path\to\ghost-brain` with your actual clone path.

Set the environment variables at the user level via **System Properties → Environment Variables**:

- `VAULT_PATH` — vault location (e.g. `C:\Users\YourName\ghostbrain\vault`)
- `GHOSTBRAIN_SCHEDULER_ENABLED` — set to `1`

Or set them in PowerShell:

```powershell
[Environment]::SetEnvironmentVariable("VAULT_PATH", "C:\Users\YourName\ghostbrain\vault", "User")
[Environment]::SetEnvironmentVariable("GHOSTBRAIN_SCHEDULER_ENABLED", "1", "User")
```

## Claude Code SessionEnd hook

Wire up the hook to capture Claude Code sessions. Add this to `%USERPROFILE%\.claude\settings.json`:

```json
"hooks": {
  "SessionEnd": [{
    "matcher": "*",
    "hooks": [{
      "type": "command",
      "command": "powershell -ExecutionPolicy Bypass -File C:\\path\\to\\ghost-brain\\orchestration\\hooks\\session-end.ps1",
      "shell": "cmd"
    }]
  }]
}
```

Replace `C:\path\to\ghost-brain` with your actual clone path.

## Meeting recorder

The recorder is fully supported on Windows via WASAPI loopback — no
BlackHole-equivalent driver, no admin rights, and no device switching.
Loopback taps the default output device directly, so `recorder.audio_device`
in `<vault>\90-meta\config.yaml` is ignored on Windows (it only applies to
the macOS backend, which switches system output to a Multi-Output Device).

### Install the recorder extra

```powershell
pip install -e ".[dev,api,recorder-win]"
```

If you're running the packaged desktop app instead of a dev checkout, the
Windows installer already bundles this — no extra step needed.

### Install whisper.cpp

Transcription runs `whisper-cli` locally; nothing is downloaded at runtime.

1. Install [whisper.cpp](https://github.com/ggml-org/whisper.cpp) and put
   `whisper-cli.exe` on your `PATH`.
2. Download a `ggml-*.bin` model (e.g. `ggml-small.en.bin`) via your browser
   or your org's approved download channel, and place it at
   `%USERPROFILE%\ghostbrain\recorder\models\`. **On corporate networks with
   TLS-intercepting proxies (Zscaler etc.), do not `curl`/`Invoke-WebRequest`
   the model at runtime — it will hang silently behind the proxy.** A
   manual browser download avoids that entirely.
   - To use a model living somewhere else, set `GHOSTBRAIN_WHISPER_MODEL` to
     its full path instead of moving it into the default directory.

Recorder preflight (surfaced in the desktop app's Meetings tab, and via
`recorder_prereqs_ok()`) checks for `pyaudiowpatch`, `whisper-cli` on PATH,
and a model file, and reports exactly which piece is missing.

### Wire up a calendar source

Auto-record picks up meetings from whatever calendar sources are configured
in `<vault>\90-meta\routing.yaml` — the same accounts you'd configure for
the calendar connector (see [Calendar](../../README.md#calendar-phase-11)
in the README), plus Microsoft 365:

```yaml
calendar:
  google:
    accounts:
      you@gmail.com: personal

microsoft:
  calendar_context: work   # required for the Microsoft source to activate
```

Without `microsoft.calendar_context` set, the Microsoft calendar source is
excluded (Apple Calendar isn't an option on Windows at all — that source is
darwin-only). Exclusion reasons for every configured-but-inactive source
show up in the recorder status response as `sourceExclusions`, which the
Meetings tab surfaces so it's clear why a calendar isn't driving
auto-record.

To restrict auto-record to specific sources (e.g. only `google`, ignoring
a configured `microsoft` block), pin the list explicitly in
`<vault>\90-meta\config.yaml`:

```yaml
recorder:
  meeting_sources: [google]
```

### Manual recording and the standalone CLI

WASAPI capture runs as an in-process thread, not a separate OS process
(unlike ffmpeg on macOS) — a backend can only see and stop a recording that
its own process started. If you run `ghostbrain-recorder` (the daemon) as a
standalone process (e.g. via Task Scheduler, see Option B above) alongside
the desktop app, any recording either one starts — calendar-driven or
manual — is invisible to the other's Meetings tab and can't be stopped from
it. Run one or the other, not both, to avoid a recording you can't see or
stop.

## What's not supported yet

- **Apple Calendar connector** — macOS-only. Use the Google Calendar connector instead (see README).
