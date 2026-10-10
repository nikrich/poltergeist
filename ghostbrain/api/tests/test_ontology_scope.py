from ghostbrain.ontology import scope
from ghostbrain.ontology.store import Store


def _note(vault, rel, fm: str, body: str):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{fm}\n---\n{body}\n", encoding="utf-8")


def test_artefact_key_prefers_id_then_doc_id_then_stem():
    assert scope.artefact_key("a/b/x.md", {"id": "evt-1", "doc_id": "d"}) == "evt-1"
    assert scope.artefact_key("a/b/x.md", {"doc_id": "abc123"}) == "abc123"
    assert scope.artefact_key("a/b/x.md", {}) == "x"


def test_find_artefacts_keyword_match_dedupes_raw_and_context_copies(tmp_vault):
    _note(tmp_vault, "20-contexts/work/jira/t1.md", "id: t1\ntitle: Orbit lapse rules", "Lapse is day 31.")
    _note(tmp_vault, "00-inbox/raw/jira/t1.md", "id: t1\ntitle: Orbit lapse rules", "Lapse is day 31.")
    _note(tmp_vault, "20-contexts/work/jira/t2.md", "id: t2\ntitle: Other", "nothing to see")
    _note(tmp_vault, "20-contexts/work/slack/s1.md", "id: s1\ntitle: chat", "the orbit go-live moved")
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, limit: [])
    assert sorted(r.aid for r in refs) == ["s1", "t1"]
    assert next(r for r in refs if r.aid == "t1").path == "20-contexts/work/jira/t1.md"


def test_generated_ontology_notes_are_never_artefacts(tmp_vault):
    _note(tmp_vault, "20-contexts/work/projects/orbit/ontology/rule/abcd1234-lapse.md",
          "type: ontology\nuuid: abcd\ngenerated: true", "Orbit lapse rule")
    _note(tmp_vault, "20-contexts/work/x.md", "id: x1\ntype: ontology", "Orbit")
    assert scope.find_artefacts(["Orbit"], search_fn=lambda q, limit: []) == []


def test_semantic_hits_are_included_and_failures_ignored(tmp_vault):
    # Outside the scan roots, so only the semantic path can surface it.
    _note(tmp_vault, "10-daily/meet.md", "id: m1\ntitle: Planning", "Orbit unit-linked policy design")
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, limit: ["10-daily/meet.md"])
    assert [r.aid for r in refs] == ["m1"]

    def boom(q, limit):
        raise RuntimeError("index not built")
    assert scope.find_artefacts(["Orbit"], search_fn=boom) == []


def test_propose_binding_skips_known_artefacts(tmp_path):
    store = Store(tmp_path / "o.db")
    refs = [scope.ArtefactRef("a1", "x.md", "X"), scope.ArtefactRef("a2", "y.md", "Y")]
    item = scope.propose_binding(store, "p1", refs)
    assert store.item(item)["payload"]["artefacts"][0]["aid"] == "a1"
    store.upsert_binding("p1", "a1", "x.md", "X", "bound")
    store.upsert_binding("p1", "a2", "y.md", "Y", "excluded")
    assert scope.propose_binding(store, "p1", refs) is None


def test_non_matching_notes_are_never_parsed(tmp_vault, monkeypatch):
    _note(tmp_vault, "20-contexts/work/jira/hit.md", "id: hit1\ntitle: Orbit", "Orbit body")
    _note(tmp_vault, "20-contexts/work/jira/miss.md", "id: miss1\ntitle: Unrelated", "UNRELATED-MARKER body")
    parsed: list[str] = []
    real_loads = scope.frontmatter.loads

    def spy(text, *args, **kwargs):
        parsed.append(text)
        return real_loads(text, *args, **kwargs)

    monkeypatch.setattr(scope.frontmatter, "loads", spy)
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, limit: [])
    assert [r.aid for r in refs] == ["hit1"]
    assert any("Orbit body" in t for t in parsed)
    assert not any("UNRELATED-MARKER" in t for t in parsed)


def test_semantic_hits_survive_when_keyword_matches_exceed_limit(tmp_vault):
    for i in range(5):
        _note(tmp_vault, f"20-contexts/work/jira/k{i}.md", f"id: k{i}\ntitle: K{i}", "Orbit keyword hit")
    _note(tmp_vault, "20-contexts/work/m/meet.md", "id: m1\ntitle: Planning", "semantic hit, mentions Orbit once")
    refs = scope.find_artefacts(["Orbit"], limit=2, search_fn=lambda q, limit: ["20-contexts/work/m/meet.md"])
    assert len(refs) == 2
    assert "m1" in [r.aid for r in refs]


def test_unreadable_paths_are_skipped(tmp_vault):
    _note(tmp_vault, "20-contexts/work/ok.md", "id: ok1\ntitle: Orbit notes", "Orbit")
    (tmp_vault / "20-contexts/work/x.md").symlink_to(tmp_vault / "nowhere.md")
    (tmp_vault / "20-contexts/work/dir.md").mkdir()
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, limit: [])
    assert [r.aid for r in refs] == ["ok1"]


def _ids(vault_seed="Orbit", search_fn=lambda q, limit: []):
    return sorted(r.aid for r in scope.find_artefacts([vault_seed], search_fn=search_fn))


def test_seed_only_in_related_frontmatter_is_not_proposed(tmp_vault):
    _note(tmp_vault, "20-contexts/personal/mail/m1.md",
          'id: m1\ntitle: Window repairs\nrelated:\n  - "[[Orbit launch plan]]"\nparent: Orbit', "Fix the flat windows.")
    assert _ids() == []


def test_seed_only_in_wikilink_target_or_embed_is_not_proposed(tmp_vault):
    _note(tmp_vault, "20-contexts/work/n/a.md", "id: a\ntitle: Misc", "See [[Orbit roadmap]] and ![[Orbit diagram.png]].")
    assert _ids() == []


def test_seed_in_body_or_title_is_proposed(tmp_vault):
    _note(tmp_vault, "20-contexts/work/n/b.md", "id: b\ntitle: Misc", "Orbit kickoff happened.")
    _note(tmp_vault, "20-contexts/work/n/c.md", "id: c\ntitle: Orbit budget", "numbers")
    _note(tmp_vault, "20-contexts/work/n/d.md", "id: d", "# Orbit heading title\ntext")
    assert _ids() == ["b", "c", "d"]


def test_seed_in_wikilink_alias_is_proposed(tmp_vault):
    _note(tmp_vault, "20-contexts/work/n/e.md", "id: e\ntitle: Misc", "Per [[plan-2026|the Orbit plan]] we ship.")
    assert _ids() == ["e"]


def test_semantic_hit_without_content_mention_is_unsure(tmp_vault):
    _note(tmp_vault, "20-contexts/work/n/f.md", "id: f\ntitle: Misc\nrelated: ['[[Orbit]]']", "unrelated text")
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, limit: ["20-contexts/work/n/f.md"])
    assert [(r.aid, r.band, r.mentions) for r in refs] == [("f", "unsure", 0)]


def test_bands_title_heading_and_many_mentions_are_in(tmp_vault):
    _note(tmp_vault, "20-contexts/work/a.md", "id: a\ntitle: Orbit kickoff", "x")
    _note(tmp_vault, "20-contexts/work/b.md", "id: b\ntitle: notes", "## Orbit pricing\ntext")
    _note(tmp_vault, "20-contexts/work/c.md", "id: c\ntitle: c", "Orbit one. Orbit two. Orbit three.")
    _note(tmp_vault, "20-contexts/work/d.md", "id: d\ntitle: d", "We mentioned Orbit once.")
    bands = {r.aid: r.band for r in scope.find_artefacts(["Orbit"], search_fn=lambda q, l: [])}
    assert bands == {"a": "in", "b": "in", "c": "in", "d": "unsure"}


def test_project_folder_note_is_in(tmp_vault):
    _note(tmp_vault, "20-contexts/work/projects/orbit/x.md", "id: x\ntitle: x", "Orbit once")
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, l: [], project_dir="20-contexts/work/projects/orbit")
    assert [(r.aid, r.band) for r in refs] == [("x", "in")]


def test_semantic_hit_without_mention_is_unsure(tmp_vault):
    _note(tmp_vault, "10-daily/m.md", "id: m1\ntitle: Planning", "unit-linked design")
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, l: ["10-daily/m.md"])
    assert [(r.aid, r.band, r.mentions) for r in refs] == [("m1", "unsure", 0)]


def test_project_folder_note_without_mention_is_in_and_generated_excluded(tmp_vault):
    d = "20-contexts/work/projects/orbit"
    _note(tmp_vault, f"{d}/plain.md", "id: p\ntitle: Plain", "nothing relevant")
    _note(tmp_vault, f"{d}/ontology/rule/r.md", "type: ontology\nuuid: r", "Orbit rule")
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, l: [], project_dir=d)
    assert [(r.aid, r.band, r.mentions) for r in refs] == [("p", "in", 0)]


def test_semantic_hit_inside_project_dir_without_mention_is_in(tmp_vault):
    d = "20-contexts/work/projects/orbit"
    _note(tmp_vault, f"{d}/s.md", "id: s\ntitle: S", "unrelated")
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, l: [f"{d}/s.md"], project_dir=d)
    assert [(r.aid, r.band) for r in refs] == [("s", "in")]


def test_link_only_heading_is_not_in(tmp_vault):
    _note(tmp_vault, "20-contexts/work/l.md", "id: l\ntitle: L", "## See [[Orbit]]\n# ![[Orbit]]\ntext")
    assert scope.find_artefacts(["Orbit"], search_fn=lambda q, l: []) == []
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, l: ["20-contexts/work/l.md"])
    assert [(r.aid, r.band) for r in refs] == [("l", "unsure")]


def test_project_dir_cannot_escape_vault(tmp_vault):
    outside = tmp_vault.parent / "x"
    outside.mkdir(exist_ok=True)
    (outside / "a.md").write_text("---\nid: out\n---\nOrbit", encoding="utf-8")
    assert scope.find_artefacts(["Orbit"], search_fn=lambda q, l: [], project_dir="../x") == []
    assert scope.find_artefacts(["Orbit"], search_fn=lambda q, l: [], project_dir=str(outside)) == []


def test_untitled_h1_links_do_not_count_but_real_text_does(tmp_vault):
    _note(tmp_vault, "20-contexts/work/e.md", "id: e", "# ![[Orbit]]\ntext")
    _note(tmp_vault, "20-contexts/work/s.md", "id: s", "# See [[Orbit]]\ntext")
    _note(tmp_vault, "20-contexts/work/p.md", "id: p", "# Orbit plan\ntext")
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, l: [])
    assert [(r.aid, r.band) for r in refs] == [("p", "in")]
