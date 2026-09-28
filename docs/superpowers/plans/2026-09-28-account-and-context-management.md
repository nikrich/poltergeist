# Account & Context Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Manage contexts (add / archive / restore) in Settings and manage each connector's accounts (context, enabled, add, remove, re-auth) in the connector detail panel.

**Architecture:** Two small backend additions — comment-preserving context writes in `routing_config.py` exposed on `/v1/vault/contexts`, and `PATCH /v1/connectors/{id}/accounts/{account_id}` over the v1.7.0 `accounts.yaml` registry — plus two desktop UI blocks built on existing hooks and components.

**Tech Stack:** Python 3.11 / FastAPI / PyYAML / pytest; React + TypeScript + TanStack Query + vitest/RTL.

**Spec:** `docs/superpowers/specs/2026-09-28-account-and-context-management-design.md`

## Global Constraints

- Worktree `/Users/jannik/development/nikrich/ghost-brain-account-ui`, branch `feat/account-management`. Every shell command starts with `cd /Users/jannik/development/nikrich/ghost-brain-account-ui && `. Verify `git branch --show-current` before committing.
- Safety: never read/write the real `~/ghostbrain`, `~/.ghostbrain`, `~/.claude`; never run the app, `ghostbrain-*`/`poltergeist` CLIs, gh, MSAL or network; no `git stash`; never touch other worktrees.
- Python: `.venv/bin/python -m pytest <path> -q -p no:cacheprovider`. Full suite: `.venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_recorder_wasapi_io.py` — only the 22 known baseline failures are allowed (test_agent_stream 1, test_calendar 1, test_joplin_connector 2, test_mcp_integration 1, test_mcp_tools 2, test_recorder_api_platform_guard 1, test_recorder_audio_backend 7, test_recorder_platform_guard 2, test_semantic 4, test_weekly_digest 1).
- Desktop (in `desktop/`): `npm run typecheck` (never `tsc --noEmit`), `npm test`, `npm run lint` (`--max-warnings 0`; release builds fail on warnings). Test-mock conventions that lint accepts: module-mock `vi.mock('../lib/api/client', ...)` as in `ProjectsSettings.test.tsx`, or per-field `window.gb.api.request = vi.fn(...) as unknown as typeof window.gb.api.request`.
- Windows CI runs desktop tests on windows-2022 at release time: no POSIX-only assumptions in tests (path separators, chmod).
- `tests/test_no_hardcoded_contexts.py` bans legacy context names repo-wide; use generic names (`personal`, `work`, `agencyx`, `acme`) in code, tests and docs.
- Context names: `^[a-z0-9][a-z0-9-]{0,39}$`; `needs_review` reserved.
- Ruff clean on lines you add. Commit trailer: your own session's attribution line.

## Review Focus

1. **A routing.yaml full of comments** — adding/archiving a context changes only the two blocks. Test: Task 1 `test_add_context_preserves_everything_else`.
2. **Flow-style `contexts: [a, b]`** (common in hand-edited files) is rewritten correctly. Test: Task 1 `test_flow_style_contexts_rewritten`.
3. **Archiving the context an account points at** — account shows "(archived)" in the select, routing falls back to specific rules / LLM. Test: Task 4 `renders archived context option`.
4. **Connector with two accounts** — hero disconnect hidden; per-row remove sends the row's id. Test: Task 4.
5. **Add account on an already-connected connector** — opens the auth modal (not blocked by state `on`). Test: Task 4.

---

### Task 1: Contexts backend (comment-preserving writes + routes)

**Files:**
- Modify: `ghostbrain/routing_config.py`, `ghostbrain/bootstrap.py` (extract `ensure_context_dirs`), `ghostbrain/api/routes/vault.py`
- Test: `tests/test_routing_config_write.py`, `ghostbrain/api/tests/test_vault_contexts_write.py`

**Interfaces — Produces:** `routing_config.CONTEXT_NAME_RE`, `RESERVED_CONTEXTS`, `ContextError(ValueError)`, `archived_contexts(root=None) -> tuple[str, ...]`, `add_context(name, root=None) -> tuple[str, ...]` (returns active list), `archive_context(name, root=None) -> tuple[str, ...]`; `bootstrap.ensure_context_dirs(root: Path, ctx: str) -> None`; routes `GET/POST /v1/vault/contexts`, `DELETE /v1/vault/contexts/{name}` returning `{"contexts": [...], "archived": [...]}`.

- [ ] **Step 1: Failing tests** — `tests/test_routing_config_write.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ghostbrain import routing_config as rc

COMMENTED = """\
# Routing rules — hand edited
version: 1

# The vault's contexts.
contexts:
  - personal
  - work

# GitHub orgs → context.
github:
  orgs:
    acme: work   # keep this comment
gmail:
  sender_domains:
    acme.com: work
"""


@pytest.fixture
def v(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(COMMENTED, encoding="utf-8")
    return root


def _text(root: Path) -> str:
    return (root / "90-meta" / "routing.yaml").read_text(encoding="utf-8")


def test_add_context_preserves_everything_else(v):
    assert rc.add_context("agencyx", v) == ("personal", "work", "agencyx")
    text = _text(v)
    assert "contexts:\n  - personal\n  - work\n  - agencyx\n" in text
    before, after = COMMENTED.split("contexts:")[0], COMMENTED.split("# GitHub orgs")[1]
    assert text.startswith(before)
    assert text.endswith(after)
    assert "acme: work   # keep this comment" in text
    assert rc.contexts(v) == ("personal", "work", "agencyx")


def test_add_creates_context_folders(v):
    rc.add_context("agencyx", v)
    ctx = v / "20-contexts" / "agencyx"
    assert (ctx / "_index.md").exists() and (ctx / "_profile.md").exists()


def test_archive_and_restore(v):
    rc.add_context("agencyx", v)
    assert rc.archive_context("agencyx", v) == ("personal", "work")
    assert rc.archived_contexts(v) == ("agencyx",)
    assert "archived_contexts:\n  - agencyx\n" in _text(v)
    assert (v / "20-contexts" / "agencyx").exists()          # nothing deleted
    assert rc.add_context("agencyx", v) == ("personal", "work", "agencyx")  # restore
    assert rc.archived_contexts(v) == ()


@pytest.mark.parametrize("name", ["", "Agency X", "needs_review", "-x", "a" * 41, "x/y", "../up"])
def test_invalid_names_rejected(v, name):
    with pytest.raises(rc.ContextError):
        rc.add_context(name, v)
    assert _text(v) == COMMENTED


def test_duplicate_and_last_and_unknown(v):
    with pytest.raises(rc.ContextError):
        rc.add_context("work", v)
    rc.archive_context("work", v)
    with pytest.raises(rc.ContextError):
        rc.archive_context("personal", v)                    # last active
    with pytest.raises(rc.ContextError):
        rc.archive_context("nope", v)


def test_flow_style_contexts_rewritten(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(
        "contexts: [personal, work]\ngithub:\n  orgs: {}\n", encoding="utf-8")
    rc.add_context("agencyx", root)
    data = yaml.safe_load(_text(root))
    assert data["contexts"] == ["personal", "work", "agencyx"]
    assert data["github"] == {"orgs": {}}


def test_missing_contexts_key_uses_defaults_then_writes(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text("github:\n  orgs: {}\n", encoding="utf-8")
    rc.add_context("agencyx", root)
    assert rc.contexts(root) == (*rc.DEFAULT_CONTEXTS, "agencyx")
```

`ghostbrain/api/tests/test_vault_contexts_write.py` (fixtures from `ghostbrain/api/tests/conftest.py`; `tmp_vault` has contexts work, consulting, side-project, personal):

```python
def test_get_includes_archived(client, auth_headers):
    body = client.get("/v1/vault/contexts", headers=auth_headers).json()
    assert body == {"contexts": ["work", "consulting", "side-project", "personal"], "archived": []}


def test_post_adds_and_delete_archives(client, auth_headers):
    r = client.post("/v1/vault/contexts", json={"name": "agencyx"}, headers=auth_headers)
    assert r.status_code == 201 and "agencyx" in r.json()["contexts"]
    r = client.delete("/v1/vault/contexts/agencyx", headers=auth_headers)
    assert r.status_code == 200
    assert "agencyx" not in r.json()["contexts"] and r.json()["archived"] == ["agencyx"]


def test_post_invalid_is_422(client, auth_headers):
    r = client.post("/v1/vault/contexts", json={"name": "Bad Name"}, headers=auth_headers)
    assert r.status_code == 422 and r.json()["detail"]


def test_delete_unknown_is_422(client, auth_headers):
    assert client.delete("/v1/vault/contexts/nope", headers=auth_headers).status_code == 422
```

- [ ] **Step 2:** run both files → FAIL (missing functions / 405).

- [ ] **Step 3: Implement** in `routing_config.py` (keep the module docstring's single-source statement; add the archived key):

```python
CONTEXT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
RESERVED_CONTEXTS = frozenset({"needs_review"})


class ContextError(ValueError):
    """Invalid, reserved, duplicate, unknown, or last-remaining context."""


def archived_contexts(root: Path | None = None) -> tuple[str, ...]:
    value = _load(root).get("archived_contexts")
    if isinstance(value, list):
        return tuple(str(c).strip() for c in value if isinstance(c, str) and c.strip())
    return ()


def add_context(name: str, root: Path | None = None) -> tuple[str, ...]:
    name = (name or "").strip()
    if not CONTEXT_NAME_RE.match(name) or name in RESERVED_CONTEXTS:
        raise ContextError(
            "context names use lowercase letters, digits and hyphens (max 40), "
            f"and can't be {sorted(RESERVED_CONTEXTS)}"
        )
    active = list(contexts(root))
    if name in active:
        raise ContextError(f"context {name!r} already exists")
    archived = [c for c in archived_contexts(root) if c != name]
    active.append(name)
    _write_context_blocks(root, active, archived)
    from ghostbrain.bootstrap import ensure_context_dirs
    ensure_context_dirs(root or vault_path(), name)
    return tuple(active)


def archive_context(name: str, root: Path | None = None) -> tuple[str, ...]:
    active = list(contexts(root))
    if name not in active:
        raise ContextError(f"unknown context {name!r}")
    if len(active) == 1:
        raise ContextError("at least one context must remain")
    active.remove(name)
    archived = [*archived_contexts(root), name]
    _write_context_blocks(root, active, archived)
    return tuple(active)
```

plus private helpers: `_load(root)` (safe-load routing.yaml → dict, `{}` on missing/invalid — reuse inside `contexts()` if convenient without changing its behaviour/warnings), and `_write_context_blocks(root, active, archived)`:
1. read the text (missing file → `""`);
2. for each key in (`contexts`, `archived_contexts`): build `f"{key}:\n" + "".join(f"  - {c}\n" for c in values)` (for an empty `archived` list write nothing and remove an existing block); locate the block = the `^key\s*:` line plus following lines that start with whitespace or `-` (stop at the first line that is empty or starts with any other char); replace it, or append `"\n" + block` at EOF when absent;
3. verify: `yaml.safe_load(new)` must be a dict whose `contexts` == active, `archived_contexts` == archived (or absent when empty), and every other top-level key equals `yaml.safe_load(old)`'s; otherwise `raise ContextError("routing.yaml has an unusual contexts layout; edit it by hand")` without writing;
4. write atomically (tempfile in the same dir + `os.replace`).

In `bootstrap.py`, move the per-context loop body (mkdir ctx root + `CONTEXT_SUBDIRS` + `_index.md` + `_profile.md`) into `def ensure_context_dirs(root: Path, ctx: str) -> None` and call it from `bootstrap()` — identical output.

In `api/routes/vault.py`:

```python
class NewContext(BaseModel):
    name: str


def _contexts_body() -> dict:
    return {"contexts": list(routing_config.contexts()), "archived": list(routing_config.archived_contexts())}


@router.get("/contexts")
def vault_contexts() -> dict:
    return _contexts_body()


@router.post("/contexts", status_code=201)
def create_context(body: NewContext) -> dict:
    try:
        routing_config.add_context(body.name)
    except routing_config.ContextError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _contexts_body()


@router.delete("/contexts/{name}")
def archive_context(name: str) -> dict:
    try:
        routing_config.archive_context(name)
    except routing_config.ContextError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _contexts_body()
```

- [ ] **Step 4:** run the two new files + `tests/test_bootstrap_contexts.py tests/test_bootstrap_routing_mode.py tests/api/routes/test_vault_contexts.py tests/test_no_hardcoded_contexts.py` → PASS (update `test_vault_contexts.py` only if it pins the old exact GET body — add `"archived": []`). Full suite once.
- [ ] **Step 5:** ruff + commit `feat(contexts): add/archive/restore contexts without touching the rest of routing.yaml`.

---

### Task 2: Account update API

**Files:** Modify `ghostbrain/api/routes/connectors.py`; Test `ghostbrain/api/tests/test_account_update_route.py`

**Interfaces — Consumes:** `accounts.SOURCE_TO_ACCOUNT_CONNECTOR`, `get_account`, `upsert_account` (raises `ValueError` on unknown context), `accounts_health.health_for(connector_id, account_id)`. **Produces:** `PATCH /v1/connectors/{connector_id}/accounts/{account_id}` body `{"context"?: str|null, "enabled"?: bool}` → `{"id","context","enabled","health"}`.

- [ ] **Step 1: Failing tests**

```python
import yaml


def _accounts(vault, entries):
    (vault / "90-meta" / "accounts.yaml").write_text(
        yaml.safe_dump({"version": 1, "accounts": entries}), encoding="utf-8")


def _registry(vault):
    return yaml.safe_load((vault / "90-meta" / "accounts.yaml").read_text())["accounts"]


def test_patch_sets_context_and_enabled(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "gmail", "id": "a@x.com"}])
    r = client.patch("/v1/connectors/gmail/accounts/a@x.com",
                     json={"context": "work", "enabled": False}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"id": "a@x.com", "context": "work", "enabled": False, "health": None}
    assert _registry(tmp_vault) == [{"connector": "gmail", "id": "a@x.com", "context": "work", "enabled": False}]


def test_patch_null_unassigns_and_partial_body_keeps_other_field(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "slack", "id": "acme", "context": "work", "enabled": False}])
    r = client.patch("/v1/connectors/slack/accounts/acme", json={"context": None}, headers=auth_headers)
    assert r.json()["context"] is None and r.json()["enabled"] is False


def test_patch_microsoft_via_teams_id(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "microsoft", "id": "me@acme.com"}])
    r = client.patch("/v1/connectors/teams_chat/accounts/me@acme.com", json={"context": "consulting"}, headers=auth_headers)
    assert r.status_code == 200 and _registry(tmp_vault)[0]["context"] == "consulting"


def test_patch_errors(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "gmail", "id": "a@x.com"}])
    assert client.patch("/v1/connectors/joplin/accounts/x", json={}, headers=auth_headers).status_code == 404
    assert client.patch("/v1/connectors/gmail/accounts/nobody@x.com", json={}, headers=auth_headers).status_code == 404
    assert client.patch("/v1/connectors/gmail/accounts/a@x.com", json={"context": "nope"}, headers=auth_headers).status_code == 422
```

- [ ] **Step 2:** run → FAIL (405).
- [ ] **Step 3: Implement** in `routes/connectors.py`:

```python
class AccountPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: str | None = None
    enabled: bool | None = None


@router.patch("/{connector_id}/accounts/{account_id}")
def update_account(connector_id: str, account_id: str, body: AccountPatch) -> dict:
    from ghostbrain import accounts, accounts_health

    acct_connector = accounts.SOURCE_TO_ACCOUNT_CONNECTOR.get(connector_id)
    if acct_connector is None:
        raise HTTPException(status_code=404, detail=f"Connector has no accounts: {connector_id}")
    acc = accounts.get_account(acct_connector, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")
    changes = body.model_dump(exclude_unset=True)
    updated = dataclasses.replace(acc, **changes)
    try:
        accounts.upsert_account(updated)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {
        "id": updated.id,
        "context": updated.context,
        "enabled": updated.enabled,
        "health": accounts_health.health_for(connector_id, updated.id),
    }
```

(`exclude_unset` makes `{"context": null}` unassign while `{}` changes nothing.) Account ids contain `@` and `.`: FastAPI path params accept them; the desktop encodes with `encodeURIComponent`.

- [ ] **Step 4:** run test file + `ghostbrain/api/tests/test_connectors*.py` → PASS; full suite once.
- [ ] **Step 5:** ruff + commit `feat(api): PATCH connector account context/enabled`.

---

### Task 3: Settings → Contexts (desktop)

**Files:** Modify `desktop/src/shared/api-types.ts` (`VaultContexts.archived?: string[]`), `desktop/src/renderer/lib/api/hooks.ts`, `desktop/src/renderer/screens/settings.tsx`; Test `desktop/src/renderer/__tests__/ContextsSettings.test.tsx`

**Interfaces — Produces:** `useCreateContext()` (mutationFn `(name: string) => post<VaultContexts>('/v1/vault/contexts', { name })`), `useArchiveContext()` (mutationFn `(name: string) => del<VaultContexts>('/v1/vault/contexts/' + encodeURIComponent(name))`), both invalidating `['vault','contexts']`, `['connectors']`, `['connector']`, `['projects']` on success. `ContextsSettings` component (exported for tests) rendered immediately above `ProjectsSettings` in the settings screen with a matching `SectionHeader`.

UI (follow `ProjectsSettings` styling and primitives — `Btn`, `Eyebrow`, `Lucide`, plain `<input>` with the same Tailwind classes):
- rows for `useContexts().data.contexts`, each with an "archive" text button → `window.confirm("Archive <name>? Its notes stay; accounts and projects pointing at it stop routing there until you restore it.")` → `archive.mutate(name, { onError: toast.error(message) })`;
- input + "add context" `Btn` → `create.mutate(value.trim().toLowerCase(), { onSuccess: clear input, onError: toast.error(e.message) })`; Enter submits; disabled when empty or pending;
- when `archived.length > 0`: `Eyebrow` "archived" and rows with a "restore" button → `create.mutate(name)`.

Tests (module-mock style of `ProjectsSettings.test.tsx`): renders active + archived; typing "AgencyX" + click add → `post('/v1/vault/contexts', { name: 'agencyx' })`; archive with `window.confirm` mocked true → `del('/v1/vault/contexts/work')`; confirm false → no call; restore → `post` with the archived name; a rejected post surfaces the toast (mock the toast module the way other tests do, or assert no crash + input kept).

- [ ] TDD: tests first (RED), implement, `npm run typecheck && npm test && npm run lint` GREEN, commit `feat(desktop): manage contexts in settings`.

---

### Task 4: Connector detail → Accounts (desktop)

**Files:** Modify `desktop/src/renderer/lib/api/hooks.ts` (`useUpdateAccount`), `desktop/src/renderer/screens/connectors.tsx`; Create `desktop/src/renderer/components/ConnectorAccounts.tsx`; Test `desktop/src/renderer/__tests__/ConnectorAccounts.test.tsx` and extend `connectors-connect.test.tsx` for the hero-disconnect rule.

**Interfaces — Consumes:** `ConnectorDetail.accounts?: ConnectorAccount[]` (`{id, context, enabled, health: {status: 'ok'|'auth_required'|'error', checkedAt, lastSuccessAt, error} | null}`, already in `api-types.ts`), `useContexts`, `useDisconnectConnector`, `ConnectorAuthModal` (in connectors.tsx — export it or pass an `onAddAccount`/`onReauth` callback prop). **Produces:** `useUpdateAccount()` — mutationFn `(a: { connectorId: string; accountId: string; context?: string | null; enabled?: boolean }) => patch(`/v1/connectors/${a.connectorId}/accounts/${encodeURIComponent(a.accountId)}`, body-with-only-provided-fields)`, invalidating `['connector', connectorId]` and `['connectors']`; `ConnectorAccounts({ connector: ConnectorDetail, onAddAccount: () => void, onReauth: (accountId: string) => void })`.

`ConnectorAccounts` renders (only when `connector.accounts` is an array):
- empty → "no accounts yet" + "add account" `Btn`;
- per account row: `font-mono text-11` id; health `Pill` — `ok` → "syncing" (tone neon/ok), `auth_required` → "needs re-auth" (oxblood), `error` → "error" (oxblood, `title={health.error}`), null → "not synced yet" (fog); context `<select aria-label={`context for ${id}`}>` with "unassigned" (value "") + active contexts + (if `account.context` not active) an extra option `"<ctx> (archived)"` with that value; onChange → `update.mutate({ connectorId, accountId, context: value || null })`; `Toggle` for enabled → `update.mutate({ ..., enabled })`; "reauthorize" small button when `auth_required` → `onReauth(id)`; remove icon button (`aria-label={`remove ${id}`}`) → `window.confirm(`Remove ${id}? This deletes its stored credentials.`)` → `disconnect.mutate({ id: connector.id, account: id })`;
- "add account" `Btn` under the list → `onAddAccount()`.

In `ConnectorDetailPanel`: render `<DetailBlock label="accounts"><ConnectorAccounts … /></DetailBlock>` before "what poltergeist pulls" when `Array.isArray(c.accounts)`; both callbacks open the existing auth modal (`setAuthOpen(true)`) regardless of `c.state`. Hero **disconnect** button rule: show when `!Array.isArray(c.accounts)` (as today) or `c.accounts.length === 1` (then pass `account: c.accounts[0].id`); hide when `c.accounts.length !== 1` for account-backed connectors (0 → nothing to disconnect; ≥2 → per-row remove).

Tests: rows + pills render for ok / auth_required / error / null; select change sends PATCH with `context: 'agencyx'` and "unassigned" sends `context: null`; archived stored context shows "(archived)"; toggle sends `enabled: false`; remove with confirm → DELETE `...credentials?account=b%40x.com`; confirm false → nothing; "add account" and "reauthorize" call their callbacks. In `connectors-connect.test.tsx`: detail with 2 accounts → no hero "disconnect"; with 1 account → hero disconnect DELETE carries that id.

- [ ] TDD RED → implement → `npm run typecheck && npm test && npm run lint` GREEN → commit `feat(desktop): per-account context, enable, add, remove and re-auth in connector detail`.

---

### Task 5: Docs + verification

- Update `docs/connectors.md` "Multiple accounts and contexts" section: contexts are created/archived in Settings → Contexts; each account's context/enabled/remove lives in the connector's detail panel; hand-editing `accounts.yaml` still works.
- Full Python suite (baseline only), `tests/test_no_hardcoded_contexts.py`, desktop typecheck/test/lint.
- Commit `docs: manage contexts and accounts in the app`.
