"""Docs roots + path guard (spec §1, §7)."""
from pathlib import Path

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library import scope
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidPath, NotFound
from tests.doc_library_helpers import lib_vault  # noqa: F401


def test_scope_roots(lib_vault: Path):
    assert scope.scope_root("work", None) == lib_vault / "20-contexts/work/docs"
    assert scope.scope_root("work", "payments") == lib_vault / "20-contexts/work/projects/payments/docs"


def test_scope_root_rejects_unknown_and_archived(lib_vault: Path):
    with pytest.raises(NotFound):
        scope.scope_root("nope", None)
    with pytest.raises(NotFound):
        scope.scope_root("work", "ghost")
    projects.update_project("work", "claims", archived=True)
    assert scope.scope_root("work", "claims").name == "docs"  # read is fine
    with pytest.raises(Conflict):
        scope.scope_root("work", "claims", for_write=True)


@pytest.mark.parametrize("rel,clean", [("", ""), ("a", "a"), ("a//b/", "a/b"), ("./a/./b", "a/b"), ("a\\b", "a/b")])
def test_clean_rel(rel, clean):
    assert scope.clean_rel(rel) == clean


@pytest.mark.parametrize("rel", ["../x", "a/../../x", "/etc", "C:/x", ".hidden", "a/.git"])
def test_clean_rel_rejects(rel):
    with pytest.raises(InvalidPath):
        scope.clean_rel(rel)


def test_resolve_in_blocks_symlink_escape(lib_vault: Path, tmp_path: Path):
    root = scope.scope_root("work", None)
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(InvalidPath):
        scope.resolve_in(root, "link")
    assert scope.resolve_in(root, "specs/v2") == root / "specs/v2"


def test_all_scopes_includes_archived(lib_vault: Path):
    projects.update_project("work", "claims", archived=True)
    keys = [(c, p) for c, p, _ in scope.all_scopes()]
    assert keys == [("work", None), ("personal", None), ("work", "payments"), ("work", "claims")]
