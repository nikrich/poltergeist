# Multi-Account Connectors — Design

**Status:** Approved in conversation 2026-09-27 (pending spec review)
**Origin:** A user working for several agencies wants to connect more than one account
per connector (two Gmails, three Slack workspaces, a Microsoft login per client tenant)
and have everything from an account indexed into that agency's context.

This is **spec A of two**. Spec B (in-app account management: contexts CRUD, "Add
account" per connector with its auth flow, remove / re-auth) builds on the registry and
read API defined here and is out of scope for this document.

## Problem

Account support is inconsistent across connectors, and account → context routing exists
for some connectors only:

| Connector | Multiple accounts today | Account → context rule today | Credential location |
|---|---|---|---|
| Gmail | yes (`gmail.accounts.<email>`) | **no** — `metadata.account` is emitted but ignored | `state/gmail.<slug>.token` |
| Google Calendar | yes (`calendar.google.accounts.<email>: ctx`) | yes | `state/google_calendar.<slug>.token` |
| Slack | yes (`slack.workspaces.<slug>.context`) | yes | `SLACK_TOKEN_<SLUG>` / `state/slack.<slug>.token` |
| Jira | yes (`jira.sites.<host>: ctx`) | yes | `.env`: one global `ATLASSIAN_EMAIL`, `ATLASSIAN_TOKEN[_<SLUG>]` |
| Confluence | yes (sites) | **no** — routes by space only | same as Jira |
| GitHub | **no** — whatever `gh` login is active | by org only | `gh` CLI keyring |
| Outlook / Teams | **no** — `get_accounts()[0]` | **no** — always LLM | MSAL cache (keychain / file) |

Per-account configuration is scattered across differently shaped `routing.yaml` blocks,
which the app cannot safely rewrite (hand-edited, comments would be lost).

There is also a reliability bug that multi-account makes acute: `GmailConnector.
health_check()` (`ghostbrain/connectors/gmail/connector.py:84`) returns `False` if **any**
account's token is missing or unrefreshable, and `run_connector`
(`ghostbrain/connectors/_runner.py`) then skips the whole run. Google refresh tokens in
Test-mode OAuth apps expire after ~7 days, so one lapsed account silently stops every
account.

Contexts themselves are already user-defined on `main` (`routing.yaml: contexts:` via
`ghostbrain/routing_config.py`, guarded by `tests/test_no_hardcoded_contexts.py`), and
projects (`90-meta/projects.json`) already sit under contexts. This spec does not change
either.

## Goals

1. Every account-bearing connector supports any number of accounts.
2. Each account can be assigned a context; everything it captures lands there without an
   LLM call, unless a more specific rule matches.
3. One account's broken credentials never stop other accounts (or the connector).
4. Per-account configuration lives in one app-owned file, so spec B can write it safely.
5. Per-account health is recorded and exposed over the API for spec B's UI.

## Non-goals

- Any desktop UI or auth flow started from the app (spec B).
- Creating / renaming / archiving contexts (spec B).
- Pinning an account to a single project (accounts map to contexts; the existing project
  step still runs inside the chosen context).
- A Poltergeist-owned Google OAuth client (restricted-scope verification).
- macOS Calendar, Claude Code, Joplin — local sources without accounts; their existing
  calendar-name / path / notebook rules are unchanged.
- Moving secrets into `accounts.yaml` or changing where existing tokens are stored.

## Design

### 1. `vault/90-meta/accounts.yaml`

```yaml
version: 1
accounts:
  - connector: gmail
    id: jannik811@gmail.com
    context: personal                # optional; omitted = unassigned
    enabled: true                    # optional, default true
    options:                         # connector-specific, all optional
      monitored_labels: []
      unread_lookback_hours: 24
  - connector: calendar_google
    id: jannik@agencyx.com
    context: agencyx
  - connector: slack
    id: agencyx                      # workspace slug
    context: agencyx
    options: { mode: mentions, lookback_hours: 24 }
  - connector: jira
    id: agencyx.atlassian.net        # site host
    context: agencyx
    options: { email: jannik@agencyx.com }
  - connector: confluence
    id: agencyx.atlassian.net
    context: agencyx
    options: { email: jannik@agencyx.com }
  - connector: github
    id: nikrich                      # gh login
    context: personal
  - connector: microsoft
    id: jannik@agencyy.com           # MSAL username; feeds outlook_mail + teams_*
    context: agencyy
    options: { tenant_id: <guid> }   # optional; overrides microsoft.tenant_id
```

Rules:

- **Account connectors:** `gmail`, `calendar_google`, `slack`, `jira`, `confluence`,
  `github`, `microsoft`. Unknown values are ignored with a warning.
- **Identity:** `(connector, id)` is unique; `id` is compared case-insensitively
  (stored as written, matched lower-cased).
- **Microsoft is one account** covering Outlook Mail, Teams Chat and Teams Meetings — one
  login, one MSAL cache entry. Google stays split (`gmail` / `calendar_google`) because the
  two already have separate tokens and consent; a user can connect Gmail without Calendar.
  Jira and Confluence are split per site for the same reason.
- **No secrets** in this file. Tokens stay where they are today. The only addition is a
  per-account file fallback for Atlassian tokens (§3), so spec B can store a pasted token
  without editing `.env`.
- **`context`** must be one of `routing_config.contexts()`. An account whose context is
  missing from that list (archived / renamed) is treated as unassigned — it keeps syncing
  and falls through to the LLM. Nothing is dropped.
- **Connector-wide settings stay in `routing.yaml`:** `gmail.denylist_domains`,
  `gmail.sender_domains`, `gmail.label_prefixes`, `gmail.relevance_gate`,
  `gmail.relevance_model`, `confluence.spaces`, `github.orgs`, `microsoft.client_id`,
  `microsoft.tenant_id`, `microsoft.outlook_mail.*`, etc. Only per-account data moves.

**Migration — seed once.** The first time the registry is read and `accounts.yaml` does
not exist, it is seeded and written atomically from:

| Source | Seeded as |
|---|---|
| `gmail.accounts.<email>: {…}` | `gmail`, options = the per-account dict, no context |
| `calendar.google.accounts.<email>: ctx` | `calendar_google`, context = ctx |
| `slack.workspaces.<slug>: {context, …}` | `slack`, context = `context`, options = rest |
| `jira.sites.<host>: ctx` | `jira`, context = ctx |
| `confluence.sites` (else `jira.sites`) | `confluence`, context = the jira site's ctx if any |
| logins listed by `gh auth status` for github.com | `github`, no context |
| `app.get_accounts()` in the MSAL cache | `microsoft`, no context |

Seeding `github` / `microsoft` is best-effort: failure to enumerate logs a warning and
seeds nothing for that connector. After seeding, `accounts.yaml` is the only source of
per-account data; the old `routing.yaml` blocks are ignored with a one-time log line.
There is deliberately no permanent fallback — two live sources would make "why did this
land there?" unanswerable.

### 2. Registry, event tagging, router, health

**`ghostbrain/accounts.py`** is the only module that reads or writes `accounts.yaml`:

```python
@dataclass(frozen=True)
class Account:
    connector: str
    id: str
    context: str | None
    enabled: bool
    options: dict

def list_accounts(connector: str | None = None, *, root: Path | None = None,
                  include_disabled: bool = False) -> list[Account]   # seeds on first call
def get_account(connector: str, id: str) -> Account | None
def context_for(connector: str | None, id: str | None) -> str | None
    # None when unassigned, unknown, or context not in routing_config.contexts()
def upsert_account(acc: Account) -> None     # validates connector + context; spec B uses it
def remove_account(connector: str, id: str) -> None

SOURCE_TO_ACCOUNT_CONNECTOR: dict[str, str]  # event source → account connector
```

Writes use temp-file + `os.replace` (same pattern as `ghostbrain/api/repo/settings.py`)
under an exclusive `fcntl` lock on `90-meta/.accounts.lock` (the scheduler and API share
the sidecar process but run concurrently; auth CLIs are separate processes). A malformed
`accounts.yaml` logs a warning and yields an empty list — it never falls back to
`routing.yaml`, so a typo cannot silently re-route.

**Event tagging.** Every account connector sets `metadata.accountId` to the matching
`Account.id`:

| Event `source` | Account connector | `accountId` value |
|---|---|---|
| `gmail` | `gmail` | account email (already in `metadata.account`) |
| `calendar` (provider `google`) | `calendar_google` | account email (already in `metadata.account`) |
| `slack` | `slack` | `metadata.workspace_slug` |
| `jira` | `jira` | `metadata.site` |
| `confluence` | `confluence` | `metadata.site` |
| `github` | `github` | gh login the fetch ran as (**new**) |
| `outlook_mail`, `teams_chat`, `teams_meetings` | `microsoft` | MSAL username (**new**) |

`calendar` events from provider `macos` map to no account connector and are unaffected.

**Router.** In `_fast_route` (`ghostbrain/worker/router.py`) the specific rules keep
their current order and behaviour: Claude Code project path, GitHub org, Confluence
space, Joplin notebook, Gmail sender domain, Gmail label prefix, macOS calendar name.
If none matches, one new rule runs before the LLM:

```python
acct_ctx = accounts.context_for(
    accounts.SOURCE_TO_ACCOUNT_CONNECTOR.get(source), metadata.get("accountId"))
if acct_ctx:
    return RoutingDecision(context=acct_ctx, confidence=0.95, method="account",
                           reasoning=f"account {account_id} → {acct_ctx}")
```

The rules this replaces are **removed**: Slack `workspaces.<slug>.context`, Google
Calendar `calendar.google.accounts`, and Jira `jira.sites` (the site is the account).
The macOS Calendar branch of the calendar rule stays. `method="account"` is a new value
of the free-form `RoutingDecision.method` string; `note_generator.py` records it as
`routingMethod` and digests display it verbatim — no enum to extend. Project selection
inside the chosen context runs as today.

**Per-account health** — `state/accounts_health.json`:

```json
{
  "gmail:jannik811@gmail.com": {
    "status": "ok",              // ok | auth_required | error
    "checkedAt": "2026-09-27T10:00:00+00:00",
    "lastSuccessAt": "2026-09-27T10:00:00+00:00",
    "error": null
  }
}
```

`accounts.for_each_account(connector, fn, *, auth_errors=(...))` iterates enabled
accounts, calls `fn(account)`, and records health per account: success → `ok` (sets
`lastSuccessAt`); an exception in `auth_errors` (e.g. `GmailAuthError`, the Microsoft
no-token error, an Atlassian/GitHub 401) → `auth_required`; anything else → `error` with
`str(exc)`. One account raising never stops the others. It returns the combined results
plus a per-account summary.

Connector `health_check()` semantics become **"at least one enabled account is usable"**,
fixing the Gmail block-everyone bug for every connector. `RunResult.details` gains
`accounts: {"<connector>:<id>": "<status>"}` so the scheduler can report "2/3 accounts ok".

**Connectors API.**

- `GET /v1/connectors`: the existing `account` field becomes the account id when the
  connector has exactly one account, `"N accounts"` when several, `null` when none.
  `state` becomes `err` when every enabled account is `auth_required`/`error`.
- `GET /v1/connectors/{id}` (`ConnectorDetail`) gains
  `accounts: [{id, context, enabled, health: {status, checkedAt, lastSuccessAt, error}}]`.
  For `outlook_mail` / `teams_chat` / `teams_meetings` this lists the `microsoft` accounts.
- `desktop/src/shared/api-types.ts` gains the matching optional `accounts` field. No UI
  consumes it in this spec.

### 3. Per-connector changes

Common pattern: each `runner.py` `_build` reads `accounts.list_accounts("<connector>")`
instead of its `routing.yaml` block, and the fetch loop goes through
`for_each_account`. The matching `__main__.py` CLI entry points change the same way. Each
auth CLI (`ghostbrain-gmail-auth`, `ghostbrain-calendar-auth google`,
`ghostbrain-slack-token-add`, `ghostbrain-microsoft-auth`) additionally **upserts the
account, unassigned, if absent** — the CLI and the future in-app path converge on the
same state.

- **Gmail** — accounts and per-account `options` (`monitored_labels`,
  `unread_lookback_hours`) from the registry. `last_run` becomes per-account
  (`state/gmail.<slug>.last_run`) so a newly added account starts from its own lookback
  window rather than the others' last run; the connector-level `gmail.last_run` is still
  written for the connectors screen. Sender-domain / label rules unchanged.
- **Google Calendar** — accounts from the registry (`calendar_google`). Its context
  mapping moves from `calendar.google.accounts` to the generic account rule.
- **Slack** — workspaces from the registry; `context` is no longer required (today a
  workspace without one is skipped, `slack/connector.py:583-585`). Tokens unchanged.
- **Jira / Confluence** — sites from the registry. `auth_for_site(host)`
  (`atlassian/_base.py:139`) resolves email as account `options.email` → `ATLASSIAN_EMAIL`,
  and token as `ATLASSIAN_TOKEN_<SLUG>` → `ATLASSIAN_TOKEN` → **new**
  `state/atlassian.<slug>.token` (chmod 600). Confluence gains site-level routing via the
  account rule; the space rule still wins when it matches.
- **GitHub** — one account per `gh` login. Per account, the token is obtained with
  `gh auth token --hostname github.com --user <login>` and `gh search` runs with
  `GH_TOKEN=<token>` in its environment, so the user's active `gh` account is never
  switched. `health_check` per account = token retrieval succeeds. Events tagged
  `accountId=<login>`. Results from several logins are de-duplicated by URL (the same PR
  can be visible to two logins); the first account's tag wins. The org → context rule is
  unchanged and still takes precedence.
- **Microsoft** — `get_token(config, username)` selects
  `app.get_accounts(username=username)` instead of `[0]`; all accounts share one MSAL
  cache. The MSAL app / authority is built per tenant (`options.tenant_id` →
  `microsoft.tenant_id` → current default). `run_device_flow` adds an account to the cache
  rather than replacing one, then upserts it into the registry. Outlook Mail, Teams Chat
  and Teams Meetings runners each iterate the `microsoft` accounts and tag `accountId`.

## Error handling

| Situation | Behaviour |
|---|---|
| One account's token missing / refresh rejected / 401 | That account → `auth_required`; others run; connector health still ok |
| All accounts failing | Connector `health_check()` false → `RunResult ok=False`; `state=err` in API |
| `accounts.yaml` malformed | Warning, empty account list, connectors report "not configured"; no fallback to `routing.yaml` |
| Unknown `connector` value / duplicate `(connector, id)` | Entry ignored with a warning; first duplicate wins |
| Account `context` not in `routing_config.contexts()` | Treated as unassigned; routes via specific rules / LLM |
| `gh` / MSAL enumeration fails during seeding | Warning; that connector seeded empty; others seeded |
| `accounts_health.json` unreadable | Treated as empty; rewritten on next run |

## Testing

- **Registry (`tests/test_accounts.py`):** seeding from a sample `routing.yaml` (every row
  of the migration table); seeding runs once; case-insensitive lookup; archived context →
  `context_for` is `None`; malformed YAML → empty list, no `routing.yaml` fallback;
  atomic write + lock under concurrent `upsert_account`; unknown connector ignored.
- **Health helper:** one account raising an auth error, one raising a generic error, one
  succeeding → statuses `auth_required` / `error` / `ok`, results from the good one
  returned.
- **Router (`tests/test_router_accounts.py`):** precedence — Gmail sender-domain rule beats
  account rule; GitHub org beats account; Confluence space beats account; account rule
  beats LLM (LLM stubbed and asserted not called); unassigned account falls to LLM; macOS
  calendar rule unaffected; `method == "account"`.
- **Per connector:** two accounts, one with failing credentials — the other still yields
  events tagged with the correct `accountId`, and `health_check()` is true. GitHub against
  a fake `gh` binary (asserts `GH_TOKEN` per call and no `gh auth switch`); Microsoft with
  a stubbed MSAL app holding two accounts in two tenants.
- **API:** `ConnectorDetail.accounts` shape; `account` summary field for 0 / 1 / N
  accounts; `state=err` when all accounts fail.
- Existing router / connector tests that relied on the removed `routing.yaml` rules are
  rewritten to use `accounts.yaml` fixtures. Remember `GHOSTBRAIN_STATE_DIR` sandboxing in
  every test that touches state.

## Slices (implementation order)

1. **Registry + health helper + router rule** — `accounts.py`, seeding, `accounts_health`,
   `method="account"` rule; no connector reads it yet (router rule inert until events carry
   `accountId`).
2. **Gmail, Google Calendar, Slack** — switch to registry, tag `accountId`, remove their
   old router rules, per-account Gmail `last_run`, auth CLIs upsert.
3. **Jira + Confluence** — registry, per-site email, `state/atlassian.<slug>.token`,
   remove `jira.sites` rule.
4. **GitHub** — per-login `GH_TOKEN`, de-dup, seeding from `gh auth status`.
5. **Microsoft** — username-selected tokens, per-tenant authority, device flow adds
   accounts, three runners iterate.
6. **Connectors API** — `accounts` in `ConnectorDetail`, summary `account`, `state=err`,
   `api-types.ts`.
