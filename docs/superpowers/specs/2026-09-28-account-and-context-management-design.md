# Account & Context Management UI — Design

**Status:** Approved in conversation 2026-09-28 ("go for it" on the scope listed in the v1.7.0 wrap-up)
**Origin:** Spec B of multi-account connectors. v1.7.0 shipped the `accounts.yaml` registry and
account → context routing, but assigning a context still means hand-editing `accounts.yaml`,
contexts can only be created by editing `routing.yaml`, and the connector "disconnect" button
is a silent no-op when a connector has more than one account.

## Goals

1. Create contexts (agencies) and archive / restore them from Settings, without hand-editing
   `routing.yaml` and without losing the user's comments in it.
2. In each connector's detail panel, list its accounts with health, assign each account a
   context (or leave it unassigned), enable / disable it, add another account, and remove one.
3. Disconnect never silently does nothing: with one account it removes that account; with
   several, removal is per account.

## Non-goals

- Renaming contexts (would require moving `20-contexts/<ctx>/` notes, rewriting projects and
  routing rules — archive + create covers the need).
- Editing per-account `options` (labels, lookback, Slack channels) in the UI.
- Editing routing rules (sender domains, labels, orgs, spaces) in the UI.

## Design

### 1. Contexts API (`ghostbrain/routing_config.py`, `ghostbrain/api/routes/vault.py`)

`routing.yaml` gains an optional top-level `archived_contexts:` list. `contexts()` is unchanged
(active contexts only), so the router, digests and every validator keep working as before.

New in `routing_config.py`:

```python
CONTEXT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
RESERVED_CONTEXTS = frozenset({"needs_review"})

def archived_contexts(root=None) -> tuple[str, ...]
def add_context(name: str, root=None) -> tuple[str, ...]      # new or restores an archived one
def archive_context(name: str, root=None) -> tuple[str, ...]
class ContextError(ValueError)                               # invalid / reserved / duplicate / last one / unknown
```

- **Validation:** name must match `CONTEXT_NAME_RE` (lowercase, digits, hyphens; it becomes a
  folder name and a router enum value) and not be reserved. Adding an active name → `ContextError`
  ("already exists"). Adding an archived name restores it. Archiving the last active context →
  `ContextError`. Archiving an unknown name → `ContextError`.
- **Comment-preserving write:** only the `contexts:` and `archived_contexts:` blocks are
  rewritten, as block lists (`key:\n  - a\n  - b\n`). A block is its `^key\s*:` line plus the
  following lines that start with whitespace or `-`; everything else in the file is kept
  byte-for-byte. A missing block is appended at EOF (same approach as bootstrap's
  `_ensure_contexts_key`). After building the new text, it is parsed and checked: the two
  lists must equal the intended values and every other top-level key must parse identically to
  before; otherwise `ContextError` and nothing is written. Written atomically (temp + replace).
- **Folders:** adding a context creates `20-contexts/<ctx>/` with bootstrap's `CONTEXT_SUBDIRS`,
  `_index.md` and `_profile.md` (factor bootstrap's per-context block into
  `bootstrap.ensure_context_dirs(root, ctx)` and call it from both places). Archiving never
  deletes anything.
- **Effects of archiving:** accounts pointing at an archived context become unassigned for
  routing (`accounts.context_for` already ignores contexts not in `contexts()`); projects under
  it drop out of router destinations the same way; notes stay where they are. Restoring brings
  all of it back.

Routes (existing `/v1/vault` router):

| Method | Path | Body | Result |
|---|---|---|---|
| GET | `/v1/vault/contexts` | — | `{"contexts": [...], "archived": [...]}` (adds `archived`) |
| POST | `/v1/vault/contexts` | `{"name": "agencyx"}` | 201 + same shape; 422 on `ContextError` |
| DELETE | `/v1/vault/contexts/{name}` | — | 200 + same shape (archived); 422 on `ContextError` |

### 2. Account update API (`ghostbrain/api/routes/connectors.py`)

| Method | Path | Body | Result |
|---|---|---|---|
| PATCH | `/v1/connectors/{connector_id}/accounts/{account_id}` | `{"context": "agencyx" \| null, "enabled": true}` (both optional) | 200 + the account (`{id, context, enabled, health}`) |

- `connector_id` is the API id (gmail, calendar, slack, jira, confluence, github, outlook_mail,
  teams_chat, teams_meetings) mapped with `accounts.SOURCE_TO_ACCOUNT_CONNECTOR`; unknown → 404.
- Unknown account → 404. Context not in `contexts()` → 422 (null = unassign).
- Implemented with `accounts.get_account` + `dataclasses.replace` + `accounts.upsert_account`.
- Removal stays the existing `DELETE /v1/connectors/{id}/credentials?account=<id>` (removes
  credentials and the registry entry).

### 3. Settings → Contexts (desktop)

A new `ContextsSettings` section directly above `ProjectsSettings` in `settings.tsx`:
- Active contexts as rows (name + archive button with `window.confirm`).
- An "add context" input + button (lower-cases input; shows the API's 422 message via toast).
- Archived contexts (if any) under a muted header, each with "restore".
- Hooks in `lib/api/hooks.ts`: `useCreateContext()`, `useArchiveContext()` — both invalidate
  `['vault','contexts']`, `['connectors']`, `['connector']` and `['projects']`.
- `VaultContexts` TS type gains `archived?: string[]`.

### 4. Connector detail → Accounts (desktop)

In `ConnectorDetailPanel`, a new `DetailBlock label="accounts"` (for connectors whose detail has
an `accounts` array — i.e. account-backed connectors) placed before "what poltergeist pulls":
- One row per account: id (mono), health pill (`ok` → "syncing", `auth_required` → "needs
  re-auth", `error` → "error" with the error as title tooltip, none → "not synced yet"),
  context `<select>` (options: "unassigned" + active contexts; a stored context that is no
  longer active shows as "<name> (archived)"), an enable toggle, and a remove button
  (`window.confirm`, then `useDisconnectConnector` with that account id).
- A needs-re-auth row gets a "reauthorize" button that opens the existing `ConnectorAuthModal`.
- "add account" button under the list opens the existing `ConnectorAuthModal`.
- Empty list: "no accounts yet" + the add button.
- Hook: `useUpdateAccount()` → PATCH, invalidates `['connector', id]` and `['connectors']`.
- The hero's generic **disconnect** button: shown only when the connector has no accounts array
  (non-account connectors — joplin, claude_code, macOS calendar) or exactly one account, in which
  case it passes that account's id (never the summary string "N accounts").

## Error handling

| Situation | Behaviour |
|---|---|
| Invalid / reserved / duplicate context name | 422 with message; toast in UI; file untouched |
| Archive last active context | 422 "at least one context must remain" |
| routing.yaml rewrite would change anything outside the two blocks | 422, nothing written, warning logged |
| PATCH unknown connector / account | 404 |
| PATCH context not active | 422 |
| Remove account fails | toast error; list unchanged |

## Testing

- `routing_config`: add / restore / archive semantics; name validation; comment preservation on
  a routing.yaml full of comments and other keys (byte-identical outside the blocks); flow-style
  `contexts: [a, b]` input rewritten to block style; missing `archived_contexts` appended;
  folders created on add; last-context guard.
- Routes: GET shape, POST 201/422, DELETE 200/422, PATCH 200/404/422 and that the change lands
  in `accounts.yaml`.
- Desktop (vitest + RTL, module-mock style of `ProjectsSettings.test.tsx`): ContextsSettings add /
  archive / restore calls; accounts block renders rows + health pills, changing the select sends
  PATCH, remove sends DELETE with the right `account`, hero disconnect hidden with 2 accounts and
  passes the id with 1.
