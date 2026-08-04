"""Read/write the user-facing slice of <vault>/90-meta/config.yaml.

Updates are merge-only: we load the full YAML, mutate the target subtree,
and write the whole document back. Comments are lost (PyYAML doesn't
round-trip them), but every other setting is preserved.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from ghostbrain.paths import vault_path

_DEFAULTS = {
    "enabled": True,
    "excluded_titles": ["Focus", "focus"],
    "manual_context": "personal",
}


def _config_path() -> Path:
    return vault_path() / "90-meta" / "config.yaml"


def _load_yaml() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_yaml_atomic(data: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config.", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp, path)
    except Exception:
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def get_recorder_settings() -> dict:
    config = _load_yaml()
    raw = (config.get("recorder") or {}) if isinstance(config.get("recorder"), dict) else {}
    out: dict = {}
    out["enabled"] = bool(raw.get("enabled", _DEFAULTS["enabled"]))
    excluded = raw.get("excluded_titles") or _DEFAULTS["excluded_titles"]
    out["excluded_titles"] = [str(x) for x in excluded if isinstance(x, (str, int))]
    out["manual_context"] = str(raw.get("manual_context") or _DEFAULTS["manual_context"])
    return out


def update_recorder_settings(**fields) -> dict:
    """Merge non-None fields into config.recorder. Returns the new settings."""
    config = _load_yaml()
    recorder = config.get("recorder") or {}
    if not isinstance(recorder, dict):
        recorder = {}

    if fields.get("enabled") is not None:
        recorder["enabled"] = bool(fields["enabled"])
    if fields.get("excluded_titles") is not None:
        recorder["excluded_titles"] = [str(x) for x in fields["excluded_titles"]]
    if fields.get("manual_context") is not None:
        recorder["manual_context"] = str(fields["manual_context"])

    config["recorder"] = recorder
    _write_yaml_atomic(config)
    return get_recorder_settings()
