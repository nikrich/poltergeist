"""POST /v1/answer — RAG ask-the-archive."""
from fastapi import APIRouter

from ghostbrain.api.models.answer import AnswerRequest, AnswerResponse
from ghostbrain.api.repo.answer import answer as repo_answer

router = APIRouter(prefix="/v1/answer", tags=["answer"])


@router.post("", response_model=AnswerResponse)
def answer(payload: AnswerRequest) -> dict:
    return repo_answer(q=payload.q, limit=payload.limit)
