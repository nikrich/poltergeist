"""Existing codebases a design session can build on.

Repos are found by walking ``design.code_roots`` (a repo is a folder with a
``.git`` directory; worktrees, with a ``.git`` file, are not repos of their
own). The scan is cached for :data:`CACHE_TTL_S`. :func:`resolve` maps a
spoken hint ("the billing frontend") to one repo: token overlap first, the
LLM only to break ties.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ghostbrain.design import settings as design_settings

log = logging.getLogger("ghostbrain.design.codebases")

CACHE_TTL_S = 600.0
PRUNE = frozenset({
    "node_modules", ".git", "dist", "build", ".next", "out", "target", ".venv", "venv", "__pycache__",
})
FRONTEND_DEPS = ("react", "next", "vue", "svelte", "@angular/core", "vite", "solid-js", "preact")
WORKSPACE_GLOBS = ("apps/*/package.json", "packages/*/package.json")
SYNONYMS = {"fe": "frontend", "frontend": "fe", "ui": "frontend", "web": "frontend"}
STOP_WORDS = frozenset({"the", "our", "existing", "use", "app", "repo", "codebase", "solution", "project"})
LLM_TOP_N = 15

SCHEMA: dict = {
    "type": "object",
    "properties": {"pick": {"type": ["string", "null"]}},
    "required": ["pick"],
    "additionalProperties": False,
}

PROMPT = """Someone in a meeting said they want to work on this codebase: "{hint}"

Candidate repositories (path, then package name):
{candidates}

Which one did they mean? Answer as JSON: {{"pick": "<the path exactly as listed>"}},
or {{"pick": null}} when none clearly fits."""

_cache: dict[tuple, tuple[float, list[Candidate]]] = {}


@dataclass(frozen=True)
class Candidate:
    path: Path
    rel: str
    name: str
    frontend: bool

    def to_dict(self) -> dict:
        return {"path": str(self.path), "rel": self.rel, "name": self.name, "frontend": self.frontend}


def roots() -> list[Path]:
    return [Path(r).expanduser() for r in design_settings.load()["code_roots"]]


def _configured_roots() -> list[Path]:
    return roots()  # scan()'s ``roots`` parameter shadows the function there


def _read_package(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _has_frontend_dep(pkg: dict) -> bool:
    for key in ("dependencies", "devDependencies"):
        deps = pkg.get(key)
        if isinstance(deps, dict) and any(d in deps for d in FRONTEND_DEPS):
            return True
    return False


def is_frontend(repo: Path) -> bool:
    """A frontend dependency in the root package.json or a workspace package."""
    if _has_frontend_dep(_read_package(repo / "package.json")):
        return True
    return any(
        _has_frontend_dep(_read_package(p)) for pattern in WORKSPACE_GLOBS for p in repo.glob(pattern)
    )


def _candidate(repo: Path, root: Path) -> Candidate:
    name = _read_package(repo / "package.json").get("name")
    rel = repo.relative_to(root).as_posix() if repo != root else repo.name
    return Candidate(
        path=repo, rel=rel, name=name if isinstance(name, str) and name else repo.name,
        frontend=is_frontend(repo),
    )


def _pruned(name: str) -> bool:
    return name in PRUNE or name.startswith(".") or "-poltergeist-" in name


def _walk(root: Path, max_depth: int) -> list[Candidate]:
    found: list[Candidate] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        if (d / ".git").is_dir():
            found.append(_candidate(d, root))
            continue  # a repo's own subfolders are not scanned
        if depth >= max_depth:
            continue
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False) and not _pruned(e.name):
                    stack.append((Path(e.path), depth + 1))
            except OSError:
                continue
    return found


def scan(roots: list[Path] | None = None, *, max_depth: int = 5, refresh: bool = False) -> list[Candidate]:
    """Every repo under ``roots`` (default: the configured code roots), sorted by rel."""
    root_list = [Path(r).expanduser() for r in (roots if roots is not None else _configured_roots())]
    key = (tuple(str(r) for r in root_list), max_depth)
    hit = _cache.get(key)
    if hit is not None and not refresh and time.monotonic() - hit[0] < CACHE_TTL_S:
        return list(hit[1])
    found: list[Candidate] = []
    for root in root_list:
        if root.is_dir():
            found.extend(_walk(root, max_depth))
    found.sort(key=lambda c: (c.rel, str(c.path)))
    _cache[key] = (time.monotonic(), found)
    return list(found)


def _tokens(text: str) -> set[str]:
    words = {w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w not in STOP_WORDS}
    return words | {SYNONYMS[w] for w in words if w in SYNONYMS}


def search(query: str, *, limit: int = 30) -> list[Candidate]:
    """Candidates for the picker: substring or all-tokens match, frontends first."""
    q = query.strip().lower()
    q_tokens = _tokens(q)
    out = []
    for c in scan():
        hay = f"{c.rel} {c.name}".lower()
        if not q or q in hay or (q_tokens and q_tokens <= _tokens(hay)):
            out.append(c)
    out.sort(key=lambda c: (not c.frontend, c.rel))
    return out[:limit]


def _default_run(prompt: str, **kw: Any) -> Any:
    from ghostbrain.llm import client

    return client.run(prompt, **kw)


def resolve(
    hint: str, candidates: list[Candidate] | None = None, *, frontend: bool = True,
    run: Callable[..., Any] | None = None,
) -> Candidate | None:
    """The repo ``hint`` names, or None when nothing (frontend, if wanted) matches."""
    hint_tokens = _tokens(hint)
    if not hint_tokens:
        return None
    pool = candidates if candidates is not None else scan()
    scored = []
    for c in pool:
        if frontend and not c.frontend:
            continue
        score = len(hint_tokens & (_tokens(c.rel) | _tokens(c.name)))
        if score:
            scored.append((score, c))
    if not scored:
        return None
    best = max(s for s, _ in scored)
    top = [c for s, c in scored if s == best]
    if len(top) == 1:
        return top[0]
    top.sort(key=lambda c: (len(c.rel), c.rel))
    shortlist = top[:LLM_TOP_N]
    prompt = PROMPT.format(
        hint=hint.strip(), candidates="\n".join(f"- {c.rel} ({c.name})" for c in shortlist),
    )
    try:
        data = (run or _default_run)(prompt, model="haiku", json_schema=SCHEMA, timeout_s=60).as_json()
    except Exception as e:  # noqa: BLE001 — a tie still resolves without the LLM
        log.warning("codebase tie-break failed: %s", e)
        return shortlist[0]
    pick = data.get("pick") if isinstance(data, dict) else None
    return next((c for c in shortlist if c.rel == pick), None)
