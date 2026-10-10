"""Live ```query``` blocks (smart templates C2): grammar and runner."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from ghostbrain.templates.query import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_QUERY_CHARS,
    MAX_QUERY_LINES,
    Mention,
    Query,
    parse_query_block,
)

TODAY = date(2026, 10, 10)


def _parse(text: str):
    return parse_query_block(text, today=TODAY)


def _codes(diags):
    return [(d.line, d.col, d.severity, d.code) for d in diags]


def test_one_on_one_block_parses():
    q, diags = _parse(
        'type: action_item\nmentions: "[[30-cross-context/people/alex]]"\n'
        "status: open\nsort: created desc\n"
    )
    assert diags == []
    assert q == Query(
        type="action_item",
        mentions=Mention("30-cross-context/people/alex.md", "alex"),
        status="open",
        sort="created",
        descending=True,
        limit=DEFAULT_LIMIT,
    )


def test_defaults_comments_quotes_and_case():
    q, diags = _parse("# open decisions\n\n  Type: 'Decision'\nCONTEXT: \"Work\"\n")
    assert diags == []
    assert q == Query(type="decision", context="work")
    assert (q.sort, q.descending, q.limit) == ("created", True, 20)


@pytest.mark.parametrize("value, expected", [
    ("Alex", Mention("Alex.md", "Alex")),
    ("@Alex", Mention("Alex.md", "Alex")),
    ('"[[Alex]]"', Mention("Alex.md", "Alex")),
    ("[[30-cross-context/people/alex|@Alex]]", Mention("30-cross-context/people/alex.md", "Alex")),
    ("[[30-cross-context/people/alex#Notes]]", Mention("30-cross-context/people/alex.md", "alex")),
])
def test_mentions_forms(value, expected):
    q, diags = _parse(f"mentions: {value}")
    assert diags == []
    assert q.mentions == expected


def test_tag_and_status_are_normalised():
    q, diags = _parse("tag: #Roadmap\nstatus: Open")
    assert diags == []
    assert (q.tag, q.status) == ("roadmap", "open")


@pytest.mark.parametrize("value, expected", [
    ("7d", date(2026, 10, 3)),
    ("2w", date(2026, 9, 26)),
    ("0d", TODAY),
    ("2026-10-01", date(2026, 10, 1)),
])
def test_since_forms(value, expected):
    q, diags = _parse(f"type: decision\nsince: {value}")
    assert diags == []
    assert q.since == expected


def test_sort_and_limit():
    q, diags = _parse("type: decision\nsort: updated asc\nlimit: 5")
    assert diags == []
    assert (q.sort, q.descending, q.limit) == ("updated", False, 5)
    q, _ = _parse("type: decision\nsort: Updated")
    assert (q.sort, q.descending) == ("updated", True)


def test_limit_over_the_cap_is_capped_with_a_warning():
    q, diags = _parse("type: decision\nlimit: 999999")
    assert q is not None and q.limit == MAX_LIMIT == 100
    assert _codes(diags) == [(2, 8, "warning", "limit-capped")]


@pytest.mark.parametrize("text, expected", [
    ("type: decision\nowner: alex", [(2, 1, "error", "unknown-key")]),
    ("type: decision\ntype: meeting", [(2, 1, "error", "duplicate-key")]),
    ("type decision", [(1, 1, "error", "syntax")]),
    ("type:", [(1, 6, "error", "empty-value")]),
    ("", [(1, 1, "error", "empty-query")]),
    ("# only a comment\n", [(1, 1, "error", "empty-query")]),
    ("since: yesterday", [(1, 8, "error", "bad-value")]),
    ("since: 2026-13-40", [(1, 8, "error", "bad-value")]),
    ("sort: title", [(1, 7, "error", "bad-value")]),
    ("limit: 0", [(1, 8, "error", "bad-value")]),
    ("limit: ten", [(1, 8, "error", "bad-value")]),
    ("status: not done", [(1, 9, "error", "bad-value")]),
    ("mentions: [[90-meta/assets/x.png]]", [(1, 11, "error", "bad-value")]),
    ("mentions: Alex [[b]]", [(1, 11, "error", "bad-value")]),
    ('mentions: "{{person.link}}"', [(1, 11, "error", "unresolved-placeholder")]),
    ("  tag: '#'", [(1, 8, "error", "bad-value")]),
])
def test_errors_carry_line_and_column(text, expected):
    q, diags = _parse(text)
    assert q is None
    assert _codes(diags) == expected


def test_unknown_key_message_lists_the_keys():
    _, diags = _parse("owner: alex")
    assert "use one of: type, context, tag, mentions, status, since, sort, limit" in diags[0].message


def test_size_caps():
    q, diags = _parse("type: decision\n" + "#\n" * MAX_QUERY_LINES)
    assert q is None and [d.code for d in diags] == ["query-too-long"]
    q, diags = _parse("type: " + "x" * MAX_QUERY_CHARS)
    assert q is None and [d.code for d in diags] == ["query-too-long"]
    q, diags = _parse("type: " + "x" * 201)
    assert q is None and [d.code for d in diags] == ["value-too-long"]


def test_rendered_one_on_one_starter_query_parses():
    """The C1 starter's fence, after rendering, is a valid C2 query."""
    from ghostbrain.templates.parse import parse_template
    from ghostbrain.templates.render import RenderEnv, render
    from ghostbrain.templates.starters import STARTER_TEMPLATES

    env = RenderEnv(now=datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2))),
                    default_context="work", contexts=("work", "personal"))
    template = parse_template(STARTER_TEMPLATES["one-on-one.md"], "one-on-one").template
    body = render(template, {"person": "Alex"}, env).body
    fences = re.findall(r"^```query\n(.*?)^```", body, flags=re.MULTILINE | re.DOTALL)
    assert len(fences) == 1
    q, diags = _parse(fences[0])
    assert diags == []
    assert q == Query(type="action_item", mentions=Mention("Alex.md", "Alex"), status="open")


import os
from pathlib import Path

from ghostbrain.templates.query import QueryRow, QueryRun, run_query
from ghostbrain.vault_index.links import LinkIndex
from ghostbrain.vault_write.etag import compute_etag

AI = "20-contexts/work/calendar/artifacts/action_items"
PEOPLE = "30-cross-context/people"
OLD_MTIME = 1_700_000_000  # 2023-11-14


def _ts(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp())


def _note(root: Path, rel: str, text: str, mtime: int = OLD_MTIME) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


def _item(title: str, *, created: str = "2026-10-01T09:00:00+00:00", status: str | None = None,
          body: str = "") -> str:
    """An action item shaped like worker/extractor.py writes them."""
    lines = ["---", "type: artifact", "artifactType: action_item", f"created: '{created}'"]
    if status is not None:
        lines.append(f"status: {status}")
    lines += ["---", "", f"# {title}", "", body or f"{title}.", ""]
    return "\n".join(lines)


def _index(root: Path) -> LinkIndex:
    index = LinkIndex(root, refresh_interval=0)
    index.refresh()
    return index


def _run(root: Path, text: str, **kw) -> QueryRun:
    q, diags = parse_query_block(text, today=TODAY)
    assert q is not None, diags
    return run_query(q, _index(root), **kw)


def _paths(run: QueryRun) -> list[str]:
    return [r.path for r in run.rows]


def test_type_matches_artifact_type_or_type(tmp_path):
    _note(tmp_path, f"{AI}/a.md", _item("Send the budget"))
    _note(tmp_path, "20-contexts/work/meetings/m.md", "---\ntype: meeting\n---\n# Planning\n")
    _note(tmp_path, "20-contexts/work/d.md", "---\ntype: artifact\nartifactType: decision\n---\nx")
    assert _paths(_run(tmp_path, "type: action_item")) == [f"{AI}/a.md"]
    assert _paths(_run(tmp_path, "type: meeting")) == ["20-contexts/work/meetings/m.md"]
    assert len(_run(tmp_path, "type: artifact").rows) == 2


def test_open_includes_notes_without_status_and_excludes_done_or_closed(tmp_path):
    _note(tmp_path, f"{AI}/none.md", _item("No status", created="2026-10-04"))
    _note(tmp_path, f"{AI}/open.md", _item("Open", status="open", created="2026-10-03"))
    _note(tmp_path, f"{AI}/done.md", _item("Done", status="Done", created="2026-10-02"))
    _note(tmp_path, f"{AI}/closed.md", _item("Closed", status="closed", created="2026-10-01"))
    _note(tmp_path, f"{AI}/blocked.md", _item("Blocked", status="blocked", created="2026-09-30"))
    assert _paths(_run(tmp_path, "type: action_item\nstatus: open")) == [
        f"{AI}/none.md", f"{AI}/open.md", f"{AI}/blocked.md",
    ]
    assert _paths(_run(tmp_path, "type: action_item\nstatus: done")) == [f"{AI}/done.md"]


def test_context_and_tag(tmp_path):
    _note(tmp_path, "20-contexts/work/a.md", "---\ntags: [Roadmap]\n---\nx")
    _note(tmp_path, "20-contexts/personal/b.md", "plan #roadmap")
    _note(tmp_path, "20-contexts/personal/c.md", "nothing")
    assert sorted(_paths(_run(tmp_path, "tag: roadmap"))) == [
        "20-contexts/personal/b.md", "20-contexts/work/a.md",
    ]
    assert sorted(_paths(_run(tmp_path, "context: personal"))) == [
        "20-contexts/personal/b.md", "20-contexts/personal/c.md",
    ]


def _mention_vault(root: Path) -> None:
    _note(root, f"{PEOPLE}/alex.md", "---\ntitle: Alex\n---\nperson page")
    _note(root, f"{AI}/link.md", _item("Linked", created="2026-10-05",
                                       body="ask [[30-cross-context/people/alex|@Alex]]"))
    _note(root, f"{AI}/bare.md", _item("Bare link", created="2026-10-04", body="ask [[alex]]"))
    _note(root, f"{AI}/text.md", _item("Text only", created="2026-10-03", body="Alex to send the numbers."))
    _note(root, f"{AI}/longer.md", _item("Other name", created="2026-10-02", body="Alexander will check."))
    _note(root, f"{AI}/fence.md", _item("Fence only", created="2026-10-01",
                                        body="```query\nmentions: Alex\n```"))
    _note(root, f"{AI}/nobody.md", _item("Nobody", created="2026-09-30"))


def test_mentions_matches_links_then_body_text(tmp_path):
    _mention_vault(tmp_path)
    expected = [f"{AI}/link.md", f"{AI}/bare.md", f"{AI}/text.md"]
    assert _paths(_run(tmp_path, 'type: action_item\nmentions: "[[30-cross-context/people/alex]]"')) == expected
    assert _paths(_run(tmp_path, "type: action_item\nmentions: Alex")) == expected
    assert _paths(_run(tmp_path, 'type: action_item\nmentions: "[[Alex]]"')) == expected


def test_mentions_excludes_the_person_page_itself(tmp_path):
    _note(tmp_path, f"{PEOPLE}/alex.md", "---\ntitle: Alex\n---\nAlex works on [[alex]]")
    _note(tmp_path, "20-contexts/work/n.md", "met Alex today")
    assert _paths(_run(tmp_path, "mentions: Alex")) == ["20-contexts/work/n.md"]


def test_mentions_a_name_with_no_page_falls_back_to_text(tmp_path):
    _note(tmp_path, f"{AI}/a.md", _item("Call", created="2026-10-02", body="Robin to call the vendor"))
    _note(tmp_path, f"{AI}/b.md", _item("Ask", created="2026-10-01", body="ask [[Robin]] later"))
    _note(tmp_path, f"{AI}/c.md", _item("Robinson", created="2026-09-30", body="Robinson owns it"))
    assert _paths(_run(tmp_path, 'type: action_item\nmentions: "[[Robin]]"')) == [f"{AI}/a.md", f"{AI}/b.md"]


def test_mentions_value_is_literal_not_a_pattern(tmp_path):
    _note(tmp_path, "20-contexts/work/a.md", "abc and a.c")
    _note(tmp_path, "20-contexts/work/b.md", "abc only")
    assert _paths(_run(tmp_path, "mentions: a.c")) == ["20-contexts/work/a.md"]


def test_since_uses_created_then_file_time(tmp_path):
    _note(tmp_path, f"{AI}/new.md", _item("New", created="2026-10-08"))
    _note(tmp_path, f"{AI}/old.md", _item("Old", created="2026-09-01"))
    _note(tmp_path, "20-contexts/work/plain.md", "no frontmatter", mtime=_ts(2026, 10, 9))
    _note(tmp_path, "20-contexts/work/stale.md", "no frontmatter", mtime=_ts(2026, 1, 1))
    assert _paths(_run(tmp_path, "since: 7d")) == ["20-contexts/work/plain.md", f"{AI}/new.md"]


def test_sort_orders_and_mixed_date_formats(tmp_path):
    w = "20-contexts/work"
    _note(tmp_path, f"{w}/a.md", "---\ncreated: 2026-10-02\nupdated: 2026-10-09T08:00:00Z\n---\na")
    _note(tmp_path, f"{w}/b.md", "---\ncreated: 2026-10-03 10:00:00\n---\nb")
    _note(tmp_path, f"{w}/c.md", "---\ncreated: 'not a date'\n---\nc", mtime=_ts(2026, 9, 1))
    _note(tmp_path, f"{w}/d.md", "---\ncreated: '2026-10-01T23:00:00-05:00'\n---\nd")
    assert _paths(_run(tmp_path, "context: work")) == [f"{w}/b.md", f"{w}/d.md", f"{w}/a.md", f"{w}/c.md"]
    assert _paths(_run(tmp_path, "context: work\nsort: created asc")) == [
        f"{w}/c.md", f"{w}/a.md", f"{w}/d.md", f"{w}/b.md",
    ]
    assert _paths(_run(tmp_path, "context: work\nsort: updated")) == [
        f"{w}/a.md", f"{w}/c.md", f"{w}/b.md", f"{w}/d.md",
    ]


def test_limit_and_cap(tmp_path):
    for i in range(130):
        _note(tmp_path, f"20-contexts/work/n{i:03}.md", "x")
    assert len(_run(tmp_path, "context: work").rows) == DEFAULT_LIMIT
    run = _run(tmp_path, "context: work\nlimit: 500")
    assert len(run.rows) == MAX_LIMIT
    assert run.rows[0].path == "20-contexts/work/n000.md"  # equal times → path order


def test_rows_carry_title_snippet_fresh_status_and_etag(tmp_path):
    rel = f"{AI}/send-the-budget-1a2b3c4d.md"
    p = _note(tmp_path, rel, _item("Send Alex the budget", body="Alex to review the numbers by Friday."))
    _note(tmp_path, "20-contexts/work/titled.md",
          "---\ntitle: Planning\ncreated: '2026-09-01'\n---\n# Ignored heading\n\nfirst line")
    _note(tmp_path, "20-contexts/work/bare-stem.md", "```\ncode\n```\n\n## Sub\nprose here")
    rows = {r.path: r for r in _run(tmp_path, "context: work").rows}
    item = rows[rel]
    assert item == QueryRow(
        path=rel, title="Send Alex the budget", context="work", status=None,
        created="2026-10-01T09:00:00+00:00", snippet="Alex to review the numbers by Friday.",
        etag=compute_etag(p.read_bytes()),
    )
    assert item.to_json() == {
        "path": rel, "title": "Send Alex the budget", "context": "work", "status": None,
        "created": "2026-10-01T09:00:00+00:00", "snippet": "Alex to review the numbers by Friday.",
        "etag": compute_etag(p.read_bytes()),
    }
    assert (rows["20-contexts/work/titled.md"].title, rows["20-contexts/work/titled.md"].snippet) == (
        "Planning", "first line")
    assert (rows["20-contexts/work/bare-stem.md"].title, rows["20-contexts/work/bare-stem.md"].snippet) == (
        "bare-stem", "prose here")


def test_row_status_and_etag_are_read_from_the_file_not_the_index(tmp_path):
    p = _note(tmp_path, f"{AI}/a.md", _item("A"))
    q, _ = parse_query_block("type: action_item", today=TODAY)
    index = _index(tmp_path)
    p.write_text(_item("A", status="done"), encoding="utf-8")  # changed after indexing
    row = run_query(q, index).rows[0]
    assert row.status == "done"
    assert row.etag == compute_etag(p.read_bytes())


def test_note_deleted_after_indexing_is_skipped(tmp_path):
    gone = _note(tmp_path, f"{AI}/gone.md", _item("Gone", created="2026-10-02"))
    _note(tmp_path, f"{AI}/kept.md", _item("Kept", created="2026-10-01"))
    q, _ = parse_query_block("type: action_item", today=TODAY)
    index = _index(tmp_path)
    gone.unlink()
    assert _paths(run_query(q, index)) == [f"{AI}/kept.md"]


def test_text_scan_is_bounded_and_reports_partial(tmp_path):
    for i in range(10):
        _note(tmp_path, f"20-contexts/work/n{i}.md", "nothing here")
    run = _run(tmp_path, "mentions: Alex", max_text_reads=3)
    assert run.rows == () and run.partial is True
    ticks = iter([0.0] + [5.0] * 20)
    run = _run(tmp_path, "mentions: Alex", clock=lambda: next(ticks))
    assert run.rows == () and run.partial is True
    assert _run(tmp_path, "mentions: Alex").partial is False


import time

from ghostbrain.templates.query import _body_text, _first_heading


def test_first_heading_strips_closing_hashes():
    assert _first_heading("# Send Alex the budget ##\n") == "Send Alex the budget"
    assert _first_heading("intro\n#\tRobin's notes\t#\n") == "Robin's notes"
    assert _first_heading("## Sub\n#nospace\n") is None


def test_first_heading_is_linear_on_hostile_lines():
    hostile = "# a" + " #" * 100_000 + "b"  # ~200k chars on one line
    start = time.perf_counter()
    assert _first_heading(hostile + "\n# Real title") == "Real title"
    assert time.perf_counter() - start < 1.0


def test_body_text_strips_query_fences_and_unclosed_runs_to_end(tmp_path):
    _note(tmp_path, "n.md", "a\n```query\nmentions: Alex\n```\nb\n```python\nx\n```\nc\n```query\nmentions: Robin\n")
    assert _body_text(tmp_path, "n.md") == "a\n\nb\n```python\nx\n```\nc\n"


def test_body_text_is_linear_on_unclosed_fences(tmp_path):
    _note(tmp_path, "n.md", "keep Alex\n" + "```query\n" * 22_000)  # ~200k chars, no closing fence
    start = time.perf_counter()
    assert _body_text(tmp_path, "n.md") == "keep Alex\n"
    assert time.perf_counter() - start < 1.0
