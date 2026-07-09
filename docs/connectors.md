# Connector setup

Every Poltergeist connector follows the same shape: **create a credential → authenticate → add a block to `<vault>/90-meta/routing.yaml` → fetch.** This page is the full per-connector reference. For a guided, agent-driven walkthrough of any connector, use the `onboarding-poltergeist` skill in `.claude/skills/`.

> **Note on command names.** CLI binaries and the Python package use the `ghostbrain-` prefix — Poltergeist's original codename. The commands below are correct as written.

- [Claude Code sessions](#claude-code-sessions)
- [GitHub](#github)
- [Jira + Confluence](#jira--confluence)
- [Calendar (Google)](#calendar-google)
- [Gmail](#gmail)
- [Slack](#slack)

## Claude Code sessions

Poltergeist reads finished Claude Code sessions via a `SessionEnd` hook and processes them through the worker pipeline:

```
SessionEnd hook → queue → worker → router → note generator → (extractor)
```

**Wire up the hook** by adding this entry to `~/.claude/settings.json`:

```json
"hooks": {
  "SessionEnd": [{
    "matcher": "*",
    "hooks": [{
      "type": "command",
      "command": "/path/to/poltergeist/orchestration/hooks/session-end.sh",
      "shell": "bash",
      "async": true
    }]
  }]
}
```

The hook reads the standard SessionEnd payload from stdin (`session_id`, `transcript_path`, `cwd`, `reason`) and drops a normalized event into the queue. The worker picks it up within ~5 seconds.

**Routing is path-first.** If the project's path matches a rule in `<vault>/90-meta/routing.yaml:claude_code.project_paths`, the event is routed instantly with confidence 1.0 — no LLM call. Only paths without a rule fall through to the LLM router.

**Default mode is `review_only`.** Every event lands in `<vault>/00-inbox/raw/claude-code/` (always), but nothing is written under `20-contexts/<ctx>/` until you flip `worker.routing_mode` to `live` in `config.yaml`. The audit log captures every routing decision so you can spot-check accuracy before going live. [SPEC §9 Phase 3](../spec/SPEC.md#section-9--build-sequence-phased) recommends 2 weeks in review-only mode.

**Extractor.** In `live` mode, every Claude session also goes through the LLM extractor, which writes specs/decisions/code/prompts/unresolved items under `20-contexts/<ctx>/claude/artifacts/<type>/`.

## GitHub

Polls GitHub for PRs you authored, PRs requesting your review, and issues assigned to you — filtered to orgs in `<vault>/90-meta/routing.yaml` under `github.orgs`. Auth piggybacks on `gh auth login` so no token is needed.

Edit `<vault>/90-meta/routing.yaml` to map your orgs to contexts:

```yaml
github:
  orgs:
    YourOrg: codeship
    YourEmployer: work
    YourSideProject: side
```

Owners not in the map fall through to the LLM router (and likely `needs_review`).

Run manually:

```bash
ghostbrain-github-fetch                # queue events for the worker
ghostbrain-github-fetch --dry-run      # preview without enqueueing
```

PR notes land at `<vault>/20-contexts/<ctx>/github/prs/<owner>-<repo>-<number>.md`. Issues at `.../github/issues/`.

Schedule via launchd (every 2 hours):

```bash
launchctl load ~/Library/LaunchAgents/com.ghostbrain.github.plist
```

## Jira + Confluence

Connectors for Atlassian Cloud, polled separately:

- **Jira** — every 4 hours. Fetches tickets where you're assignee, reporter, or watcher, updated within the lookback window. JQL: see `ghostbrain/connectors/jira/__init__.py`.
- **Confluence** — daily at 06:00 (just before the digest at 06:30 so the day's edits show up). Fetches pages updated in monitored spaces.

Auth via Atlassian API tokens, read from your `.env` (never in source or vault):

```
ATLASSIAN_EMAIL=your.email@example.com
ATLASSIAN_TOKEN_<SITE>=<api token from id.atlassian.com>
```

`<SITE>` is the site slug uppercased — e.g. `yourco.atlassian.net` → `ATLASSIAN_TOKEN_SFT`. A single shared `ATLASSIAN_TOKEN` works as a fallback if you only have one site.

Configure sites + spaces in `<vault>/90-meta/routing.yaml`:

```yaml
jira:
  sites:
    yourco.atlassian.net: work        # site → context
confluence:
  sites:
    yourco.atlassian.net: work
  spaces:
    DOCS: work                        # space key → context
    PROJ: work
```

Find space keys in any Confluence page URL: `.../wiki/spaces/<KEY>/...`.

Run manually:

```bash
ghostbrain-jira-fetch [--dry-run]
ghostbrain-confluence-fetch [--dry-run]
```

Schedule via launchd:

```bash
launchctl load ~/Library/LaunchAgents/com.ghostbrain.jira.plist
launchctl load ~/Library/LaunchAgents/com.ghostbrain.confluence.plist
```

Notes land at `<vault>/20-contexts/<ctx>/jira/tickets/<KEY>.md` and `<vault>/20-contexts/<ctx>/confluence/<title>-<id>.md`.

**Heads up on body content.** Ticket descriptions and Confluence page bodies are stored verbatim. If your Atlassian tickets/pages contain PII or sensitive data, the vault has it too. The vault is local-only by default; think before pushing it to a git remote.

## Calendar (Google)

Polls your Google Calendar(s) hourly. Today's events appear in the morning digest's `## Today` section.

### One-time setup

1. Create a Google Cloud project at <https://console.cloud.google.com/projectcreate>. Enable the **Google Calendar API**.
2. Configure the **OAuth consent screen** as External, fill basic metadata, add yourself as a test user.
3. Create an **OAuth client ID** (type: "Desktop app"). Download the JSON to `~/.ghostbrain/state/google_oauth_client.json` and `chmod 600`.
4. Configure your accounts in `<vault>/90-meta/routing.yaml`:
   ```yaml
   calendar:
     google:
       accounts:
         you@gmail.com: personal
         you@workspace.com: work
   ```
5. Run the consent flow once per account:
   ```bash
   ghostbrain-calendar-auth google you@gmail.com
   ghostbrain-calendar-auth google you@workspace.com
   ```
   Each opens a browser; refresh tokens land at `~/.ghostbrain/state/google_calendar.<slug>.token`.

### Run

```bash
ghostbrain-calendar-fetch [--dry-run]
```

Or schedule via launchd:

```bash
launchctl load ~/Library/LaunchAgents/com.ghostbrain.calendar.plist
```

Polls every hour. Events land at `<vault>/20-contexts/<ctx>/calendar/<file>.md`. The daily digest's `## Today` section reads them by `start` frontmatter.

### Caveat: refresh-token expiry

Google External-app + Test mode expires refresh tokens after ~7 days. For long-term use either:

- Publish your OAuth consent screen (button on the consent screen page). Calendar.readonly scope may not require formal verification for single-user personal apps.
- Re-run `ghostbrain-calendar-auth google <email>` weekly.

## Gmail

Polls one or more Gmail accounts. Surfaces threads that are either unread within the last 24h or carry a monitored label. Events route via sender domain (strongest signal) or label prefix; everything else falls through to the LLM router.

### One-time setup

Reuses the same OAuth client you set up for the calendar connector. If you skipped that, do steps 1–3 from the calendar setup first (Google Cloud project + OAuth consent screen + Desktop OAuth client at `~/.ghostbrain/state/google_oauth_client.json`). Then enable the **Gmail API** in the same project.

1. Configure accounts and routing in `<vault>/90-meta/routing.yaml`:
   ```yaml
   gmail:
     accounts:
       you@gmail.com:
         monitored_labels: ["work/important", "consulting/internal"]
         unread_lookback_hours: 24
     sender_domains:
       company.example.com: work
       client.example.com: consulting
     label_prefixes:
       "work/": work
       "consulting/": consulting
   ```
2. Run consent once per account:
   ```bash
   ghostbrain-gmail-auth you@gmail.com
   ```
   Refresh token lands at `~/.ghostbrain/state/gmail.<slug>.token`.

### Run

```bash
ghostbrain-gmail-fetch [--dry-run]
```

Threads land in `<vault>/00-inbox/raw/gmail/` and route to `<vault>/20-contexts/<ctx>/gmail/`.

### Filtering philosophy

Gmail is noisy, so the connector deliberately doesn't pull "all mail":

- Domain-routed mail (e.g., `@company.example.com`) lands no matter what.
- Labeled mail (e.g., `work/important`) lands no matter what.
- Everything else only shows up while it's still **unread** within the configured lookback window — once you've read a newsletter, it stops appearing in future fetches.

If something important keeps slipping through, add a sender_domain or label rule rather than widening the unread filter.

## Slack

Polls one or more Slack workspaces for `@`-mentions of the authenticated user over the last 24h. Only mentions — no raw channel volume. Each mention routes via workspace slug (e.g., `work → work-context`) without an LLM call.

### One-time setup per workspace

1. Create a Slack app: `https://api.slack.com/apps` → **Create New App** → **From scratch** → name it, pick the workspace.
2. **OAuth & Permissions** → add **User Token Scopes**:
   - `search:read`
   - `users:read`
   - `team:read`
   - `channels:history`
   - `groups:history`
   - `im:history`
   - `mpim:history`
3. **Install to Workspace** → approve. Copy the **User OAuth Token** (starts with `xoxp-`).
4. Save the token:
   ```bash
   ghostbrain-slack-token-add <slug> xoxp-...your-token...
   ```
   The slug is whatever you'll use in `routing.yaml`. The CLI verifies the token by calling `auth.test` and writes it 0600 to `~/.ghostbrain/state/slack.<slug>.token`.
5. Configure the workspace in `<vault>/90-meta/routing.yaml`:
   ```yaml
   slack:
     workspaces:
       work-workspace:
         context: work
         lookback_hours: 24
         mentions_only: true
       consulting:
         context: consulting
   ```

Repeat for each workspace.

### Run

```bash
ghostbrain-slack-fetch [--dry-run]
```

Mentions land in `<vault>/00-inbox/raw/slack/` and route to `<vault>/20-contexts/<ctx>/slack/`. Each note's frontmatter carries `workspace_slug`, `channel_name`, `user_name`, `permalink`, `is_dm`, `thread_ts` — Dataview-friendly.

### Filtering philosophy

Mentions-only is the default because it's already a high-signal filter the user maintains in Slack itself. If you want to widen — say, ingest every message in a specific channel — that's an `--include-channels` flag the connector doesn't have yet. Open an issue if you need it.

### Caveat: admin-restricted workspaces

Slack workspaces with **Information Barriers** (common on enterprise plans) can silently filter user-token API responses — granting the scopes you ask for, then returning empty results when you call them. Symptoms:

- `auth.test` succeeds and reports the right team.
- `conversations.list` for `private_channel` returns `ok: true` with `channels: []` even though you're a member of dozens.
- `search.messages` returns `ok: true` with `total: 0` for every query.
- `users.conversations` shows `general` + `random` only, even though you actively chat in many private channels.

This is a tenant-side policy and there's no way around it from the API. Options: file an admin ticket, use a different workspace, or accept that the connector will produce nothing useful for that workspace.

The connector code itself is correct — it'll work the day it's pointed at a workspace where API access isn't policy-restricted.

## Adding a new connector

A connector is a class that subclasses `ghostbrain.connectors._base.Connector` and implements `fetch()`, `normalize()`, and `health_check()`. Five steps to add e.g. a Linear connector:

1. Create `ghostbrain/connectors/linear/`.
2. Implement `LinearConnector(Connector)`.
3. Register it in the connector registry.
4. Add routing rules in `<vault>/90-meta/routing.yaml`.
5. Add a schedule entry in `orchestration/launchd/`.

Prompts live in `<vault>/90-meta/prompts/` — edit them directly to tune classification, extraction, or digest tone.

See [SPEC §4](../spec/SPEC.md#section-4--connector-architecture) and [§4.4](../spec/SPEC.md#44-adding-a-new-connector).
