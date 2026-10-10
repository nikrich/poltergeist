"""Git worktrees a design session builds an existing frontend in.

A session gets a sibling worktree ``<repo>-poltergeist-<date>-<slug>`` on a
new branch ``poltergeist/<date>-<slug>`` cut from the remote default branch,
so the user's own checkout (dirty or not) is never touched and nothing is
pushed. Every agent run is one ``rev N: <summary>`` commit, like scaffold
prototypes.

The dev server executes the app's package.json scripts and config files, so
after the bootstrap run those are protected: :func:`snapshot_protected`
before an agent run, :func:`restore_protected` after it.
"""
from __future__ import annotations

import fnmatch
import glob
import logging
import os
import re
import shutil
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import IO

from ghostbrain.design import codebases
from ghostbrain.design.scaffold import _GIT_CONFIG, _GIT_ENV_DROP, _REV_RE

log = logging.getLogger("ghostbrain.design.worktree")

FETCH_TIMEOUT_S = 20
GIT_TIMEOUT_S = 60
INSTALL_TIMEOUT_S = 600
LOG_TAIL_LINES = 15
APP_DIR_GLOBS = ("apps/*", "packages/*", "frontend", "web", "client", "ui")
APP_DIR_PREFERRED = ("web", "frontend", "client", "ui")
LOCKFILES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock")
# Files the dev server or the package manager executes or obeys: protected
# at any depth (nested workspace packages run too). Patterns are matched on
# the file name; ``<dir>/**`` covers a directory of that name.
PROTECTED_GLOBS: tuple[str, ...] = (
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml",
    "pnpm-workspace.yaml", "yarn.lock", "bun.lockb",
    ".npmrc", ".yarnrc", ".yarnrc.yml", ".pnpmfile.cjs", ".nvmrc", ".node-version", ".tool-versions",
    ".env*", ".babelrc*", ".postcssrc*", ".swcrc", ".browserslistrc",
    "*.config.js", "*.config.cjs", "*.config.mjs", "*.config.ts", "*.config.mts", "*.config.cts",
    "*.config.json", ".gitattributes", ".gitmodules", ".git",
    ".poltergeist/**", ".yarn/**", ".husky/**",
)
# Never walked: third-party code and build output, not the agent's to touch.
_WALK_SKIP = {"node_modules", "dist", "build", "out", ".next", ".turbo", ".cache", "coverage"}
# GUI launches get a bare PATH; node usually lives in one of these.
EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "~/.volta/bin")
NVM_GLOB = "~/.nvm/versions/node/*/bin"

Runner = Callable[..., int]


class WorktreeError(RuntimeError):
    pass


@dataclass
class Worktree:
    repo: Path
    path: Path
    branch: str
    base: str
    app_dir: Path

    def to_dict(self) -> dict:
        return {
            "repo": str(self.repo), "name": self.repo.name, "app_dir": str(self.app_dir),
            "worktree": str(self.path), "branch": self.branch, "base": self.base,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Worktree:
        path = Path(d["worktree"])
        return cls(
            repo=Path(d["repo"]), path=path, branch=str(d["branch"]), base=str(d["base"]),
            app_dir=Path(d.get("app_dir") or path),
        )


# --- git ------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_DROP}
    env["GIT_TERMINAL_PROMPT"] = "0"  # a fetch must never wait for a password
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return env


def _git_run(cwd: Path, *args: str, timeout: float = GIT_TIMEOUT_S) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *_GIT_CONFIG, *args],
            env=_git_env(), capture_output=True, text=True, timeout=timeout, check=False,
        )
    except FileNotFoundError as e:
        raise WorktreeError("git is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise WorktreeError(f"git {args[0]} timed out") from e


def _git(cwd: Path, *args: str, timeout: float = GIT_TIMEOUT_S) -> str:
    proc = _git_run(cwd, *args, timeout=timeout)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr.strip() or proc.stdout.strip()).splitlines()[-5:])
        raise WorktreeError(f"git {args[0]} failed: {tail}")
    return proc.stdout


def _ok(cwd: Path, *args: str) -> bool:
    return _git_run(cwd, *args).returncode == 0


def _fetch(repo: Path, branch: str) -> None:
    try:
        _git_run(repo, "fetch", "-q", "origin", branch, timeout=FETCH_TIMEOUT_S)
    except WorktreeError as e:  # offline / no access: build on what is there
        log.info("fetch origin %s skipped: %s", branch, e)


def _base(repo: Path) -> str:
    """The remote default branch (fetched first), else a local main/master, else HEAD."""
    proc = _git_run(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    head = proc.stdout.strip() if proc.returncode == 0 else ""
    for ref in [head] if head else ["origin/main", "origin/master"]:
        _fetch(repo, ref.removeprefix("origin/"))
        if _ok(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"):
            return ref
    for ref in ("main", "master"):
        if _ok(repo, "rev-parse", "--verify", "-q", f"refs/heads/{ref}^{{commit}}"):
            return ref
    return "HEAD"


# Inside a worktree the agent can write any file, including ``.git`` (the
# gitdir pointer). Git there runs only against the gitdir under the main
# repo's ``.git/worktrees/`` — which the agent cannot reach — and with every
# config hook that would run a command switched off.
_WT_HARDENING = [
    "-c", "core.fsmonitor=false",
    "-c", "core.untrackedCache=false",
    "-c", "diff.external=",
    "-c", "core.pager=cat",
]


def _gitdir(wt: Worktree) -> Path:
    """The worktree's gitdir, checked to live under the main repo."""
    try:
        text = (wt.path / ".git").read_text(encoding="utf-8").strip()
    except OSError as e:
        raise WorktreeError(f"{wt.path} is not a worktree any more") from e
    if (wt.path / ".git").is_symlink() or not text.startswith("gitdir:"):
        raise WorktreeError("the worktree's .git link was changed; refusing to run git there")
    gitdir = Path(text[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = wt.path / gitdir
    real = gitdir.resolve()
    allowed = (Path(wt.repo).resolve() / ".git" / "worktrees").resolve()
    if allowed not in real.parents or not real.is_dir():
        raise WorktreeError("the worktree's .git link was changed; refusing to run git there")
    return real


def _wt_run(wt: Worktree, *args: str, timeout: float = GIT_TIMEOUT_S) -> subprocess.CompletedProcess:
    gitdir = _gitdir(wt)
    return _git_run(wt.path, f"--git-dir={gitdir}", f"--work-tree={wt.path}", *_WT_HARDENING, *args,
                    timeout=timeout)


def _wt_git(wt: Worktree, *args: str) -> str:
    proc = _wt_run(wt, *args)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr.strip() or proc.stdout.strip()).splitlines()[-5:])
        raise WorktreeError(f"git {args[0]} failed: {tail}")
    return proc.stdout


def create(repo: Path, *, day: date, slug: str) -> Worktree:
    """A sibling worktree on a fresh ``poltergeist/<day>-<slug>`` branch (suffixed
    ``-2``, ``-3``… when the folder or branch already exists)."""
    repo = Path(repo).resolve()
    if not _ok(repo, "rev-parse", "--git-dir"):
        raise WorktreeError(f"not a git repository: {repo}")
    base = _base(repo)
    stem = f"{day.isoformat()}-{slug}"
    n = 1
    while True:
        suffix = "" if n == 1 else f"-{n}"
        path = repo.parent / f"{repo.name}-poltergeist-{stem}{suffix}"
        branch = f"poltergeist/{stem}{suffix}"
        if not path.exists() and not _ok(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}"):
            break
        n += 1
    _git(repo, "worktree", "add", "-q", "-b", branch, str(path), base)
    return Worktree(repo=repo, path=path, branch=branch, base=base, app_dir=find_app_dir(path) or path)


def commit(wt: Worktree, message: str, *, allow_empty: bool = False) -> str | None:
    """Commit everything; the short sha, or None when nothing changed (unless
    ``allow_empty``: every ``rev N:`` needs its commit to be revertable)."""
    _wt_git(wt, "add", "-A")
    if not allow_empty and _wt_run(wt, "diff", "--cached", "--quiet").returncode == 0:
        return None
    _wt_git(wt, "commit", "-q", *(["--allow-empty"] if allow_empty else []), "-m", message)
    return _wt_git(wt, "rev-parse", "--short", "HEAD").strip()


def _log(wt: Worktree) -> list[tuple[str, int, str, str]]:
    """(sha, rev, iso date, summary) for every ``rev N:`` commit since base, oldest first."""
    try:
        out = _wt_git(wt, "log", "--reverse", "--format=%H%x1f%cI%x1f%s", f"{wt.base}..HEAD")
    except WorktreeError:
        return []
    entries = []
    for line in out.splitlines():
        sha, at, subject = line.split("\x1f", 2)
        m = _REV_RE.match(subject)
        if m:
            entries.append((sha, int(m.group(1)), at, m.group(2)))
    return entries


def revisions(wt: Worktree) -> list[dict]:
    """``[{rev, at, summary}]`` oldest first."""
    return [{"rev": rev, "at": at, "summary": summary} for _, rev, at, summary in _log(wt)]


def revert_to(wt: Worktree, rev: int) -> None:
    """Make the tree what it was at ``rev N:`` and commit that as ``revert to rev N``."""
    shas = [sha for sha, r, _, _ in _log(wt) if r == rev]
    if not shas:
        raise KeyError(f"no revision {rev}")
    _wt_git(wt, "read-tree", "-u", "--reset", shas[-1])
    commit(wt, f"revert to rev {rev}")


def deps_changed(wt: Worktree, since_sha: str) -> bool:
    """Whether package.json or a lockfile changed between ``since_sha`` and HEAD."""
    out = _wt_git(wt, "diff", "--name-only", since_sha, "HEAD")
    names = {"package.json", *LOCKFILES}
    return any(Path(p).name in names for p in out.splitlines())


def remove(wt: Worktree) -> dict:
    """Delete the worktree folder; keep the branch when it has unmerged commits."""
    if wt.path.exists():
        proc = _git_run(wt.repo, "worktree", "remove", "--force", str(wt.path))
        if proc.returncode != 0:
            return {"removed": False, "branch_kept": True,
                    "reason": (proc.stderr.strip() or proc.stdout.strip()) or "git worktree remove failed"}
    else:
        _git_run(wt.repo, "worktree", "prune")
    if not _ok(wt.repo, "rev-parse", "--verify", "-q", f"refs/heads/{wt.branch}"):
        return {"removed": True, "branch_kept": False, "reason": None}
    if _ok(wt.repo, "branch", "-d", wt.branch):
        return {"removed": True, "branch_kept": False, "reason": None}
    return {"removed": True, "branch_kept": True, "reason": f"unmerged commits on {wt.branch}"}


# --- app dir / install ----------------------------------------------------------


def _runnable_frontend(d: Path) -> bool:
    pkg = codebases._read_package(d / "package.json")
    scripts = pkg.get("scripts")
    has_script = isinstance(scripts, dict) and ("dev" in scripts or "start" in scripts)
    return has_script and codebases._has_frontend_dep(pkg)


def find_app_dir(worktree: Path) -> Path | None:
    """The folder whose dev/start script serves the frontend; None when there is none."""
    root = Path(worktree)
    if _runnable_frontend(root):
        return root
    found = sorted({d for pattern in APP_DIR_GLOBS for d in root.glob(pattern) if d.is_dir() and _runnable_frontend(d)})
    if not found:
        return None
    preferred = [d for d in found if d.name in APP_DIR_PREFERRED]
    return (preferred or found)[0]


def package_manager(app_dir: Path) -> str:
    d = Path(app_dir)
    if (d / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (d / "yarn.lock").exists():
        return "yarn"
    return "npm"


def install_argv(app_dir: Path) -> list[str]:
    pm = package_manager(app_dir)
    if pm == "pnpm":
        return ["pnpm", "install", "--frozen-lockfile"]
    if pm == "yarn":
        return ["yarn", "install", "--frozen-lockfile"]
    if (Path(app_dir) / "package-lock.json").exists():
        return ["npm", "ci", "--no-audit", "--no-fund"]
    return ["npm", "install", "--no-audit", "--no-fund"]


def _version_key(bin_dir: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", Path(bin_dir).parent.name))


# Install runs the repo's lifecycle scripts outside any sandbox, so it gets
# only what a package manager needs: no API keys, tokens or app settings.
_INSTALL_ENV_KEYS = {
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TERM", "TZ",
    "NVM_DIR", "VOLTA_HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
    "no_proxy", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "COREPACK_HOME",
}
_INSTALL_ENV_PREFIXES = ("npm_config_", "NPM_CONFIG_", "YARN_", "PNPM_HOME")


def install_env() -> dict[str, str]:
    """A minimal environment with node's usual homes appended to PATH."""
    env = {k: v for k, v in os.environ.items()
           if k in _INSTALL_ENV_KEYS or k.startswith(_INSTALL_ENV_PREFIXES)}
    nvm = sorted(glob.glob(os.path.expanduser(NVM_GLOB)), key=_version_key, reverse=True)
    extra = [os.path.expanduser(p) for p in EXTRA_PATH] + nvm
    env["PATH"] = os.pathsep.join([p for p in [env.get("PATH", "")] if p] + extra)
    return env


def _run_install(argv: list[str], *, cwd: Path, timeout_s: float, log_file: IO[str]) -> int:
    """Run ``argv`` (no shell) into ``log_file``; on timeout kill its whole process group."""
    proc = subprocess.Popen(
        argv, cwd=str(cwd), env=install_env(), stdout=log_file, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        return proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.wait()
        raise


def _wipe_node_modules(root: Path) -> None:
    """Remove every node_modules folder in the worktree (they are reinstalled):
    anything an agent left there must not run. Symlinks are unlinked, never
    followed; each entry is renamed before it is deleted so a swap can't
    redirect the delete."""
    for dirpath, dirnames, _ in os.walk(root, followlinks=False):
        if ".git" in dirnames:
            dirnames.remove(".git")
        if "node_modules" in dirnames:
            dirnames.remove("node_modules")
            target = Path(dirpath) / "node_modules"
            doomed = target.with_name(f"node_modules.gb-wipe-{os.getpid()}")
            try:
                os.rename(target, doomed)
            except OSError:
                continue
            if doomed.is_symlink() or not doomed.is_dir():
                doomed.unlink(missing_ok=True)
            else:
                shutil.rmtree(doomed, ignore_errors=True)


def _require_pristine(wt: Worktree) -> None:
    """Install runs lifecycle scripts unsandboxed: only ever on the tree as
    created from the repo, before any agent edit (scripts it calls could
    otherwise be agent-written). Ignored files count too — a fresh worktree
    has none once node_modules is gone."""
    _wipe_node_modules(wt.path)
    head = _wt_git(wt, "rev-parse", "HEAD").strip()
    base = _wt_git(wt, "rev-parse", f"{wt.base}^{{commit}}").strip()
    status = _wt_git(wt, "status", "--porcelain", "-z", "--ignored", "--untracked-files=all")
    if head != base or status.strip("\0"):
        raise WorktreeError(
            "the worktree changed since it was created; dependencies are only installed on a fresh "
            "worktree — start a new session to reinstall")


def install(wt: Worktree, *, log_path: Path, timeout_s: int = INSTALL_TIMEOUT_S,
            runner: Runner | None = None) -> None:
    """Install the app's dependencies. A workspace without a lockfile in the app
    dir installs at the worktree root, where its lockfile is."""
    _require_pristine(wt)
    cwd = wt.app_dir
    if not any((cwd / f).exists() for f in LOCKFILES) and any((wt.path / f).exists() for f in LOCKFILES):
        cwd = wt.path
    argv = install_argv(cwd)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            rc = (runner or _run_install)(argv, cwd=cwd, timeout_s=timeout_s, log_file=log_file)
    except subprocess.TimeoutExpired as e:
        raise WorktreeError("dependency install timed out") from e
    except FileNotFoundError as e:
        raise WorktreeError(f"{argv[0]} not found — is Node.js installed?") from e
    if rc != 0:
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        tail = "\n".join(lines[-LOG_TAIL_LINES:])
        raise WorktreeError(f"{argv[0]} install failed: {tail}")


# --- protected files ------------------------------------------------------------


def _name_matches(name: str) -> bool:
    return any(not pat.endswith("/**") and fnmatch.fnmatchcase(name, pat) for pat in PROTECTED_GLOBS)


_PROTECTED_DIRS = tuple(pat[:-3] for pat in PROTECTED_GLOBS if pat.endswith("/**"))


def _protected_now(wt: Worktree) -> set[str]:
    """Worktree-relative paths of every protected file, and of every symlink
    with a protected name. Symlinks are never followed: an agent-planted link
    to ``~`` must not pull the home folder into the restore."""
    root = wt.path
    out: set[str] = set()
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        rel_here = here.relative_to(root)
        in_protected_dir = any(part in _PROTECTED_DIRS for part in rel_here.parts)
        keep = []
        for d in dirnames:
            p = here / d
            if p.is_symlink():
                # Not descended; a link with a protected name is itself undone.
                if d in _PROTECTED_DIRS or _name_matches(d) or in_protected_dir:
                    out.add(p.relative_to(root).as_posix())
                continue
            if d == ".git" or d in _WALK_SKIP:
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in filenames:
            if in_protected_dir or _name_matches(f):
                out.add((here / f).relative_to(root).as_posix())
    return out


def _safe_target(wt: Worktree, rel: str) -> Path | None:
    """``wt.path / rel`` when every parent below the worktree is a real
    directory (no symlink, no ``..``), else None."""
    if not rel or rel.startswith("/") or "\\" in rel or any(part in ("", ".", "..") for part in rel.split("/")):
        return None
    p = wt.path / rel
    cur = wt.path
    for part in Path(rel).parts[:-1]:
        cur = cur / part
        if cur.is_symlink() or (cur.exists() and not cur.is_dir()):
            return None
    return p


def _read(p: Path) -> str | None:
    """Content (through a symlink, so a user's own linked ``.env`` survives
    unchanged); None when absent or unreadable."""
    try:
        return p.read_text(encoding="utf-8", errors="surrogateescape") if p.is_file() else None
    except OSError:
        return None


def snapshot_protected(wt: Worktree) -> dict[str, str | None]:
    """Worktree-relative path -> content of every protected file (symlinks
    with protected names are recorded as absent, so a restore removes them)."""
    return {rel: (None if (wt.path / rel).is_symlink() and not (wt.path / rel).is_file() else _read(wt.path / rel))
            for rel in sorted(_protected_now(wt))}


def restore_protected(wt: Worktree, snap: dict[str, str | None]) -> list[str]:
    """Put every protected file back as snapshotted: rewrite changed ones,
    recreate deleted ones, delete new ones. Returns the paths it touched."""
    changed: list[str] = []
    for rel in sorted(set(snap) | _protected_now(wt)):
        p = _safe_target(wt, rel)
        if p is None:
            # A parent is a symlink (or the path is malformed): never write or
            # delete through it. Protected-name links themselves sort before
            # their children and are undone first.
            log.warning("skipped protected path %r in %s: unsafe parent", rel, wt.path)
            continue
        want = snap.get(rel)
        have = _read(p)
        if have == want and not (want is None and (p.exists() or p.is_symlink())):
            continue
        if p.is_symlink() or p.exists():
            p.unlink()  # never write through a symlink the agent planted
        if want is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(want, encoding="utf-8", errors="surrogateescape")
        changed.append(rel)
    if changed:
        log.warning("reverted protected files in %s: %s", wt.path, ", ".join(changed))
    return changed
