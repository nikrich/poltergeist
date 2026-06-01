# Installing Poltergeist on Windows

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

## What's not supported yet

- **Meeting recorder** — requires platform-specific audio capture (BlackHole on macOS, PulseAudio/PipeWire on Linux). Not wired for Windows yet. The desktop app's Meetings tab returns "unsupported" on Windows.
- **Apple Calendar connector** — macOS-only. Use the Google Calendar connector instead (see README).
