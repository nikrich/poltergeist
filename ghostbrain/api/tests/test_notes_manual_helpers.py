"""Pure helpers for manual jot id, slug, and tag extraction."""
from datetime import datetime, timezone

import pytest

from ghostbrain.api.repo.notes_manual import (
    extract_tags,
    make_jot_id,
    make_slug,
    title_from_body,
)


def test_make_slug_lowercases_and_collapses_non_alnum():
    assert make_slug("Ghostbrain Jot Idea!") == "ghostbrain-jot-idea"


def test_make_slug_truncates_to_32_chars():
    s = make_slug("a" * 100)
    assert len(s) == 32
    assert s == "a" * 32


def test_make_slug_strips_leading_and_trailing_dashes():
    assert make_slug("!!hello world!!") == "hello-world"


def test_make_slug_empty_falls_back_to_untitled():
    assert make_slug("") == "untitled"
    assert make_slug("###") == "untitled"


def test_make_jot_id_format():
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    jot_id = make_jot_id("Ghostbrain idea", when=when)
    assert jot_id == "manual-20260514T093015-ghostbrain-idea"


def test_make_jot_id_rejects_naive_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_jot_id("Ghostbrain idea", when=datetime(2026, 5, 14, 9, 30, 15))


def test_extract_tags_finds_hashtags():
    body = "thinking about #ui and the #ascp-wizard flow #idea"
    assert extract_tags(body) == ["ui", "ascp-wizard", "idea"]


def test_extract_tags_deduplicates_and_preserves_first_order():
    body = "#a #b #a"
    assert extract_tags(body) == ["a", "b"]


def test_extract_tags_ignores_in_word_hashes():
    # `colour#fff` is not a tag — must be whitespace-preceded.
    assert extract_tags("colour#fff is bold") == []


def test_extract_tags_does_not_end_with_hyphen():
    assert extract_tags("done #todo- next") == ["todo"]


def test_title_from_body_uses_first_nonempty_line():
    assert title_from_body("\n\nfirst line\nsecond\n") == "first line"


def test_title_from_body_strips_markdown_headers():
    assert title_from_body("# my heading\nbody") == "my heading"


def test_title_from_body_truncates_long_titles():
    assert title_from_body("a" * 200) == "a" * 80
