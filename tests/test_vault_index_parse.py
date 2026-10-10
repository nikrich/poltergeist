"""Pure parsing of one vault note into a link-index entry."""
from __future__ import annotations

from ghostbrain.vault_index.parse import (
    HASHTAG_RE,
    SNIPPET_MAX,
    OutLink,
    normalize_target,
    parse_note,
    split_frontmatter,
)


def test_normalize_target_forms():
    assert normalize_target("20-contexts/work/a") == "20-contexts/work/a.md"
    assert normalize_target(" 20-contexts/work/a.md ") == "20-contexts/work/a.md"
    assert normalize_target("/10-daily/2026-10-09") == "10-daily/2026-10-09.md"
    assert normalize_target("20-contexts\\work\\a") == "20-contexts/work/a.md"
    assert normalize_target("Alpha plan") == "Alpha plan.md"
    assert normalize_target("v1.2 notes") == "v1.2 notes.md"
    assert normalize_target("90-meta/assets/x.png") is None
    assert normalize_target("report.PDF") is None
    assert normalize_target("   ") is None


def test_split_frontmatter_variants():
    assert split_frontmatter("---\ntitle: A\n---\nbody") == ({"title": "A"}, "body")
    assert split_frontmatter("---\n---\nbody") == ({}, "body")
    assert split_frontmatter("no fm") == ({}, "no fm")
    # malformed YAML: metadata dropped, body still separated
    assert split_frontmatter("---\ntitle: [unclosed\n---\nbody") == ({}, "body")
    # non-mapping frontmatter
    assert split_frontmatter("---\n- a list\n---\nbody") == ({}, "body")
    # no closing fence: the whole text is body
    assert split_frontmatter("---\ntitle: A\nno close") == ({}, "---\ntitle: A\nno close")
    # CRLF files
    assert split_frontmatter("---\r\ntitle: A\r\n---\r\nbody") == ({"title": "A"}, "body")


def test_parse_note_fields_and_links():
    text = (
        "---\n"
        "title: Alpha plan\n"
        "type: page\n"
        "artifactType: decision\n"
        "source: manual\n"
        "status: open\n"
        "tags: [roadmap, Q4]\n"
        "created: 2026-10-01\n"
        "updated: 2026-10-02\n"
        "related:\n- '[[20-contexts/work/b]]'\n"
        "parent: '[[20-contexts/work/p]]'\n"
        "---\n"
        "intro line\n"
        "see [[20-contexts/work/c|C note]] and [[d#Heading]] #launch\n"
        "![[90-meta/assets/x.png]] and ![[embedded-note]] and [[#local]]\n"
    )
    e = parse_note("20-contexts/work/alpha.md", text, mtime_ns=5, size=len(text))
    assert e.path == "20-contexts/work/alpha.md"
    assert e.title == "Alpha plan"
    assert e.context == "work"
    assert (e.type, e.artifact_type, e.source, e.status) == ("page", "decision", "manual", "open")
    assert e.tags == ("roadmap", "Q4")
    assert e.hashtags == ("launch",)
    assert (e.created, e.updated) == ("2026-10-01", "2026-10-02")
    assert (e.mtime_ns, e.size) == (5, len(text))
    line = "see [[20-contexts/work/c|C note]] and [[d#Heading]] #launch"
    embed_line = "![[90-meta/assets/x.png]] and ![[embedded-note]] and [[#local]]"
    assert e.links == (
        OutLink("20-contexts/work/b.md", "related", 0.7, ""),
        OutLink("20-contexts/work/p.md", "wikilink", 1.0, ""),
        OutLink("20-contexts/work/c.md", "wikilink", 0.5, line),
        OutLink("d.md", "wikilink", 0.5, line),
        OutLink("embedded-note.md", "wikilink", 0.5, embed_line),
    )


def test_parse_note_defaults_without_frontmatter():
    e = parse_note("10-daily/2026-10-09.md", "just #Ops text #ops", mtime_ns=1, size=19)
    assert e.title == "2026-10-09"
    assert e.context == ""
    assert e.tags == ()
    assert e.hashtags == ("ops",)
    assert e.links == ()
    assert (e.type, e.status, e.created, e.updated) == (None, None, None, None)


def test_parse_note_context_falls_back_to_frontmatter_outside_contexts():
    e = parse_note(
        "00-inbox/raw/manual/j.md", "---\ncontext: work\n---\nx", mtime_ns=1, size=1
    )
    assert e.context == "work"
    e2 = parse_note("30-cross-context/people/alex.md", "x", mtime_ns=1, size=1)
    assert e2.context == ""


def test_parse_note_tolerates_odd_frontmatter_values():
    text = "---\ntitle: ''\ntags: solo\nrelated: '[[20-contexts/work/b]]'\n---\nbody"
    e = parse_note("20-contexts/work/odd.md", text, mtime_ns=1, size=1)
    assert e.title == "odd"  # empty title falls back to stem
    assert e.tags == ()  # non-list tags ignored (same as graph.py today)
    assert e.links == ()  # non-list related ignored


def test_snippet_is_stripped_and_capped():
    long_line = "   " + "x" * 300 + " [[20-contexts/work/b]]"
    e = parse_note("20-contexts/work/a.md", long_line, mtime_ns=1, size=1)
    assert e.links[0].snippet == long_line.strip()[:SNIPPET_MAX]
    assert len(e.links[0].snippet) == SNIPPET_MAX


def test_hashtag_regex_matches_notes_manual():
    from ghostbrain.api.repo.notes_manual import _TAG_RE

    assert HASHTAG_RE.pattern == _TAG_RE.pattern
    assert HASHTAG_RE.flags == _TAG_RE.flags
