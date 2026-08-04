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
