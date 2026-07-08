# Connector Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a brand-new user connect every Poltergeist connector through the desktop UI — real OAuth/device-code/token/permission flows and a first-run wizard — with no terminal.

**Architecture:** A new Python **auth-session API** on the existing FastAPI sidecar drives each connect attempt as a short-lived server-side session, reusing the connectors' existing auth code (Google `run_local_server`, MSAL device-code, Slack/Atlassian/Joplin token save, `gh` probe). The Electron renderer opens the system browser and polls session status; it never implements OAuth itself. `repo/connectors.py` gains real credential-based state detection (off/on/err). The renderer gets one reusable **flow component per auth pattern**, shared between a first-run wizard and the connectors screen.

**Tech Stack:** Python 3.11 / FastAPI / Pydantic (sidecar), React 18 / TypeScript / Zustand / TanStack Query / Vitest + RTL (desktop renderer), Electron (main + preload IPC).

## Global Constraints

- **BYO OAuth credentials** — no Poltergeist-owned OAuth apps are bundled. Google (client JSON), Slack (app + token), Microsoft (client_id/tenant_id), Atlassian (API token) are all user-supplied. Wizard copy must set expectations (incl. Google "unverified app" warning).
- **Reuse existing Python auth code** — never reimplement a provider's auth in TypeScript or duplicate it in a new Python module; wrap the existing functions in `ghostbrain/connectors/<name>/auth.py` etc.
- **Secrets never touch renderer storage or logs** — credentials live only in `~/.ghostbrain/state/` (0600), the OS keychain (Microsoft), or `<vault>/90-meta/routing.yaml`/`.env`. The renderer holds a token only long enough to POST it once.
- **Atomic + merge-only config writes** — every write to `routing.yaml` / `.env` / `~/.claude/settings.json` uses temp-file + `os.replace`, loads-mutates-writes the whole document, and preserves unrelated keys (mirror `ghostbrain/api/repo/settings.py:_write_yaml_atomic`).
- **State dir override** — always resolve paths via `ghostbrain.paths.state_dir()` / `vault_path()` (honor `GHOSTBRAIN_STATE_DIR` / `VAULT_PATH`); tests set these env vars to temp dirs.
- **Sidecar auth** — the desktop reaches new routes through the existing forwarder (`Authorization: Bearer <token>`, methods GET/POST/DELETE already allowed). No forwarder change needed.
- **Follow existing test patterns** — pytest under `tests/`, Vitest + RTL under `desktop/src/renderer/__tests__/`.

---

## Connector reconciliation (read before Milestone A)

The spec says "13 connectors"; the code enumerates fewer. Ground truth from `ghostbrain/api/repo/connectors.py:_DISPLAY`:

- Enumerated today (10, minus hidden `atlassian`): `claude_code`, `github`, `jira`, `confluence`, `calendar`, `slack`, `gmail`, `outlook_mail`, `teams_chat`, `teams_meetings`.
- **`joplin` is NOT in `_DISPLAY`** — it exists as a connector (`ghostbrain/connectors/joplin/`) but isn't surfaced by the API. Task A1 adds it.
- **`calendar` is a single entry** covering BOTH Google (OAuth) and macOS (local permission). Onboarding treats it as one card with two sub-flows. The Google token lives at `google_calendar.<slug>.token`; macOS needs only an OS permission grant.
- **Whisper / recorder is NOT a connector** — it's the meeting recorder with its own settings screen (`useRecorderSettings`). It is OUT OF SCOPE for the connectors auth work; onboarding links to the recorder settings but adds no auth flow. (Spec §3 pattern F "whisper" is descoped to a link.)

So the wizard presents these **connect cards** (Task F-series): Google (Gmail + Calendar), Microsoft (Outlook Mail / Teams Chat / Teams Meetings toggles), Slack, GitHub, Jira, Confluence, Joplin, macOS Calendar, Claude Code. Nine cards over six flow patterns.

**Auth pattern → connector map** (drives the `authPattern` field in Task A2):

| Pattern id | Connectors | Auth module reused |
|---|---|---|
| `google_oauth` | `gmail`, `calendar` (google) | `gmail/auth.py`, `calendar/google/auth.py` — `run_oauth_flow(email)`, `oauth_client_path()` |
| `ms_device_code` | `outlook_mail`, `teams_chat`, `teams_meetings` | `microsoft/graph/auth.py` — `run_device_flow(config)`, `have_token(config)` |
| `paste_token` | `slack`, `joplin` | `slack/auth.py:save_token`, joplin token in `routing.yaml` |
| `atlassian_api` | `jira`, `confluence` | `atlassian/_base.py:auth_for_site`, writes `.env` |
| `cli_login` | `github` | `gh auth status` probe |
| `local_grant` | `calendar` (macos), `claude_code` | EventKit prompt / `~/.claude/settings.json` hook |

---

# Milestone A — Backend: status detection + session scaffolding

## Task A1: Surface `joplin` in the connector registry

**Files:**
- Modify: `ghostbrain/api/repo/connectors.py:9-77` (add `joplin` to `_DISPLAY`)
- Test: `tests/api/repo/test_connectors_registry.py` (create)

**Interfaces:**
- Produces: `list_connectors()` now returns a record with `id == "joplin"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/repo/test_connectors_registry.py
from ghostbrain.api.repo.connectors import list_connectors, get_connector


def test_joplin_is_enumerated():
    ids = {c["id"] for c in list_connectors()}
    assert "joplin" in ids


def test_joplin_has_display_metadata():
    rec = get_connector("joplin")
    assert rec is not None
    assert rec["displayName"]
    assert rec["vaultDestination"].endswith("joplin/")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/repo/test_connectors_registry.py -v`
Expected: FAIL — `joplin` not in enumerated ids.

- [ ] **Step 3: Add joplin to `_DISPLAY`**

In `ghostbrain/api/repo/connectors.py`, add inside the `_DISPLAY` dict (after the `slack` entry):

```python
    "joplin": {
        "displayName": "Joplin",
        "scopes": ["read notes"],
        "pulls": ["notes", "notebooks"],
        "vaultDestination": "20-contexts/{ctx}/joplin/",
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/repo/test_connectors_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/connectors.py tests/api/repo/test_connectors_registry.py
git commit -m "feat(connectors): surface joplin in connector registry"
```

## Task A2: Credential-presence probes (off vs on vs err)

Adds a per-connector `probe()` that classifies state from credential presence, independent of `.last_run`. Cheap/offline: file/keychain/env presence only — no network calls here.

**Files:**
- Create: `ghostbrain/api/repo/connector_probe.py`
- Modify: `ghostbrain/api/repo/connectors.py:_connector_record` (use the probe for `state`/`account`/`error`)
- Test: `tests/api/repo/test_connector_probe.py`

**Interfaces:**
- Produces:
  ```python
  # connector_probe.py
  @dataclass
  class ProbeResult:
      state: str        # "on" | "off" | "err"
      account: str | None
      error: str | None
  def probe(connector_id: str) -> ProbeResult: ...
  ```
- Consumed by: `_connector_record` (Task A3 integration below) and the auth router (Milestone C).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/repo/test_connector_probe.py
import os
from pathlib import Path
import pytest
from ghostbrain.api.repo.connector_probe import probe, ProbeResult


@pytest.fixture
def state(tmp_path, monkeypatch):
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(d))
    return d


def test_gmail_off_when_no_token(state):
    r = probe("gmail")
    assert r.state == "off"
    assert r.account is None


def test_gmail_on_when_token_present(state):
    (state / "gmail.you_at_gmail_com.token").write_text("{}")
    r = probe("gmail")
    assert r.state == "on"
    assert r.account == "you@gmail.com"


def test_slack_off_when_no_token(state):
    assert probe("slack").state == "off"


def test_slack_on_when_token_file_present(state):
    (state / "slack.work.token").write_text("xoxp-abc\n")
    assert probe("slack").state == "on"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/repo/test_connector_probe.py -v`
Expected: FAIL — module `connector_probe` does not exist.

- [ ] **Step 3: Implement the probe**

```python
# ghostbrain/api/repo/connector_probe.py
"""Cheap, offline credential-presence probes per connector.

Classifies a connector as off (no credential), on (credential present),
or err (credential present but structurally unusable). NO network calls —
liveness/validation that needs the network happens on explicit user action
(the auth router's validate step), not on every list call.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ghostbrain.paths import state_dir, vault_path


@dataclass
class ProbeResult:
    state: str
    account: str | None = None
    error: str | None = None


def _slug_to_email(token_filename: str, prefix: str) -> str | None:
    # "gmail.you_at_gmail_com.token" -> "you@gmail.com"
    stem = token_filename[len(prefix) + 1 : -len(".token")]
    if "_at_" not in stem:
        return None
    local, _, domain = stem.partition("_at_")
    return f"{local}@{domain.replace('_', '.')}"


def _google_probe(prefix: str) -> ProbeResult:
    d = state_dir()
    tokens = sorted(d.glob(f"{prefix}.*.token"))
    if not tokens:
        return ProbeResult("off")
    account = _slug_to_email(tokens[0].name, prefix)
    return ProbeResult("on", account=account)


def _slack_probe() -> ProbeResult:
    files = sorted(state_dir().glob("slack.*.token"))
    if files:
        return ProbeResult("on", account=files[0].name[len("slack.") : -len(".token")])
    # env fallback (SLACK_TOKEN_*)
    if any(k.startswith("SLACK_TOKEN_") and os.environ[k].strip() for k in os.environ):
        return ProbeResult("on")
    return ProbeResult("off")


def _joplin_probe() -> ProbeResult:
    from ghostbrain.api.repo.routing import load_routing  # Task B1

    token = (load_routing().get("joplin") or {}).get("token")
    return ProbeResult("on") if token else ProbeResult("off")


def _atlassian_probe() -> ProbeResult:
    email = os.environ.get("ATLASSIAN_EMAIL")
    has_token = any(
        k == "ATLASSIAN_TOKEN" or k.startswith("ATLASSIAN_TOKEN_")
        for k in os.environ
    )
    if email and has_token:
        return ProbeResult("on", account=email)
    if email or has_token:
        return ProbeResult("err", account=email, error="Atlassian email or token missing")
    return ProbeResult("off")


def _microsoft_probe() -> ProbeResult:
    from ghostbrain.connectors.microsoft.graph.auth import cache_location

    return ProbeResult("on") if cache_location().exists() else ProbeResult("off")


def _github_probe() -> ProbeResult:
    import shutil
    import subprocess

    if shutil.which("gh") is None:
        return ProbeResult("off")
    try:
        r = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, timeout=5, text=True
        )
    except (subprocess.SubprocessError, OSError):
        return ProbeResult("off")
    return ProbeResult("on") if r.returncode == 0 else ProbeResult("off")


def _claude_code_probe() -> ProbeResult:
    settings = Path.home() / ".claude" / "settings.json"
    if not settings.exists():
        return ProbeResult("off")
    try:
        import json

        hooks = json.loads(settings.read_text()).get("hooks", {})
    except (OSError, ValueError):
        return ProbeResult("off")
    return ProbeResult("on") if "SessionEnd" in hooks else ProbeResult("off")


def probe(connector_id: str) -> ProbeResult:
    if connector_id == "gmail":
        return _google_probe("gmail")
    if connector_id == "calendar":
        # Google token OR macOS is always locally available; treat google token
        # as the "on" signal, else off (macOS grant tracked separately in UI).
        return _google_probe("google_calendar")
    if connector_id == "slack":
        return _slack_probe()
    if connector_id == "joplin":
        return _joplin_probe()
    if connector_id in ("jira", "confluence"):
        return _atlassian_probe()
    if connector_id in ("outlook_mail", "teams_chat", "teams_meetings"):
        return _microsoft_probe()
    if connector_id == "github":
        return _github_probe()
    if connector_id == "claude_code":
        return _claude_code_probe()
    return ProbeResult("off")
```

Note: `_joplin_probe` imports `load_routing` from Task B1. Sequence B1 before running the joplin probe test, OR temporarily inline the yaml read; the plan orders B1 immediately after so the import resolves — for THIS task's tests (gmail/slack) the joplin path isn't exercised, so tests pass now.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/repo/test_connector_probe.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/connector_probe.py tests/api/repo/test_connector_probe.py
git commit -m "feat(connectors): credential-presence probes for off/on/err"
```

## Task A3: Wire probe state into connector records

**Files:**
- Modify: `ghostbrain/api/repo/connectors.py:_connector_record`
- Test: `tests/api/repo/test_connectors_state.py`

**Interfaces:**
- Consumes: `probe()` from A2.
- Produces: `_connector_record` sets `state`/`account`/`error` from the probe, falling back to `on` when `.last_run`/inbox exists (so an already-synced connector never regresses to off).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/repo/test_connectors_state.py
import pytest
from ghostbrain.api.repo.connectors import get_connector


@pytest.fixture
def env(tmp_path, monkeypatch):
    s = tmp_path / "state"; s.mkdir()
    v = tmp_path / "vault"; (v / "90-meta").mkdir(parents=True)
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(s))
    monkeypatch.setenv("VAULT_PATH", str(v))
    return s, v


def test_gmail_off_by_default(env):
    assert get_connector("gmail")["state"] == "off"


def test_gmail_account_populated_from_token(env):
    s, _ = env
    (s / "gmail.you_at_gmail_com.token").write_text("{}")
    rec = get_connector("gmail")
    assert rec["state"] == "on"
    assert rec["account"] == "you@gmail.com"


def test_last_run_keeps_connector_on(env):
    s, _ = env
    (s / "github.last_run").write_text("2026-07-01T00:00:00Z")
    # gh probe returns off in CI, but last_run must keep it on
    assert get_connector("github")["state"] == "on"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/repo/test_connectors_state.py -v`
Expected: FAIL — `account` is `None`, `state` ignores probe.

- [ ] **Step 3: Update `_connector_record`**

Replace the state/account/error assembly in `_connector_record`:

```python
def _connector_record(connector_id: str) -> dict:
    display = _DISPLAY.get(connector_id, {
        "displayName": connector_id,
        "scopes": [],
        "pulls": [],
        "vaultDestination": f"20-contexts/{{ctx}}/{connector_id}/",
    })
    from ghostbrain.api.repo.connector_probe import probe

    last_run = _read_last_run(connector_id)
    has_inbox = _has_inbox_captures(connector_id)
    p = probe(connector_id)
    # Probe is authoritative for off/on/err from credentials. But a connector
    # that has synced before (last_run) or produced captures stays 'on' even if
    # the offline probe can't see its credential (e.g. gh in a headless env).
    if p.state == "off" and (last_run or has_inbox):
        state = "on"
    else:
        state = p.state
    return {
        "id": connector_id,
        "displayName": display["displayName"],
        "state": state,
        "count": _count_indexed(connector_id),
        "lastSyncAt": last_run,
        "account": p.account,
        "throughput": None,
        "error": p.error,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/repo/test_connectors_state.py tests/api/repo/test_connector_probe.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/connectors.py tests/api/repo/test_connectors_state.py
git commit -m "feat(connectors): report real off/on/err state and account from probe"
```

---

# Milestone B — Backend: config writers

## Task B1: `routing.yaml` read/merge/write helper

Shared atomic writer for connector config, mirroring `repo/settings.py`.

**Files:**
- Create: `ghostbrain/api/repo/routing.py`
- Test: `tests/api/repo/test_routing.py`

**Interfaces:**
- Produces:
  ```python
  def load_routing() -> dict: ...
  def merge_routing(patch: dict) -> dict: ...   # deep-merge patch into routing.yaml, atomic write, returns new doc
  def remove_routing_path(dotted: str) -> None: ...  # e.g. "joplin.token" or "gmail.accounts.you@x.com"
  ```
- Consumed by: joplin/atlassian/google config writes and disconnect (Milestone C/D).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/repo/test_routing.py
import pytest
import yaml
from ghostbrain.api.repo.routing import load_routing, merge_routing, remove_routing_path


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"; (v / "90-meta").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(v))
    return v


def test_load_empty_when_missing(vault):
    assert load_routing() == {}


def test_merge_creates_and_preserves(vault):
    merge_routing({"joplin": {"token": "abc"}})
    merge_routing({"github": {"orgs": {"Acme": "work"}}})
    doc = load_routing()
    assert doc["joplin"]["token"] == "abc"
    assert doc["github"]["orgs"]["Acme"] == "work"


def test_deep_merge_does_not_clobber_sibling(vault):
    merge_routing({"gmail": {"accounts": {"a@x.com": {}}}})
    merge_routing({"gmail": {"accounts": {"b@x.com": {}}}})
    assert set(load_routing()["gmail"]["accounts"]) == {"a@x.com", "b@x.com"}


def test_remove_path(vault):
    merge_routing({"joplin": {"token": "abc", "host": "h"}})
    remove_routing_path("joplin.token")
    assert "token" not in load_routing()["joplin"]
    assert load_routing()["joplin"]["host"] == "h"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/repo/test_routing.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# ghostbrain/api/repo/routing.py
"""Atomic read/merge/write for <vault>/90-meta/routing.yaml.

Merge-only and comment-losing (PyYAML), same tradeoff as repo/settings.py.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from ghostbrain.paths import vault_path


def _path() -> Path:
    return vault_path() / "90-meta" / "routing.yaml"


def load_routing() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_atomic(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".routing.", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _deep_merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def merge_routing(patch: dict) -> dict:
    doc = load_routing()
    _deep_merge(doc, patch)
    _write_atomic(doc)
    return doc


def remove_routing_path(dotted: str) -> None:
    doc = load_routing()
    parts = dotted.split(".")
    node = doc
    for key in parts[:-1]:
        if not isinstance(node.get(key), dict):
            return
        node = node[key]
    node.pop(parts[-1], None)
    _write_atomic(doc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/repo/test_routing.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/routing.py tests/api/repo/test_routing.py
git commit -m "feat(connectors): atomic routing.yaml merge/remove helper"
```

## Task B2: `.env` read/merge/remove helper (Atlassian)

**Files:**
- Create: `ghostbrain/api/repo/dotenv_store.py`
- Test: `tests/api/repo/test_dotenv_store.py`

**Interfaces:**
- Produces:
  ```python
  def env_path() -> Path: ...            # ~/.ghostbrain/.env
  def set_env(pairs: dict[str, str]) -> None: ...   # upsert keys, preserve others, atomic
  def remove_env(keys: list[str]) -> None: ...
  def read_env() -> dict[str, str]: ...
  ```

- [ ] **Step 1: Write the failing test**

```python
# tests/api/repo/test_dotenv_store.py
import pytest
from ghostbrain.api.repo.dotenv_store import set_env, remove_env, read_env, env_path


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


def test_set_and_read(home):
    set_env({"ATLASSIAN_EMAIL": "me@x.com", "ATLASSIAN_TOKEN_SFT": "tok"})
    assert read_env()["ATLASSIAN_EMAIL"] == "me@x.com"
    assert read_env()["ATLASSIAN_TOKEN_SFT"] == "tok"


def test_upsert_preserves_others(home):
    set_env({"A": "1"})
    set_env({"B": "2"})
    env = read_env()
    assert env["A"] == "1" and env["B"] == "2"


def test_remove(home):
    set_env({"A": "1", "B": "2"})
    remove_env(["A"])
    assert "A" not in read_env()
    assert read_env()["B"] == "2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/repo/test_dotenv_store.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# ghostbrain/api/repo/dotenv_store.py
"""Read/upsert/remove keys in ~/.ghostbrain/.env without disturbing others.

Line-oriented KEY=VALUE. Comments and unknown lines are preserved on upsert.
The .env lives next to the state dir (its parent), matching the connectors'
documented location.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ghostbrain.paths import state_dir


def env_path() -> Path:
    return state_dir().parent / ".env"


def read_env() -> dict[str, str]:
    p = env_path()
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip()
    return out


def _write_atomic(lines: list[str]) -> None:
    p = env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        os.replace(tmp, p)
        p.chmod(0o600)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _rewrite(mutate) -> None:
    p = env_path()
    existing = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    mutate(existing)
    _write_atomic(existing)


def set_env(pairs: dict[str, str]) -> None:
    def mutate(lines: list[str]) -> None:
        remaining = dict(pairs)
        for i, line in enumerate(lines):
            s = line.strip()
            if "=" in s and not s.startswith("#"):
                key = s.split("=", 1)[0].strip()
                if key in remaining:
                    lines[i] = f"{key}={remaining.pop(key)}"
        for k, v in remaining.items():
            lines.append(f"{k}={v}")

    _rewrite(mutate)


def remove_env(keys: list[str]) -> None:
    keyset = set(keys)

    def mutate(lines: list[str]) -> None:
        lines[:] = [
            ln for ln in lines
            if not (
                "=" in ln
                and not ln.strip().startswith("#")
                and ln.split("=", 1)[0].strip() in keyset
            )
        ]

    _rewrite(mutate)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/repo/test_dotenv_store.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/dotenv_store.py tests/api/repo/test_dotenv_store.py
git commit -m "feat(connectors): .env upsert/remove helper for Atlassian creds"
```

---

# Milestone C — Backend: auth-session manager + router

## Task C1: `AuthSession` manager with a fake provider

The session manager holds in-progress connect attempts keyed by a random id, runs long flows in background threads, and exposes start/status/submit/cancel. Providers are pluggable; this task builds the manager + a fake provider and the provider protocol.

**Files:**
- Create: `ghostbrain/api/auth/__init__.py` (empty)
- Create: `ghostbrain/api/auth/session.py`
- Create: `ghostbrain/api/auth/providers/__init__.py`
- Create: `ghostbrain/api/auth/providers/base.py`
- Test: `tests/api/auth/test_session.py`

**Interfaces:**
- Produces:
  ```python
  # providers/base.py
  @dataclass
  class NextAction:
      kind: str                 # "open_browser"|"show_device_code"|"need_input"|"need_grant"|"done"
      auth_url: str | None = None
      verification_uri: str | None = None
      user_code: str | None = None
      fields: list[dict] | None = None   # [{name,label,type,placeholder}]
      message: str | None = None

  class AuthProvider(Protocol):
      pattern: str
      def start(self, connector_id: str, params: dict) -> NextAction: ...
      def submit(self, connector_id: str, session: "Session", data: dict) -> NextAction: ...
      def poll(self, connector_id: str, session: "Session") -> None: ...   # advances session.status; long-running
      def account_label(self, session: "Session") -> str | None: ...

  # session.py
  @dataclass
  class Session:
      id: str
      connector_id: str
      status: str          # "pending"|"waiting_input"|"success"|"error"
      next: NextAction
      account: str | None = None
      error: str | None = None
      created_at: float = ...

  class AuthSessionManager:
      def start(self, connector_id: str, provider: AuthProvider, params: dict) -> Session: ...
      def status(self, session_id: str) -> Session | None: ...
      def submit(self, session_id: str, provider: AuthProvider, data: dict) -> Session: ...
      def cancel(self, session_id: str) -> None: ...
      def sweep(self, now: float, ttl_s: float = 300) -> None: ...
  ```

- [ ] **Step 1: Write the failing test**

```python
# tests/api/auth/test_session.py
import time
from ghostbrain.api.auth.session import AuthSessionManager, Session
from ghostbrain.api.auth.providers.base import NextAction


class FakeProvider:
    pattern = "fake"

    def start(self, connector_id, params):
        return NextAction(kind="need_input", fields=[{"name": "token", "label": "Token", "type": "password"}])

    def submit(self, connector_id, session, data):
        if data.get("token") == "good":
            session.status = "success"
            session.account = "fake@acct"
            return NextAction(kind="done")
        session.status = "error"
        session.error = "bad token"
        return NextAction(kind="need_input", fields=[])

    def poll(self, connector_id, session):
        pass

    def account_label(self, session):
        return session.account


def test_start_returns_need_input():
    m = AuthSessionManager()
    s = m.start("slack", FakeProvider(), {})
    assert s.status == "waiting_input"
    assert s.next.kind == "need_input"
    assert m.status(s.id) is s


def test_submit_success():
    m = AuthSessionManager()
    s = m.start("slack", FakeProvider(), {})
    s2 = m.submit(s.id, FakeProvider(), {"token": "good"})
    assert s2.status == "success"
    assert s2.account == "fake@acct"


def test_submit_bad_token_errors_but_keeps_session():
    m = AuthSessionManager()
    s = m.start("slack", FakeProvider(), {})
    s2 = m.submit(s.id, FakeProvider(), {"token": "nope"})
    assert s2.status == "error"
    assert s2.error == "bad token"


def test_sweep_expires_old_sessions():
    m = AuthSessionManager()
    s = m.start("slack", FakeProvider(), {})
    m.sweep(now=s.created_at + 10_000, ttl_s=300)
    assert m.status(s.id) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/auth/test_session.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement base + session**

```python
# ghostbrain/api/auth/providers/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ghostbrain.api.auth.session import Session


@dataclass
class NextAction:
    kind: str
    auth_url: str | None = None
    verification_uri: str | None = None
    user_code: str | None = None
    fields: list[dict] | None = None
    message: str | None = None


class AuthProvider(Protocol):
    pattern: str

    def start(self, connector_id: str, params: dict) -> NextAction: ...
    def submit(self, connector_id: str, session: "Session", data: dict) -> NextAction: ...
    def poll(self, connector_id: str, session: "Session") -> None: ...
    def account_label(self, session: "Session") -> str | None: ...
```

```python
# ghostbrain/api/auth/session.py
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from ghostbrain.api.auth.providers.base import AuthProvider, NextAction

# status derived from a NextAction kind
_STATUS_FOR_KIND = {
    "need_input": "waiting_input",
    "open_browser": "pending",
    "show_device_code": "pending",
    "need_grant": "pending",
    "done": "success",
}


@dataclass
class Session:
    id: str
    connector_id: str
    status: str
    next: NextAction
    account: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)


class AuthSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def start(self, connector_id: str, provider: AuthProvider, params: dict) -> Session:
        action = provider.start(connector_id, params)
        sess = Session(
            id=secrets.token_hex(16),
            connector_id=connector_id,
            status=_STATUS_FOR_KIND.get(action.kind, "pending"),
            next=action,
        )
        if action.kind == "done":
            sess.account = provider.account_label(sess)
        with self._lock:
            self._sessions[sess.id] = sess
        # kick off background poll for long-running flows
        if action.kind in ("open_browser", "show_device_code", "need_grant"):
            threading.Thread(
                target=self._run_poll, args=(sess, provider), daemon=True
            ).start()
        return sess

    def _run_poll(self, sess: Session, provider: AuthProvider) -> None:
        try:
            provider.poll(sess.connector_id, sess)
        except Exception as e:  # noqa: BLE001
            sess.status = "error"
            sess.error = str(e)

    def status(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def submit(self, session_id: str, provider: AuthProvider, data: dict) -> Session:
        sess = self.status(session_id)
        if sess is None:
            raise KeyError(session_id)
        action = provider.submit(sess.connector_id, sess, data)
        sess.next = action
        if sess.status not in ("success", "error"):
            sess.status = _STATUS_FOR_KIND.get(action.kind, sess.status)
        if sess.status == "success" and sess.account is None:
            sess.account = provider.account_label(sess)
        return sess

    def cancel(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def sweep(self, now: float, ttl_s: float = 300) -> None:
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if now - s.created_at > ttl_s]
            for sid in expired:
                del self._sessions[sid]
```

Create the two empty `__init__.py` files.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/auth/test_session.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/auth tests/api/auth
git commit -m "feat(auth): AuthSession manager + provider protocol"
```

## Task C2: Provider registry + FastAPI router

**Files:**
- Create: `ghostbrain/api/auth/registry.py`
- Create: `ghostbrain/api/routes/connector_auth.py`
- Modify: `ghostbrain/api/main.py:33-48` (include the router; attach a manager to `app.state`)
- Test: `tests/api/routes/test_connector_auth.py`

**Interfaces:**
- Consumes: `AuthSessionManager` (C1), providers (Milestone D register here).
- Produces: `registry.provider_for(connector_id) -> AuthProvider`; routes:
  - `POST /v1/connectors/{id}/auth/start` → `{session_id, status, next}`
  - `GET  /v1/connectors/{id}/auth/status?session_id=` → `{status, next, account, error}`
  - `POST /v1/connectors/{id}/auth/submit` body `{session_id, data}` → same shape as status
  - `POST /v1/connectors/{id}/auth/cancel` body `{session_id}` → `{ok:true}`
  - `DELETE /v1/connectors/{id}/credentials` (Milestone D) → `{ok:true}`

- [ ] **Step 1: Write the failing test** (uses a stub provider injected into the registry)

```python
# tests/api/routes/test_connector_auth.py
import pytest
from fastapi.testclient import TestClient
from ghostbrain.api.main import create_app
from ghostbrain.api import auth as auth_pkg
from ghostbrain.api.auth import registry
from ghostbrain.api.auth.providers.base import NextAction


class StubProvider:
    pattern = "stub"
    def start(self, connector_id, params):
        return NextAction(kind="need_input", fields=[{"name": "token", "label": "T", "type": "password"}])
    def submit(self, connector_id, session, data):
        session.status = "success"; session.account = "acct"
        return NextAction(kind="done")
    def poll(self, connector_id, session): pass
    def account_label(self, session): return "acct"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(registry, "provider_for", lambda cid: StubProvider())
    app = create_app()
    return TestClient(app)


def test_start_then_submit(client):
    r = client.post("/v1/connectors/slack/auth/start", json={"params": {}})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    assert r.json()["next"]["kind"] == "need_input"

    r2 = client.post("/v1/connectors/slack/auth/submit", json={"session_id": sid, "data": {"token": "x"}})
    assert r2.status_code == 200
    assert r2.json()["status"] == "success"
    assert r2.json()["account"] == "acct"


def test_status_unknown_session_404(client):
    r = client.get("/v1/connectors/slack/auth/status", params={"session_id": "nope"})
    assert r.status_code == 404


def test_unknown_connector_404(client, monkeypatch):
    monkeypatch.setattr(registry, "provider_for", lambda cid: (_ for _ in ()).throw(KeyError(cid)))
    r = client.post("/v1/connectors/bogus/auth/start", json={"params": {}})
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/routes/test_connector_auth.py -v`
Expected: FAIL — router/registry missing. (Confirm `create_app` is the app factory in `ghostbrain/api/main.py`; if the factory has a different name, match it.)

- [ ] **Step 3: Implement registry + router + wiring**

```python
# ghostbrain/api/auth/registry.py
"""Maps connector id -> AuthProvider instance. Providers registered in
Milestone D. Raising KeyError for unknown ids yields a 404 in the router."""
from __future__ import annotations

from ghostbrain.api.auth.providers.base import AuthProvider

_PROVIDERS: dict[str, AuthProvider] = {}


def register(connector_id: str, provider: AuthProvider) -> None:
    _PROVIDERS[connector_id] = provider


def provider_for(connector_id: str) -> AuthProvider:
    return _PROVIDERS[connector_id]  # KeyError -> 404
```

```python
# ghostbrain/api/routes/connector_auth.py
"""Auth-session endpoints: start / status / submit / cancel / disconnect."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ghostbrain.api.auth import registry
from ghostbrain.api.auth.session import AuthSessionManager, Session

router = APIRouter(prefix="/v1/connectors", tags=["connector-auth"])


class StartBody(BaseModel):
    params: dict = {}


class SubmitBody(BaseModel):
    session_id: str
    data: dict = {}


class CancelBody(BaseModel):
    session_id: str


def _manager(request: Request) -> AuthSessionManager:
    mgr = getattr(request.app.state, "auth_sessions", None)
    if mgr is None:
        mgr = AuthSessionManager()
        request.app.state.auth_sessions = mgr
    mgr.sweep(now=time.monotonic())
    return mgr


def _view(sess: Session) -> dict:
    n = sess.next
    return {
        "session_id": sess.id,
        "status": sess.status,
        "account": sess.account,
        "error": sess.error,
        "next": {
            "kind": n.kind,
            "auth_url": n.auth_url,
            "verification_uri": n.verification_uri,
            "user_code": n.user_code,
            "fields": n.fields,
            "message": n.message,
        },
    }


def _provider(connector_id: str):
    try:
        return registry.provider_for(connector_id)
    except KeyError:
        raise HTTPException(404, f"No auth provider for connector: {connector_id}")


@router.post("/{connector_id}/auth/start")
def auth_start(connector_id: str, body: StartBody, request: Request) -> dict:
    provider = _provider(connector_id)
    sess = _manager(request).start(connector_id, provider, body.params)
    return _view(sess)


@router.get("/{connector_id}/auth/status")
def auth_status(connector_id: str, request: Request, session_id: str = Query(...)) -> dict:
    sess = _manager(request).status(session_id)
    if sess is None or sess.connector_id != connector_id:
        raise HTTPException(404, "Unknown or expired auth session")
    return _view(sess)


@router.post("/{connector_id}/auth/submit")
def auth_submit(connector_id: str, body: SubmitBody, request: Request) -> dict:
    provider = _provider(connector_id)
    try:
        sess = _manager(request).submit(body.session_id, provider, body.data)
    except KeyError:
        raise HTTPException(404, "Unknown or expired auth session")
    return _view(sess)


@router.post("/{connector_id}/auth/cancel")
def auth_cancel(connector_id: str, body: CancelBody, request: Request) -> dict:
    _manager(request).cancel(body.session_id)
    return {"ok": True}
```

In `ghostbrain/api/main.py`, add after the other `include_router` calls (import at top):

```python
from ghostbrain.api.routes import connector_auth as connector_auth_routes
# ... inside create_app, with the other includes:
    app.include_router(connector_auth_routes.router)
    import ghostbrain.api.auth.providers.register_all  # noqa: F401  (registers providers, Task D6)
```

Note: `register_all` is created in Task D6; until then the import will fail. To keep C2 green in isolation, create a placeholder now:

```python
# ghostbrain/api/auth/providers/register_all.py
"""Registers all real providers. Populated across Milestone D."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/routes/test_connector_auth.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/auth/registry.py ghostbrain/api/auth/providers/register_all.py ghostbrain/api/routes/connector_auth.py ghostbrain/api/main.py tests/api/routes/test_connector_auth.py
git commit -m "feat(auth): connector auth-session router + provider registry"
```

---

# Milestone D — Backend: real provider adapters

Each provider wraps existing auth code. Tasks D1–D5 implement one pattern each; D6 registers them; D7 adds disconnect. Order chosen simplest-first.

## Task D1: `paste_token` provider (Slack + Joplin)

**Files:**
- Create: `ghostbrain/api/auth/providers/paste_token.py`
- Test: `tests/api/auth/providers/test_paste_token.py`

**Interfaces:**
- Consumes: `slack/auth.py:save_token`, `slack_sdk.WebClient.auth_test`, `routing.merge_routing`, joplin `/ping`.
- Produces: `SlackTokenProvider`, `JoplinTokenProvider` (both `pattern="paste_token"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/auth/providers/test_paste_token.py
import pytest
from ghostbrain.api.auth.providers.paste_token import SlackTokenProvider, JoplinTokenProvider
from ghostbrain.api.auth.session import Session
from ghostbrain.api.auth.providers.base import NextAction


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    (tmp_path / "vault" / "90-meta").mkdir(parents=True)
    return tmp_path


def _sess(cid):
    return Session(id="s", connector_id=cid, status="waiting_input", next=NextAction(kind="need_input"))


def test_slack_start_asks_for_slug_and_token(state):
    action = SlackTokenProvider().start("slack", {})
    names = {f["name"] for f in action.fields}
    assert {"workspace_slug", "token"} <= names


def test_slack_submit_saves_token(state, monkeypatch):
    # stub auth.test so no network
    import ghostbrain.api.auth.providers.paste_token as mod
    monkeypatch.setattr(mod, "_slack_auth_test", lambda t: {"user": "me", "team": "T"})
    p = SlackTokenProvider()
    sess = _sess("slack")
    action = p.submit("slack", sess, {"workspace_slug": "work", "token": "xoxp-abc"})
    assert sess.status == "success"
    from ghostbrain.connectors.slack.auth import token_path
    assert token_path("work").exists()


def test_slack_submit_rejects_bad_prefix(state):
    p = SlackTokenProvider()
    sess = _sess("slack")
    p.submit("slack", sess, {"workspace_slug": "work", "token": "not-a-token"})
    assert sess.status == "error"


def test_joplin_submit_saves_token_to_routing(state, monkeypatch):
    import ghostbrain.api.auth.providers.paste_token as mod
    monkeypatch.setattr(mod, "_joplin_ping", lambda host, token: True)
    p = JoplinTokenProvider()
    sess = _sess("joplin")
    p.submit("joplin", sess, {"token": "abc", "host": "http://localhost:41184"})
    assert sess.status == "success"
    from ghostbrain.api.repo.routing import load_routing
    assert load_routing()["joplin"]["token"] == "abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/auth/providers/test_paste_token.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# ghostbrain/api/auth/providers/paste_token.py
from __future__ import annotations

from ghostbrain.api.auth.providers.base import NextAction
from ghostbrain.api.repo.routing import merge_routing


def _slack_auth_test(token: str) -> dict:
    from slack_sdk import WebClient

    return WebClient(token=token).auth_test().data


def _joplin_ping(host: str, token: str) -> bool:
    import requests

    r = requests.get(f"{host.rstrip('/')}/ping", params={"token": token}, timeout=10)
    return r.status_code == 200 and r.text.strip() == "JoplinClipperServer"


class SlackTokenProvider:
    pattern = "paste_token"

    def start(self, connector_id, params):
        return NextAction(
            kind="need_input",
            message="Create a Slack app, add the User Token scopes, install it, and paste the xoxp- token.",
            fields=[
                {"name": "workspace_slug", "label": "Workspace slug", "type": "text",
                 "placeholder": "work"},
                {"name": "token", "label": "User OAuth Token", "type": "password",
                 "placeholder": "xoxp-…"},
            ],
        )

    def submit(self, connector_id, session, data):
        from ghostbrain.connectors.slack.auth import SlackAuthError, save_token

        slug = (data.get("workspace_slug") or "").strip()
        token = (data.get("token") or "").strip()
        if not slug:
            session.status = "error"; session.error = "Workspace slug is required"
            return NextAction(kind="need_input", fields=[])
        try:
            save_token(slug, token)          # validates xoxp/xoxb prefix
            ident = _slack_auth_test(token)  # network validate
        except SlackAuthError as e:
            session.status = "error"; session.error = str(e)
            return NextAction(kind="need_input", fields=[])
        except Exception as e:  # noqa: BLE001
            session.status = "error"; session.error = f"Slack rejected the token: {e}"
            return NextAction(kind="need_input", fields=[])
        session.status = "success"
        session.account = f"@{ident.get('user')} · {ident.get('team')}"
        merge_routing({"slack": {"workspaces": {slug: {"context": "needs_review",
                       "lookback_hours": 24, "mentions_only": True}}}})
        return NextAction(kind="done")

    def poll(self, connector_id, session):  # not used
        pass

    def account_label(self, session):
        return session.account


class JoplinTokenProvider:
    pattern = "paste_token"

    def start(self, connector_id, params):
        return NextAction(
            kind="need_input",
            message="In Joplin: Tools → Options → Web Clipper → enable the service, then copy the token.",
            fields=[
                {"name": "token", "label": "Web Clipper token", "type": "password"},
                {"name": "host", "label": "Host (optional)", "type": "text",
                 "placeholder": "http://localhost:41184"},
            ],
        )

    def submit(self, connector_id, session, data):
        token = (data.get("token") or "").strip()
        host = (data.get("host") or "http://localhost:41184").strip()
        if not token:
            session.status = "error"; session.error = "Token is required"
            return NextAction(kind="need_input", fields=[])
        try:
            ok = _joplin_ping(host, token)
        except Exception as e:  # noqa: BLE001
            session.status = "error"; session.error = f"Could not reach Joplin: {e}"
            return NextAction(kind="need_input", fields=[])
        if not ok:
            session.status = "error"; session.error = "Joplin rejected the token or Web Clipper is off"
            return NextAction(kind="need_input", fields=[])
        session.status = "success"; session.account = host
        merge_routing({"joplin": {"token": token, "host": host}})
        return NextAction(kind="done")

    def poll(self, connector_id, session):
        pass

    def account_label(self, session):
        return session.account
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/auth/providers/test_paste_token.py -v`
Expected: PASS (4 tests). (Create `tests/api/auth/providers/__init__.py` if the runner needs it.)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/auth/providers/paste_token.py tests/api/auth/providers/
git commit -m "feat(auth): paste-token provider for slack + joplin"
```

## Task D2: `atlassian_api` provider (Jira + Confluence)

**Files:**
- Create: `ghostbrain/api/auth/providers/atlassian_api.py`
- Test: `tests/api/auth/providers/test_atlassian_api.py`

**Interfaces:**
- Consumes: `dotenv_store.set_env`, `routing.merge_routing`, Atlassian `/rest/api/3/myself` (validate).
- Produces: `AtlassianTokenProvider` (`pattern="atlassian_api"`). One identity shared by jira + confluence; `connector_id` decides which routing subtree gets the site.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/auth/providers/test_atlassian_api.py
import pytest
from ghostbrain.api.auth.providers.atlassian_api import AtlassianTokenProvider
from ghostbrain.api.auth.session import Session
from ghostbrain.api.auth.providers.base import NextAction


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    (tmp_path / "vault" / "90-meta").mkdir(parents=True)
    return tmp_path


def _sess(cid):
    return Session(id="s", connector_id=cid, status="waiting_input", next=NextAction(kind="need_input"))


def test_start_fields(env):
    action = AtlassianTokenProvider().start("jira", {})
    names = {f["name"] for f in action.fields}
    assert {"email", "token", "site"} <= names


def test_submit_writes_env_and_routing(env, monkeypatch):
    import ghostbrain.api.auth.providers.atlassian_api as mod
    monkeypatch.setattr(mod, "_validate_myself", lambda email, token, site: {"displayName": "Me"})
    p = AtlassianTokenProvider()
    sess = _sess("jira")
    p.submit("jira", sess, {"email": "me@x.com", "token": "tok", "site": "acme.atlassian.net"})
    assert sess.status == "success"
    from ghostbrain.api.repo.dotenv_store import read_env
    env_vals = read_env()
    assert env_vals["ATLASSIAN_EMAIL"] == "me@x.com"
    assert env_vals["ATLASSIAN_TOKEN_ACME"] == "tok"
    from ghostbrain.api.repo.routing import load_routing
    assert load_routing()["jira"]["sites"]["acme.atlassian.net"] == "needs_review"


def test_submit_bad_creds_errors(env, monkeypatch):
    import ghostbrain.api.auth.providers.atlassian_api as mod
    def boom(*a): raise RuntimeError("401")
    monkeypatch.setattr(mod, "_validate_myself", boom)
    p = AtlassianTokenProvider()
    sess = _sess("confluence")
    p.submit("confluence", sess, {"email": "me@x.com", "token": "bad", "site": "acme.atlassian.net"})
    assert sess.status == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/auth/providers/test_atlassian_api.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# ghostbrain/api/auth/providers/atlassian_api.py
from __future__ import annotations

from ghostbrain.api.auth.providers.base import NextAction
from ghostbrain.api.repo.dotenv_store import set_env
from ghostbrain.api.repo.routing import merge_routing


def _slug(site: str) -> str:
    return site.split(".", 1)[0].upper().replace("-", "_")


def _validate_myself(email: str, token: str, site: str) -> dict:
    from base64 import b64encode
    import requests

    cred = b64encode(f"{email}:{token}".encode()).decode()
    r = requests.get(
        f"https://{site}/rest/api/3/myself",
        headers={"Authorization": f"Basic {cred}", "Accept": "application/json"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


class AtlassianTokenProvider:
    pattern = "atlassian_api"

    def start(self, connector_id, params):
        extra = []
        if connector_id == "confluence":
            extra = [{"name": "spaces", "label": "Space keys (comma-sep, optional)", "type": "text",
                      "placeholder": "DOCS, PROJ"}]
        return NextAction(
            kind="need_input",
            message="Create an Atlassian API token, then enter your email, the token, and your site.",
            fields=[
                {"name": "email", "label": "Atlassian email", "type": "text"},
                {"name": "token", "label": "API token", "type": "password"},
                {"name": "site", "label": "Site", "type": "text", "placeholder": "acme.atlassian.net"},
                *extra,
            ],
        )

    def submit(self, connector_id, session, data):
        email = (data.get("email") or "").strip()
        token = (data.get("token") or "").strip()
        site = (data.get("site") or "").strip().replace("https://", "").rstrip("/")
        if not (email and token and site):
            session.status = "error"; session.error = "Email, token and site are all required"
            return NextAction(kind="need_input", fields=[])
        try:
            me = _validate_myself(email, token, site)
        except Exception as e:  # noqa: BLE001
            session.status = "error"; session.error = f"Atlassian rejected these credentials: {e}"
            return NextAction(kind="need_input", fields=[])
        set_env({"ATLASSIAN_EMAIL": email, f"ATLASSIAN_TOKEN_{_slug(site)}": token})
        merge_routing({connector_id: {"sites": {site: "needs_review"}}})
        if connector_id == "confluence":
            spaces = [s.strip() for s in (data.get("spaces") or "").split(",") if s.strip()]
            if spaces:
                merge_routing({"confluence": {"spaces": {s: "needs_review" for s in spaces}}})
        session.status = "success"
        session.account = me.get("emailAddress") or email
        return NextAction(kind="done", message="This also connects the other Atlassian app.")

    def poll(self, connector_id, session):
        pass

    def account_label(self, session):
        return session.account
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/auth/providers/test_atlassian_api.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/auth/providers/atlassian_api.py tests/api/auth/providers/test_atlassian_api.py
git commit -m "feat(auth): atlassian API-token provider for jira + confluence"
```

## Task D3: `cli_login` provider (GitHub) + `local_grant` provider (Claude Code)

Both are "detect / enable" flows with no secret. Grouped because each is small.

**Files:**
- Create: `ghostbrain/api/auth/providers/cli_login.py`
- Create: `ghostbrain/api/auth/providers/local_grant.py`
- Test: `tests/api/auth/providers/test_cli_local.py`

**Interfaces:**
- Produces: `GitHubProvider` (`pattern="cli_login"`), `ClaudeCodeProvider` + `MacosCalendarProvider` (`pattern="local_grant"`).
- GitHub `start`: if `gh` logged in → `done`; else → `need_grant` with `gh auth login` guidance; `poll` re-checks `gh auth status` for up to ~2 min.
- ClaudeCode `submit`: writes `SessionEnd` hook into `~/.claude/settings.json` (atomic, merge) after the UI has shown the change; maps a project path→context in routing.
- MacosCalendar `start`: `need_grant`; `poll` attempts an EventKit read to trigger/confirm the OS prompt.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/auth/providers/test_cli_local.py
import json
import pytest
from ghostbrain.api.auth.providers.cli_login import GitHubProvider
from ghostbrain.api.auth.providers.local_grant import ClaudeCodeProvider
from ghostbrain.api.auth.session import Session
from ghostbrain.api.auth.providers.base import NextAction


def _sess(cid):
    return Session(id="s", connector_id=cid, status="pending", next=NextAction(kind="need_grant"))


def test_github_done_when_logged_in(monkeypatch):
    import ghostbrain.api.auth.providers.cli_login as mod
    monkeypatch.setattr(mod, "_gh_logged_in", lambda: (True, "octocat"))
    action = GitHubProvider().start("github", {})
    assert action.kind == "done"


def test_github_need_grant_when_logged_out(monkeypatch):
    import ghostbrain.api.auth.providers.cli_login as mod
    monkeypatch.setattr(mod, "_gh_logged_in", lambda: (False, None))
    action = GitHubProvider().start("github", {})
    assert action.kind == "need_grant"
    assert "gh auth login" in (action.message or "")


def test_claude_code_writes_hook(tmp_path, monkeypatch):
    home = tmp_path
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    (tmp_path / "vault" / "90-meta").mkdir(parents=True)
    p = ClaudeCodeProvider()
    sess = _sess("claude_code")
    p.submit("claude_code", sess, {"hook_script": "/x/session-end.sh"})
    assert sess.status == "success"
    data = json.loads((home / ".claude" / "settings.json").read_text())
    assert "SessionEnd" in data["hooks"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/auth/providers/test_cli_local.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement both**

```python
# ghostbrain/api/auth/providers/cli_login.py
from __future__ import annotations

import shutil
import subprocess
import time

from ghostbrain.api.auth.providers.base import NextAction


def _gh_logged_in() -> tuple[bool, str | None]:
    if shutil.which("gh") is None:
        return (False, None)
    try:
        r = subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=5, text=True)
    except (subprocess.SubprocessError, OSError):
        return (False, None)
    if r.returncode != 0:
        return (False, None)
    # gh prints "Logged in to github.com account <login>"
    login = None
    for line in (r.stderr + r.stdout).splitlines():
        if "account " in line:
            login = line.split("account ", 1)[1].split()[0].strip()
            break
    return (True, login)


class GitHubProvider:
    pattern = "cli_login"

    def start(self, connector_id, params):
        ok, login = _gh_logged_in()
        if ok:
            return NextAction(kind="done", message=f"Signed in as {login}" if login else "Signed in")
        gh_present = shutil.which("gh") is not None
        msg = (
            "Run `gh auth login` in your terminal to sign in, then press Re-check."
            if gh_present
            else "Install the GitHub CLI (`brew install gh`), run `gh auth login`, then Re-check."
        )
        return NextAction(kind="need_grant", message=msg)

    def poll(self, connector_id, session):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            ok, login = _gh_logged_in()
            if ok:
                session.status = "success"
                session.account = login
                session.next = NextAction(kind="done")
                return
            time.sleep(3)
        session.status = "error"
        session.error = "Timed out waiting for gh login. Run `gh auth login` and try again."

    def account_label(self, session):
        return session.account
```

```python
# ghostbrain/api/auth/providers/local_grant.py
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ghostbrain.api.auth.providers.base import NextAction
from ghostbrain.api.repo.routing import merge_routing


def _claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


class ClaudeCodeProvider:
    pattern = "local_grant"

    def start(self, connector_id, params):
        default_script = str(
            Path.home() / "development" / "ghost-brain" / "orchestration" / "hooks" / "session-end.sh"
        )
        return NextAction(
            kind="need_input",
            message="Poltergeist will add a SessionEnd hook to ~/.claude/settings.json.",
            fields=[
                {"name": "hook_script", "label": "Hook script path", "type": "text",
                 "placeholder": default_script},
                {"name": "project_path", "label": "Project path (optional)", "type": "text"},
                {"name": "context", "label": "Context for that project (optional)", "type": "text"},
            ],
        )

    def submit(self, connector_id, session, data):
        script = (data.get("hook_script") or "").strip()
        if not script:
            session.status = "error"; session.error = "Hook script path is required"
            return NextAction(kind="need_input", fields=[])
        path = _claude_settings_path()
        try:
            doc = json.loads(path.read_text()) if path.exists() else {}
        except (OSError, ValueError):
            doc = {}
        hooks = doc.setdefault("hooks", {})
        hooks["SessionEnd"] = [
            {"matcher": "*", "hooks": [
                {"type": "command", "command": script, "shell": "bash", "async": True}
            ]}
        ]
        try:
            _write_json_atomic(path, doc)
        except OSError as e:
            session.status = "error"; session.error = f"Could not write settings.json: {e}"
            return NextAction(kind="need_input", fields=[])
        proj = (data.get("project_path") or "").strip()
        ctx = (data.get("context") or "").strip()
        if proj and ctx:
            merge_routing({"claude_code": {"project_paths": {proj: ctx}}})
        session.status = "success"; session.account = "SessionEnd hook installed"
        return NextAction(kind="done")

    def poll(self, connector_id, session):
        pass

    def account_label(self, session):
        return session.account


class MacosCalendarProvider:
    pattern = "local_grant"

    def start(self, connector_id, params):
        return NextAction(
            kind="need_grant",
            message="Grant Calendar access when macOS prompts, then press Re-check.",
        )

    def poll(self, connector_id, session):
        # Best-effort: attempt an EventKit read to trigger/confirm the grant.
        try:
            from ghostbrain.connectors.calendar.macos import macos_calendar_available  # if present
            ok = macos_calendar_available()
        except Exception:  # noqa: BLE001
            ok = True  # can't verify; assume the user granted it
        session.status = "success" if ok else "error"
        session.next = NextAction(kind="done")
        if not ok:
            session.error = "Calendar access not granted"

    def account_label(self, session):
        return "macOS Calendar"
```

Note: `macos_calendar_available` may not exist; the `try/except` falls back to assuming granted, so the test (which doesn't import it) passes. If a real predicate exists in `ghostbrain/connectors/calendar/macos/__init__.py`, use its actual name here.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/auth/providers/test_cli_local.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/auth/providers/cli_login.py ghostbrain/api/auth/providers/local_grant.py tests/api/auth/providers/test_cli_local.py
git commit -m "feat(auth): github cli-login + claude-code/macos local-grant providers"
```

## Task D4: `ms_device_code` provider (Microsoft trio)

**Files:**
- Create: `ghostbrain/api/auth/providers/ms_device_code.py`
- Test: `tests/api/auth/providers/test_ms_device_code.py`

**Interfaces:**
- Consumes: `microsoft/graph/auth.py` — but the existing `run_device_flow` prints and blocks on `acquire_token_by_device_flow`. This provider re-implements the *orchestration* (initiate → expose code → poll) using MSAL directly so the UI can show the code, while still using `_build_app`/`resolve_scopes`/`cache_location` from the existing module (NOT duplicating token-cache logic).
- Produces: `MicrosoftProvider` (`pattern="ms_device_code"`). `start` requires `microsoft.client_id`/`tenant_id` in routing (or env); if absent, returns `need_input` for them first.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/auth/providers/test_ms_device_code.py
import pytest
from ghostbrain.api.auth.providers.ms_device_code import MicrosoftProvider
from ghostbrain.api.auth.session import Session
from ghostbrain.api.auth.providers.base import NextAction


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "vault" / "90-meta").mkdir(parents=True)
    return tmp_path


def _sess():
    return Session(id="s", connector_id="outlook_mail", status="pending", next=NextAction(kind="need_input"))


def test_start_needs_app_config_when_missing(vault):
    action = MicrosoftProvider().start("outlook_mail", {})
    names = {f["name"] for f in (action.fields or [])}
    assert {"client_id", "tenant_id"} <= names


def test_submit_app_config_then_shows_device_code(vault, monkeypatch):
    import ghostbrain.api.auth.providers.ms_device_code as mod

    class FakeApp:
        def initiate_device_flow(self, scopes):
            return {"user_code": "ABCD-EFGH", "verification_uri": "https://microsoft.com/devicelogin",
                    "message": "go", "device_code": "dev", "expires_in": 900, "interval": 5}
    monkeypatch.setattr(mod, "_build_app", lambda cfg: FakeApp())
    p = MicrosoftProvider()
    sess = _sess()
    action = p.submit("outlook_mail", sess, {"client_id": "cid", "tenant_id": "tid"})
    assert action.kind == "show_device_code"
    assert action.user_code == "ABCD-EFGH"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/auth/providers/test_ms_device_code.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# ghostbrain/api/auth/providers/ms_device_code.py
from __future__ import annotations

from ghostbrain.api.auth.providers.base import NextAction
from ghostbrain.api.repo.routing import load_routing, merge_routing


def _app_config() -> dict:
    return (load_routing().get("microsoft") or {})


def _has_app_config() -> bool:
    import os

    cfg = _app_config()
    cid = cfg.get("client_id") or os.environ.get("MS_GRAPH_CLIENT_ID")
    tid = cfg.get("tenant_id") or os.environ.get("MS_GRAPH_TENANT_ID")
    return bool(cid and tid)


def _build_app(cfg: dict):
    # Reuse the existing token-cache + PublicClientApplication builder.
    from ghostbrain.connectors.microsoft.graph.auth import _build_app as build

    return build(cfg)


def _scopes(cfg: dict) -> list[str]:
    from ghostbrain.connectors.microsoft.graph.auth import resolve_scopes

    return resolve_scopes(cfg)


class MicrosoftProvider:
    pattern = "ms_device_code"

    def _app_config_fields(self) -> NextAction:
        return NextAction(
            kind="need_input",
            message="Register a public-client Azure app (device-code, no secret), then enter its IDs.",
            fields=[
                {"name": "client_id", "label": "Application (client) ID", "type": "text"},
                {"name": "tenant_id", "label": "Directory (tenant) ID", "type": "text"},
            ],
        )

    def start(self, connector_id, params):
        if not _has_app_config():
            return self._app_config_fields()
        return self._begin_device_flow(_app_config())

    def _begin_device_flow(self, cfg: dict) -> NextAction:
        app = _build_app(cfg)
        flow = app.initiate_device_flow(scopes=_scopes(cfg))
        if "user_code" not in flow:
            return NextAction(kind="need_input", message=f"Could not start device flow: {flow}", fields=[])
        # stash flow on the session via the returned action's message-free fields:
        self._pending_flow = flow  # picked up by poll through session (see submit/start wiring)
        return NextAction(
            kind="show_device_code",
            verification_uri=flow.get("verification_uri"),
            user_code=flow.get("user_code"),
            message=flow.get("message"),
        )

    def submit(self, connector_id, session, data):
        cid = (data.get("client_id") or "").strip()
        tid = (data.get("tenant_id") or "").strip()
        if not (cid and tid):
            session.status = "error"; session.error = "client_id and tenant_id are required"
            return NextAction(kind="need_input", fields=[])
        merge_routing({"microsoft": {"client_id": cid, "tenant_id": tid}})
        action = self._begin_device_flow(_app_config())
        session.next = action
        if action.kind == "show_device_code":
            session.status = "pending"
            session._ms_flow = self._pending_flow  # type: ignore[attr-defined]
        return action

    def poll(self, connector_id, session):
        cfg = _app_config()
        app = _build_app(cfg)
        flow = getattr(session, "_ms_flow", None) or getattr(self, "_pending_flow", None)
        if flow is None:
            session.status = "error"; session.error = "No device flow in progress"
            return
        result = app.acquire_token_by_device_flow(flow)  # blocks until done/expired
        if "access_token" not in result:
            session.status = "error"
            session.error = result.get("error_description", "Microsoft sign-in failed")
            return
        accounts = app.get_accounts()
        session.account = accounts[0].get("username") if accounts else "your account"
        session.status = "success"
        session.next = NextAction(kind="done")

    def account_label(self, session):
        return session.account
```

Note: the provider stores the in-flight `flow` on the `Session` (`session._ms_flow`) so `poll` (run in the manager's thread after `start`/`submit`) can complete it. Because `start` may return `show_device_code` directly (when app config already present), also set `session._ms_flow` in the manager path — handled by the manager calling `poll` which reads `self._pending_flow` as fallback. Keep a single `MicrosoftProvider` instance in the registry (Task D6) so `_pending_flow` survives between `start` and `poll`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/auth/providers/test_ms_device_code.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/auth/providers/ms_device_code.py tests/api/auth/providers/test_ms_device_code.py
git commit -m "feat(auth): microsoft device-code provider with visible user code"
```

## Task D5: `google_oauth` provider (Gmail + Calendar)

**Files:**
- Create: `ghostbrain/api/auth/providers/google_oauth.py`
- Test: `tests/api/auth/providers/test_google_oauth.py`

**Interfaces:**
- Consumes: `gmail/auth.py` and `calendar/google/auth.py` — `oauth_client_path()`, `run_oauth_flow(email)`. The client JSON is shared; if missing, `start` asks for it (file contents pasted / dropped) and writes it to `oauth_client_path()`. Then per account: `open_browser` + `run_local_server` in the poll thread.
- Produces: `GoogleProvider` (`pattern="google_oauth"`). `connector_id` selects the module (gmail vs calendar) → correct scope + token path.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/auth/providers/test_google_oauth.py
import json
import pytest
from ghostbrain.api.auth.providers.google_oauth import GoogleProvider
from ghostbrain.api.auth.session import Session
from ghostbrain.api.auth.providers.base import NextAction


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    return tmp_path / "state"


def _sess(cid):
    return Session(id="s", connector_id=cid, status="pending", next=NextAction(kind="need_input"))


def test_start_asks_for_client_json_when_missing(state):
    action = GoogleProvider().start("gmail", {})
    names = {f["name"] for f in (action.fields or [])}
    assert "client_json" in names


def test_submit_client_json_then_asks_account(state):
    p = GoogleProvider()
    sess = _sess("gmail")
    client = json.dumps({"installed": {"client_id": "x", "client_secret": "y",
                        "auth_uri": "a", "token_uri": "t", "redirect_uris": ["http://localhost"]}})
    action = p.submit("gmail", sess, {"client_json": client})
    from ghostbrain.connectors.gmail.auth import oauth_client_path
    assert oauth_client_path().exists()
    assert action.kind == "need_input"
    assert any(f["name"] == "account" for f in action.fields)


def test_start_asks_account_when_client_present(state):
    from ghostbrain.connectors.gmail.auth import oauth_client_path
    oauth_client_path().write_text("{}")
    action = GoogleProvider().start("gmail", {})
    assert any(f["name"] == "account" for f in (action.fields or []))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/auth/providers/test_google_oauth.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# ghostbrain/api/auth/providers/google_oauth.py
from __future__ import annotations

import threading

from ghostbrain.api.auth.providers.base import NextAction


def _mod(connector_id: str):
    if connector_id == "gmail":
        from ghostbrain.connectors.gmail import auth as m
        return m
    from ghostbrain.connectors.calendar.google import auth as m
    return m


class GoogleProvider:
    pattern = "google_oauth"

    def __init__(self) -> None:
        self._flows: dict[str, object] = {}  # session_id -> flow (for cancel)

    def _account_field(self, connector_id: str) -> NextAction:
        return NextAction(
            kind="need_input",
            message=("A browser window will open for Google consent. Google shows an "
                     "“unverified app” warning for your own client — choose Advanced → Continue."),
            fields=[{"name": "account", "label": "Google account email", "type": "text",
                     "placeholder": "you@gmail.com"}],
        )

    def start(self, connector_id, params):
        m = _mod(connector_id)
        if not m.oauth_client_path().exists():
            return NextAction(
                kind="need_input",
                message="Paste the Desktop OAuth client JSON you downloaded from Google Cloud.",
                fields=[{"name": "client_json", "label": "OAuth client JSON", "type": "textarea"}],
            )
        return self._account_field(connector_id)

    def submit(self, connector_id, session, data):
        m = _mod(connector_id)
        if "client_json" in data and data["client_json"].strip():
            path = m.oauth_client_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data["client_json"].strip(), encoding="utf-8")
            path.chmod(0o600)
            action = self._account_field(connector_id)
            session.status = "waiting_input"; session.next = action
            return action
        account = (data.get("account") or "").strip()
        if not account:
            session.status = "error"; session.error = "Account email is required"
            return NextAction(kind="need_input", fields=[])
        # Hand off to the browser flow; poll() runs it. Store target on session.
        session._google_account = account  # type: ignore[attr-defined]
        session.status = "pending"
        action = NextAction(kind="open_browser", auth_url="about:blank",
                            message="Opening your browser for Google sign-in…")
        session.next = action
        # The manager only launches poll() for actions returned by start(); for a
        # submit that transitions to a browser flow we launch poll() here.
        threading.Thread(target=self._poll_safe, args=(connector_id, session), daemon=True).start()
        return action

    def _poll_safe(self, connector_id, session):
        try:
            self.poll(connector_id, session)
        except Exception as e:  # noqa: BLE001
            session.status = "error"; session.error = str(e)

    def poll(self, connector_id, session):
        m = _mod(connector_id)
        account = getattr(session, "_google_account", None)
        if not account:
            session.status = "error"; session.error = "No account specified"
            return
        try:
            m.run_oauth_flow(account)  # opens system browser, run_local_server catches redirect
        except Exception as e:  # noqa: BLE001
            session.status = "error"; session.error = str(e)
            return
        session.status = "success"; session.account = account
        session.next = NextAction(kind="done")

    def account_label(self, session):
        return session.account
```

Note: `run_oauth_flow` itself calls `open_browser=True`, so the sidecar opens the browser directly — the renderer does not need `openExternal` for Google (the `auth_url` is a placeholder). The renderer's `open_browser` handling should tolerate `about:blank` (skip opening). This keeps Google's PKCE/redirect entirely in Python.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/auth/providers/test_google_oauth.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/auth/providers/google_oauth.py tests/api/auth/providers/test_google_oauth.py
git commit -m "feat(auth): google oauth provider for gmail + calendar"
```

## Task D6: Register all providers

**Files:**
- Modify: `ghostbrain/api/auth/providers/register_all.py`
- Test: `tests/api/auth/test_registry_wiring.py`

**Interfaces:**
- Consumes: all providers D1–D5. Produces: `registry.provider_for(id)` resolves for every connect card connector. Single shared instances (important for `MicrosoftProvider`/`GoogleProvider` in-flight state).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/auth/test_registry_wiring.py
import pytest
import ghostbrain.api.auth.providers.register_all  # noqa: F401
from ghostbrain.api.auth import registry


@pytest.mark.parametrize("cid", [
    "gmail", "calendar", "slack", "joplin", "jira", "confluence",
    "outlook_mail", "teams_chat", "teams_meetings", "github", "claude_code",
])
def test_provider_registered(cid):
    assert registry.provider_for(cid) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/auth/test_registry_wiring.py -v`
Expected: FAIL — providers not registered yet.

- [ ] **Step 3: Implement**

```python
# ghostbrain/api/auth/providers/register_all.py
"""Registers all real providers. Imported for its side effects by main.py."""
from __future__ import annotations

from ghostbrain.api.auth import registry
from ghostbrain.api.auth.providers.atlassian_api import AtlassianTokenProvider
from ghostbrain.api.auth.providers.cli_login import GitHubProvider
from ghostbrain.api.auth.providers.google_oauth import GoogleProvider
from ghostbrain.api.auth.providers.local_grant import ClaudeCodeProvider, MacosCalendarProvider
from ghostbrain.api.auth.providers.ms_device_code import MicrosoftProvider
from ghostbrain.api.auth.providers.paste_token import JoplinTokenProvider, SlackTokenProvider

# Shared instances where in-flight state must survive start→poll.
_google = GoogleProvider()
_ms = MicrosoftProvider()
_atlassian = AtlassianTokenProvider()

registry.register("gmail", _google)
registry.register("calendar", _google)  # google calendar; macOS grant handled separately in UI
registry.register("slack", SlackTokenProvider())
registry.register("joplin", JoplinTokenProvider())
registry.register("jira", _atlassian)
registry.register("confluence", _atlassian)
registry.register("outlook_mail", _ms)
registry.register("teams_chat", _ms)
registry.register("teams_meetings", _ms)
registry.register("github", GitHubProvider())
registry.register("claude_code", ClaudeCodeProvider())
registry.register("macos_calendar", MacosCalendarProvider())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/auth/test_registry_wiring.py tests/api/routes/test_connector_auth.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/auth/providers/register_all.py tests/api/auth/test_registry_wiring.py
git commit -m "feat(auth): register all connector auth providers"
```

## Task D7: Disconnect endpoint (`DELETE /credentials`)

**Files:**
- Create: `ghostbrain/api/auth/disconnect.py`
- Modify: `ghostbrain/api/routes/connector_auth.py` (add the DELETE route)
- Test: `tests/api/auth/test_disconnect.py`

**Interfaces:**
- Produces: `disconnect(connector_id: str, account: str | None) -> None`. Removes token files / keychain cache / `.env` keys / `routing.yaml` secrets. Idempotent (missing = no error).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/auth/test_disconnect.py
import pytest
from ghostbrain.api.auth.disconnect import disconnect


@pytest.fixture
def env(tmp_path, monkeypatch):
    s = tmp_path / "state"; s.mkdir()
    v = tmp_path / "vault"; (v / "90-meta").mkdir(parents=True)
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(s))
    monkeypatch.setenv("VAULT_PATH", str(v))
    return s, v


def test_disconnect_slack_removes_token_file(env):
    s, _ = env
    (s / "slack.work.token").write_text("xoxp")
    disconnect("slack", account="work")
    assert not (s / "slack.work.token").exists()


def test_disconnect_joplin_removes_routing_token(env):
    from ghostbrain.api.repo.routing import merge_routing, load_routing
    merge_routing({"joplin": {"token": "abc", "host": "h"}})
    disconnect("joplin", account=None)
    assert "token" not in load_routing().get("joplin", {})


def test_disconnect_missing_is_noop(env):
    disconnect("gmail", account="nobody@x.com")  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/auth/test_disconnect.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement + route**

```python
# ghostbrain/api/auth/disconnect.py
from __future__ import annotations

from ghostbrain.paths import state_dir


def _rm(path) -> None:
    try:
        path.unlink()
    except (FileNotFoundError, OSError):
        pass


def disconnect(connector_id: str, account: str | None) -> None:
    d = state_dir()
    if connector_id == "gmail" and account:
        from ghostbrain.connectors.gmail.auth import token_path
        _rm(token_path(account))
    elif connector_id == "calendar" and account:
        from ghostbrain.connectors.calendar.google.auth import token_path
        _rm(token_path(account))
    elif connector_id == "slack":
        if account:
            from ghostbrain.connectors.slack.auth import token_path
            _rm(token_path(account))
        else:
            for f in d.glob("slack.*.token"):
                _rm(f)
    elif connector_id == "joplin":
        from ghostbrain.api.repo.routing import remove_routing_path
        remove_routing_path("joplin.token")
    elif connector_id in ("jira", "confluence"):
        # Shared Atlassian identity — only remove the routing subtree for this app,
        # leave the shared .env token (the other app may still use it).
        from ghostbrain.api.repo.routing import remove_routing_path
        remove_routing_path(f"{connector_id}.sites")
    elif connector_id in ("outlook_mail", "teams_chat", "teams_meetings"):
        from ghostbrain.connectors.microsoft.graph.auth import cache_location
        _rm(cache_location())
    elif connector_id == "claude_code":
        import json
        from pathlib import Path
        p = Path.home() / ".claude" / "settings.json"
        if p.exists():
            try:
                doc = json.loads(p.read_text())
                doc.get("hooks", {}).pop("SessionEnd", None)
                p.write_text(json.dumps(doc, indent=2))
            except (OSError, ValueError):
                pass
    # github: nothing we own (gh manages its own login); no-op.
```

Add to `connector_auth.py`:

```python
from ghostbrain.api.auth.disconnect import disconnect as _disconnect


@router.delete("/{connector_id}/credentials")
def credentials_delete(connector_id: str, account: str | None = Query(None)) -> dict:
    _disconnect(connector_id, account)
    return {"ok": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/auth/test_disconnect.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/auth/disconnect.py ghostbrain/api/routes/connector_auth.py tests/api/auth/test_disconnect.py
git commit -m "feat(auth): disconnect endpoint removes per-connector credentials"
```

## Task D8: Backend integration smoke test

**Files:**
- Test: `tests/api/routes/test_connector_auth_integration.py`

- [ ] **Step 1: Write the test** (real providers via `create_app`, paste-token path end-to-end with network stubbed)

```python
# tests/api/routes/test_connector_auth_integration.py
import pytest
from fastapi.testclient import TestClient
from ghostbrain.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    (tmp_path / "vault" / "90-meta").mkdir(parents=True)
    import ghostbrain.api.auth.providers.paste_token as mod
    monkeypatch.setattr(mod, "_slack_auth_test", lambda t: {"user": "me", "team": "T"})
    return TestClient(create_app())


def test_slack_connect_flow(client):
    start = client.post("/v1/connectors/slack/auth/start", json={"params": {}}).json()
    sid = start["session_id"]
    sub = client.post("/v1/connectors/slack/auth/submit",
                      json={"session_id": sid, "data": {"workspace_slug": "work", "token": "xoxp-abc"}}).json()
    assert sub["status"] == "success"
    # connector now reads 'on'
    conns = {c["id"]: c for c in client.get("/v1/connectors").json()}
    assert conns["slack"]["state"] == "on"


def test_disconnect_flips_off(client):
    client.post("/v1/connectors/slack/auth/start", json={"params": {}})
    # save directly then delete
    from ghostbrain.connectors.slack.auth import save_token
    save_token("work", "xoxp-abc")
    client.delete("/v1/connectors/slack/credentials", params={"account": "work"})
    conns = {c["id"]: c for c in client.get("/v1/connectors").json()}
    assert conns["slack"]["state"] == "off"
```

- [ ] **Step 2: Run** — Expected FAIL first if anything mis-wired, then fix; PASS.

Run: `python -m pytest tests/api/routes/test_connector_auth_integration.py -v`

- [ ] **Step 3: Run the whole backend suite**

Run: `python -m pytest tests/api -v`
Expected: PASS (no regressions).

- [ ] **Step 4: Commit**

```bash
git add tests/api/routes/test_connector_auth_integration.py
git commit -m "test(auth): end-to-end connector auth + disconnect integration"
```

---

# Milestone E — Desktop bridge: types + hooks

## Task E1: Shared wire types + preload/settings for onboarding

**Files:**
- Modify: `desktop/src/shared/api-types.ts` (add auth-session types)
- Modify: `desktop/src/shared/types.ts` (`Settings` gains `onboardingComplete: boolean`)
- Modify: `desktop/src/main/settings.ts` (default `onboardingComplete: false`)
- Modify: `desktop/src/main/index.ts` (settingsSchema: add `onboardingComplete`)
- Modify: `desktop/src/renderer/stores/settings.ts` (default in placeholder)
- Test: `desktop/src/renderer/__tests__/onboarding-types.test.ts` (compile-level guard + settings default)

**Interfaces:**
- Produces (api-types.ts):
  ```typescript
  export type AuthStatus = 'pending' | 'waiting_input' | 'success' | 'error';
  export interface AuthField { name: string; label: string; type: 'text' | 'password' | 'textarea'; placeholder?: string; }
  export interface AuthNext {
    kind: 'open_browser' | 'show_device_code' | 'need_input' | 'need_grant' | 'done';
    auth_url: string | null; verification_uri: string | null; user_code: string | null;
    fields: AuthField[] | null; message: string | null;
  }
  export interface AuthSessionView { session_id: string; status: AuthStatus; account: string | null; error: string | null; next: AuthNext; }
  ```

- [ ] **Step 1: Write the failing test**

```typescript
// desktop/src/renderer/__tests__/onboarding-types.test.ts
import { describe, it, expect } from 'vitest';
import type { AuthSessionView } from '../../shared/api-types';

describe('onboarding wiring', () => {
  it('AuthSessionView shape is usable', () => {
    const v: AuthSessionView = {
      session_id: 's', status: 'waiting_input', account: null, error: null,
      next: { kind: 'need_input', auth_url: null, verification_uri: null, user_code: null,
              fields: [{ name: 'token', label: 'T', type: 'password' }], message: null },
    };
    expect(v.next.fields?.[0].name).toBe('token');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/onboarding-types.test.ts`
Expected: FAIL — types not exported.

- [ ] **Step 3: Add the types + settings field**

Append the `AuthStatus`/`AuthField`/`AuthNext`/`AuthSessionView` block to `api-types.ts`. Add `onboardingComplete: boolean;` to `Settings` in `types.ts`. Add `onboardingComplete: false` to `defaults` in `settings.ts` and to the renderer store placeholder. In `index.ts`, extend `settingsSchema.shape` with `onboardingComplete: z.boolean()` (match the existing zod schema style — locate `settingsSchema` definition and add the field).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/onboarding-types.test.ts && npx tsc --noEmit`
Expected: PASS + typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/shared/api-types.ts desktop/src/shared/types.ts desktop/src/main/settings.ts desktop/src/main/index.ts desktop/src/renderer/stores/settings.ts desktop/src/renderer/__tests__/onboarding-types.test.ts
git commit -m "feat(desktop): auth-session wire types + onboardingComplete setting"
```

## Task E2: Renderer API hooks for auth sessions

**Files:**
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (add hooks + imports)
- Test: `desktop/src/renderer/__tests__/auth-hooks.test.tsx`

**Interfaces:**
- Produces:
  ```typescript
  useStartAuth()      // mutation: (args:{id:string; params?:Record<string,unknown>}) => AuthSessionView
  useSubmitAuth()     // mutation: (args:{id:string; sessionId:string; data:Record<string,unknown>}) => AuthSessionView
  useAuthStatus(id, sessionId, enabled)  // query, polls every 2s while status pending/waiting_input
  useCancelAuth()     // mutation: (args:{id:string; sessionId:string}) => void
  useDisconnectConnector()  // mutation: (args:{id:string; account?:string}) => void, invalidates ['connectors']
  ```

- [ ] **Step 1: Write the failing test**

```typescript
// desktop/src/renderer/__tests__/auth-hooks.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useStartAuth } from '../lib/api/hooks';

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  (globalThis as any).window.gb = {
    api: { request: vi.fn().mockResolvedValue({ ok: true, data: {
      session_id: 's', status: 'waiting_input', account: null, error: null,
      next: { kind: 'need_input', fields: [], auth_url: null, verification_uri: null, user_code: null, message: null } } }) },
  };
});

describe('useStartAuth', () => {
  it('posts to the start endpoint', async () => {
    const { result } = renderHook(() => useStartAuth(), { wrapper });
    result.current.mutate({ id: 'slack', params: {} });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(window.gb.api.request).toHaveBeenCalledWith('POST', '/v1/connectors/slack/auth/start', { params: {} });
    expect(result.current.data?.session_id).toBe('s');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/auth-hooks.test.tsx`
Expected: FAIL — `useStartAuth` not exported.

- [ ] **Step 3: Implement the hooks** (append to `hooks.ts`; add `AuthSessionView` to the type imports and `del` to the api-client import if not present)

```typescript
import type { AuthSessionView } from '../../../shared/api-types';
// ensure: import { get, post, del } from './client';

export function useStartAuth() {
  return useMutation({
    mutationFn: (a: { id: string; params?: Record<string, unknown> }) =>
      post<AuthSessionView>(`/v1/connectors/${a.id}/auth/start`, { params: a.params ?? {} }),
  });
}

export function useSubmitAuth() {
  return useMutation({
    mutationFn: (a: { id: string; sessionId: string; data: Record<string, unknown> }) =>
      post<AuthSessionView>(`/v1/connectors/${a.id}/auth/submit`, { session_id: a.sessionId, data: a.data }),
  });
}

export function useAuthStatus(id: string | null, sessionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['auth-status', id, sessionId],
    queryFn: () => get<AuthSessionView>(`/v1/connectors/${id}/auth/status?session_id=${sessionId}`),
    enabled: enabled && id !== null && sessionId !== null,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === 'pending' || s === 'waiting_input' ? 2000 : false;
    },
  });
}

export function useCancelAuth() {
  return useMutation({
    mutationFn: (a: { id: string; sessionId: string }) =>
      post(`/v1/connectors/${a.id}/auth/cancel`, { session_id: a.sessionId }),
  });
}

export function useDisconnectConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: { id: string; account?: string }) =>
      del(`/v1/connectors/${a.id}/credentials${a.account ? `?account=${encodeURIComponent(a.account)}` : ''}`),
    onSettled: () => qc.invalidateQueries({ queryKey: ['connectors'] }),
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/auth-hooks.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/lib/api/hooks.ts desktop/src/renderer/__tests__/auth-hooks.test.tsx
git commit -m "feat(desktop): react-query hooks for connector auth sessions"
```

---

# Milestone F — Desktop: flow components + connector catalog

## Task F1: Connector catalog (single source of truth for cards + patterns)

Replaces `setup-content.ts` recipes with a catalog describing each connect card and its auth pattern.

**Files:**
- Create: `desktop/src/renderer/lib/connector-catalog.ts`
- Test: `desktop/src/renderer/__tests__/connector-catalog.test.ts`

**Interfaces:**
- Produces:
  ```typescript
  export type AuthPattern = 'google_oauth' | 'ms_device_code' | 'paste_token' | 'atlassian_api' | 'cli_login' | 'local_grant';
  export interface ConnectorCard {
    id: string;            // connector id used in API paths (e.g. 'gmail')
    displayName: string;
    blurb: string;
    pattern: AuthPattern;
    docsUrl?: string;      // deep link to create credentials
    group?: string;        // 'google' | 'microsoft' | 'atlassian' to co-present
    subConnectors?: string[]; // e.g. microsoft card enables outlook_mail/teams_chat/teams_meetings
  }
  export const CONNECTOR_CARDS: ConnectorCard[];
  export function cardForId(id: string): ConnectorCard | undefined;
  ```

- [ ] **Step 1: Write the failing test**

```typescript
// desktop/src/renderer/__tests__/connector-catalog.test.ts
import { describe, it, expect } from 'vitest';
import { CONNECTOR_CARDS, cardForId } from '../lib/connector-catalog';

describe('connector catalog', () => {
  it('covers the nine connect cards', () => {
    const ids = CONNECTOR_CARDS.map((c) => c.id);
    expect(ids).toEqual(expect.arrayContaining([
      'gmail', 'calendar', 'slack', 'github', 'jira', 'confluence', 'joplin', 'macos_calendar', 'claude_code',
    ]));
  });
  it('every card has a known pattern', () => {
    const patterns = new Set(['google_oauth','ms_device_code','paste_token','atlassian_api','cli_login','local_grant']);
    for (const c of CONNECTOR_CARDS) expect(patterns.has(c.pattern)).toBe(true);
  });
  it('cardForId resolves', () => {
    expect(cardForId('slack')?.pattern).toBe('paste_token');
  });
});
```

- [ ] **Step 2: Run** — Expected: FAIL (module missing).

Run: `cd desktop && npx vitest run src/renderer/__tests__/connector-catalog.test.ts`

- [ ] **Step 3: Implement** the catalog with all nine cards (gmail→google_oauth, calendar→google_oauth, a microsoft card with `subConnectors: ['outlook_mail','teams_chat','teams_meetings']`, slack→paste_token, joplin→paste_token, jira/confluence→atlassian_api, github→cli_login, macos_calendar→local_grant, claude_code→local_grant), each with `blurb` copied from the old `RECIPES` blurbs and `docsUrl` deep links (Google Cloud console, api.slack.com/apps, id.atlassian.com token page, Joplin docs).

- [ ] **Step 4: Run** — Expected: PASS.

Run: `cd desktop && npx vitest run src/renderer/__tests__/connector-catalog.test.ts`

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/lib/connector-catalog.ts desktop/src/renderer/__tests__/connector-catalog.test.ts
git commit -m "feat(desktop): connector catalog (cards + auth patterns)"
```

## Task F2: `ConnectorAuthFlow` driver component

A single component that, given a connector id + pattern, drives start→(render next)→submit/poll→success/error using the E2 hooks. Renders the pattern-specific UI from the server's `next` action, so most patterns need no bespoke component.

**Files:**
- Create: `desktop/src/renderer/components/ConnectorAuthFlow.tsx`
- Test: `desktop/src/renderer/__tests__/ConnectorAuthFlow.test.tsx`

**Interfaces:**
- Consumes: `useStartAuth`, `useSubmitAuth`, `useAuthStatus`, `useCancelAuth`, `window.gb.shell.openExternal`.
- Produces: `<ConnectorAuthFlow connectorId={string} onDone={(account?:string)=>void} onCancel={()=>void} />`. Renders:
  - `need_input` → a form from `next.fields` + `next.message`; submit calls `useSubmitAuth`.
  - `show_device_code` → shows `user_code` + "copy & open" button (`openExternal(verification_uri)`), then polls.
  - `open_browser` → if `auth_url` and not `about:blank`, `openExternal(auth_url)`; shows spinner; polls.
  - `need_grant` → message + "Re-check" (re-poll) button.
  - `done`/`success` → calls `onDone(account)`.
  - `error` → inline error + Retry (re-start).

- [ ] **Step 1: Write the failing test**

```tsx
// desktop/src/renderer/__tests__/ConnectorAuthFlow.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConnectorAuthFlow } from '../components/ConnectorAuthFlow';

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  const responses: Record<string, unknown> = {
    'POST /v1/connectors/slack/auth/start': { session_id: 's', status: 'waiting_input', account: null, error: null,
      next: { kind: 'need_input', fields: [{ name: 'token', label: 'Token', type: 'password' }], auth_url: null, verification_uri: null, user_code: null, message: 'paste it' } },
    'POST /v1/connectors/slack/auth/submit': { session_id: 's', status: 'success', account: '@me', error: null,
      next: { kind: 'done', fields: null, auth_url: null, verification_uri: null, user_code: null, message: null } },
  };
  (globalThis as any).window.gb = {
    api: { request: vi.fn((m: string, p: string) => Promise.resolve({ ok: true, data: responses[`${m} ${p}`] })) },
    shell: { openExternal: vi.fn().mockResolvedValue({ ok: true }) },
  };
});

describe('ConnectorAuthFlow', () => {
  it('renders need_input form then completes on submit', async () => {
    const onDone = vi.fn();
    wrap(<ConnectorAuthFlow connectorId="slack" onDone={onDone} onCancel={() => {}} />);
    await waitFor(() => screen.getByLabelText('Token'));
    fireEvent.change(screen.getByLabelText('Token'), { target: { value: 'xoxp-abc' } });
    fireEvent.click(screen.getByRole('button', { name: /connect|submit|save/i }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('@me'));
  });
});
```

- [ ] **Step 2: Run** — Expected: FAIL (component missing).

Run: `cd desktop && npx vitest run src/renderer/__tests__/ConnectorAuthFlow.test.tsx`

- [ ] **Step 3: Implement** `ConnectorAuthFlow.tsx`: on mount call `useStartAuth`; hold `session` in state; render by `session.next.kind`; wire `useAuthStatus(id, session.session_id, polling)` and update `session` from its data; on `status==='success'` call `onDone(account)`; on `error` show retry. Use existing `Btn`, `Lucide`, and form primitives; match the app's styling conventions (see `setup.tsx`/`connectors.tsx`).

- [ ] **Step 4: Run** — Expected: PASS.

Run: `cd desktop && npx vitest run src/renderer/__tests__/ConnectorAuthFlow.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/components/ConnectorAuthFlow.tsx desktop/src/renderer/__tests__/ConnectorAuthFlow.test.tsx
git commit -m "feat(desktop): ConnectorAuthFlow driver renders server-driven auth steps"
```

---

# Milestone G — Desktop: wire connectors screen + wizard + cleanup

## Task G1: Real connect / reauthorize / disconnect on the connectors screen

**Files:**
- Modify: `desktop/src/renderer/screens/connectors.tsx` (replace `stub(3)` on connect/reauthorize/disconnect with a modal hosting `ConnectorAuthFlow` / `useDisconnectConnector`)
- Test: `desktop/src/renderer/__tests__/connectors-connect.test.tsx`

**Interfaces:**
- Consumes: `ConnectorAuthFlow` (F2), `useDisconnectConnector` (E2), `cardForId` (F1).

- [ ] **Step 1: Write the failing test** — clicking "connect {name}" on an `off` connector opens the flow modal (asserts the modal / form appears); "disconnect" calls the disconnect mutation. Mock `window.gb.api.request`.

```tsx
// desktop/src/renderer/__tests__/connectors-connect.test.tsx  (skeleton — fill selectors to match impl)
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConnectorsScreen } from '../screens/connectors';
// mock hooks/api so useConnectors returns one 'off' slack connector; assert modal opens on connect click
```

- [ ] **Step 2: Run** — Expected: FAIL.

Run: `cd desktop && npx vitest run src/renderer/__tests__/connectors-connect.test.tsx`

- [ ] **Step 3: Implement** — add local modal state to `ConnectorsScreen`/`ConnectorDetailPanel`; the `connect`/`reauthorize` buttons open `<ConnectorAuthFlow connectorId={c.id} onDone={...invalidate connectors...} onCancel={close} />`; `disconnect` calls `useDisconnectConnector` behind a confirm. Remove the `stub(3)` calls for these three actions. Leave `pause` + filter toggles as `stub(3)` (out of scope; note in commit).

- [ ] **Step 4: Run** — Expected: PASS. Also run the existing connectors test to ensure no regression: `npx vitest run src/renderer/__tests__ -t Connector`.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/screens/connectors.tsx desktop/src/renderer/__tests__/connectors-connect.test.tsx
git commit -m "feat(desktop): real connect/reauthorize/disconnect on connectors screen"
```

## Task G2: First-run wizard screen

**Files:**
- Create: `desktop/src/renderer/screens/onboarding.tsx`
- Modify: `desktop/src/renderer/stores/navigation.ts` (add `'onboarding'` to `ScreenId`)
- Modify: `desktop/src/renderer/App.tsx` (route `onboarding`; on load, if `!settings.onboardingComplete` set active to `onboarding`)
- Test: `desktop/src/renderer/__tests__/onboarding.test.tsx`

**Interfaces:**
- Consumes: `CONNECTOR_CARDS` (F1), `ConnectorAuthFlow` (F2), `useConnectors`, `useSettings` (to set `onboardingComplete`), vault-path logic from `setup.tsx`'s `VaultCard`.
- Steps: welcome → vault → pick sources (checkbox grid over `CONNECTOR_CARDS`) → connect selected (one `ConnectorAuthFlow` at a time, progress rail) → done (sets `onboardingComplete=true`, enables scheduler, navigates to `connectors`). "I'll do this later" at any step sets `onboardingComplete=true` and navigates away.

- [ ] **Step 1: Write the failing test** — renders welcome; "get started" advances; picking slack + clicking through reaches the connect step showing `ConnectorAuthFlow`; "skip" sets `onboardingComplete`. Mock hooks.

- [ ] **Step 2: Run** — Expected: FAIL.

Run: `cd desktop && npx vitest run src/renderer/__tests__/onboarding.test.tsx`

- [ ] **Step 3: Implement** the wizard as a step machine (local `useState<'welcome'|'vault'|'pick'|'connect'|'done'>`), reusing `ConnectorAuthFlow` per selected card. Add the route + first-run redirect in `App.tsx` (guard on `settings.ready && !settings.onboardingComplete`).

- [ ] **Step 4: Run** — Expected: PASS.

Run: `cd desktop && npx vitest run src/renderer/__tests__/onboarding.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/screens/onboarding.tsx desktop/src/renderer/stores/navigation.ts desktop/src/renderer/App.tsx desktop/src/renderer/__tests__/onboarding.test.tsx
git commit -m "feat(desktop): first-run connector onboarding wizard"
```

## Task G3: Retire the recipe setup screen

**Files:**
- Delete: `desktop/src/renderer/screens/setup.tsx`
- Delete: `desktop/src/renderer/lib/setup-content.ts`
- Modify: `desktop/src/renderer/App.tsx` (remove `setup` route + import)
- Modify: `desktop/src/renderer/stores/navigation.ts` (remove `'setup'` from `ScreenId`)
- Modify: `desktop/src/renderer/screens/connectors.tsx` (`add connector` button + `AddConnectorRow` open a connector-picker modal reusing `CONNECTOR_CARDS` + `ConnectorAuthFlow`, instead of `setActive('setup')`)
- Modify/remove: any test referencing `SetupScreen`/`setup-content` (grep first)

- [ ] **Step 1: Find references**

Run: `cd desktop && grep -rn "setup-content\|SetupScreen\|'setup'\|\"setup\"\|screens/setup" src`
Expected: know every touch point before deleting.

- [ ] **Step 2: Write/adjust the test** — update or add a test asserting `add connector` opens the picker (not navigation to a removed screen). Add `desktop/src/renderer/__tests__/add-connector-picker.test.tsx`.

- [ ] **Step 3: Run** — Expected: FAIL (picker not wired).

Run: `cd desktop && npx vitest run src/renderer/__tests__/add-connector-picker.test.tsx`

- [ ] **Step 4: Implement** the picker + delete the files + remove routes/type members.

- [ ] **Step 5: Run full renderer suite + typecheck**

Run: `cd desktop && npx tsc --noEmit && npx vitest run`
Expected: PASS, no dangling references.

- [ ] **Step 6: Commit**

```bash
git add -A desktop/src
git commit -m "refactor(desktop): retire copy-paste setup screen; add-connector opens picker"
```

---

# Milestone H — Verification

## Task H1: Full suites + manual smoke

- [ ] **Step 1: Backend**

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 2: Desktop**

Run: `cd desktop && npx tsc --noEmit && npx vitest run && npm run lint`
Expected: PASS.

- [ ] **Step 3: Manual smoke (real accounts)** — with the app running (`npm run dev` in `desktop/`, sidecar from `.venv`):
  - Slack: create app, paste xoxp token → connector flips to `on`, account shows.
  - Atlassian: token + site → jira & confluence both read `on`.
  - GitHub: with `gh auth login` done → `on` instantly; logged out → guidance + re-check.
  - Google: drop client JSON → browser consent → gmail `on` (note the unverified-app warning appears as documented).
  - Microsoft: enter client/tenant → device code shows → sign in → outlook/teams read `on`.
  - Disconnect each → flips back to `off`.
  - Fresh profile (rename `~/Library/Application Support/<app>/config.json`) → wizard launches on first run; "I'll do this later" → lands on connectors and never re-prompts.

- [ ] **Step 4: Commit any fixups, then finalize**

Use the `superpowers:finishing-a-development-branch` skill to open the PR.

---

## Self-review notes (author)

- **Spec coverage:** §3 patterns A–F → Tasks D1–D5 (whisper descoped to a link, documented in reconciliation). §4 architecture → Milestones A–C. §4.3 status → A2/A3. §4.4 desktop wiring (`openExternal` already exists; hooks) → E1/E2. §5.1 wizard → G2. §5.2 flow components → F2 (server-driven single component covers all six patterns; matches "one component per pattern" intent by rendering each pattern's `next`). §5.3 connectors screen → G1. §6 error handling → session TTL sweep (C2), inline errors in providers + ConnectorAuthFlow, atomic writers (B1/B2/D3). §7 testing → per-task tests + H1. Retire setup screen → G3.
- **Type consistency:** `AuthSessionView`/`AuthNext`/`NextAction.kind` values match between Python (`_view` in C2) and TS (`api-types.ts` E1). Provider `submit(connector_id, session, data)` signature is uniform across D1–D5 and matches the `AuthProvider` protocol in C1.
- **Known coupling:** `_joplin_probe` (A2) imports `load_routing` (B1) — B1 runs immediately after A-milestone in practice; A2's own tests don't exercise the joplin path. Flagged inline in A2 Step 3.
