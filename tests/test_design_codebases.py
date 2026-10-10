"""Finding existing codebases for a design session to build on."""
from __future__ import annotations

import json
from pathlib import Path

from ghostbrain.design import codebases
from ghostbrain.design.codebases import Candidate


def _repo(p, pkg=None):
    (p / ".git").mkdir(parents=True)
    if pkg is not None:
        (p / "package.json").write_text(json.dumps(pkg))


def _never(*a, **kw):
    raise AssertionError("the LLM must not be asked")


def _answer(d):
    class _Result:
        def as_json(self):
            return d

    def run(prompt, **kw):
        run.calls.append((prompt, kw))
        return _Result()

    run.calls = []
    return run


def _failing(*a, **kw):
    raise RuntimeError("claude down")


def test_scan_finds_nested_repos_and_prunes(tmp_path):
    _repo(tmp_path / "work" / "sbx-fe-orbit", {"name": "orbit-web", "dependencies": {"react": "18"}})
    _repo(tmp_path / "work" / "hive" / "repos" / "bff-orbit")
    (tmp_path / "work" / "x" / "node_modules" / "y" / ".git").mkdir(parents=True)
    (tmp_path / "wt-poltergeist-2026-10-10-a").mkdir(); (tmp_path / "wt-poltergeist-2026-10-10-a" / ".git").write_text("gitdir: x")
    (tmp_path / "work" / "sbx-fe-orbit" / "inner" / ".git").mkdir(parents=True)  # inside a repo: not descended
    found = {c.rel: c for c in codebases.scan([tmp_path], refresh=True)}
    assert set(found) == {"work/sbx-fe-orbit", "work/hive/repos/bff-orbit"}
    assert found["work/sbx-fe-orbit"].frontend and found["work/sbx-fe-orbit"].name == "orbit-web"
    assert not found["work/hive/repos/bff-orbit"].frontend


def test_scan_skips_hidden_and_poltergeist_dirs_with_real_git_dirs(tmp_path):
    _repo(tmp_path / ".hidden" / "r")
    _repo(tmp_path / "app-poltergeist-2026-10-10-x")
    _repo(tmp_path / "dist" / "r")
    assert codebases.scan([tmp_path], refresh=True) == []


def test_scan_respects_depth(tmp_path):
    _repo(tmp_path / "a" / "b" / "c" / "d" / "e" / "f")
    assert codebases.scan([tmp_path], max_depth=5, refresh=True) == []


def test_scan_finds_repo_at_max_depth(tmp_path):
    _repo(tmp_path / "a" / "b" / "c" / "d" / "e")
    assert [c.rel for c in codebases.scan([tmp_path], max_depth=5, refresh=True)] == ["a/b/c/d/e"]


def test_scan_missing_root_is_empty(tmp_path):
    assert codebases.scan([tmp_path / "nope"], refresh=True) == []


def test_scan_caches_until_refresh(tmp_path):
    _repo(tmp_path / "one")
    assert len(codebases.scan([tmp_path], refresh=True)) == 1
    _repo(tmp_path / "two")
    assert len(codebases.scan([tmp_path])) == 1
    assert len(codebases.scan([tmp_path], refresh=True)) == 2


def test_frontend_detected_from_workspace_package(tmp_path):
    _repo(tmp_path / "mono", {"name": "mono", "workspaces": ["apps/*"]})
    (tmp_path / "mono" / "apps" / "web").mkdir(parents=True)
    (tmp_path / "mono" / "apps" / "web" / "package.json").write_text(
        json.dumps({"devDependencies": {"vite": "5"}}))
    _repo(tmp_path / "broken", None)
    (tmp_path / "broken" / "package.json").write_text("{not json")
    found = {c.rel: c for c in codebases.scan([tmp_path], refresh=True)}
    assert found["mono"].frontend
    assert not found["broken"].frontend and found["broken"].name == "broken"


def test_candidate_to_dict(tmp_path):
    c = Candidate(tmp_path / "fe", "x/fe", "fe", True)
    assert c.to_dict() == {"path": str(tmp_path / "fe"), "rel": "x/fe", "name": "fe", "frontend": True}


def test_roots_come_from_settings_expanded(tmp_path, monkeypatch):
    monkeypatch.setattr(codebases.design_settings, "load", lambda: {"code_roots": ["~/dev", str(tmp_path)]})
    assert codebases.roots() == [Path("~/dev").expanduser(), tmp_path]


def test_search_filters_by_tokens_and_substring(tmp_path, monkeypatch):
    _repo(tmp_path / "sbx-fe-orbit", {"name": "orbit-web", "dependencies": {"react": "18"}})
    _repo(tmp_path / "claims-service")
    monkeypatch.setattr(codebases, "roots", lambda: [tmp_path])
    codebases.scan([tmp_path], refresh=True)
    assert [c.rel for c in codebases.search("orbit")] == ["sbx-fe-orbit"]
    assert [c.rel for c in codebases.search("claims-serv")] == ["claims-service"]
    assert {c.rel for c in codebases.search("")} == {"sbx-fe-orbit", "claims-service"}
    assert codebases.search("", limit=1)[0].frontend  # frontends first


def test_resolve_prefers_frontend_on_token_match(tmp_path):
    cands = [Candidate(tmp_path/"bff", "x/acme-platform-bff-orbit", "acme-platform-bff-orbit", False),
             Candidate(tmp_path/"fe", "x/sbx-fe-orbit", "orbit-web", True)]
    assert codebases.resolve("ORBIT frontend", cands, run=_never).name == "orbit-web"


def test_resolve_uses_llm_to_break_ties(tmp_path):
    cands = [Candidate(tmp_path/"a", "a/claims-web", "claims-web", True),
             Candidate(tmp_path/"b", "b/claims-portal", "claims-portal", True)]
    run = _answer({"pick": "b/claims-portal"})
    picked = codebases.resolve("claims", cands, run=run)
    assert picked.rel == "b/claims-portal"
    assert run.calls[0][1]["model"] == "haiku"


def test_resolve_llm_none_or_unknown_pick_is_none(tmp_path):
    cands = [Candidate(tmp_path/"a", "a/claims-web", "claims-web", True),
             Candidate(tmp_path/"b", "b/claims-portal", "claims-portal", True)]
    assert codebases.resolve("claims", cands, run=_answer({"pick": None})) is None
    assert codebases.resolve("claims", cands, run=_answer({"pick": "zzz"})) is None


def test_resolve_llm_failure_falls_back_to_shortest_rel(tmp_path):
    cands = [Candidate(tmp_path/"a", "deep/er/claims-web", "claims-web", True),
             Candidate(tmp_path/"b", "b/claims-portal", "claims-portal", True)]
    assert codebases.resolve("claims", cands, run=_failing).rel == "b/claims-portal"


def test_resolve_none_when_nothing_matches(tmp_path):
    assert codebases.resolve("ORBIT", [Candidate(tmp_path, "x/other", "other", True)], run=_never) is None


def test_resolve_ignores_stop_words(tmp_path):
    assert codebases.resolve("the existing app", [Candidate(tmp_path, "x/app", "app", True)], run=_never) is None


def test_resolve_no_frontend_candidate_returns_none_when_frontend_wanted(tmp_path):
    cands = [Candidate(tmp_path/"bff", "x/bff-orbit", "bff-orbit", False)]
    assert codebases.resolve("ORBIT frontend", cands, run=_never) is None


def test_resolve_any_candidate_when_frontend_not_required(tmp_path):
    cands = [Candidate(tmp_path/"bff", "x/bff-orbit", "bff-orbit", False)]
    assert codebases.resolve("ORBIT", cands, frontend=False, run=_never).rel == "x/bff-orbit"
