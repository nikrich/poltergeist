<h1 align="center">Poltergeist</h1>

<p align="center"><em>a quiet brain for your loud apps</em></p>

<p align="center">
  <a href="https://github.com/nikrich/poltergeist/actions/workflows/release.yml"><img alt="release pipeline" src="https://github.com/nikrich/poltergeist/actions/workflows/release.yml/badge.svg"></a>
  <a href="https://github.com/nikrich/poltergeist/releases/latest"><img alt="latest release" src="https://img.shields.io/github/v/release/nikrich/poltergeist?display_name=tag&label=release&color=C5FF3D&labelColor=0E0F12"></a>
  <a href="https://github.com/nikrich/poltergeist/releases"><img alt="downloads" src="https://img.shields.io/github/downloads/nikrich/poltergeist/total?color=C5FF3D&labelColor=0E0F12"></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-3776ab?logo=python&logoColor=white&labelColor=0E0F12">
  <img alt="platform" src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-f2f3f5?labelColor=0E0F12">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-C5FF3D?labelColor=0E0F12">
</p>

<p align="center">
  <a href="https://getpoltergeist.com"><b>getpoltergeist.com</b></a> ·
  <a href="https://github.com/nikrich/poltergeist/releases/latest"><b>Download</b></a> ·
  <a href="#quick-start"><b>Quick start</b></a> ·
  <a href="#documentation"><b>Docs</b></a>
</p>

<p align="center">
  <img alt="Poltergeist — a 40-second tour" src="media/poltergeist-demo.gif" width="900">
</p>

<p align="center"><sub>A 40-second tour — today's digest, asking the archive, the capture inbox, live connectors, and quick jots.<br><a href="media/poltergeist-demo.webm">Watch the higher-quality video →</a></sub></p>

Poltergeist is a **local-first memory layer for your work life**. It quietly haunts every app you use — Claude Code & Desktop, GitHub, Jira, Confluence, Slack, Gmail, Microsoft 365, your calendar — pulls every passing thought into a plain-markdown Obsidian vault on your machine, classifies and summarizes it with an LLM, and serves it back as a daily digest you can actually act on.

No manual capture. No SaaS holding your context hostage. Just markdown, on your disk, forever.

## Why Poltergeist

Most "second brain" tools fail in one of two ways: they're **manual**, so you stop feeding them, or they're **SaaS**, so your most sensitive professional context lives on someone else's servers. Poltergeist is built to avoid both:

- **Zero-effort capture.** Connectors watch the apps you already use and file everything automatically. You never "save a note" again.
- **Local-first and private.** Your vault is plain markdown files on your own disk. Nothing leaves your machine unless you push it somewhere. Credentials are stored `0600` in local state, never in the vault or source.
- **Your existing Claude subscription powers it.** LLM calls run through the `claude` CLI, so a Claude subscription is all you need — no separate API key or metered billing (the metered API is supported if you prefer it).
- **Open format, no lock-in.** The vault is a standard Obsidian vault. Every note is readable with `cat`. Walk away any time and keep everything.
- **Extensible.** A small connector pattern for new sources, and a plugin system for extending the desktop app.

## What it does

| | |
|---|---|
| **Connectors** | Claude Code, GitHub, Jira, Confluence, Slack, Gmail, Google + macOS Calendar, Joplin, Microsoft 365 (Outlook mail, Teams chat, Teams meeting transcripts) |
| **Daily digest** | Every morning: what happened yesterday, what's on today, across every context |
| **Weekly digest** | What's drifting, what's recurring, who needs unblocking — patterns no single day shows |
| **Ask the archive** | RAG-backed Q&A over your entire history, with citations, from the desktop app or any MCP client |
| **Profile engine** | Learns how you work from your sessions and keeps per-project `CLAUDE.md` files up to date |
| **Desktop app** | Digest reader, archive search, capture inbox, quick jots, connector health, built-in scheduler |
| **Plugins** | Extend the desktop app with third-party plugins; install from folder, git, or the marketplace |

> **Status: alpha.** All connectors above are live today. The meeting recorder and richer metrics are the main work in progress. Poltergeist is designed to be adopted incrementally — wire up only the connectors you want.

## How it works

```
Sources (Claude Code, GitHub, Jira, Slack, Gmail, …)
        │  connectors normalize to a standard event shape
        ▼
Filesystem queue: <vault>/90-meta/queue/pending/
        │
        ▼
Worker pipeline: route → generate note → extract artifacts → audit
        │
        ▼
Obsidian vault: 20-contexts/<ctx>/<source>/, 80-profile/, 60-dashboards/
        │
        ▼
Daily digest at <vault>/10-daily/<date>.md
```

Everything in the pipeline is inspectable: events are JSON files, notes are markdown, and every routing decision is written to a JSONL audit log. See [SPEC §2](./spec/SPEC.md#section-2--system-overview) for the full architecture.

**Under the hood:** Python 3.11+, an in-app asyncio scheduler (no broker, no Docker), a filesystem queue, and Obsidian as the storage layer. Cross-platform — connectors, worker, digests, and the desktop app run on macOS, Linux, and Windows ([per-OS notes](./docs/install/)). The meeting recorder is macOS-only for now.

## Quick start

Get your first connector flowing in about five minutes.

> **A note on command names.** CLI binaries and the Python package use the `ghostbrain-` prefix — Poltergeist's original codename. A rename is on the roadmap; until then, the commands below are correct as written. The packaged desktop app bundles every one of them into a single `ghostbrain-api <subcommand>` binary; a source/pip install gets them as separate `ghostbrain-<subcommand>` scripts instead.

### 1. Install

Grab the installer for your OS from [GitHub Releases](https://github.com/nikrich/poltergeist/releases)
(macOS `.dmg`, Windows `Setup.exe`, Linux `.AppImage`/`.deb`). The app is
self-contained: on first launch it creates the vault at `~/ghostbrain/vault/`
and everything except LLM features works immediately. LLM features (chat,
digests) additionally need the [Claude Code CLI](https://claude.com/claude-code)
installed and logged in.

Connector setup (gmail, slack, github, …) uses the bundled CLI — no Python
install needed. On macOS, Settings → background → "command line tool" installs
a `poltergeist` command; elsewhere invoke the bundled binary directly
(e.g. `<install dir>/resources/sidecar/ghostbrain-api/ghostbrain-api gmail-auth you@example.com`;
on Windows the binary is `ghostbrain-api.exe`).
The developer setup (`pip install -e .`) is only for working on Poltergeist itself — see [Contributing](#contributing).

### 2. Verify Claude Code is logged in

LLM calls run as `claude -p "<prompt>" --output-format json`, inheriting your existing Claude login:

```bash
claude --version
claude     # interactive — quit out once you see the prompt
```

### 3. Bootstrap the vault

The desktop app does this automatically on first launch. Running from a source/pip install instead? Bootstrap manually:

```bash
ghostbrain-bootstrap                          # idempotent — creates ~/ghostbrain/vault/
export VAULT_PATH="$HOME/ghostbrain/vault"    # or point it anywhere you like
```

Either way, open the vault in Obsidian and install the community plugins it relies on: **Dataview, Templater, Periodic Notes, Local REST API**.

### 4. Connect a source

Every connector is the same shape: create a credential → authenticate → add its block to `<vault>/90-meta/routing.yaml` → fetch. GitHub is the quickest first one — it reuses your `gh` login:

```bash
gh auth login                                       # if not already logged in
# add to <vault>/90-meta/routing.yaml:
#   github:
#     orgs: { your-org: personal }
ghostbrain-api github-fetch --dry-run               # preview — queues nothing
ghostbrain-api github-fetch                         # queue events
ghostbrain-api worker                               # turn queued events into vault notes
```

(Source/pip install: drop the `ghostbrain-api` prefix, e.g. `ghostbrain-github-fetch`, `ghostbrain-worker`.)

Commands below are subcommands — prefix with `ghostbrain-api ` (app) or `ghostbrain-` (source/pip install):

| Connector | Authenticate | You'll need |
|---|---|---|
| GitHub | uses `gh` | `gh auth login` |
| Gmail | `gmail-auth <email>` | Google Desktop OAuth client JSON |
| Calendar (Google) | `calendar-auth google <email>` | same Google OAuth client |
| Slack | `slack-token-add <slug> <xoxp>` | Slack app + user token (`xoxp-…`) |
| Jira / Confluence | env `ATLASSIAN_EMAIL` + `ATLASSIAN_TOKEN` | Atlassian API token |
| Joplin | token in `routing.yaml` | Joplin Web Clipper token |
| Microsoft (Outlook / Teams) | `microsoft-auth` | Entra app (client id + tenant id) |
| Claude Code | SessionEnd hook | — |

Full per-connector walkthroughs — OAuth scopes, routing rules, scheduling, caveats — live in **[docs/connectors.md](./docs/connectors.md)**. For an agent-guided setup of any connector, use the `onboarding-poltergeist` skill in `.claude/skills/`.

> Connectors are wired up from the CLI + `routing.yaml` for now — the desktop app's "connect" buttons are placeholders.

### 5. Keep it running

The desktop app's sidecar runs all connectors and the worker on an asyncio scheduler — no launchd, systemd, or Task Scheduler required. Enable it in **Settings → Scheduler**, or set `GHOSTBRAIN_SCHEDULER_ENABLED=1` before launching `ghostbrain-worker`. Prefer OS-native scheduling? Templates for [launchd](./docs/install/macos-launchd.md), [systemd](./docs/install/linux.md), and [Task Scheduler](./docs/install/windows.md) are included.

## Query your vault from Claude (MCP)

Poltergeist ships an MCP server so Claude Code & Desktop can query your vault mid-task — ask it questions, search it, read notes:

```bash
pip install -e ".[mcp]"     # adds the ghostbrain-mcp entrypoint
```

(Using the packaged app instead? Point `.mcp.json` at the bundled binary's `mcp` subcommand — `<install dir>/resources/sidecar/ghostbrain-api/ghostbrain-api mcp` — no pip install needed.)

Add to your `.mcp.json` (project scope) or `~/.claude.json` (user scope):

```json
{ "mcpServers": { "poltergeist": { "command": "ghostbrain-mcp" } } }
```

The server forwards to the running desktop-app sidecar (it must be open). Tools: `poltergeist_ask` (RAG answer + citations), `poltergeist_search` (ranked hits), `poltergeist_get_note` (full note by path). The `poltergeist-recall` skill in `.claude/skills/` automates the wiring and tells Claude when to use it.

## Privacy & data ownership

- **Everything is local.** The vault, the queue, the audit log, and all credentials live on your machine. There is no Poltergeist cloud and no telemetry.
- **Verbatim content stays verbatim.** Connectors store ticket descriptions, emails, and messages as-is. If your sources contain sensitive data, so does your vault — it's local-only by default; think before pushing it to a remote.
- **Every decision is auditable.** The worker writes each routing and processing decision to `90-meta/audit/<date>.jsonl`, and new connectors default to review-only mode so you can spot-check accuracy before going live.
- **Budget-capped LLM calls.** Every call carries a `--max-budget-usd` cap, and models per task (routing, extraction, digest) are configurable in `config.yaml`.

## Documentation

| Guide | Covers |
|---|---|
| [Connector setup](./docs/connectors.md) | Per-connector auth, routing, scheduling, and caveats |
| [Operations](./docs/operations.md) | Daily/weekly digests, profile auto-update, `CLAUDE.md` generation, LLM config, install verification |
| [Install notes](./docs/install/) | macOS launchd, Linux systemd, Windows Task Scheduler |
| [SPEC.md](./spec/SPEC.md) | The full system specification — architecture, vault structure, build phases |

## Repo layout

```
poltergeist/
├── spec/SPEC.md              # source of truth — read first
├── ghostbrain/               # Python package (connectors, worker, LLM client, MCP server)
├── desktop/                  # Electron desktop app + Python sidecar
├── plugins/                  # bundled desktop-app plugins
├── orchestration/            # SessionEnd hook + launchd templates
├── docs/                     # setup + operations guides
├── website/                  # getpoltergeist.com
└── tests/
```

## Contributing

Poltergeist is alpha and the surface area will change between phases. Issues and PRs are welcome — please open an issue first to discuss substantive changes. New connectors and prompt improvements are particularly useful; the connector pattern is documented in [docs/connectors.md](./docs/connectors.md#adding-a-new-connector).

### Developer setup

Working on Poltergeist itself (not just using it)? Set up the repo from source:

```bash
git clone https://github.com/nikrich/poltergeist.git && cd poltergeist
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

This gives you the full `ghostbrain-*` CLI, the test suite, and the desktop app's Python sidecar in dev mode. Run the suites with `pytest tests/ -q` and `cd desktop && npm test`.

If you're a coding agent working on this repo: read [spec/SPEC.md](./spec/SPEC.md) end-to-end, determine the current phase from `git log --oneline`, work on the next phase only ([acceptance criteria in §9](./spec/SPEC.md#section-9--build-sequence-phased)), and commit each phase with its name in the message.

## License

[MIT](./LICENSE)
