# Installing Poltergeist on Linux

This guide walks you through a working installation of Poltergeist on Linux. The desktop app with the built-in scheduler is the recommended path; `ghostbrain-worker` can also run under systemd if you prefer.

## Prerequisites

- **Python 3.11+** — install via your distribution's package manager or [python.org](https://www.python.org/downloads/).
- **pip** — usually bundled with Python.
- **git**.
- **Obsidian** — download the AppImage or Flatpak from [obsidian.md](https://obsidian.md/download).
- **Claude Code CLI** — required for the LLM backend. See [installing Claude Code](https://claude.ai/docs/download).
- **ffmpeg** (optional for now) — the meeting recorder will need it once Linux support lands. Install via your package manager.

## Clone and install

```bash
git clone <repository-url> ghost-brain
cd ghost-brain
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,api]"
```

The `[api]` extra is needed if you want the desktop app to spawn the sidecar from your venv during development.

## Bootstrap the vault

```bash
ghostbrain-bootstrap
```

This creates the directory tree and seed files. By default, the vault lives at `~/ghostbrain/vault/`. To use a different location:

```bash
export VAULT_PATH="/path/to/vault"
ghostbrain-bootstrap
```

## Install Obsidian plugins

Open the vault in Obsidian, then go to **Settings → Community plugins** and install:

- Dataview
- Templater
- Periodic Notes
- Local REST API

These must be installed through the in-app browser.

## Configure routing

Edit `<vault>/90-meta/routing.yaml` to map your sources (GitHub orgs, Jira sites, Claude Code project paths, etc.) to context names. Refer back to the README for the full routing details rather than redoing them here.

## Always-on scheduler

### Option A: Desktop app (recommended)

Download the AppImage from the latest release (or build it locally once available). Launch it, then enable the scheduler in **Settings → Scheduler → Background** to run connectors and the worker on a schedule.

### Option B: systemd user unit

Run `ghostbrain-worker` as a background service:

1. Create `~/.config/systemd/user/ghostbrain-worker.service`:

```ini
[Unit]
Description=Ghostbrain worker
After=network-online.target

[Service]
Type=simple
ExecStart=%h/development/ghost-brain/.venv/bin/ghostbrain-worker
Restart=on-failure
Environment=VAULT_PATH=%h/ghostbrain/vault
Environment=GHOSTBRAIN_SCHEDULER_ENABLED=1

[Install]
WantedBy=default.target
```

Adjust the `ExecStart` path to wherever you cloned the repo.

2. Enable and start it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ghostbrain-worker
```

3. Check logs:

```bash
journalctl --user -u ghostbrain-worker -f
```

## Claude Code SessionEnd hook

Wire up the hook to capture Claude Code sessions. Add this to `~/.config/claude/settings.json`:

```json
"hooks": {
  "SessionEnd": [{
    "matcher": "*",
    "hooks": [{
      "type": "command",
      "command": "bash /path/to/ghost-brain/orchestration/hooks/session-end.sh",
      "shell": "bash"
    }]
  }]
}
```

Replace `/path/to/ghost-brain` with your actual clone path.

## What's not supported yet

- **Meeting recorder** — requires Linux-specific audio capture (PulseAudio/PipeWire loopback), which isn't wired yet. The desktop app's Meetings tab returns "unsupported" on Linux.
- **Apple Calendar connector** — macOS-only. Use the Google Calendar connector instead (see README).
