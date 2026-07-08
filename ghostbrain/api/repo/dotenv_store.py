"""Read/upsert/remove keys in ~/.ghostbrain/.env without disturbing others.

Line-oriented KEY=VALUE. Comments and unknown lines are preserved on upsert.
The .env lives next to the state dir (its parent), matching the connectors'
documented location.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ghostbrain.paths import state_dir


def env_path() -> Path:
    return state_dir().parent / ".env"


def read_env() -> dict[str, str]:
    p = env_path()
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip()
    return out


def _write_atomic(lines: list[str]) -> None:
    p = env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        os.replace(tmp, p)
        p.chmod(0o600)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _rewrite(mutate) -> None:
    p = env_path()
    existing = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    mutate(existing)
    _write_atomic(existing)


def set_env(pairs: dict[str, str]) -> None:
    def mutate(lines: list[str]) -> None:
        remaining = dict(pairs)
        for i, line in enumerate(lines):
            s = line.strip()
            if "=" in s and not s.startswith("#"):
                key = s.split("=", 1)[0].strip()
                if key in remaining:
                    lines[i] = f"{key}={remaining.pop(key)}"
        for k, v in remaining.items():
            lines.append(f"{k}={v}")

    _rewrite(mutate)
    for k, v in pairs.items():
        os.environ[k] = v


def remove_env(keys: list[str]) -> None:
    keyset = set(keys)

    def mutate(lines: list[str]) -> None:
        lines[:] = [
            ln for ln in lines
            if not (
                "=" in ln
                and not ln.strip().startswith("#")
                and ln.split("=", 1)[0].strip() in keyset
            )
        ]

    _rewrite(mutate)
    for k in keys:
        os.environ.pop(k, None)
