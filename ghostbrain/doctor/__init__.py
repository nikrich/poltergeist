"""First-run health checks (`ghostbrain-api doctor`) and their fixes (`setup`).

Every check is a zero-argument function returning a CheckResult and MUST NOT
raise — run_checks() converts a crash into a `fail` so the report is always
complete. Checks register themselves in module order via @register; the
check modules are imported at the bottom of this file so importing
`ghostbrain.doctor` is enough to populate CHECKS.
"""
from __future__ import annotations

import dataclasses
import json
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

Status = Literal["ok", "warn", "fail", "skip"]
FixKind = Literal["automated", "interactive", "manual"]


@dataclass
class Fix:
    kind: FixKind
    command: str
    note: str = ""


@dataclass
class CheckResult:
    id: str
    status: Status
    summary: str
    detail: str = ""
    fix: Fix | None = None
    data: dict = field(default_factory=dict)


CheckFn = Callable[[], CheckResult]
CHECKS: list[tuple[str, CheckFn]] = []

_MARK = {"ok": "✔", "warn": "!", "fail": "✘", "skip": "-"}


def register(check_id: str) -> Callable[[CheckFn], CheckFn]:
    def deco(fn: CheckFn) -> CheckFn:
        CHECKS.append((check_id, fn))
        return fn
    return deco


def run_checks(platform: str | None = None) -> list[CheckResult]:
    """Run every registered check. `platform` is informational for callers
    that want to label output; checks decide applicability themselves."""
    out: list[CheckResult] = []
    for check_id, fn in CHECKS:
        try:
            out.append(fn())
        except Exception as e:  # noqa: BLE001 — a crashed check is a finding, not an abort
            out.append(CheckResult(
                id=check_id, status="fail",
                summary=f"check crashed: {e}",
                detail=traceback.format_exc(),
            ))
    return out


def to_json(results: list[CheckResult], *, platform: str) -> str:
    from ghostbrain.api.main import API_VERSION  # local: keep doctor import light

    return json.dumps({
        "platform": platform,
        "version": API_VERSION,
        "checks": [dataclasses.asdict(r) for r in results],
    }, indent=2)


def render_table(results: list[CheckResult]) -> str:
    width = max((len(r.id) for r in results), default=8)
    lines: list[str] = []
    for r in results:
        lines.append(f"{_MARK[r.status]} {r.id.ljust(width)}  {r.summary}")
        if r.fix and r.status in ("fail", "warn"):
            lines.append(f"  {' ' * width}  → {r.fix.command}")
            if r.fix.note:
                lines.append(f"  {' ' * width}    {r.fix.note}")
    return "\n".join(lines)


def current_platform() -> str:
    return sys.platform


# Populate CHECKS. Order here is the order the skill walks failures.
from ghostbrain.doctor import checks_app as _checks_app  # noqa: F401,I001
from ghostbrain.doctor import checks_recorder as _checks_recorder  # noqa: F401
from ghostbrain.doctor import checks_connectors as _checks_connectors  # noqa: F401
