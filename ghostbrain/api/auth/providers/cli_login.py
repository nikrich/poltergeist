"""GitHub CLI login provider for detecting existing gh auth."""
from __future__ import annotations

import shutil
import subprocess
import time

from ghostbrain.api.auth.providers.base import NextAction


def _gh_logged_in() -> tuple[bool, str | None]:
    """Check if gh is installed and logged in. Returns (logged_in, login_name)."""
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
    """Provider for GitHub CLI-based login."""

    pattern = "cli_login"

    def start(self, connector_id, params):
        """Start GitHub auth. If gh is already logged in, return done. Otherwise request grant."""
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
        """Poll for gh login completion (up to 120 seconds)."""
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
        """Return the account label (GitHub login)."""
        return session.account
