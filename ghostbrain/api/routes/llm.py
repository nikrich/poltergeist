"""POST /v1/llm/run — raw prompt runner (plugins assemble their own context)."""
import logging

from fastapi import APIRouter, HTTPException

from ghostbrain.api.models.llm import LlmRunRequest, LlmRunResponse
from ghostbrain.llm.client import run as llm_run

log = logging.getLogger("ghostbrain.api.llm")

router = APIRouter(prefix="/v1/llm", tags=["llm"])


@router.post("/run", response_model=LlmRunResponse)
def llm_run_endpoint(payload: LlmRunRequest) -> dict:
    if not payload.prompt.strip():
        raise HTTPException(status_code=422, detail="prompt must not be empty")
    try:
        result = llm_run(
            payload.prompt,
            model=payload.model,
            json_schema=payload.jsonSchema,
            system_prompt=payload.system,
            budget_usd=payload.budgetUsd,
            timeout_s=payload.timeoutSeconds,
        )
        return {
            "text": result.text,
            "structured": result.structured,
            "error": None,
            "costUsd": result.cost_usd,
            "durationMs": result.duration_ms,
        }
    except Exception as e:  # noqa: BLE001 — same contract as answer.py
        log.exception("llm run failed")
        return {"text": "", "structured": None, "error": f"{type(e).__name__}: {e}",
                "costUsd": None, "durationMs": None}
