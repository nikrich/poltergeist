from __future__ import annotations

import json

import pytest

from ghostbrain import doctor
from ghostbrain.doctor import CheckResult, Fix


@pytest.fixture(autouse=True)
def _empty_registry(monkeypatch):
    monkeypatch.setattr(doctor, "CHECKS", [])


def test_run_checks_returns_results_in_registration_order():
    @doctor.register("b-check")
    def _b() -> CheckResult:
        return CheckResult(id="b-check", status="ok", summary="b fine")

    @doctor.register("a-check")
    def _a() -> CheckResult:
        return CheckResult(id="a-check", status="ok", summary="a fine")

    assert [r.id for r in doctor.run_checks()] == ["b-check", "a-check"]


def test_crashing_check_becomes_fail_not_exception():
    @doctor.register("boom")
    def _boom() -> CheckResult:
        raise RuntimeError("kaboom")

    (res,) = doctor.run_checks()
    assert res.status == "fail"
    assert res.id == "boom"
    assert "kaboom" in res.detail


def test_to_json_shape_is_stable():
    @doctor.register("ffmpeg")
    def _f() -> CheckResult:
        return CheckResult(
            id="ffmpeg", status="fail", summary="ffmpeg not found",
            fix=Fix(kind="automated", command="setup deps --only ffmpeg"),
        )

    doc = json.loads(doctor.to_json(doctor.run_checks(), platform="darwin"))
    assert set(doc) == {"platform", "version", "checks"}
    assert doc["platform"] == "darwin"
    assert doc["checks"] == [{
        "id": "ffmpeg", "status": "fail", "summary": "ffmpeg not found", "detail": "",
        "fix": {"kind": "automated", "command": "setup deps --only ffmpeg", "note": ""},
        "data": {},
    }]


def test_render_table_marks_status_and_indents_fix():
    results = [
        CheckResult(id="vault", status="ok", summary="~/ghostbrain/vault"),
        CheckResult(id="ffmpeg", status="fail", summary="not found",
                    fix=Fix(kind="automated", command="setup deps --only ffmpeg")),
        CheckResult(id="scheduler", status="warn", summary="disabled",
                    fix=Fix(kind="manual", command="Settings → background → Run scheduler in-app")),
    ]
    text = doctor.render_table(results)
    lines = text.splitlines()
    assert lines[0].startswith("✔ vault")
    assert lines[1].startswith("✘ ffmpeg")
    assert lines[2].strip() == "→ setup deps --only ffmpeg"
    assert lines[3].startswith("! scheduler")
    assert "Settings → background" in lines[4]


def test_cli_exit_code_and_json_flag(capsys):
    @doctor.register("ffmpeg")
    def _f() -> CheckResult:
        return CheckResult(id="ffmpeg", status="fail", summary="not found")

    from ghostbrain.doctor import cli

    assert cli.main([]) == 1
    assert "✘ ffmpeg" in capsys.readouterr().out
    assert cli.main(["--json"]) == 1
    assert json.loads(capsys.readouterr().out)["checks"][0]["id"] == "ffmpeg"


def test_doctor_is_a_registered_subcommand():
    from ghostbrain.api.__main__ import SUBCOMMANDS

    assert SUBCOMMANDS["doctor"] == "ghostbrain.doctor.cli:main"
