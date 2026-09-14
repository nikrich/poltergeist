"""GET /v1/doctor — the first-run checks, for the desktop app to render later."""
from __future__ import annotations

import json

from fastapi import APIRouter

from ghostbrain import doctor

router = APIRouter(prefix="/v1/doctor", tags=["doctor"])


@router.get("")
def get_doctor() -> dict:
    results = doctor.run_checks(doctor.current_platform())
    return json.loads(doctor.to_json(results, platform=doctor.current_platform()))
