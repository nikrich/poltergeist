# Connector setup

Every Poltergeist connector follows the same shape: **create a credential → authenticate → connect the account → fetch.** Authenticating (or the app's "connect" flow) registers the account in `<vault>/90-meta/accounts.yaml`; the desktop app's connector cards do the first three for most connectors. This page is the full per-connector reference. For a guided walkthrough, use the `poltergeist-setup` Claude Code skill (see the README).

> **Command names.** Commands below are written as `poltergeist <sub>`, the shim the app installs from Settings → background → "command line tool". The same subcommands are available as `ghostbrain-api <sub>` (the bundled binary, at `/Applications/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api` on macOS) and, on a `pip install` from source, as `ghostbrain-<sub>`.

- [Multiple accounts and contexts](#multiple-accounts-and-contexts)
- [Claude Code sessions](#claude-code-sessions)
- [GitHub](#github)
- [Jira + Confluence](#jira--confluence)
- [Calendar (Google)](#calendar-google)
- [Gmail](#gmail)
- [Google Drive](#google-drive)
- [Slack](#slack)

## Multiple accounts and contexts

Every account-bearing connector (`gmail`, `gdrive`, `calendar_google`, `slack`, `jira`, `confluence`, `github`, `microsoft`) supports any number of accounts. Manage contexts and accounts through the app or by hand-editing files.

### Managing contexts in the app

**Create, archive, and restore contexts** in Settings → Projects (the contexts section at the top). Contexts are permanent fixtures in your vault — names start with a letter or digit, use lowercase letters/digits/hyphens, and max 40 characters; names YAML would read as a number, boolean or date (e.g. `2024`, `yes`, `off`) are rejected — add a letter. Archived contexts keep their notes intact; accounts and projects pointing at them stop routing there until you restore them. Archiving does not touch explicit `routing.yaml` rules (sender domains, labels, GitHub orgs, Confluence spaces, Claude Code paths) — any that name the archived context still file notes there until you edit them. The app rewrites the `contexts:` and `archived_contexts:` lists in `<vault>/90-meta/routing.yaml`, preserving all other content (including comments).

> **Comments caveat (pre-existing).** Some connect flows — Joplin, Atlassian (Confluence spaces), Claude Code, and the Microsoft app config — rewrite the whole of `routing.yaml` and drop its comments. Keep a copy if you rely on them.

### Managing accounts in the app

Each connector's detail panel lists all registered accounts with health status (`syncing`, `needs re-auth`, `error`, or `not synced yet`). For each account you can:

- **Assign or change its context** — pick one from your contexts, or leave unassigned (routes through the LLM).
- **Enable / disable** — disabled accounts don't sync but remain registered.
- **Reauthorize** — re-run the auth flow if the account needs re-auth.
- **Remove** — unregister the account from `accounts.yaml` and delete its stored credentials (token files, the MSAL account, or the Atlassian API token — unless the other Atlassian app still uses that site). Re-adding it means signing in again.
- **Add another account** — connect a new account of the same connector type (e.g., a second Gmail account, a different Slack workspace).

### Per-account data file

Per-account configuration lives in `<vault>/90-meta/accounts.yaml`, which you can also edit by hand. The file is seeded once from any legacy per-account `routing.yaml` blocks the first time it's read:

```yaml
version: 1
accounts:
  - connector: gmail
    id: you@gmail.com
    context: personal                # optional; omitted = unassigned
    enabled: true                    # optional, default true
    options:                         # connector-specific, all optional
      monitored_labels: []
      unread_lookback_hours: 24
  - connector: slack
    id: agencyx                      # workspace slug
    context: agencyx
    options: { mode: mentions, lookback_hours: 24 }
  - connector: jira
    id: agencyx.atlassian.net        # site host
    context: agencyx
    options: { email: you@agencyx.com }  # the email for this site's API token
```

**Accounts start unassigned.** Connecting an account in the app (or via a `ghostbrain-*-auth` CLI) registers it in `accounts.yaml` with no `context` — it keeps syncing and its events fall through to the LLM router until you set `context:` on that entry, which routes everything from that account straight to the named context with no LLM call.

**Connecting the same connector again adds another account** — there's no limit, and each account is tracked (and can fail or need re-auth) independently.

**Routing order.** In `_fast_route`, the existing specific rules keep winning first (Claude Code project path, GitHub org, Confluence space, Joplin notebook, Gmail sender domain, Gmail label prefix, macOS calendar name). If none of those match, a new **account rule** runs before the LLM: it looks up the event's account in `accounts.yaml` and, if that account has a `context`, routes there (`method: "account"`, confidence 0.95). Only if the account is unassigned (or unknown) does the event fall through to the LLM router.

**Per-account failure isolation.** Each account's health is tracked separately (`ok`, `auth_required`, or `error`) and surfaced by `GET /v1/connectors/{id}`. If only some of a connector's accounts fail in a run, the others keep syncing normally and the failed ones show `needs re-auth` / `error` for just that account. If *every* account of a connector fails in a run, the connector reports "all accounts failed" and its sync window does **not** advance — the backlog is picked up on the next run instead of being skipped.

**GitHub** has no per-login "connect" step — it inherits whatever you're logged into via `gh auth login`. If you register GitHub accounts in `accounts.yaml`, every registered `gh` login is fetched (org filtering in `github.orgs` still limits what's pulled, and GitHub org rules still win routing over the account rule); with none registered, it fetches whichever login `gh` is currently authenticated as, as before.

**Microsoft** (Outlook Mail, Teams Chat, Teams Meetings) is one account covering all three. If no Microsoft account is listed in `accounts.yaml`, those connectors keep using the first signed-in Microsoft account from the MSAL cache, same as before.

No secrets are ever stored in `accounts.yaml` — tokens stay exactly where they are today (OS keychain / `state/*.token` / `.env`).

**Per-run limits apply per account.** Caps such as `max_messages_per_run` (Outlook, Teams Chat) and the per-run thread/result limits of Gmail, Slack, Jira and Confluence are applied to each account's fetch, so a connector with several accounts can pull up to that many items per account per run.

**Re-seeding.** Deleting `accounts.yaml` makes it re-seed from `routing.yaml`'s legacy per-account blocks (plus live `gh` / Microsoft logins) on the next start; accounts you connected or assigned since are lost unless they're also in those blocks.

## Claude Code sessions

Poltergeist reads finished Claude Code sessions via a `SessionEnd` hook and processes them through the worker pipeline:

```
SessionEnd hook → queue → worker → router → note generator → (extractor)
```

**Wire up the hook** by running `poltergeist setup install-hook`, or use the app's Claude Code card, which does the same.

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
    YourOrg: consulting
    YourEmployer: work
    YourSideProject: side
```

Owners not in the map fall through to the LLM router (and likely `needs_review`).

Run manually:

```bash
poltergeist github-fetch                # queue events for the worker
poltergeist github-fetch --dry-run      # preview without enqueueing
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

`<SITE>` is the site slug (the host's first label) uppercased, with `-` → `_` — e.g. `yourco.atlassian.net` → `ATLASSIAN_TOKEN_YOURCO`, `your-co.atlassian.net` → `ATLASSIAN_TOKEN_YOUR_CO`. A single shared `ATLASSIAN_TOKEN` works as a fallback if you only have one site. Connecting a site in the app instead stores its token in `~/.ghostbrain/state/atlassian.<slug>.token` and its email in the site's `accounts.yaml` entry as `options.email` (the per-site email, which wins over `ATLASSIAN_EMAIL`); the token itself never goes in `accounts.yaml`. If `.env` already has `ATLASSIAN_TOKEN_<SITE>` for that site, reconnecting overwrites it with the new token (see [Multiple accounts and contexts](#multiple-accounts-and-contexts)).

Sites are accounts — connect them in the app, or add them to `<vault>/90-meta/accounts.yaml` directly:

```yaml
accounts:
  - connector: jira
    id: yourco.atlassian.net          # site → context
    context: work
  - connector: confluence
    id: yourco.atlassian.net
    context: work
```

Confluence space keys still map to a context in `routing.yaml`:

```yaml
confluence:
  spaces:
    DOCS: work                        # space key → context
    PROJ: work
```

Find space keys in any Confluence page URL: `.../wiki/spaces/<KEY>/...`.

Run manually:

```bash
poltergeist jira-fetch [--dry-run]
poltergeist confluence-fetch [--dry-run]
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
4. Accounts are registered in `<vault>/90-meta/accounts.yaml` when you authenticate (step 5); assign each a context there:
   ```yaml
   accounts:
     - connector: calendar_google
       id: you@gmail.com
       context: personal
     - connector: calendar_google
       id: you@workspace.com
       context: work
   ```
5. Run the consent flow once per account:
   ```bash
   poltergeist calendar-auth google you@gmail.com
   poltergeist calendar-auth google you@workspace.com
   ```
   Each opens a browser; refresh tokens land at `~/.ghostbrain/state/google_calendar.<slug>.token`.

### Run

```bash
poltergeist calendar-fetch [--dry-run]
```

Or schedule via launchd:

```bash
launchctl load ~/Library/LaunchAgents/com.ghostbrain.calendar.plist
```

Polls every hour. Events land at `<vault>/20-contexts/<ctx>/calendar/<file>.md`. The daily digest's `## Today` section reads them by `start` frontmatter.

### Caveat: refresh-token expiry

Google External-app + Test mode expires refresh tokens after ~7 days. For long-term use either:

- Publish your OAuth consent screen (button on the consent screen page). Calendar.readonly scope may not require formal verification for single-user personal apps.
- Re-run `poltergeist calendar-auth google <email>` weekly.

## Gmail

Polls one or more Gmail accounts. Surfaces threads that are either unread within the last 24h or carry a monitored label. Events route via sender domain (strongest signal) or label prefix; everything else falls through to the LLM router.

### One-time setup

Reuses the same OAuth client you set up for the calendar connector. If you skipped that, do steps 1–3 from the calendar setup first (Google Cloud project + OAuth consent screen + Desktop OAuth client at `~/.ghostbrain/state/google_oauth_client.json`). Then enable the **Gmail API** in the same project.

1. Run consent once per account — this also registers the account, unassigned, in `<vault>/90-meta/accounts.yaml`:
   ```bash
   poltergeist gmail-auth you@gmail.com
   ```
   Refresh token lands at `~/.ghostbrain/state/gmail.<slug>.token`.
2. Assign each account a context (and, optionally, its own labels/lookback) in `accounts.yaml`:
   ```yaml
   accounts:
     - connector: gmail
       id: you@gmail.com
       context: personal
       options:
         monitored_labels: ["work/important", "consulting/internal"]
         unread_lookback_hours: 24
   ```
   Sender-domain and label routing (which win over the account's own context) still live in `routing.yaml`:
   ```yaml
   gmail:
     sender_domains:
       company.example.com: work
       client.example.com: consulting
     label_prefixes:
       "work/": work
       "consulting/": consulting
   ```

### Run

```bash
poltergeist gmail-fetch [--dry-run]
```

Threads land in `<vault>/00-inbox/raw/gmail/` and route to `<vault>/20-contexts/<ctx>/gmail/`.

### Filtering philosophy

Gmail is noisy, so the connector deliberately doesn't pull "all mail":

- Domain-routed mail (e.g., `@company.example.com`) lands no matter what.
- Labeled mail (e.g., `work/important`) lands no matter what.
- Everything else only shows up while it's still **unread** within the configured lookback window — once you've read a newsletter, it stops appearing in future fetches.

If something important keeps slipping through, add a sender_domain or label rule rather than widening the unread filter.

### Backfilling past mail

The daily fetch above only looks at the last 24h. To index older mail for an account, open **Connectors → Gmail** in the app and click **backfill…** on that account's row, then choose how far back to go — 1, 2, 3 (default) or 5 years.

- **What's included:** threads you took part in — sent by you, replied to, starred, or marked important — minus anything in Gmail's Promotions category and any domain listed in `gmail.denylist_domains` (`routing.yaml`).
- **How it's processed:** each thread is routed the same way as daily mail — sender-domain/label rules first, then the account's own context, then the LLM router — but backfill skips the daily sync's relevance gate entirely, since taking part in a thread is itself the relevance signal.
- **Pace:** up to ~750 threads/hour (25 threads every 2 minutes; slower when AI routing is needed). It runs in small batches between other jobs, each capped at about a minute. A multi-year backfill can take hours to finish; that's expected. Assigning the account a context (on its row) avoids AI routing for its mail and speeds the backfill up.
- **Pause / resume / cancel:** the dialog and the account row show progress once a backfill starts, with buttons to pause, resume, or cancel it. Cancelling stops the job but keeps every note already imported — nothing is deleted.
- **Restarts:** progress is saved to a per-account state file after every thread, so a backfill picks up where it left off after an app restart or crash — no thread is re-imported twice.
- **Requires the in-app scheduler:** backfill is driven by the same scheduler as the rest of Poltergeist's background work, so **Settings → Background → "Run scheduler in-app"** must be on. If it's off, starting a backfill is blocked with a message explaining why.
- **Re-auth:** if the account's Gmail token expires mid-backfill, the row shows "needs re-auth" — click **reauthorize**, complete the OAuth flow, then **resume** to continue from where it stopped.
- **Transient errors:** ordinary Gmail API hiccups (rate limits, timeouts) are retried automatically on the next tick; they don't stop the backfill or require any action.
- **AI routing outages:** if the LLM router fails for 5 threads in a row (they land in `needs_review`), the backfill stops with "AI routing unavailable — resume later". Click **resume** once the LLM provider works again.

## Google Drive

Imports Google Docs, Google Sheets, PDFs, Word (`.docx`) and Excel (`.xlsx`) files **you own or have edited** — one note per file under `<vault>/20-contexts/<ctx>/gdrive/`, named `<title>-<fileId>.md` and updated in place when the file changes (its context is kept; no re-routing). Files only shared with you, not owned or edited, are ignored.

### One-time setup

1. Reuse the Desktop OAuth client from Gmail/Calendar (`~/.ghostbrain/state/google_oauth_client.json`). If you skipped those, do steps 1–3 from the [calendar setup](#calendar-google) first.
2. In that client's Google Cloud project, enable the **Google Drive API**, **Google Docs API** and **Google Sheets API** (APIs & Services → Library) — all three, since Docs and Sheets need their own APIs beyond Drive itself. A missing one surfaces on the connector as `Enable the Google <Drive|Docs|Sheets> API in Google Cloud for your OAuth client's project (APIs & Services → Library)`, naming the specific API that's missing.
3. Connect in the app: Connectors → Google Drive → add account. This registers the account, unassigned, in `<vault>/90-meta/accounts.yaml` — assign it a context the same way as any other account-bearing connector (see [Multiple accounts and contexts](#multiple-accounts-and-contexts)).

### Run

- **Hourly sync:** files modified since the account's last run (first run: last 7 days), kept only if you own them or have edited them. Files edited in the last 30 minutes wait for the next run (a 30-minute debounce, so a file mid-edit isn't imported half-written). New files become notes; changed files are rewritten in place — same note, same context, no re-routing.
- **Backfill:** Connectors → Google Drive → account → **backfill…**, to index older files (1–5 years). See below.

### Backfilling past files

The hourly sync above only looks back 7 days on first run. To index older files for an account, open **Connectors → Google Drive** in the app and click **backfill…** on that account's row, then choose how far back to go — 1, 2, 3 (default) or 5 years.

- **What's included:** files you own or have edited (Drive's `ownedByMe` or `modifiedByMe`) — the same filter the hourly sync applies. Files merely shared with you are skipped.
- **How it's processed:** each file goes through the same ingest path as the hourly sync — new files become notes, changed files are rewritten in place (context kept, no re-routing), and files already imported and unchanged are left alone. The account row and dialog report five running counts: imported, updated, already had (unchanged, skipped), failed, and too large.
- **Pace:** up to ~750 files/hour (25 files every 2 minutes; slower when AI routing is needed). It runs in small batches between other jobs, walking backwards month by month, each tick capped at about a minute. A multi-year backfill can take hours to finish; that's expected. Assigning the account a context (on its row) avoids AI routing for its files and speeds the backfill up.
- **Pause / resume / cancel:** the dialog and the account row show progress once a backfill starts, with buttons to pause, resume, or cancel it. Cancelling stops the job but keeps every note already imported — nothing is deleted.
- **Restarts:** progress is saved to a per-account state file after every file, so a backfill picks up where it left off after an app restart or crash — re-processing a file is harmless since ingest always upserts the same note.
- **Requires the in-app scheduler:** backfill is driven by the same scheduler as the rest of Poltergeist's background work, so **Settings → Background → "Run scheduler in-app"** must be on. If it's off, starting a backfill is blocked with a message explaining why.
- **Re-auth:** if the account's Drive token expires mid-backfill, the row shows "needs re-auth" — click **reauthorize**, complete the OAuth flow, then **resume** to continue from where it stopped.
- **API not enabled:** if the Drive, Docs or Sheets API isn't enabled on the OAuth client's project, the backfill stops with the same `Enable the Google <API> API…` message the hourly sync shows. Enable the named API in Google Cloud, then **resume** — no reauthorize needed, since the account's own credentials were fine.
- **Transient errors:** ordinary Drive API hiccups (rate limits, timeouts) are retried automatically on the next tick; they don't stop the backfill or require any action.
- **AI routing outages:** if the LLM router fails for 5 files in a row (they land in `needs_review`), the backfill stops with "AI routing unavailable — resume later". Click **resume** once the LLM provider works again.

### Limits

Files over 200 MB are skipped (reported as "too large"). Sheets: first 50 tabs, 5,000 rows × 50 columns per tab. Note bodies are capped at 1,000,000 characters. Truncation is marked in the note (`_…truncated at 5,000 rows_`, `_…truncated at 50 columns_`, `_…N more tabs_`, `_…truncated (document continues in Drive)_`); a file with no extractable text notes `_No extractable text — open in Drive._` instead of an empty body.

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
   poltergeist slack-token-add <slug> xoxp-...your-token...
   ```
   The slug is whatever you'll use in `accounts.yaml`. The CLI verifies the token by calling `auth.test`, writes it 0600 to `~/.ghostbrain/state/slack.<slug>.token`, and registers the workspace, unassigned, in `<vault>/90-meta/accounts.yaml`.
5. Assign the workspace a context in `<vault>/90-meta/accounts.yaml`:
   ```yaml
   accounts:
     - connector: slack
       id: work-workspace
       context: work
       options: { lookback_hours: 24, mode: mentions }
     - connector: slack
       id: consulting
       context: consulting
   ```
   A workspace with no `context` still gets polled — its mentions just fall through to the LLM router instead of routing instantly.

Repeat for each workspace.

### Run

```bash
poltergeist slack-fetch [--dry-run]
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
