"""B3: the MCP write_doc tool says when a document waits for approval."""
from __future__ import annotations

from ghostbrain.mcp import tools


def test_write_doc_says_when_the_doc_waits_for_approval():
    class HeldClient:
        def write_doc(self, title, html):
            return {"path": "20-contexts/generated-docs/x.html", "title": title,
                    "status": "pending", "changeId": "7"}

    out = tools.write_doc(HeldClient(), "X", "<script></script>")
    assert out == (
        "20-contexts/generated-docs/x.html is waiting for the user's approval on the Changes "
        "screen (change #7); it is not in the vault until they approve it."
    )
