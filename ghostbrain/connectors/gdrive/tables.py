"""Rows of cell values → Markdown tables, with the size caps from the spec.
Shared by Google Sheets (Sheets API values), uploaded .xlsx (openpyxl) and
tables inside Google Docs (Docs API fallback)."""
from __future__ import annotations

import dataclasses

MAX_ROWS = 5000
MAX_COLS = 50
MAX_COLS_A1 = "AX"  # column letter of MAX_COLS
MAX_TABS = 50


@dataclasses.dataclass
class Tab:
    name: str
    rows: list[list]
    more_rows: bool = False
    more_cols: bool = False


def _cell(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\n", "<br>")
    return text.replace("|", "\\|")


def _trimmed(rows: list[list]) -> tuple[list[list[str]], int]:
    cells = [[_cell(v) for v in row] for row in rows]
    while cells and not any(c.strip() for c in cells[-1]):
        cells.pop()
    width = 0
    for row in cells:
        for i in range(len(row) - 1, -1, -1):
            if row[i].strip():
                width = max(width, i + 1)
                break
    return [(row + [""] * width)[:width] for row in cells], width


def markdown_table(rows: list[list]) -> str:
    cells, width = _trimmed(rows)
    if not cells or width == 0:
        return ""
    lines = [
        "| " + " | ".join(cells[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in cells[1:]]
    return "\n".join(lines)


def render_tab(tab: Tab) -> tuple[str, bool]:
    more_rows = tab.more_rows or len(tab.rows) > MAX_ROWS
    kept = tab.rows[:MAX_ROWS]
    more_cols = tab.more_cols or any(len(r) > MAX_COLS for r in kept)
    table = markdown_table([list(r)[:MAX_COLS] for r in kept])
    if not table:
        return "", False
    parts = [f"## {tab.name}", "", table]
    notes = []
    if more_rows:
        notes.append(f"_…truncated at {MAX_ROWS:,} rows_")
    if more_cols:
        notes.append(f"_…truncated at {MAX_COLS} columns_")
    if notes:
        parts += [""] + notes
    return "\n".join(parts), bool(notes)


def render_tables(tabs: list[Tab], *, extra_tabs: int = 0) -> tuple[str, bool]:
    """Render up to MAX_TABS non-empty tabs. ``extra_tabs`` counts tabs the
    caller didn't even fetch (beyond MAX_TABS)."""
    parts: list[str] = []
    truncated = False
    extra = extra_tabs
    for tab in tabs:
        if len(parts) == MAX_TABS:
            extra += 1
            continue
        text, cut = render_tab(tab)
        if text:
            parts.append(text)
            truncated |= cut
    if extra:
        parts.append(f"_…{extra} more tabs_")
        truncated = True
    return "\n\n".join(parts), truncated
