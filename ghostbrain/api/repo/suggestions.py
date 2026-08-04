"""Suggestions stub for Phase 1.

Returns a small set of always-on hints derived from the connector list.
Phase 2 replaces this with an LLM-driven suggestion engine that reads
captures + meetings + activity.
"""
from __future__ import annotations

from ghostbrain.api.repo.connectors import list_connectors


def list_suggestions() -> list[dict]:
    suggestions: list[dict] = []
    connectors = list_connectors()
    off_connectors = [c for c in connectors if c["state"] == "off"]
    if off_connectors:
        names = ", ".join(c["displayName"] for c in off_connectors[:3])
        suggestions.append({
            "id": "connect-something",
            "icon": "link",
            "title": f"connect {off_connectors[0]['displayName']}",
            "body": f"these connectors are configured but not running: {names}.",
            "accent": False,
        })
    err_connectors = [c for c in connectors if c["state"] == "err"]
    if err_connectors:
        names = ", ".join(c["displayName"] for c in err_connectors[:2])
        suggestions.append({
            "id": "fix-errors",
            "icon": "alert-circle",
            "title": "connector error" + ("s" if len(err_connectors) > 1 else ""),
            "body": f"{names} reported an error and stopped syncing. reauthorize?",
            "accent": True,
        })
    return suggestions
