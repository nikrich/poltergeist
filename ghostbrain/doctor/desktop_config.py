"""Read the Electron app's settings file (app.getPath('userData')/config.json).

The sidecar never writes this file; doctor only reads `schedulerEnabled` and
`vaultPath` to explain states the app owns.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_DIR = "ghostbrain-desktop"


def _platform() -> str:
    return sys.platform


def path() -> Path:
    if _platform() == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR / "config.json"
    if _platform() == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        return base / APP_DIR / "config.json"
    return Path.home() / ".config" / APP_DIR / "config.json"


def load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
