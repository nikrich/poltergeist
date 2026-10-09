"""Byte-exact frontmatter text ops for the vault write path (spec B1)."""
from __future__ import annotations

import pytest

from ghostbrain.vault_write import (
    DELETE_FIELD,
    MalformedNote,
    apply_fields,
    find_key_block,
    lines_of,
    load_metadata,
    parse_note,
    splice_body,
)

AWKWARD = (
    "---\n"
    "# leading comment\n"
    'title: "Quoted: title"   # trailing comment\n'
    "zeta: 1\n"
    "alpha: 'it''s'\n"
    "unicode: café ✓ 日本\n"
    "tags:\n"
    "  - one\n"
    "  - two\n"
    "nested:\n"
    "  k: v\n"
    "updated: 2026-01-01T00:00:00+00:00\n"
    "empty:\n"
    "---\n"
    "\n"
    "old body\n"
)
CRLF = "---\r\ntitle: a\r\nzeta: 1\r\n---\r\n\r\nbody line\r\n"
BOM = "\ufeff---\ntitle: a\n---\n\nbody\n"
NO_TRAILING_NL = "---\ntitle: a\n---\n\nbody without newline"
FENCE_AT_EOF = "---\ntitle: a\n---"
LEADING_BLANKS = "\n\n---\ntitle: a\n---\nbody right after fence\n"
EMPTY_FM = "---\n---\nbody\n"
NO_FM = "just a body\nsecond line\n"
UNTERMINATED = "---\n\nA horizontal rule opened this note.\n"

ALL_SAMPLES = [AWKWARD, CRLF, BOM, NO_TRAILING_NL, FENCE_AT_EOF, LEADING_BLANKS, EMPTY_FM, NO_FM, UNTERMINATED, ""]
WITH_FM = [AWKWARD, CRLF, BOM, NO_TRAILING_NL, LEADING_BLANKS, EMPTY_FM]


def _changed_lines(old: str, new: str) -> list[int]:
    a, b = old.split("\n"), new.split("\n")
    assert len(a) == len(b), "line count changed"
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y]


@pytest.mark.parametrize("text", ALL_SAMPLES)
def test_parse_render_round_trip_is_identity(text):
    assert parse_note(text).render() == text


def test_parse_splits_awkward_note():
    p = parse_note(AWKWARD)
    assert p.has_frontmatter
    assert p.fm_head == "---\n"
    assert p.fm_inner.startswith("# leading comment\n")
    assert p.fm_close == "---\n"
    assert p.gap == "\n"
    assert p.body == "old body\n"
    assert p.eol == "\n"


def test_parse_keeps_bom_out_of_head_and_body():
    p = parse_note(BOM)
    assert p.bom == "\ufeff"
    assert p.frontmatter_text.startswith("\ufeff---\n")
    assert p.body == "body\n"


def test_parse_detects_crlf():
    assert parse_note(CRLF).eol == "\r\n"


def test_unterminated_fence_is_not_frontmatter():
    p = parse_note(UNTERMINATED)
    assert not p.has_frontmatter
    assert p.body == UNTERMINATED


def test_leading_blank_lines_belong_to_the_frontmatter_head():
    p = parse_note(LEADING_BLANKS)
    assert p.has_frontmatter
    assert p.fm_head == "\n\n---\n"
    assert p.gap == ""
    assert p.body == "body right after fence\n"


@pytest.mark.parametrize("text", WITH_FM)
def test_splice_keeps_frontmatter_bytes_identical(text):
    before = parse_note(text)
    after = splice_body(before, "# new\n\nreplaced body", ensure_newline=True)
    assert after.render().startswith(before.frontmatter_text)
    assert after.frontmatter_text == before.frontmatter_text
    assert after.render().endswith("replaced body" + before.eol)


def test_splice_awkward_note_exact_bytes():
    out = splice_body(parse_note(AWKWARD), "new body", ensure_newline=True).render()
    assert out == AWKWARD.replace("old body\n", "new body\n")


def test_splice_converts_body_to_crlf_on_crlf_file():
    out = splice_body(parse_note(CRLF), "x\ny", ensure_newline=True).render()
    assert out == "---\r\ntitle: a\r\nzeta: 1\r\n---\r\n\r\nx\r\ny\r\n"


def test_splice_collapses_trailing_newlines_to_one():
    out = splice_body(parse_note(AWKWARD), "x\n\n\n", ensure_newline=True).render()
    assert out.endswith("\n\nx\n")


def test_splice_without_ensure_newline_is_verbatim():
    out = splice_body(parse_note(NO_FM), "<p>x</p>", ensure_newline=False).render()
    assert out == "<p>x</p>"


def test_splice_fence_at_eof_adds_eol_and_blank_line():
    out = splice_body(parse_note(FENCE_AT_EOF), "x", ensure_newline=True).render()
    assert out == "---\ntitle: a\n---\n\nx\n"


def test_splice_keeps_body_directly_after_fence():
    out = splice_body(parse_note(LEADING_BLANKS), "new", ensure_newline=True).render()
    assert out == "\n\n---\ntitle: a\n---\nnew\n"


def test_splice_no_frontmatter_keeps_bom():
    out = splice_body(parse_note("\ufeffplain\n"), "rewritten", ensure_newline=True).render()
    assert out == "\ufeffrewritten\n"


def test_field_edit_touches_exactly_one_line_and_keeps_inline_comment():
    out = apply_fields(parse_note(AWKWARD), {"title": "New: title"}).render()
    changed = _changed_lines(AWKWARD, out)
    assert len(changed) == 1
    assert out.split("\n")[changed[0]] == "title: 'New: title'   # trailing comment"


def test_field_edit_of_timestamp_rewrites_only_that_line():
    out = apply_fields(parse_note(AWKWARD), {"updated": "2026-10-09T10:00:00+00:00"}).render()
    changed = _changed_lines(AWKWARD, out)
    assert len(changed) == 1
    assert out.split("\n")[changed[0]] == "updated: '2026-10-09T10:00:00+00:00'"


def test_field_edit_unicode_value():
    out = apply_fields(parse_note(AWKWARD), {"unicode": "naïve ✓"}).render()
    assert _changed_lines(AWKWARD, out) == [5]
    assert "unicode: naïve ✓\n" in out


def test_field_edit_null_key_gets_a_value():
    out = apply_fields(parse_note(AWKWARD), {"empty": "now set"}).render()
    assert len(_changed_lines(AWKWARD, out)) == 1
    assert "empty: now set\n---\n" in out


def test_multiline_field_reserialises_only_its_block():
    out = apply_fields(parse_note(AWKWARD), {"tags": ["one", "three"]}).render()
    before = AWKWARD.split("tags:\n")[0]
    after_block = "nested:\n  k: v\n"
    assert out.startswith(before)
    assert out[len(before):].startswith("tags:\n- one\n- three\nnested:\n")
    assert out.split("- three\n", 1)[1] == AWKWARD.split("  - two\n", 1)[1]
    assert after_block in out


def test_missing_key_inserted_before_closing_fence():
    out = apply_fields(parse_note(AWKWARD), {"added": 3}).render()
    assert out == AWKWARD.replace("empty:\n---\n", "empty:\nadded: 3\n---\n")


def test_nested_key_is_not_a_top_level_match():
    out = apply_fields(parse_note(AWKWARD), {"k": 1}).render()
    assert "nested:\n  k: v\n" in out
    assert "empty:\nk: 1\n---\n" in out


def test_unchanged_value_is_byte_identical():
    p = parse_note(AWKWARD)
    assert apply_fields(p, {"zeta": 1, "tags": ["one", "two"]}).render() == AWKWARD


def test_delete_field_removes_block_and_missing_delete_is_noop():
    out = apply_fields(parse_note(AWKWARD), {"tags": DELETE_FIELD, "nope": DELETE_FIELD}).render()
    assert out == AWKWARD.replace("tags:\n  - one\n  - two\n", "")


def test_quoted_key_is_matched():
    text = '---\n"weird key": 1\nother: 2\n---\n\nb\n'
    out = apply_fields(parse_note(text), {"weird key": 5}).render()
    assert out == '---\n"weird key": 5\nother: 2\n---\n\nb\n'


def test_fields_on_crlf_file_use_crlf():
    out = apply_fields(parse_note(CRLF), {"title": "b", "new": 1}).render()
    assert out == "---\r\ntitle: b\r\nzeta: 1\r\nnew: 1\r\n---\r\n\r\nbody line\r\n"


def test_fields_on_file_without_frontmatter_creates_block():
    out = apply_fields(parse_note(NO_FM), {"source": "manual"}).render()
    assert out == "---\nsource: manual\n---\n\njust a body\nsecond line\n"


def test_fields_on_bom_file_keep_bom():
    out = apply_fields(parse_note(BOM), {"title": "b"}).render()
    assert out == "\ufeff---\ntitle: b\n---\n\nbody\n"


def test_fields_on_invalid_yaml_raise():
    bad = "---\ntitle: [unclosed\n---\n\nbody\n"
    with pytest.raises(MalformedNote):
        apply_fields(parse_note(bad), {"title": "x"})


def test_long_value_wraps_like_pyyaml_and_stays_valid():
    long = "word " * 30
    out = apply_fields(parse_note(AWKWARD), {"title": long.strip()}).render()
    assert load_metadata(parse_note(out))["title"] == long.strip()
    assert "# trailing comment" not in out  # a wrapped (multi-line) value replaces the whole line


def test_find_key_block_spans_and_lines_of():
    lines = lines_of(parse_note(AWKWARD).fm_inner)
    assert find_key_block(lines, "tags") == (5, 8)
    assert find_key_block(lines, "zeta") == (2, 3)
    assert find_key_block(lines, "missing") is None
    assert lines_of("a\nb") == ["a\n", "b"]
    assert lines_of("a b\n") == ["a b\n"]  # only \n splits


def test_load_metadata():
    meta = load_metadata(parse_note(AWKWARD))
    assert meta["title"] == "Quoted: title"
    assert meta["alpha"] == "it's"
    assert meta["tags"] == ["one", "two"]
    assert load_metadata(parse_note(NO_FM)) == {}
    assert load_metadata(parse_note(EMPTY_FM)) == {}
    with pytest.raises(MalformedNote):
        load_metadata(parse_note("---\n- a list\n---\n\nb\n"))
