# tests/test_mcp_tools.py
from ghostbrain.mcp import tools


class FakeClient:
    def __init__(self, answer=None, search=None, note=None):
        self._answer, self._search, self._note = answer, search, note
        self.calls = []

    def answer(self, q, limit=8):
        self.calls.append(("answer", q, limit))
        return self._answer

    def search(self, q, limit=10):
        self.calls.append(("search", q, limit))
        return self._search

    def get_note(self, path):
        self.calls.append(("get_note", path))
        return self._note


def test_ask_includes_answer_and_source_paths():
    client = FakeClient(answer={
        "answer": "Use sonnet.",
        "sources": [
            {"path": "20-contexts/sanlam/a.md", "title": "A", "score": 0.81, "snippet": "..."},
            {"path": "20-contexts/codeship/b.md", "title": "B", "score": 0.77, "snippet": "..."},
        ],
    })
    out = tools.ask(client, "which model?", limit=5)
    assert "Use sonnet." in out
    assert "20-contexts/sanlam/a.md" in out
    assert "20-contexts/codeship/b.md" in out
    assert client.calls == [("answer", "which model?", 5)]


def test_ask_reports_empty_answer_error():
    client = FakeClient(answer={"answer": "", "sources": [], "error": "LLMTimeout: timed out"})
    out = tools.ask(client, "q")
    assert "LLMTimeout" in out


def test_search_lists_ranked_hits():
    client = FakeClient(search={"total": 1, "items": [
        {"path": "p.md", "title": "T", "score": 0.9, "snippet": "snip"},
    ]})
    out = tools.search(client, "x", limit=3)
    assert "p.md" in out
    assert "T" in out
    assert "snip" in out
    assert client.calls == [("search", "x", 3)]


def test_search_empty_says_no_matches():
    client = FakeClient(search={"total": 0, "items": []})
    out = tools.search(client, "x")
    assert "no" in out.lower()


def test_get_note_renders_title_and_body():
    client = FakeClient(note={"path": "p.md", "title": "Title", "body": "Body text", "frontmatter": {"context": "sanlam"}})
    out = tools.get_note(client, "p.md")
    assert "Title" in out
    assert "Body text" in out
    assert "p.md" in out


def test_write_doc_returns_path():
    class FakeClient:
        def write_doc(self, title, html):
            return {"path": "20-contexts/generated-docs/20260701T120000-x.html", "title": title}

    from ghostbrain.mcp import tools

    out = tools.write_doc(FakeClient(), "X", "<html></html>")
    assert out == "20-contexts/generated-docs/20260701T120000-x.html"


def test_write_doc_error_is_returned_not_raised():
    class BoomClient:
        def write_doc(self, title, html):
            raise RuntimeError("sidecar down")

    from ghostbrain.mcp import tools

    out = tools.write_doc(BoomClient(), "X", "<html></html>")
    assert "could not save" in out.lower()
