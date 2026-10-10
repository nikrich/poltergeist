"""Prototype folder: scaffold, git revisions, revert, eject.

A prototype folder holds ``src/`` (the React app the UI agent edits),
``design-pack/`` (a copy of the chosen pack) and its own git repo. Every
agent run is one commit whose message is ``rev N: <summary>``; the revision
list is read back from ``git log``. Git is optional: without it the folder
still works, it just has no history (``commit`` returns ``""``).
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from ghostbrain.design import packs

log = logging.getLogger("ghostbrain.design.scaffold")

TEMPLATE_DIR = Path(__file__).parent / "scaffold_template"
TITLE_PLACEHOLDER = '"__PROTOTYPE_TITLE__"'
GITIGNORE = "dist/\nnode_modules/\n"
_REV_RE = re.compile(r"^rev (\d+): (.*)$")

# Never depend on (or be broken by) the user's global git setup.
_GIT_CONFIG = [
    "-c", "user.name=Poltergeist",
    "-c", "user.email=poltergeist@localhost",
    "-c", "commit.gpgsign=false",
    "-c", "core.hooksPath=/dev/null",
]
# Inherited repo-location variables would point git at another repo.
_GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY")


def _git_bin() -> str | None:
    return shutil.which("git")


def _git(prototype_dir: Path, *args: str) -> str:
    git = _git_bin()
    if git is None:
        raise FileNotFoundError("git")
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_DROP}
    proc = subprocess.run(
        [git, *_GIT_CONFIG, *args],
        cwd=str(prototype_dir), env=env, capture_output=True, text=True, timeout=60, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def _has_repo(prototype_dir: Path) -> bool:
    return _git_bin() is not None and (Path(prototype_dir) / ".git").exists()


def create(prototype_dir: Path, pack_id: str, *, title: str) -> None:
    """Lay out ``src/`` + ``design-pack/`` and commit ``rev 0: scaffold``."""
    d = Path(prototype_dir)
    d.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE_DIR / "src", d / "src", dirs_exist_ok=True)
    app = d / "src" / "App.tsx"
    app.write_text(
        app.read_text(encoding="utf-8").replace(TITLE_PLACEHOLDER, json.dumps(title or "Prototype")),
        encoding="utf-8",
    )
    packs.copy_into(pack_id, d / "design-pack")
    (d / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    if _git_bin() is None:
        log.warning("git not found; prototype %s will have no revision history", d)
        return
    _git(d, "init", "-q")
    commit(d, "rev 0: scaffold")


META_GITIGNORE = "dist/\ninstall.log\nprotected.json\n"


def init_meta(folder: Path) -> None:
    """A worktree artefact's folder: session files only (the code lives in
    the worktree), with its own git for board revisions."""
    d = Path(folder)
    d.mkdir(parents=True, exist_ok=True)
    (d / ".gitignore").write_text(META_GITIGNORE, encoding="utf-8")
    if _git_bin() is None:
        log.warning("git not found; artefact %s will have no revision history", d)
        return
    _git(d, "init", "-q")
    commit(d, "rev 0: session")


def commit(prototype_dir: Path, message: str) -> str:
    """Commit everything (even when nothing changed) and return the short sha."""
    d = Path(prototype_dir)
    if not _has_repo(d):
        return ""
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "--allow-empty", "-m", message)
    return _git(d, "rev-parse", "--short", "HEAD").strip()


def _log(prototype_dir: Path) -> list[tuple[str, int, str, str]]:
    """(sha, rev, iso date, summary) for every ``rev N:`` commit, oldest first."""
    if not _has_repo(prototype_dir):
        return []
    try:
        out = _git(Path(prototype_dir), "log", "--reverse", "--format=%H%x1f%cI%x1f%s")
    except RuntimeError:  # a repo with no commits yet
        return []
    entries = []
    for line in out.splitlines():
        sha, at, subject = line.split("\x1f", 2)
        m = _REV_RE.match(subject)
        if m:
            entries.append((sha, int(m.group(1)), at, m.group(2)))
    return entries


def revisions(prototype_dir: Path) -> list[dict]:
    """``[{rev, at, summary}]`` oldest first."""
    return [{"rev": rev, "at": at, "summary": summary} for _, rev, at, summary in _log(prototype_dir)]


def revert_to(prototype_dir: Path, rev: int) -> None:
    """Restore ``src/`` as of the ``rev N:`` commit and commit that as
    ``revert to rev N``. Only ``src/`` changes: board.json, session.jsonl and
    design-pack/ stay as they are. The caller numbers the next rev itself
    (the revert commit is not a ``rev N:`` commit)."""
    entries = _log(prototype_dir)
    shas = [sha for sha, r, _, _ in entries if r == rev]
    if not shas:
        raise KeyError(f"no revision {rev}")
    d = Path(prototype_dir)
    # Drop src/ entirely (tracked and untracked) so files added after rev N go,
    # then check out that commit's src/.
    _git(d, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "src")
    shutil.rmtree(d / "src", ignore_errors=True)
    _git(d, "checkout", shas[-1], "--", "src")
    commit(d, f"revert to rev {rev}")


_PACKAGE_JSON = {
    "name": "prototype",
    "private": True,
    "version": "0.0.0",
    "type": "module",
    "scripts": {"dev": "vite", "build": "tsc --noEmit && vite build", "preview": "vite preview"},
    "dependencies": {"react": "18.3.1", "react-dom": "18.3.1"},
    "devDependencies": {
        "@types/react": "^18.3.3",
        "@types/react-dom": "^18.3.0",
        "@vitejs/plugin-react": "^4.3.1",
        "typescript": "^5.5.4",
        "vite": "^5.4.0",
    },
}

_VITE_CONFIG = """\
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
});
"""

_TSCONFIG = {
    "compilerOptions": {
        "target": "ES2020",
        "lib": ["ES2020", "DOM", "DOM.Iterable"],
        "module": "ESNext",
        "moduleResolution": "bundler",
        "jsx": "react-jsx",
        "strict": True,
        "noEmit": True,
        "skipLibCheck": True,
    },
    "include": ["src"],
}

_INDEX_HTML = """\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <link rel="stylesheet" href="./design-pack/tokens.css" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
"""


def eject(prototype_dir: Path) -> Path:
    """Write a Vite project around ``src/`` so ``npm i && npm run dev`` works."""
    d = Path(prototype_dir)
    (d / "package.json").write_text(json.dumps(_PACKAGE_JSON, indent=2) + "\n", encoding="utf-8")
    (d / "vite.config.ts").write_text(_VITE_CONFIG, encoding="utf-8")
    (d / "tsconfig.json").write_text(json.dumps(_TSCONFIG, indent=2) + "\n", encoding="utf-8")
    # Types for `import './styles.css'` under `tsc --noEmit`.
    (d / "src" / "vite-env.d.ts").write_text('/// <reference types="vite/client" />\n', encoding="utf-8")
    (d / "index.html").write_text(_INDEX_HTML.format(title=html.escape(d.name)), encoding="utf-8")
    return d
