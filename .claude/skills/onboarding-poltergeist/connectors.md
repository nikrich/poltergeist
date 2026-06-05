# Connector setup reference

Per-connector detail for `onboarding-poltergeist`. Each connector = (1) create an external credential, (2) authenticate, (3) add its `routing.yaml` block, (4) fetch to verify. All paths assume default `~/ghostbrain/vault/` and state `~/.ghostbrain/state/`. Use generic placeholders below — substitute the user's real values into THEIR vault (never into the repo).

Routing maps source signals to a **context** (`sanlam`, `codeship`, `reducedrecipes`, `personal`). Below, `<ctx>` means one of those.

---

## gmail

**Credential (once):** Google Cloud project → enable **Gmail API** → OAuth consent screen (External; add the user as a Test user) → Credentials → OAuth client ID → **Desktop app** → download JSON to:
```bash
mkdir -p ~/.ghostbrain/state
mv ~/Downloads/client_secret_*.json ~/.ghostbrain/state/google_oauth_client.json && chmod 600 $_
```
**Authenticate:** `ghostbrain-gmail-auth you@example.com` (browser consent; token → `~/.ghostbrain/state/gmail.<slug>.token`). Scope: `gmail.readonly`.
**routing.yaml:**
```yaml
gmail:
  accounts:
    you@example.com:
      monitored_labels: ["work/important"]
      unread_lookback_hours: 24
  denylist_domains: []          # exact or *.subdomain — dropped before the LLM gate
  relevance_gate: true          # Haiku relevance filter
  label_prefixes: { "work/": <ctx> }      # fast routing (optional)
  sender_domains: { "company.example.com": <ctx> }   # strongest routing signal (optional)
```
**Noise model:** a thread surfaces only if it has a monitored label OR is unread within `unread_lookback_hours`; then denylist + Haiku gate apply. **Verify:** `ghostbrain-gmail-fetch --dry-run`.

---

## calendar (google)

Reuses the SAME `google_oauth_client.json` as gmail — just **enable the Google Calendar API** in the project.
**Authenticate:** `ghostbrain-calendar-auth google you@example.com` (token → `google_calendar.<slug>.token`; scope `calendar.readonly`).
**routing.yaml:**
```yaml
calendar:
  google:
    accounts: { you@example.com: <ctx> }
```
**Verify:** `ghostbrain-calendar-fetch --dry-run`.

## calendar (macOS)

No auth — reads Apple Calendar via EventKit/JXA. Grant access in **System Settings → Privacy & Security → Calendars**.
```yaml
calendar:
  macos:
    accounts: { "default": <ctx> }
```

---

## slack

**Credential (once):** create a Slack app (https://api.slack.com/apps) → **OAuth & Permissions → User Token Scopes**: `search:read`, `users:read`, `team:read`, `channels:history`, `groups:history`, `im:history`, `mpim:history` → Install to workspace → copy the **User OAuth Token** (`xoxp-…`).
**Authenticate:** `ghostbrain-slack-token-add <workspace-slug> xoxp-…` (verifies via `auth.test`; token → `slack.<slug>.token`, 0600). Alt: env `SLACK_TOKEN_<UPPER_SLUG>`.
**routing.yaml:**
```yaml
slack:
  workspaces:
    <workspace-slug>:
      context: <ctx>
      lookback_hours: 24
      mentions_only: true
```
**Verify:** `ghostbrain-slack-fetch --dry-run`.

---

## github

**Credential:** the `gh` CLI, logged in (`gh auth login`) with access to the orgs. No token stored by ghostbrain — it shells out to `gh`.
**routing.yaml:**
```yaml
github:
  orgs: { your-org: <ctx> }
```
Pulls authored PRs, review-requested PRs, assigned issues (first run looks back 7 days). **Verify:** `ghostbrain-github-fetch --dry-run`.

---

## jira / confluence (shared Atlassian auth)

**Credential (once):** API token at https://id.atlassian.com/manage-profile/security/api-tokens. Provide via env (NOT source):
```bash
export ATLASSIAN_EMAIL="you@example.com"
export ATLASSIAN_TOKEN_YOURSITE="<api-token>"   # per-site: YOURSITE = host before .atlassian.net, upper-cased
# or a single ATLASSIAN_TOKEN fallback
```
**routing.yaml:**
```yaml
jira:
  sites: { yoursite.atlassian.net: <ctx> }
confluence:
  sites:  { yoursite.atlassian.net: <ctx> }      # falls back to jira.sites if omitted
  spaces: { SPACEKEY: <ctx> }
```
Health check hits `/rest/api/3/myself`. **Verify:** `ghostbrain-jira-fetch --dry-run`, `ghostbrain-confluence-fetch --dry-run`.

---

## joplin

**Credential:** in Joplin desktop → Tools → Options → **Web Clipper → Enable Web Clipper Service**; copy the token (default port 41184).
**routing.yaml:**
```yaml
joplin:
  token: "<web-clipper-token>"
  # host: "http://localhost:41184"   # only if you changed the port
  notebooks: { "Work": <ctx> }        # empty = ingest all notebooks
```
**Verify:** `ghostbrain-joplin-fetch --dry-run` (health check pings `/ping`).

---

## microsoft (outlook mail / teams chat / teams meetings)

All three share one Entra app + one device-code sign-in.

**Credential (once):** Entra ID → **App registrations → New registration** (public client). Under **Authentication** add platform "Mobile and desktop applications" and set **Allow public client flows = Yes**. Under **API permissions → Microsoft Graph → Delegated**, add the scopes you need and **Grant admin consent**:
- Teams meeting transcripts: `OnlineMeetings.Read`, `OnlineMeetingTranscript.Read.All`
- Calendar auto-discovery of meetings: also `Calendars.Read`
- Outlook mail: `Mail.Read` · Teams chat: `Chat.Read`

Copy the **Application (client) ID** and **Directory (tenant) ID**.

**routing.yaml** (IDs can instead be env `MS_GRAPH_CLIENT_ID` / `MS_GRAPH_TENANT_ID`):
```yaml
microsoft:
  client_id: "<application-client-id>"
  tenant_id: "<directory-tenant-id>"
  # Request ONLY the scopes you actually consented, or silent refresh fails:
  scopes: ["OnlineMeetings.Read", "OnlineMeetingTranscript.Read.All"]
  outlook_mail:   { unread_lookback_hours: 24, relevance_gate: true }
  teams_chat:     { max_messages_per_run: 100, relevance_gate: true }
  teams_meetings:
    body_cap_chars: 200000
    # Transcripts-only mode (no Calendars.Read / admin consent for calendar):
    meetings:
      - "https://teams.microsoft.com/l/meetup-join/...join-url..."   # or /meet/<id>, or a bare numeric ID
    # Omit `meetings` to auto-discover from the calendar instead (needs Calendars.Read):
    # calendar_lookback_days: 7
```
**Authenticate:** `ghostbrain-microsoft-auth` → prints a code + `microsoft.com/devicelogin` URL; sign in. One sign-in covers all three; token cached in the OS keychain (`~/.ghostbrain/state/microsoft/token_cache.bin`).
**Verify:** `ghostbrain-outlook-mail-fetch`, `ghostbrain-teams-chat-fetch`, `ghostbrain-teams-meetings-fetch`.

**Discovery note:** `getAllTranscripts` is application-only and unusable with delegated auth. So meetings discovery is either the configured `meetings:` list or the calendar walk (which needs the additional `Calendars.Read`). "Transcripts-only" means you avoid `Calendars.Read` + calendar auto-discovery — the two transcript scopes themselves may still require admin consent (tenant-dependent); that's separate.

---

## claude_code

Event-driven (not polling) — captures each Claude Code session via a **SessionEnd hook**.
**Setup:** add to `~/.claude/settings.json`:
```json
"hooks": { "SessionEnd": [{ "matcher": "*", "hooks": [
  { "type": "command", "command": "<repo>/orchestration/hooks/session-end.sh", "shell": "bash", "async": true }
]}]}
```
**routing.yaml** (path-first routing, longest-prefix wins):
```yaml
claude_code:
  project_paths:
    ~/development/work-repo: <ctx>
    ~/development/consulting: codeship
```
**Verify:** finish a Claude Code session, then check `vault/00-inbox/raw/claude-code/` for the captured transcript. No `.last_run`; "on" state = presence of inbox captures.

---

## After connectors: run the pipeline

```bash
ghostbrain-worker            # daemon: drains queue/pending → notes (+ audit log)
ghostbrain-digest            # daily digest → vault/10-daily/
ghostbrain-claude-md         # regenerate per-project CLAUDE.md from the profile
```
For the desktop app, enable **Settings → Run scheduler in-app** (sets `GHOSTBRAIN_SCHEDULER_ENABLED=1`) so connectors poll and the worker runs automatically. Flip `worker.routing_mode` in `config.yaml` from `review_only` to `live` once you trust the routing.
