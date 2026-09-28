from __future__ import annotations

from ghostbrain.connectors.gdrive.docs_json import document_to_markdown


def _p(text, style="NORMAL_TEXT", bullet=None, link=None):
    run = {"textRun": {"content": text + "\n", "textStyle": {"link": {"url": link}} if link else {}}}
    para = {"elements": [run], "paragraphStyle": {"namedStyleType": style}}
    if bullet is not None:
        para["bullet"] = {"listId": "l1", "nestingLevel": bullet}
    return {"paragraph": para}


def test_headings_paragraphs_lists_links():
    doc = {"body": {"content": [
        {"sectionBreak": {}},
        _p("Plan", "TITLE"),
        _p("Scope", "HEADING_2"),
        _p("Plain text."),
        _p("one", bullet=0),
        _p("nested", bullet=1),
        _p("site", link="https://x.test"),
        _p(""),
    ]}}
    assert document_to_markdown(doc).split("\n\n") == [
        "# Plan", "## Scope", "Plain text.", "- one", "  - nested", "[site](https://x.test)",
    ]


def test_table_and_soft_line_breaks():
    cell = lambda t: {"content": [_p(t)]}
    doc = {"body": {"content": [
        _p("a\u000bb"),
        {"table": {"tableRows": [
            {"tableCells": [cell("H1"), cell("H2")]},
            {"tableCells": [cell("x"), cell("y|z")]},
        ]}},
    ]}}
    assert document_to_markdown(doc).split("\n\n") == [
        "a\nb", "| H1 | H2 |\n| --- | --- |\n| x | y\\|z |",
    ]
