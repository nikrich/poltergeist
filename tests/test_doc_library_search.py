"""Fuzzy title/path search, preferred project first."""
from pathlib import Path

import pytest

from ghostbrain.api.repo.doc_library import ops, search
from tests.doc_library_helpers import lib_vault  # noqa: F401


@pytest.fixture(autouse=True)
def seeded(lib_vault: Path, monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "body")
    ops.upload("work", "payments", "specs", "Rate card Q4.xlsx", "", b"1")
    ops.upload("work", "claims", "", "Interchange rates 2026.pdf", "", b"2")
    ops.upload("personal", None, "rates", "Mortgage.pdf", "", b"3")
    ops.upload("work", None, "", "Unrelated.pdf", "", b"4")


def test_ranking_and_project_preference():
    titles = [s["title"] for s in search.search("rate")]
    assert titles[:2] == ["Interchange rates 2026", "Rate card Q4"] or titles[:2] == ["Rate card Q4", "Interchange rates 2026"]
    assert "Mortgage" in titles  # path match ("rates/")
    assert "Unrelated" not in titles
    preferred = [s["title"] for s in search.search("rate", project="work/claims")]
    assert preferred[0] == "Interchange rates 2026"


def test_subsequence_and_empty():
    assert [s["title"] for s in search.search("rcq4")] == ["Rate card Q4"]
    assert search.search("   ") == []
