"""POST /v1/answer — RAG ask-the-archive."""
import logging

from fastapi import APIRouter, HTTPException

from ghostbrain.api.models.answer import AnswerRequest, AnswerResponse
from ghostbrain.api.repo.answer import answer as repo_answer
from ghostbrain.api.repo.settings import ProviderUnavailable

log = logging.getLogger("ghostbrain.api.answer")

router = APIRouter(prefix="/v1/answer", tags=["answer"])


@router.post("", response_model=AnswerResponse)
def answer(payload: AnswerRequest) -> dict:
    try:
        return repo_answer(q=payload.q, limit=payload.limit)
    except ProviderUnavailable as e:
        raise HTTPException(status_code=412, detail=str(e))
    except Exception as e:  # noqa: BLE001
        # Anything unexpected (model load failure, missing index, etc.) gets
        # caught here so the UI sees a structured error instead of an opaque
        # HTTP 500. The traceback still lands in the sidecar log for debug.
        log.exception("answer endpoint failed for q=%r", payload.q)
        return {
            "query": payload.q,
            "answer": "",
            "sources": [],
            "error": f"{type(e).__name__}: {e}",
        }
