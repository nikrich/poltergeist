"""Atomic read/merge/write for <vault>/90-meta/routing.yaml.

Merge-only and comment-losing (PyYAML), same tradeoff as repo/settings.py.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from ghostbrain.paths import vault_path


def _path() -> Path:
    return vault_path() / "90-meta" / "routing.yaml"


def load_routing() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_atomic(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".routing.", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _deep_merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def merge_routing(patch: dict) -> dict:
    doc = load_routing()
    _deep_merge(doc, patch)
    _write_atomic(doc)
    return doc


def remove_routing_path(dotted: str) -> None:
    doc = load_routing()
    parts = dotted.split(".")
    node = doc
    for key in parts[:-1]:
        if not isinstance(node.get(key), dict):
            return
        node = node[key]
    node.pop(parts[-1], None)
    _write_atomic(doc)
