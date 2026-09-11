"""Local grant providers: Claude Code settings hook and macOS Calendar access."""
from __future__ import annotations

from ghostbrain.api import claude_settings
from ghostbrain.api.auth.providers.base import NextAction
from ghostbrain.api.repo.routing import merge_routing
from ghostbrain.doctor.fixes import hook


class ClaudeCodeProvider:
    """Provider for Claude Code settings hook integration."""

    pattern = "local_grant"

    def start(self, connector_id, params):
        """Prompt for hook script and optional project path/context."""
        default_script = hook.hook_command()
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
        """Write SessionEnd hook to ~/.claude/settings.json (atomic, merge-only)."""
        script = (data.get("hook_script") or "").strip()
        if not script:
            session.status = "error"
            session.error = "Hook script path is required"
            return NextAction(kind="need_input", fields=[])
        try:
            doc = claude_settings.load()
        except ValueError:
            session.status = "error"
            session.error = "~/.claude/settings.json is not valid JSON; fix it by hand first"
            return NextAction(kind="need_input", fields=[])
        doc = hook.install(doc, script)
        try:
            claude_settings.write_atomic(doc)
        except OSError as e:
            session.status = "error"
            session.error = f"Could not write settings.json: {e}"
            return NextAction(kind="need_input", fields=[])
        proj = (data.get("project_path") or "").strip()
        ctx = (data.get("context") or "").strip()
        if proj and ctx:
            merge_routing({"claude_code": {"project_paths": {proj: ctx}}})
        session.status = "success"
        session.account = "SessionEnd hook installed"
        return NextAction(kind="done")

    def poll(self, connector_id, session):
        """No async polling needed for Claude Code provider."""

    def account_label(self, session):
        """Return account label."""
        return session.account


def _macos_calendar_authorized() -> bool | None:
    """Best-effort check of EventKit calendar authorization status.

    Returns True if access is granted, False if explicitly denied/restricted,
    or None if the status cannot be determined (not macOS, EventKit unavailable,
    or authorization is still not-determined).
    """
    try:
        from EventKit import EKAuthorizationStatusAuthorized, EKEntityTypeEvent, EKEventStore

        current = EKEventStore.authorizationStatusForEntityType_(EKEntityTypeEvent)
        if current == EKAuthorizationStatusAuthorized:
            return True
        # EKAuthorizationStatusDenied / Restricted are non-zero, non-authorized
        # statuses distinct from NotDetermined (0). Without importing every
        # symbol, treat any determined-but-not-authorized status as denied,
        # and fall back to "unknown" only when we can't tell.
        try:
            from EventKit import EKAuthorizationStatusDenied, EKAuthorizationStatusRestricted

            if current in (EKAuthorizationStatusDenied, EKAuthorizationStatusRestricted):
                return False
        except ImportError:
            pass
        return None
    except Exception:  # noqa: BLE001
        return None


class MacosCalendarProvider:
    """Provider for macOS Calendar access (best-effort EventKit check)."""

    pattern = "local_grant"

    def start(self, connector_id, params):
        """Prompt user to grant Calendar access when macOS prompts."""
        return NextAction(
            kind="need_grant",
            message="Grant Calendar access when macOS prompts, then press Re-check.",
        )

    def submit(self, connector_id, session, data):
        """No form input for this flow; return the session's current next action unchanged."""
        return session.next

    def poll(self, connector_id, session):
        """Best-effort: check EventKit authorization status to confirm the grant."""
        try:
            status = _macos_calendar_authorized()
        except Exception:  # noqa: BLE001
            status = None
        if status is False:
            session.status = "error"
            session.error = (
                "Calendar access was denied. Grant it in System Settings → "
                "Privacy → Calendars, then re-check."
            )
            session.next = NextAction(kind="need_grant", message=session.error)
        else:
            # True (authorized) or None (can't confirm, e.g. non-macOS) —
            # best-effort: assume granted per spec §9.
            session.status = "success"
            session.next = NextAction(kind="done")

    def account_label(self, session):
        """Return account label."""
        return "macOS Calendar"
