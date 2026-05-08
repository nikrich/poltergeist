"""Ghost Brain — personal second-brain automation for Obsidian."""

from __future__ import annotations

__version__ = "0.1.0"

# Load .env from the repo root (or wherever cwd resolves) so connector
# auth secrets reach our subprocess environment without being committed
# anywhere. Existing os.environ values win — tests' monkeypatch isn't
# overridden, and shell-set values still take precedence over .env.
try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # pragma: no cover — dotenv is a hard dep, but stay defensive
    pass
else:
    _load_dotenv()
