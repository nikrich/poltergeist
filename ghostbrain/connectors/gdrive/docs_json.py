"""Docs API ``documents.get`` JSON → Markdown. Only used for Google Docs
over Drive's 10 MB export limit; covers headings, paragraphs, bullet
nesting, links, soft line breaks and tables."""
from __future__ import annotations

from ghostbrain.connectors.gdrive.tables import markdown_table

_HEADINGS = {
    "TITLE": "#", "SUBTITLE": "##",
    "HEADING_1": "#", "HEADING_2": "##", "HEADING_3": "###",
    "HEADING_4": "####", "HEADING_5": "#####", "HEADING_6": "######",
}


def _runs(paragraph: dict) -> str:
    parts: list[str] = []
    for el in paragraph.get("elements") or []:
        run = el.get("textRun")
        if not run:
            continue
        text = (run.get("content") or "").replace("\n", "")
        if not text:
            continue
        url = (((run.get("textStyle") or {}).get("link")) or {}).get("url")
        parts.append(f"[{text}]({url})" if url else text)
    return "".join(parts).replace("\u000b", "\n").strip()


def _paragraph(paragraph: dict) -> str:
    text = _runs(paragraph)
    if not text:
        return ""
    style = (paragraph.get("paragraphStyle") or {}).get("namedStyleType", "NORMAL_TEXT")
    if style in _HEADINGS:
        return f"{_HEADINGS[style]} {text}"
    if "bullet" in paragraph:
        level = int(paragraph["bullet"].get("nestingLevel") or 0)
        return "  " * level + "- " + text
    return text


def _table(table: dict) -> str:
    rows = []
    for row in table.get("tableRows") or []:
        rows.append([
            " ".join(_runs(c["paragraph"]) for c in cell.get("content") or [] if "paragraph" in c)
            for cell in row.get("tableCells") or []
        ])
    return markdown_table(rows)


def document_to_markdown(doc: dict) -> str:
    blocks: list[str] = []
    for el in (doc.get("body") or {}).get("content") or []:
        if "paragraph" in el:
            blocks.append(_paragraph(el["paragraph"]))
        elif "table" in el:
            blocks.append(_table(el["table"]))
    return "\n\n".join(b for b in blocks if b)
