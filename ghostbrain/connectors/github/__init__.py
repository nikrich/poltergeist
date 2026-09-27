"""GitHub connector. Shells out to `gh` CLI so we inherit the user's
existing OAuth login — no token management, no env var.

Fetches three kinds of events filtered to monitored orgs (routing.yaml
github.orgs):
- PRs the user authored (their work shipping)
- PRs requesting their review (their blockers)
- Issues assigned to the user (their todos)

Each surfaces as a single event keyed by `github:<type>:<owner>/<repo>#<n>`,
deduplicated against earlier runs by the queue's done/ folder.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ghostbrain.accounts_health import for_each_account
from ghostbrain.connectors._base import Connector

log = logging.getLogger("ghostbrain.connectors.github")

# Fields we ask `gh search` to return. Note: `reviewRequests` is not an
# available JSON field in `gh search prs`; review-request signal comes from
# the query filter (--review-requested=@me) instead.
PR_FIELDS = (
    "number,title,body,url,state,repository,author,assignees,"
    "labels,isDraft,createdAt,updatedAt,closedAt"
)
ISSUE_FIELDS = (
    "number,title,body,url,state,repository,author,assignees,"
    "labels,createdAt,updatedAt,closedAt"
)

DEFAULT_LIMIT = 50  # gh search caps at 1000; 50 is plenty per query

# On first run there's no last_run state — default to fetching the last 7
# days rather than all of GitHub history.
FIRST_RUN_LOOKBACK_DAYS = 7


class GitHubAuthError(RuntimeError):
    """`gh auth token --user <login>` failed — that login needs `gh auth login`."""


# Ambient token env vars gh checks before falling back to the keyring/config
# login for a --hostname/--user pair. Stripped from the env of the `gh auth
# token` call so a leaked/exported token can't make every login resolve to
# the same identity.
_AMBIENT_TOKEN_VARS = (
    "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
)

# Case-insensitive substrings in `gh search` stderr that indicate the token
# itself (not the query) is bad — surfaced as GitHubAuthError instead of a
# silent "ok" so the account gets marked auth_required.
_AUTH_FAILURE_MARKERS = ("401", "bad credentials", "authentication", "auth token")


class GitHubConnector(Connector):
    """See module docstring."""

    name = "github"
    version = "1.0"

    def __init__(
        self,
        config: dict,
        queue_dir: Path,
        state_dir: Path,
        *,
        gh_binary: str | None = None,
    ) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.orgs = list(config.get("orgs") or [])
        self.accounts: list[str] = [str(a) for a in (config.get("accounts") or [])]
        self._gh = gh_binary or shutil.which("gh")
        if self._gh is None:
            raise RuntimeError(
                "`gh` binary not on PATH. Install GitHub CLI and run `gh auth login`."
            )

    def health_check(self) -> bool:
        if not self.accounts:
            try:
                proc = self._run_gh(["auth", "status"], timeout_s=15)
            except subprocess.SubprocessError:
                return False
            return proc.returncode == 0
        for login in self.accounts:
            try:
                self._token_for(login)
                return True
            except GitHubAuthError:
                continue
        return False

    def _token_for(self, login: str) -> str:
        env = {k: v for k, v in os.environ.items() if k not in _AMBIENT_TOKEN_VARS}
        try:
            proc = self._run_gh(
                ["auth", "token", "--hostname", "github.com", "--user", login],
                timeout_s=15, env=env,
            )
        except subprocess.SubprocessError as e:
            raise GitHubAuthError(f"gh auth token failed for {login}: {e}") from e
        token = (proc.stdout or "").strip()
        if proc.returncode != 0 or not token:
            raise GitHubAuthError(
                f"no gh token for {login}; run `gh auth login` as that account"
            )
        return token

    def fetch(self, since: datetime) -> list[dict]:
        if not self.orgs:
            log.info("no monitored orgs configured; skipping GitHub fetch")
            return []

        # First-run guard: if last_run was never set we'd fetch from 1970.
        # Cap the lookback at FIRST_RUN_LOOKBACK_DAYS instead.
        floor = datetime.now(timezone.utc) - timedelta(days=FIRST_RUN_LOOKBACK_DAYS)
        if since < floor:
            since = floor

        updated_qualifier = f">={since.date().isoformat()}"
        owner_csv = ",".join(self.orgs)

        if not self.accounts:
            events = self._search_all(owner_csv, updated_qualifier, None)
        else:
            def one(login: str) -> list[dict]:
                env = {**os.environ, "GH_TOKEN": self._token_for(login)}
                found = self._search_all(owner_csv, updated_qualifier, env)
                for ev in found:
                    ev["metadata"]["accountId"] = login
                return found

            events = for_each_account(
                "github", self.accounts, one,
                account_id=lambda login: login, auth_errors=(GitHubAuthError,),
            )

        # Dedup by (type, repo, number) — same PR may appear in multiple queries
        # (and across logins; first account wins).
        seen: set[tuple[str, str, int]] = set()
        unique: list[dict] = []
        for ev in events:
            key = (ev["type"], ev["metadata"]["repo"], ev["metadata"]["number"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(ev)

        log.info("github fetch: %d unique event(s) across %d org(s)",
                 len(unique), len(self.orgs))
        return unique

    def normalize(self, raw: dict) -> dict:
        # `fetch` already produces normalized events. Identity here for
        # consistency with the Connector contract.
        return raw

    # ------------------------------------------------------------------
    # gh CLI plumbing
    # ------------------------------------------------------------------

    def _search_all(
        self, owner_csv: str, updated_qualifier: str, env: dict | None,
    ) -> list[dict]:
        events: list[dict] = []
        events.extend(self._search_prs(
            owner_csv, ["--author=@me", "--state=open", f"--updated={updated_qualifier}"],
            origin="authored", env=env,
        ))
        events.extend(self._search_prs(
            owner_csv, ["--review-requested=@me", "--state=open", f"--updated={updated_qualifier}"],
            origin="review-requested", env=env,
        ))
        events.extend(self._search_issues(
            owner_csv, ["--assignee=@me", "--state=open", f"--updated={updated_qualifier}"],
            origin="assigned", env=env,
        ))
        return events

    def _search_prs(
        self,
        owner_csv: str,
        extra_args: list[str],
        *,
        origin: str,
        env: dict | None = None,
    ) -> list[dict]:
        cmd = [
            self._gh, "search", "prs",
            "--owner", owner_csv,
            "--limit", str(DEFAULT_LIMIT),
            "--json", PR_FIELDS,
            *extra_args,
        ]
        items = self._run_gh_json(cmd, env)
        return [self._normalize_pr(item, origin=origin) for item in items]

    def _search_issues(
        self,
        owner_csv: str,
        extra_args: list[str],
        *,
        origin: str,
        env: dict | None = None,
    ) -> list[dict]:
        cmd = [
            self._gh, "search", "issues",
            "--owner", owner_csv,
            "--limit", str(DEFAULT_LIMIT),
            "--json", ISSUE_FIELDS,
            *extra_args,
        ]
        items = self._run_gh_json(cmd, env)
        return [self._normalize_issue(item, origin=origin) for item in items]

    def _run_gh_json(self, cmd: list[str], env: dict | None = None) -> list[dict]:
        try:
            proc = self._run_gh(cmd[1:], timeout_s=60, env=env)
        except subprocess.SubprocessError as e:
            log.warning("gh subprocess failed: %s", e)
            return []
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()[:200]
            # Multi-account path only (env is set): a search-time auth
            # failure must not be swallowed as a quiet "no results" — that
            # would record the account `ok` even though its token is dead.
            if env is not None and any(m in stderr.lower() for m in _AUTH_FAILURE_MARKERS):
                raise GitHubAuthError(f"gh search failed (exit {proc.returncode}): {stderr}")
            log.warning("gh exited %d: %s", proc.returncode, stderr)
            return []
        try:
            data = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError as e:
            log.warning("gh stdout not JSON: %s", e)
            return []
        return data if isinstance(data, list) else []

    def _run_gh(
        self, args: list[str], *, timeout_s: int, env: dict | None = None,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self._gh, *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize_pr(self, raw: dict, *, origin: str) -> dict:
        repo = (raw.get("repository") or {}).get("nameWithOwner", "?/?")
        owner = repo.split("/", 1)[0] if "/" in repo else repo
        number = int(raw.get("number") or 0)
        author = (raw.get("author") or {}).get("login", "?")

        subtype = self._derive_pr_subtype(raw, origin)
        timestamp = raw.get("updatedAt") or raw.get("createdAt") or _now_iso()

        return {
            "id": f"github:pr:{repo}#{number}",
            "source": "github",
            "type": "pr",
            "subtype": subtype,
            "timestamp": timestamp,
            "actorId": f"github:{author}",
            "title": str(raw.get("title") or "").strip(),
            "body": str(raw.get("body") or "").strip(),
            "url": str(raw.get("url") or ""),
            "rawData": raw,
            "metadata": {
                "repo": repo,
                "org": owner,
                "number": number,
                "state": raw.get("state"),
                "isDraft": bool(raw.get("isDraft")),
                "labels": [l.get("name") for l in (raw.get("labels") or []) if l.get("name")],
                "origin": origin,
                "author": author,
            },
        }

    def _normalize_issue(self, raw: dict, *, origin: str) -> dict:
        repo = (raw.get("repository") or {}).get("nameWithOwner", "?/?")
        owner = repo.split("/", 1)[0] if "/" in repo else repo
        number = int(raw.get("number") or 0)
        author = (raw.get("author") or {}).get("login", "?")

        timestamp = raw.get("updatedAt") or raw.get("createdAt") or _now_iso()

        return {
            "id": f"github:issue:{repo}#{number}",
            "source": "github",
            "type": "issue",
            "subtype": "open" if raw.get("state") == "OPEN" else "closed",
            "timestamp": timestamp,
            "actorId": f"github:{author}",
            "title": str(raw.get("title") or "").strip(),
            "body": str(raw.get("body") or "").strip(),
            "url": str(raw.get("url") or ""),
            "rawData": raw,
            "metadata": {
                "repo": repo,
                "org": owner,
                "number": number,
                "state": raw.get("state"),
                "labels": [l.get("name") for l in (raw.get("labels") or []) if l.get("name")],
                "origin": origin,
                "author": author,
            },
        }

    def _derive_pr_subtype(self, raw: dict, origin: str) -> str:
        state = raw.get("state") or ""
        if state == "MERGED":
            return "merged"
        if state == "CLOSED":
            return "closed"
        if origin == "review-requested":
            return "review-requested"
        if raw.get("isDraft"):
            return "draft"
        return "opened"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
