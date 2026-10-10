"""The ``design:`` block of ``<vault>/90-meta/config.yaml``.

    design:
      listen: true          # listen for spoken design commands while recording
      budget_usd: 2.0       # max spend per UI/board agent run
      default_pack: poltergeist-neutral
      code_roots: [~/development]   # folders searched for existing codebases

Reads never fail: a missing or malformed value falls back to its default,
and a default pack that has since been deleted falls back to the built-in.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from ghostbrain.design import packs
from ghostbrain.recorder import config as rcfg

DEFAULTS: dict[str, Any] = {
    "listen": True,
    "budget_usd": 2.0,
    "default_pack": packs.BUILTIN_PACK_ID,
    "code_roots": ["~/development"],
}
BUDGET_MIN_USD = 0.1
BUDGET_MAX_USD = 20.0
CODE_ROOTS_MAX = 10


def _clean_roots(raw: list) -> list[str]:
    """Stripped, non-blank strings in order, without duplicates."""
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out


def _block(config: dict) -> dict:
    raw = config.get("design")
    return raw if isinstance(raw, dict) else {}


def load() -> dict:
    raw = _block(rcfg.load_config_yaml())
    out = dict(DEFAULTS)
    if isinstance(raw.get("listen"), bool):
        out["listen"] = raw["listen"]
    budget = raw.get("budget_usd")
    if (
        isinstance(budget, (int, float)) and not isinstance(budget, bool)
        and BUDGET_MIN_USD <= budget <= BUDGET_MAX_USD
    ):
        out["budget_usd"] = float(budget)
    pack = raw.get("default_pack")
    if isinstance(pack, str) and packs.get_pack(pack) is not None:
        out["default_pack"] = pack
    roots = raw.get("code_roots")
    if isinstance(roots, list) and (cleaned := _clean_roots(roots)):
        out["code_roots"] = cleaned[:CODE_ROOTS_MAX]
    else:
        out["code_roots"] = list(DEFAULTS["code_roots"])
    return out


def _write_yaml_atomic(data: dict) -> None:
    path = rcfg.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config.", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def update(**fields) -> dict:
    """Merge non-None fields into ``design:``. Raises ValueError on bad input."""
    unknown = set(fields) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown design settings: {sorted(unknown)}")
    config = rcfg.load_config_yaml()
    block = _block(config)

    if fields.get("listen") is not None:
        block["listen"] = bool(fields["listen"])
    if fields.get("budget_usd") is not None:
        budget = fields["budget_usd"]
        if isinstance(budget, bool) or not isinstance(budget, (int, float)):
            raise ValueError("budget_usd must be a number")
        if not BUDGET_MIN_USD <= budget <= BUDGET_MAX_USD:
            raise ValueError(f"budget_usd must be between {BUDGET_MIN_USD} and {BUDGET_MAX_USD}")
        block["budget_usd"] = float(budget)
    if fields.get("default_pack") is not None:
        pack = str(fields["default_pack"])
        if packs.get_pack(pack) is None:
            raise ValueError(f"unknown design system: {pack!r}")
        block["default_pack"] = pack
    if fields.get("code_roots") is not None:
        roots = fields["code_roots"]
        if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots):
            raise ValueError("code_roots must be a list of folder paths")
        cleaned = _clean_roots(roots)
        if len(cleaned) > CODE_ROOTS_MAX:
            raise ValueError(f"code_roots allows at most {CODE_ROOTS_MAX} folders")
        block["code_roots"] = cleaned

    config["design"] = block
    _write_yaml_atomic(config)
    return load()
