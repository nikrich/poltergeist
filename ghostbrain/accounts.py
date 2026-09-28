"""Per-account connector registry — ``<vault>/90-meta/accounts.yaml``.

One list of connected accounts (a Gmail address, a Slack workspace, an
Atlassian site, a gh login, a Microsoft username), each optionally mapped to a
context. This module is the only reader and writer of that file: connectors
read their accounts here, and the router maps ``metadata.accountId`` to a
context here.

The file is seeded once from the legacy per-account blocks in routing.yaml
(``gmail.accounts``, ``calendar.google.accounts``, ``slack.workspaces``,
``jira.sites``, ``confluence.sites``) plus live ``gh`` / MSAL logins, the
first time it is read and does not exist. After that those routing.yaml
blocks are ignored. Secrets never live here.
"""
from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import yaml

from ghostbrain import routing_config
from ghostbrain.paths import state_dir, vault_path

try:
    import fcntl
except ImportError:  # Windows: in-process lock only
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger("ghostbrain.accounts")

ACCOUNT_CONNECTORS: tuple[str, ...] = (
    "gmail", "calendar_google", "slack", "jira", "confluence", "github", "microsoft",
)

# Event source / connector id -> account connector. Calendar events from the
# macos provider have no account connector (see account_connector_for_event).
SOURCE_TO_ACCOUNT_CONNECTOR: dict[str, str] = {
    "gmail": "gmail",
    "calendar": "calendar_google",
    "slack": "slack",
    "jira": "jira",
    "confluence": "confluence",
    "github": "github",
    "outlook_mail": "microsoft",
    "teams_chat": "microsoft",
    "teams_meetings": "microsoft",
}

# Placeholder contexts older connect flows wrote; never a real assignment.
_UNASSIGNED = frozenset({"needs_review"})

_thread_lock = threading.RLock()

# routing.yaml paths already warned about as unreadable (warn once per path).
_warned_routing: set[str] = set()


@dataclasses.dataclass(frozen=True)
class Account:
    connector: str
    id: str
    context: str | None = None
    enabled: bool = True
    options: dict = dataclasses.field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.connector, self.id.lower())


def accounts_path(root: Path | None = None) -> Path:
    return (root or vault_path()) / "90-meta" / "accounts.yaml"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_accounts(
    connector: str | None = None,
    *,
    root: Path | None = None,
    include_disabled: bool = False,
) -> list[Account]:
    _ensure_seeded(root)
    return [
        a for a in _read(accounts_path(root))
        if (connector is None or a.connector == connector)
        and (include_disabled or a.enabled)
    ]


def get_account(
    connector: str | None, account_id: str | None, *, root: Path | None = None,
) -> Account | None:
    if not connector or not account_id:
        return None
    key = (connector, str(account_id).lower())
    for a in list_accounts(connector, root=root, include_disabled=True):
        if a.key == key:
            return a
    return None


def context_for(
    connector: str | None, account_id: str | None, *, root: Path | None = None,
) -> str | None:
    """The account's context, or None when unassigned, unknown, or the
    context is no longer in routing.yaml's ``contexts:`` list."""
    acc = get_account(connector, account_id, root=root)
    if acc is None or not acc.context:
        return None
    if acc.context not in routing_config.contexts(root):
        return None
    return acc.context


def account_connector_for_event(event: dict) -> str | None:
    source = event.get("source") or ""
    if source == "calendar":
        provider = (event.get("metadata") or {}).get("provider")
        return "calendar_google" if provider == "google" else None
    return SOURCE_TO_ACCOUNT_CONNECTOR.get(source)


def upsert_account(
    acc: Account, *, root: Path | None = None, check_context: bool = True,
) -> Account:
    """Insert or replace ``acc``. ``check_context=False`` skips the
    "context is in contexts()" check — for updates that don't touch the
    context, so an account whose context was archived stays editable."""
    return _upsert(acc, root=root, check_context=check_context)


def _upsert(acc: Account, *, root: Path | None, check_context: bool) -> Account:
    _validate(acc, root, check_context=check_context)
    _ensure_seeded(root)
    path = accounts_path(root)
    with _locked(root):
        current = _read(path)
        out: list[Account] = []
        replaced = False
        for a in current:
            if a.key == acc.key:
                out.append(acc)
                replaced = True
            else:
                out.append(a)
        if not replaced:
            out.append(acc)
        _write(path, out)
    return acc


def ensure_account(
    connector: str,
    account_id: str,
    *,
    options: dict | None = None,
    root: Path | None = None,
) -> Account:
    """Add the account unassigned if absent; otherwise merge ``options`` into
    it, keeping its context and enabled flag. Used by auth flows."""
    existing = get_account(connector, account_id, root=root)
    if existing is None:
        return upsert_account(
            Account(connector, account_id.strip(), None, True, dict(options or {})),
            root=root,
        )
    if options:
        merged = {**existing.options, **options}
        if merged != existing.options:
            # The stored context may no longer be in contexts(); keep it
            # as-is rather than failing a sign-in over it.
            return _upsert(
                dataclasses.replace(existing, options=merged), root=root, check_context=False,
            )
    return existing


def remove_account(connector: str, account_id: str, *, root: Path | None = None) -> bool:
    _ensure_seeded(root)
    path = accounts_path(root)
    key = (connector, str(account_id).lower())
    with _locked(root):
        current = _read(path)
        kept = [a for a in current if a.key != key]
        if len(kept) == len(current):
            return False
        _write(path, kept)
    return True


def gh_logins(host: str = "github.com") -> list[str]:
    """Every account ``gh`` knows for ``host`` (gh supports several logins
    per host). Empty when gh is missing or fails."""
    gh = shutil.which("gh")
    if gh is None:
        return []
    try:
        r = subprocess.run(
            [gh, "auth", "status", "--hostname", host],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("gh auth status failed: %s", e)
        return []
    found = re.findall(r"account (\S+)", (r.stdout or "") + (r.stderr or ""))
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _locked(root: Path | None) -> Iterator[None]:
    """Serialise writers across threads (scheduler + API share a process) and,
    where fcntl exists, across processes (auth CLIs, the worker). The lock
    file lives in the state dir, not the vault, so it never lands in a
    synced or git-tracked vault."""
    with _thread_lock:
        if fcntl is None:
            yield
            return
        try:
            lock_dir = state_dir()
            lock_dir.mkdir(parents=True, exist_ok=True)
            fh = open(lock_dir / "accounts.lock", "a+")  # noqa: SIM115 — closed below
        except OSError as e:
            log.warning("could not open accounts lock file (%s); thread lock only", e)
            yield
            return
        with fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


def _read(path: Path) -> list[Account]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, yaml.YAMLError) as e:
        log.warning("could not read %s (%s); no accounts loaded", path, e)
        return []
    return _parse({"accounts": []} if data is None else data, path)


def _parse(data: object, source: Path) -> list[Account]:
    entries = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        log.warning("%s is malformed (no `accounts:` list); no accounts loaded", source)
        return []
    out: list[Account] = []
    seen: set[tuple[str, str]] = set()
    for i, raw in enumerate(entries):
        if not isinstance(raw, dict):
            log.warning("%s: ignoring entry %d (not a mapping)", source, i)
            continue
        connector = str(raw.get("connector") or "").strip()
        acc_id = str(raw.get("id") or "").strip()
        if connector not in ACCOUNT_CONNECTORS or not acc_id:
            log.warning("%s: ignoring entry %d (connector=%r id=%r)", source, i, connector, acc_id)
            continue
        ctx = raw.get("context")
        ctx = ctx.strip() if isinstance(ctx, str) and ctx.strip() else None
        options = raw.get("options")
        acc = Account(
            connector=connector,
            id=acc_id,
            context=ctx,
            enabled=bool(raw.get("enabled", True)),
            options=dict(options) if isinstance(options, dict) else {},
        )
        if acc.key in seen:
            log.warning("%s: ignoring duplicate %s account %s", source, connector, acc_id)
            continue
        seen.add(acc.key)
        out.append(acc)
    return out


def _to_dict(acc: Account) -> dict:
    d: dict = {"connector": acc.connector, "id": acc.id}
    if acc.context:
        d["context"] = acc.context
    if not acc.enabled:
        d["enabled"] = False
    if acc.options:
        d["options"] = dict(acc.options)
    return d


def _write(path: Path, accs: list[Account]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"version": 1, "accounts": [_to_dict(a) for a in accs]}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".accounts.", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(
                "# Connected accounts per connector, each optionally mapped to a context.\n"
                "# Managed by Poltergeist (connect flows / Settings); safe to hand-edit.\n"
            )
            yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _validate(acc: Account, root: Path | None, *, check_context: bool = True) -> None:
    if acc.connector not in ACCOUNT_CONNECTORS:
        raise ValueError(f"unknown account connector: {acc.connector!r}")
    if not acc.id or not acc.id.strip():
        raise ValueError("account id is required")
    if (
        check_context
        and acc.context is not None
        and acc.context not in routing_config.contexts(root)
    ):
        raise ValueError(
            f"unknown context: {acc.context!r}; valid: {list(routing_config.contexts(root))}"
        )


# ---------------------------------------------------------------------------
# Seeding (once, from legacy routing.yaml blocks + live logins)
# ---------------------------------------------------------------------------


def _ensure_seeded(root: Path | None) -> None:
    path = accounts_path(root)
    if path.exists() or not path.parent.exists():
        return
    with _locked(root):
        if path.exists():
            return
        seeded = _seed(root)
        if seeded is None:
            # routing.yaml missing or unreadable: persisting now would
            # freeze an empty registry and drop the legacy accounts for
            # good. Seed on a later call once routing.yaml is valid.
            return
        _write(path, seeded)
    log.info(
        "seeded %s with %d account(s) from routing.yaml; its per-account blocks "
        "(gmail.accounts, calendar.google.accounts, slack.workspaces, jira.sites, "
        "confluence.sites) are no longer read",
        path, len(seeded),
    )


def _seed(root: Path | None) -> list[Account] | None:
    """The seeded accounts, or None when routing.yaml is missing or not a
    readable mapping (nothing must be persisted then)."""
    routing = _load_routing(root)
    if routing is None:
        return None
    accs = _seed_from_routing(routing)
    if os.environ.get("GHOSTBRAIN_ACCOUNTS_LIVE_SEED", "1") != "0":
        try:
            accs += [Account("github", login) for login in gh_logins()]
        except Exception as e:  # noqa: BLE001
            log.warning("could not list gh logins while seeding: %s", e)
        try:
            accs += [Account("microsoft", u) for u in _msal_usernames(routing)]
        except Exception as e:  # noqa: BLE001
            log.warning("could not list Microsoft accounts while seeding: %s", e)
    out: list[Account] = []
    seen: set[tuple[str, str]] = set()
    for a in accs:
        if a.key not in seen:
            seen.add(a.key)
            out.append(a)
    return out


def _load_routing(root: Path | None) -> dict | None:
    """routing.yaml as a mapping, or None (warned once per path) when it is
    missing, unreadable, or not a mapping."""
    f = (root or vault_path()) / "90-meta" / "routing.yaml"
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        reason = "is missing"
    except (OSError, yaml.YAMLError) as e:
        reason = f"could not be parsed ({e})"
    else:
        if isinstance(data, dict):
            _warned_routing.discard(str(f))
            return data
        reason = "is not a mapping"
    if str(f) not in _warned_routing:
        _warned_routing.add(str(f))
        log.warning(
            "%s %s; not seeding accounts.yaml until it is valid", f, reason,
        )
    return None


def _ctx(value: object) -> str | None:
    if isinstance(value, str) and value.strip() and value.strip() not in _UNASSIGNED:
        return value.strip()
    return None


def _mapping(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {str(v): None for v in value}
    return {}


def _seed_from_routing(routing: dict) -> list[Account]:
    out: list[Account] = []

    gmail = routing.get("gmail") or {}
    for email, cfg in _mapping(gmail.get("accounts")).items():
        out.append(Account("gmail", str(email), None, True, dict(cfg) if isinstance(cfg, dict) else {}))

    google = (routing.get("calendar") or {}).get("google") or {}
    calendars = google.get("calendars_per_account") or {}
    for email, ctx in _mapping(google.get("accounts")).items():
        opts = {"calendars": list(calendars[email])} if calendars.get(email) else {}
        out.append(Account("calendar_google", str(email), _ctx(ctx), True, opts))

    for slug, cfg in _mapping((routing.get("slack") or {}).get("workspaces")).items():
        cfg = dict(cfg) if isinstance(cfg, dict) else {"context": cfg}
        ctx = _ctx(cfg.pop("context", None))
        out.append(Account("slack", str(slug), ctx, True, cfg))

    jira_sites = _mapping((routing.get("jira") or {}).get("sites"))
    for host, ctx in jira_sites.items():
        out.append(Account("jira", str(host), _ctx(ctx)))

    confluence = routing.get("confluence") or {}
    conf_sites = _mapping(confluence.get("sites"))
    if not conf_sites and confluence.get("spaces"):
        conf_sites = jira_sites
    for host, ctx in conf_sites.items():
        out.append(Account("confluence", str(host), _ctx(ctx) or _ctx(jira_sites.get(host))))

    return out


def _msal_usernames(routing: dict) -> list[str]:
    from ghostbrain.connectors.microsoft.graph import auth as ms_auth

    if not ms_auth.cache_location().exists():
        return []
    app = ms_auth._build_app(routing.get("microsoft") or {})
    return [a["username"] for a in app.get_accounts() if a.get("username")]
