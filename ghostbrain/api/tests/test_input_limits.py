"""Long-input limits: MCP `ask`/`search` forward free-text questions to
/v1/answer and /v1/search — a 500-char cap 422s real questions."""
from ghostbrain.api.models.answer import AnswerRequest
from ghostbrain.api.models.search import SearchRequest


def test_answer_accepts_long_question():
    assert AnswerRequest(q="x" * 20_000).q


def test_search_accepts_long_query():
    assert SearchRequest(q="x" * 2_000).q
