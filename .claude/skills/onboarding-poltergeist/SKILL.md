---
name: onboarding-poltergeist
description: Use when setting up Poltergeist (the ghostbrain second-brain) for the first time, onboarding a new user, or authenticating/configuring any connector — gmail, google or macOS calendar, slack, github, jira, confluence, joplin, microsoft (outlook mail / teams chat / teams meeting transcripts), or claude code. Triggers include "set up poltergeist", "connect <tool>", "bootstrap the vault", or a connector showing "off" / not pulling data.
---

# Onboarding Poltergeist

## Overview

Poltergeist (Python package: **`ghostbrain`** — legacy namespace) ingests your tools into an Obsidian-style markdown vault. Onboarding is always the same four phases:

1. **Install** the package + **bootstrap** the vault.
2. **Per connector** (repeat for each tool): create the external credential → run the auth command → add the connector's block to `routing.yaml` → dry-run to verify.
3. **Run the worker** (and optionally the in-app scheduler) so queued events become notes.
4. Optional: digests, CLAUDE.md generation.

**The desktop app's "connect <X>" buttons are stubs** — they do nothing. Every connector is set up from the CLI + `routing.yaml`, never the UI. This is the single most common point of confusion.

## Critical facts (memorize these)

- **CLI prefix:** every command is `ghostbrain-*` (e.g. `ghostbrain-bootstrap`, `ghostbrain-gmail-auth`).
- **Vault:** `$VAULT_PATH` or default `~/ghostbrain/vault/`. The one file users edit is **`vault/90-meta/routing.yaml`**. Pipeline tuning lives in `vault/90-meta/config.yaml`.
- **Secrets/state:** `~/.ghostbrain/state/` (or `$GHOSTBRAIN_STATE_DIR`) — deliberately separate from the vault. Holds OAuth tokens, `.last_run` cursors, the Microsoft keychain cache. **Never sync or commit it.**
- **Queue model:** connectors only drop events into `vault/90-meta/queue/pending/`. The **worker** routes them into notes. Nothing reaches `20-contexts/` until `worker.routing_mode: live` in `config.yaml` (default is `review_only` — raw events land in `00-inbox/` only).
- **Per-connector config is required:** a connector reads ONLY its own block in `routing.yaml`. If that block is missing it silently reports **"skipped (not configured)"**.
- **"On" state:** a connector shows "on" once it has `~/.ghostbrain/state/<id>.last_run` (or, for claude_code, captures in the inbox). LLM calls shell out to `claude -p`, so the `claude` CLI must be on PATH and logged in.

## Install + bootstrap

```bash
cd <repo>
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # add the ".[api]" extra too for the desktop sidecar/scheduler
ghostbrain-bootstrap             # idempotent; creates ~/ghostbrain/vault/ and seeds routing.yaml
export VAULT_PATH="$HOME/ghostbrain/vault"
```

## Connector quick reference

Per-connector specifics (exact prerequisites, routing keys, gotchas) are in **`connectors.md`** in this skill directory — read it for whichever connector you're setting up.

| Connector | External credential to create first | Authenticate / configure | Verify |
|---|---|---|---|
| **gmail** | Google Desktop OAuth client JSON → `~/.ghostbrain/state/google_oauth_client.json` (enable Gmail API) | `ghostbrain-gmail-auth <email>` + `gmail.accounts` block | `ghostbrain-gmail-fetch --dry-run` |
| **calendar (google)** | same Google OAuth client (enable Calendar API) | `ghostbrain-calendar-auth google <email>` + `calendar.google.accounts` | `ghostbrain-calendar-fetch --dry-run` |
| **calendar (macOS)** | none (grant Calendar access in System Settings) | `calendar.macos.accounts` block | `ghostbrain-calendar-fetch --dry-run` |
| **slack** | Slack app + User OAuth token (`xoxp-…`) with the listed scopes | `ghostbrain-slack-token-add <slug> <xoxp>` + `slack.workspaces` | `ghostbrain-slack-fetch --dry-run` |
| **github** | `gh` CLI logged in (`gh auth login`) | `github.orgs` block | `ghostbrain-github-fetch --dry-run` |
| **jira / confluence** | Atlassian API token → env `ATLASSIAN_EMAIL` + `ATLASSIAN_TOKEN[_<SITE>]` | `jira.sites` / `confluence.sites`+`spaces` | `ghostbrain-jira-fetch --dry-run` |
| **joplin** | Joplin Web Clipper token (enable in Joplin) | `joplin.token` (+ `notebooks`) in routing.yaml | `ghostbrain-joplin-fetch --dry-run` |
| **microsoft** (outlook/teams) | Entra app (public client) → `client_id`+`tenant_id`; delegated scopes + admin consent | `ghostbrain-microsoft-auth` + `microsoft.*` blocks | `ghostbrain-teams-meetings-fetch` |
| **claude_code** | none | wire SessionEnd hook → `orchestration/hooks/session-end.sh`; `claude_code.project_paths` | run a Claude session, check `00-inbox/raw/claude-code/` |

## Verify any connector

```bash
ghostbrain-<connector>-fetch --dry-run    # lists what WOULD be pulled, enqueues nothing
ghostbrain-<connector>-fetch              # prints "queued N event(s)"
```
- `queued 0` with no error = wired correctly, just nothing new since the last run.
- `skipped (not configured)` = its block is missing from `routing.yaml`.
- `FAILED — …auth…` = re-run that connector's auth command.
- Run `ghostbrain-worker` and tail `vault/90-meta/audit/*.jsonl` for `connector_run` then `event_processed status=success`. The connector flips "on" once `~/.ghostbrain/state/<id>.last_run` exists.

## Common gotchas

- **Connect buttons are stubs** — always use the CLI + routing.yaml.
- **Google:** gmail + calendar share ONE Desktop OAuth client JSON. An "External + Testing" consent screen expires refresh tokens ~weekly — publish the consent screen, or re-auth.
- **Microsoft is delegated device-code.** `getAllTranscripts` is application-only (unusable here). Calendar auto-discovery for meetings needs `Calendars.Read` + admin consent. To pull transcripts with **transcripts-only** scope today, list meetings explicitly in `microsoft.teams_meetings.meetings` (join URLs, `/meet/<id>` links, or bare IDs). Set `microsoft.scopes` to ONLY the scopes you actually consented, or silent token refresh fails.
- **Contexts are hard-coded** (`sanlam / codeship / reducedrecipes / personal` in `bootstrap.py:CONTEXTS`). Route to one of those, or events fall to `needs_review`.
- **Nothing appears in `20-contexts/`** until `worker.routing_mode` is flipped from `review_only` to `live` in `config.yaml`.
