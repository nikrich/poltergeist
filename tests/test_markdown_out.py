from ghostbrain.connectors.atlassian.markdown_out import to_storage_html


def test_headings_and_paragraphs():
    html = to_storage_html("# Title\n\nbody text")
    assert "<h1>Title</h1>" in html and "<p>body text</p>" in html


def test_tables_extension_enabled():
    html = to_storage_html("| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<table>" in html


def test_fenced_code():
    html = to_storage_html("```\ncode here\n```")
    assert "code here" in html and "<pre>" in html


def test_wikilinks_flattened():
    html = to_storage_html("see [[20-contexts/x/note]]")
    assert "note" in html and "[[" not in html
    html = to_storage_html("see [[20-contexts/x/note|the note]]")
    assert "the note" in html and "[[" not in html
