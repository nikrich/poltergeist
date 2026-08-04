"""Ghost Brain — personal second-brain automation for Obsidian."""

from __future__ import annotations

__version__ = "0.1.0"

# Load .env so connector auth secrets reach our subprocess environment
# without being committed anywhere. Existing os.environ values win — tests'
# monkeypatch isn't overridden, and shell-set values still take precedence
# over .env.
#
# Lookup order (later wins for shadowing keys NOT already set):
#   1. ~/.ghostbrain/.env       — packaged app's canonical location
#   2. <cwd>-upward             — dev / launchd path; finds repo .env
#
# When the packaged app spawns the sidecar, cwd is the user-data dir
# (no .env there), so without (1) every secret-driven connector silently
# health-checks itself off.
try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # pragma: no cover — dotenv is a hard dep, but stay defensive
    pass
else:
    from pathlib import Path as _Path
    _home_env = _Path.home() / ".ghostbrain" / ".env"
    if _home_env.exists():
        _load_dotenv(_home_env)
    _load_dotenv()  # cwd-upward fallback
