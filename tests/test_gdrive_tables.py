from __future__ import annotations

from ghostbrain.connectors.gdrive import tables
from ghostbrain.connectors.gdrive.tables import Tab


def test_markdown_table_header_escaping_and_trim():
    out = tables.markdown_table([
        ["Name", "Note", None, ""],
        ["a|b", "line1\nline2", None, ""],
        [3, 4.5, None, None],
        [None, "", None, None],
    ])
    assert out.splitlines() == [
        "| Name | Note |",
        "| --- | --- |",
        "| a\\|b | line1<br>line2 |",
        "| 3 | 4.5 |",
    ]


def test_markdown_table_pads_ragged_rows():
    assert tables.markdown_table([["a", "b", "c"], ["x"]]).splitlines()[-1] == "| x |  |  |"


def test_markdown_table_empty():
    assert tables.markdown_table([[None, ""], []]) == ""


def test_render_tab_row_and_col_caps():
    rows = [[f"c{j}" for j in range(tables.MAX_COLS + 3)] for _ in range(tables.MAX_ROWS + 10)]
    text, cut = tables.render_tab(Tab("Big", rows))
    lines = text.splitlines()
    assert lines[0] == "## Big"
    assert cut is True
    assert "_…truncated at 5,000 rows_" in lines
    assert "_…truncated at 50 columns_" in lines
    assert lines[2].count(" | ") == tables.MAX_COLS - 1
    assert sum(1 for line in lines if line.startswith("| c0 ")) == tables.MAX_ROWS


def test_render_tab_flags_from_caller():
    text, cut = tables.render_tab(Tab("T", [["a"]], more_rows=True))
    assert cut and text.endswith("_…truncated at 5,000 rows_")


def test_render_tables_skips_empty_and_caps_tabs():
    tabs = [Tab("Empty", [])] + [Tab(f"T{i}", [["v"]]) for i in range(tables.MAX_TABS + 2)]
    text, cut = tables.render_tables(tabs, extra_tabs=3)
    assert "## Empty" not in text
    assert text.count("\n## ") + text.startswith("## ") == tables.MAX_TABS
    assert text.endswith("_…5 more tabs_")
    assert cut


def test_max_cols_a1_matches_max_cols():
    n = 0
    for ch in tables.MAX_COLS_A1:
        n = n * 26 + (ord(ch) - 64)
    assert n == tables.MAX_COLS
