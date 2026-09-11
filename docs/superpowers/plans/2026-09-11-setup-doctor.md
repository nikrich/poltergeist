# Setup Doctor + Claude Code Setup Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a `.dmg` user one command (`ghostbrain-api doctor`) that finds every first-run gap, automated `setup <fix>` commands for the ones our code can close, and a Claude Code skill that walks them from install to a verified test recording.

**Architecture:** A new `ghostbrain/doctor/` package holds pure check functions that return `CheckResult` records and a `setup` dispatcher with one module per fix. Both are exposed as subcommands of the bundled `ghostbrain-api` binary (the only executable a `.dmg` user has) and as `GET /v1/doctor`. A `session-end` subcommand replaces the never-shipped hook script. The skill is markdown in `.claude/skills/poltergeist-setup/` that drives the CLI. Seven small companion fixes make the checks rarely fire on a fresh install.

**Tech Stack:** Python 3.11+, FastAPI, httpx, PyYAML, PyObjC (EventKit already; CoreAudio new), pytest; Electron/TypeScript/vitest for the desktop bits; Homebrew for macOS deps.

**Spec:** `docs/superpowers/specs/2026-09-10-setup-doctor-design.md`

## Global Constraints

- Work in the worktree `/Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor` on branch `feat/setup-doctor`. Every shell command starts with `cd` to that path (subagents otherwise run git in the main repo).
- Python tests: `.venv/bin/python -m pytest <path> -q -p no:cacheprovider`. Create the venv once with `uv sync --extra dev --extra api -q` if `.venv/bin/python` is missing. Never run the suite without Task 1's fixture in place; it clobbers the live app's state.
- Desktop tests: `cd desktop && npm test`; gates before any desktop commit: `npm run typecheck` and `npm run lint` (zero warnings, release builds enforce it).
- Ruff is configured (`pyproject.toml [tool.ruff]`); run `.venv/bin/python -m ruff check <files>` on every new Python file and fix what it reports in that file. Pre-existing findings elsewhere are not yours.
- Subcommand names: `doctor`, `setup`, `session-end`. Console scripts: `ghostbrain-doctor`, `ghostbrain-setup`, `ghostbrain-session-end`. `tests/test_api_main_dispatch.py::test_subcommands_exactly_mirror_pyproject_scripts` must stay green.
- `CheckResult.id` values are a contract: `app`, `vault`, `contexts`, `claude-cli`, `ffmpeg`, `whisper-cli`, `whisper-model`, `switchaudio`, `blackhole`, `audio-device`, `audio-routing`, `scheduler`, `routing-mode`, `connectors`, `claude-hook`, `cli-shim`, `recorder-backend`.
- Fix kinds: `automated` (skill runs it), `interactive` (needs a terminal password prompt), `manual` (Settings path or outside our control).
- Default audio device name comes from `ghostbrain.recorder.daemon.DEFAULT_AUDIO_DEVICE` (`"Ghost Brain"`); never hardcode the string elsewhere.
- Desktop config file: `app.getPath('userData')/config.json`, i.e. `~/Library/Application Support/ghostbrain-desktop/config.json` on macOS, `%APPDATA%\ghostbrain-desktop\config.json` on Windows, `~/.config/ghostbrain-desktop/config.json` on Linux. Keys used: `schedulerEnabled`, `vaultPath`.
- Commit messages are conventional commits; end each with the two attribution trailers used in this repo:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Am1c7X3TWrhHBnMPwzDRVx
  ```

## File structure

Created:
- `ghostbrain/doctor/__init__.py` — `CheckResult`, `Fix`, `run_checks()`, `to_json()`, `render_table()`.
- `ghostbrain/doctor/checks_recorder.py` — ffmpeg, whisper-cli, whisper-model, switchaudio, blackhole, audio-device, audio-routing, recorder-backend.
- `ghostbrain/doctor/checks_app.py` — app, vault, contexts, claude-cli, scheduler, routing-mode.
- `ghostbrain/doctor/checks_connectors.py` — connectors, claude-hook, cli-shim.
- `ghostbrain/doctor/desktop_config.py` — locate and read the desktop `config.json`.
- `ghostbrain/doctor/cli.py` — `doctor` entry point.
- `ghostbrain/doctor/setup.py` — `setup` entry point and dispatcher.
- `ghostbrain/doctor/fixes/{deps,models,cli_shim,go_live,hook,audio_device}.py` — one fix each.
- `ghostbrain/hooks/__init__.py`, `ghostbrain/hooks/session_end.py` — hook port.
- `ghostbrain/api/routes/doctor.py` — `GET /v1/doctor`.
- `ghostbrain/api/claude_settings.py` — shared `~/.claude/settings.json` read/merge helpers (extracted from `local_grant.py`).
- `tests/test_doctor_*.py`, `tests/test_setup_*.py`, `tests/test_session_end.py`.
- `docs/install/macos.md`, `.claude/skills/poltergeist-setup/{SKILL.md,checks.md}`.

Modified: `tests/conftest.py`, `ghostbrain/api/__main__.py`, `pyproject.toml`, `packaging/sidecar.spec`, `ghostbrain/api/main.py`, `ghostbrain/api/auth/providers/local_grant.py`, `ghostbrain/api/repo/connector_probe.py`, `ghostbrain/api/repo/recorder.py`, `ghostbrain/api/routes/recorder.py`, `ghostbrain/recorder/manual.py`, `ghostbrain/bootstrap.py`, `ghostbrain/api/runtime.py`, `desktop/src/main/settings.ts`, `desktop/src/main/sidecar.ts`, `desktop/src/main/index.ts`, `desktop/src/renderer/screens/connectors.tsx`, `docs/connectors.md`, `docs/install/windows.md`, `README.md`.

Deleted: `.claude/skills/onboarding-poltergeist/`.

---

### Task 1: Sandbox every test away from the live app's state

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/test_conftest_isolation.py`

**Interfaces:**
- Produces: an autouse fixture `_isolate_user_state` that sets `GHOSTBRAIN_STATE_DIR`, `GHOSTBRAIN_RUN_DIR`, `VAULT_PATH`, and `HOME` to per-test temp dirs. Every later test relies on it implicitly.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_conftest_isolation.py
"""The suite must never touch the real ~/.ghostbrain, ~/ghostbrain, or ~/.claude.

On 2026-09-03 a local pytest run overwrote ~/.ghostbrain/state/recorder.json
while a meeting was being recorded; the app flipped to "idle" mid-meeting.
"""
from __future__ import annotations

import os
from pathlib import Path


def test_state_dir_is_sandboxed():
    from ghostbrain.recorder import state as state_mod

    real_home = Path(os.environ["REAL_HOME_FOR_TEST"])
    assert not str(state_mod.state_file()).startswith(str(real_home / ".ghostbrain"))


def test_home_vault_and_run_dir_are_sandboxed(tmp_path: Path):
    from ghostbrain.api import runtime
    from ghostbrain.paths import vault_path

    assert Path.home() != Path(os.environ["REAL_HOME_FOR_TEST"])
    assert str(vault_path()).startswith(str(tmp_path.parent))
    assert str(runtime.run_dir()).startswith(str(tmp_path.parent))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_conftest_isolation.py -q -p no:cacheprovider`
Expected: FAIL with `KeyError: 'REAL_HOME_FOR_TEST'` (the fixture that records it does not exist yet).

- [ ] **Step 3: Add the autouse fixture**

Insert at the top of `tests/conftest.py`, after the imports and before the existing `vault` fixture:

```python
import os


@pytest.fixture(autouse=True)
def _isolate_user_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every home-relative path the code reads at a per-test temp dir.

    Tests that need the real home (none today) must opt out explicitly with
    ``monkeypatch.delenv``. REAL_HOME_FOR_TEST lets a test assert the sandbox held.
    """
    monkeypatch.setenv("REAL_HOME_FOR_TEST", str(Path.home()))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() on Windows
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("GHOSTBRAIN_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
```

- [ ] **Step 4: Run the new test and the recorder tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_conftest_isolation.py tests/test_recorder.py tests/test_recorder_stop_singleton.py -q -p no:cacheprovider`
Expected: the two isolation tests PASS. `test_recorder.py` may show the same pre-existing darwin-only skips as before; no new failures. Then check nothing wrote to the real home: `ls -la ~/.ghostbrain/state/recorder.json` shows an mtime older than the run.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add tests/conftest.py tests/test_conftest_isolation.py
git commit -m "test: sandbox HOME, state, run, and vault dirs for every test

A local pytest run overwrote the live sidecar's recorder.json mid-meeting on
2026-09-03. Autouse fixture points every home-relative path at tmp_path."
```

---

### Task 2: Doctor core — result types, runner, table, JSON, `doctor` subcommand

**Files:**
- Create: `ghostbrain/doctor/__init__.py`, `ghostbrain/doctor/cli.py`
- Modify: `ghostbrain/api/__main__.py:153-181` (SUBCOMMANDS), `pyproject.toml:77-104` ([project.scripts])
- Test: `tests/test_doctor_core.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass class Fix: kind: Literal["automated","interactive","manual"]; command: str; note: str = ""
  @dataclass class CheckResult: id: str; status: Literal["ok","warn","fail","skip"]; summary: str; detail: str = ""; fix: Fix | None = None; data: dict = field(default_factory=dict)
  CheckFn = Callable[[], CheckResult]
  CHECKS: list[tuple[str, CheckFn]]            # ordered registry, filled by Tasks 3-5 via register()
  def register(check_id: str) -> Callable[[CheckFn], CheckFn]
  def run_checks(platform: str | None = None) -> list[CheckResult]
  def to_json(results, *, platform: str) -> str
  def render_table(results) -> str
  ```
- `cli.main(argv=None) -> int` prints the table (or JSON with `--json`), exit 1 if any `fail`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_doctor_core.py
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_doctor_core.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.doctor'`.

- [ ] **Step 3: Implement the core**

```python
# ghostbrain/doctor/__init__.py
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
from dataclasses import dataclass, field
from typing import Callable, Literal

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
    for check_id, fn in list(CHECKS):
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
from ghostbrain.doctor import checks_app as _checks_app  # noqa: E402,F401
from ghostbrain.doctor import checks_recorder as _checks_recorder  # noqa: E402,F401
from ghostbrain.doctor import checks_connectors as _checks_connectors  # noqa: E402,F401
```

Create the three check modules as empty placeholders so the imports resolve (Tasks 3–5 fill them):

```python
# ghostbrain/doctor/checks_app.py
"""App, vault, contexts, claude-cli, scheduler, routing-mode checks (Task 4)."""
from __future__ import annotations
```

Same one-docstring content for `ghostbrain/doctor/checks_recorder.py` ("Recorder dependency checks (Task 3).") and `ghostbrain/doctor/checks_connectors.py` ("Connector, Claude Code hook, and CLI shim checks (Task 5).").

```python
# ghostbrain/doctor/cli.py
"""`ghostbrain-api doctor [--json]` — run every first-run check."""
from __future__ import annotations

import argparse
import sys

from ghostbrain import doctor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostbrain-doctor")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    results = doctor.run_checks(doctor.current_platform())
    if args.json:
        print(doctor.to_json(results, platform=doctor.current_platform()))
    else:
        print(doctor.render_table(results))
    return 1 if any(r.status == "fail" for r in results) else 0
```

Register the subcommand. In `ghostbrain/api/__main__.py` add to `SUBCOMMANDS` after `"mcp"`:

```python
    "doctor": "ghostbrain.doctor.cli:main",
```

In `pyproject.toml` `[project.scripts]` add after `ghostbrain-mcp`:

```toml
ghostbrain-doctor = "ghostbrain.doctor.cli:main"
```

- [ ] **Step 4: Run the tests plus the parity test**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_doctor_core.py tests/test_api_main_dispatch.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/doctor`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/doctor tests/test_doctor_core.py ghostbrain/api/__main__.py pyproject.toml
git commit -m "feat(doctor): check registry, table/JSON output, and doctor subcommand"
```

---

### Task 3: Recorder dependency checks

**Files:**
- Modify: `ghostbrain/doctor/checks_recorder.py`
- Test: `tests/test_doctor_recorder_checks.py`

**Interfaces:**
- Consumes: `register`, `CheckResult`, `Fix` from Task 2; `ghostbrain.recorder.audio.get_backend().preflight() -> tuple[bool, list[str]]`; `ghostbrain.recorder.transcribe._resolve_model(None)` (raises `TranscribeError`); `ghostbrain.recorder.audio_switcher.list_outputs() -> list[str]`, `current_output() -> str`, `AudioSwitcherError`; `ghostbrain.recorder.daemon.DaemonConfig.load().audio_device`.
- Produces: check ids `ffmpeg`, `whisper-cli`, `whisper-model`, `switchaudio`, `blackhole`, `audio-device`, `audio-routing`, `recorder-backend`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_doctor_recorder_checks.py
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.doctor import checks_recorder as cr
from ghostbrain.recorder import audio_switcher


@pytest.fixture
def darwin(monkeypatch):
    monkeypatch.setattr(cr, "_platform", lambda: "darwin")


def _which(present: set[str]):
    return lambda name: f"/opt/homebrew/bin/{name}" if name in present else None


def test_ffmpeg_missing_is_automated_fix(darwin, monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", _which(set()))
    r = cr.check_ffmpeg()
    assert r.status == "fail"
    assert r.fix.kind == "automated"
    assert r.fix.command == "setup deps --only ffmpeg"


def test_ffmpeg_present_ok(darwin, monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", _which({"ffmpeg"}))
    assert cr.check_ffmpeg().status == "ok"


def test_whisper_cli_missing(darwin, monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", _which(set()))
    r = cr.check_whisper_cli()
    assert r.status == "fail"
    assert r.fix.command == "setup deps --only whisper-cpp"


def test_whisper_model_missing_and_present(darwin, monkeypatch, tmp_path: Path):
    from ghostbrain.recorder import transcribe

    monkeypatch.setattr(transcribe, "DEFAULT_MODEL_DIR", tmp_path)
    monkeypatch.delenv("GHOSTBRAIN_WHISPER_MODEL", raising=False)
    r = cr.check_whisper_model()
    assert r.status == "fail"
    assert r.fix.command == "setup fetch-model"
    (tmp_path / "ggml-small.en.bin").write_bytes(b"x" * 10)
    r = cr.check_whisper_model()
    assert r.status == "ok"
    assert r.data["model"].endswith("ggml-small.en.bin")


def test_blackhole_and_audio_device(darwin, monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", _which({"SwitchAudioSource"}))
    monkeypatch.setattr(audio_switcher, "list_outputs", lambda: ["MacBook Pro Speakers"])
    monkeypatch.setattr(cr, "_configured_device", lambda: "Ghost Brain")
    assert cr.check_blackhole().status == "fail"
    assert cr.check_blackhole().fix.kind == "interactive"
    assert cr.check_audio_device().status == "fail"
    assert cr.check_audio_device().fix.command == "setup audio-device"

    monkeypatch.setattr(
        audio_switcher, "list_outputs",
        lambda: ["BlackHole 2ch", "MacBook Pro Speakers", "Ghost Brain"],
    )
    assert cr.check_blackhole().status == "ok"
    assert cr.check_audio_device().status == "ok"


def test_audio_routing_is_warn_only(darwin, monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", _which({"SwitchAudioSource"}))
    monkeypatch.setattr(cr, "_configured_device", lambda: "Ghost Brain")
    monkeypatch.setattr(audio_switcher, "current_output", lambda: "MacBook Pro Speakers")
    r = cr.check_audio_routing()
    assert r.status == "warn"
    assert r.fix.kind == "manual"
    monkeypatch.setattr(audio_switcher, "current_output", lambda: "Ghost Brain")
    assert cr.check_audio_routing().status == "ok"


def test_switchaudio_missing_makes_dependent_checks_skip(darwin, monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", _which(set()))
    assert cr.check_switchaudio().status == "fail"
    assert cr.check_blackhole().status == "skip"
    assert cr.check_audio_device().status == "skip"
    assert cr.check_audio_routing().status == "skip"


def test_mac_only_checks_skip_on_linux(monkeypatch):
    monkeypatch.setattr(cr, "_platform", lambda: "linux")
    for fn in (cr.check_ffmpeg, cr.check_whisper_cli, cr.check_whisper_model,
               cr.check_switchaudio, cr.check_blackhole, cr.check_audio_device,
               cr.check_audio_routing):
        assert fn().status == "skip", fn.__name__


def test_recorder_backend_check_surfaces_preflight_on_windows(monkeypatch):
    monkeypatch.setattr(cr, "_platform", lambda: "win32")

    class FakeBackend:
        def preflight(self):
            return False, ["sounddevice not installed"]

    monkeypatch.setattr(cr, "_backend", lambda: FakeBackend())
    r = cr.check_recorder_backend()
    assert r.status == "fail"
    assert "sounddevice" in r.detail
    assert r.fix.kind == "manual"
    assert "docs/install/windows.md" in r.fix.command


def test_registration_order():
    from ghostbrain import doctor

    ids = [i for i, _ in doctor.CHECKS]
    rec = [i for i in ids if i in cr.IDS]
    assert rec == list(cr.IDS)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_doctor_recorder_checks.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: module 'ghostbrain.doctor.checks_recorder' has no attribute '_platform'`.

- [ ] **Step 3: Implement the checks**

```python
# ghostbrain/doctor/checks_recorder.py
"""Recorder dependency checks.

macOS needs: ffmpeg (capture), whisper-cli + a ggml model (transcription),
SwitchAudioSource (routing), BlackHole 2ch (virtual output), and a multi-output
device named per `recorder.audio_device` so system audio reaches BlackHole
while the user still hears it. Windows uses the WASAPI backend's own preflight.
"""
from __future__ import annotations

import shutil
import sys

from ghostbrain.doctor import CheckResult, Fix, register

IDS = (
    "ffmpeg", "whisper-cli", "whisper-model", "switchaudio",
    "blackhole", "audio-device", "audio-routing", "recorder-backend",
)

BLACKHOLE_DEVICE = "BlackHole 2ch"


def _platform() -> str:
    return sys.platform


def _backend():
    from ghostbrain.recorder.audio import get_backend

    return get_backend()


def _configured_device() -> str:
    from ghostbrain.recorder.daemon import DaemonConfig

    return DaemonConfig.load().audio_device


def _skip(check_id: str) -> CheckResult:
    return CheckResult(id=check_id, status="skip", summary="not applicable on this platform")


def _mac_only(check_id: str) -> CheckResult | None:
    return None if _platform() == "darwin" else _skip(check_id)


@register("ffmpeg")
def check_ffmpeg() -> CheckResult:
    if (s := _mac_only("ffmpeg")) is not None:
        return s
    path = shutil.which("ffmpeg")
    if path:
        return CheckResult(id="ffmpeg", status="ok", summary=path)
    return CheckResult(
        id="ffmpeg", status="fail", summary="ffmpeg not found on PATH",
        detail="ffmpeg captures BlackHole + microphone into the meeting WAV.",
        fix=Fix(kind="automated", command="setup deps --only ffmpeg"),
    )


@register("whisper-cli")
def check_whisper_cli() -> CheckResult:
    if (s := _mac_only("whisper-cli")) is not None:
        return s
    path = shutil.which("whisper-cli")
    if path:
        return CheckResult(id="whisper-cli", status="ok", summary=path)
    return CheckResult(
        id="whisper-cli", status="fail", summary="whisper-cli not found on PATH",
        detail="whisper.cpp's CLI transcribes recordings locally.",
        fix=Fix(kind="automated", command="setup deps --only whisper-cpp"),
    )


@register("whisper-model")
def check_whisper_model() -> CheckResult:
    if (s := _mac_only("whisper-model")) is not None:
        return s
    from ghostbrain.recorder.transcribe import DEFAULT_MODEL_DIR, TranscribeError, _resolve_model

    try:
        model = _resolve_model(None)
    except TranscribeError as e:
        return CheckResult(
            id="whisper-model", status="fail",
            summary=f"no ggml-*.bin in {DEFAULT_MODEL_DIR}",
            detail=str(e),
            fix=Fix(kind="automated", command="setup fetch-model",
                    note="downloads ggml-medium.en.bin (~1.5 GB); pass base.en or small.en for a smaller model"),
        )
    return CheckResult(id="whisper-model", status="ok", summary=model.name, data={"model": str(model)})


@register("switchaudio")
def check_switchaudio() -> CheckResult:
    if (s := _mac_only("switchaudio")) is not None:
        return s
    path = shutil.which("SwitchAudioSource")
    if path:
        return CheckResult(id="switchaudio", status="ok", summary=path)
    return CheckResult(
        id="switchaudio", status="fail", summary="SwitchAudioSource not found on PATH",
        detail="Used to flip macOS output to the multi-output device for the meeting and back after.",
        fix=Fix(kind="automated", command="setup deps --only switchaudio-osx"),
    )


def _outputs() -> list[str] | None:
    """None when SwitchAudioSource is unavailable (dependent checks skip)."""
    if shutil.which("SwitchAudioSource") is None:
        return None
    from ghostbrain.recorder import audio_switcher

    try:
        return audio_switcher.list_outputs()
    except audio_switcher.AudioSwitcherError:
        return None


@register("blackhole")
def check_blackhole() -> CheckResult:
    if (s := _mac_only("blackhole")) is not None:
        return s
    outputs = _outputs()
    if outputs is None:
        return CheckResult(id="blackhole", status="skip", summary="needs SwitchAudioSource first")
    if BLACKHOLE_DEVICE in outputs:
        return CheckResult(id="blackhole", status="ok", summary=BLACKHOLE_DEVICE)
    return CheckResult(
        id="blackhole", status="fail", summary=f"{BLACKHOLE_DEVICE} not installed",
        detail="Virtual output that lets ffmpeg capture what the meeting app plays.",
        fix=Fix(kind="interactive", command="setup deps --only blackhole",
                note="the installer asks for your macOS password, so run this one in Terminal"),
    )


@register("audio-device")
def check_audio_device() -> CheckResult:
    if (s := _mac_only("audio-device")) is not None:
        return s
    outputs = _outputs()
    if outputs is None:
        return CheckResult(id="audio-device", status="skip", summary="needs SwitchAudioSource first")
    name = _configured_device()
    if name in outputs:
        return CheckResult(id="audio-device", status="ok", summary=name, data={"device": name})
    return CheckResult(
        id="audio-device", status="fail", summary=f"no output device named '{name}'",
        detail="A multi-output device (speakers + BlackHole) so you hear the meeting while it is captured.",
        fix=Fix(kind="automated", command="setup audio-device"),
        data={"device": name},
    )


@register("audio-routing")
def check_audio_routing() -> CheckResult:
    if (s := _mac_only("audio-routing")) is not None:
        return s
    if shutil.which("SwitchAudioSource") is None:
        return CheckResult(id="audio-routing", status="skip", summary="needs SwitchAudioSource first")
    from ghostbrain.recorder import audio_switcher

    name = _configured_device()
    try:
        current = audio_switcher.current_output()
    except audio_switcher.AudioSwitcherError as e:
        return CheckResult(id="audio-routing", status="warn", summary=f"could not read output: {e}")
    if current == name:
        return CheckResult(id="audio-routing", status="ok", summary=current)
    return CheckResult(
        id="audio-routing", status="warn", summary=f"output is '{current}', not '{name}'",
        detail="Calendar recordings switch this automatically; the manual Record button needs it set first.",
        fix=Fix(kind="manual", command=f"Sound menu → Output → {name}"),
    )


@register("recorder-backend")
def check_recorder_backend() -> CheckResult:
    if _platform() != "win32":
        return _skip("recorder-backend")
    ok, missing = _backend().preflight()
    if ok:
        return CheckResult(id="recorder-backend", status="ok", summary="WASAPI backend ready")
    return CheckResult(
        id="recorder-backend", status="fail", summary="recorder prerequisites missing",
        detail="\n".join(missing),
        fix=Fix(kind="manual", command="follow docs/install/windows.md (dependencies section)"),
    )
```

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_doctor_recorder_checks.py tests/test_doctor_core.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/doctor`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/doctor/checks_recorder.py tests/test_doctor_recorder_checks.py
git commit -m "feat(doctor): recorder dependency checks (ffmpeg, whisper, BlackHole, multi-output device)"
```

---

### Task 4: App, vault, contexts, claude-cli, scheduler, routing-mode checks

**Files:**
- Create: `ghostbrain/doctor/desktop_config.py`
- Modify: `ghostbrain/doctor/checks_app.py`
- Test: `tests/test_doctor_app_checks.py`

**Interfaces:**
- Consumes: `ghostbrain.api.runtime.load_descriptor() -> dict | None` (None when absent or pid dead), `descriptor_path()`; `ghostbrain.paths.vault_path()`; `ghostbrain.routing_config.contexts() -> tuple[str, ...]`; `httpx`.
- Produces: `desktop_config.path() -> Path`, `desktop_config.load() -> dict` (empty dict when missing/invalid); check ids `app`, `vault`, `contexts`, `claude-cli`, `scheduler`, `routing-mode`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_doctor_app_checks.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.doctor import checks_app as ca
from ghostbrain.doctor import desktop_config


def test_desktop_config_path_per_platform(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(desktop_config, "_platform", lambda: "darwin")
    assert desktop_config.path() == Path.home() / "Library" / "Application Support" / "ghostbrain-desktop" / "config.json"
    monkeypatch.setattr(desktop_config, "_platform", lambda: "linux")
    assert desktop_config.path() == Path.home() / ".config" / "ghostbrain-desktop" / "config.json"
    monkeypatch.setattr(desktop_config, "_platform", lambda: "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    assert desktop_config.path() == tmp_path / "AppData" / "Roaming" / "ghostbrain-desktop" / "config.json"


def test_desktop_config_load_tolerates_missing_and_garbage(monkeypatch, tmp_path: Path):
    p = tmp_path / "config.json"
    monkeypatch.setattr(desktop_config, "path", lambda: p)
    assert desktop_config.load() == {}
    p.write_text("{not json")
    assert desktop_config.load() == {}
    p.write_text(json.dumps({"schedulerEnabled": True}))
    assert desktop_config.load() == {"schedulerEnabled": True}


def test_app_not_installed(monkeypatch):
    monkeypatch.setattr(ca, "_app_installed", lambda: False)
    r = ca.check_app()
    assert r.status == "fail"
    assert "Poltergeist.app" in r.summary
    assert r.fix.kind == "manual"


def test_app_installed_but_not_running(monkeypatch):
    monkeypatch.setattr(ca, "_app_installed", lambda: True)
    monkeypatch.setattr(ca, "_app_process_running", lambda: False)
    monkeypatch.setattr(ca, "_descriptor", lambda: None)
    r = ca.check_app()
    assert r.status == "fail"
    assert "open Poltergeist" in r.fix.command


def test_app_running_but_sidecar_unpublished_is_the_relaunch_race(monkeypatch):
    monkeypatch.setattr(ca, "_app_installed", lambda: True)
    monkeypatch.setattr(ca, "_app_process_running", lambda: True)
    monkeypatch.setattr(ca, "_descriptor", lambda: None)
    r = ca.check_app()
    assert r.status == "fail"
    assert "quit" in r.fix.command.lower() and "reopen" in r.fix.command.lower()


def test_app_healthy(monkeypatch):
    monkeypatch.setattr(ca, "_app_installed", lambda: True)
    monkeypatch.setattr(ca, "_app_process_running", lambda: True)
    monkeypatch.setattr(ca, "_descriptor", lambda: {"port": 4242, "token": "t", "pid": 1})
    monkeypatch.setattr(ca, "_health_ok", lambda port, token: True)
    r = ca.check_app()
    assert r.status == "ok"
    assert r.data == {"port": 4242}


def test_vault_missing_marker_and_desktop_mismatch(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setattr(desktop_config, "load", lambda: {})
    r = ca.check_vault()
    assert r.status == "fail"
    assert r.fix.command == "setup bootstrap"

    (tmp_path / "vault" / "90-meta").mkdir(parents=True)
    (tmp_path / "vault" / "90-meta" / "routing.yaml").write_text("contexts: [personal]\n")
    assert ca.check_vault().status == "ok"

    monkeypatch.setattr(desktop_config, "load", lambda: {"vaultPath": str(tmp_path / "other")})
    r = ca.check_vault()
    assert r.status == "warn"
    assert "other" in r.detail


def test_contexts_empty_vs_present(monkeypatch):
    monkeypatch.setattr(ca, "_contexts", lambda: ())
    assert ca.check_contexts().status == "fail"
    monkeypatch.setattr(ca, "_contexts", lambda: ("personal", "work"))
    r = ca.check_contexts()
    assert r.status == "ok"
    assert r.data["contexts"] == ["personal", "work"]


def test_claude_cli(monkeypatch):
    monkeypatch.setattr(ca.shutil, "which", lambda n: None)
    r = ca.check_claude_cli()
    assert r.status == "fail"
    assert "claude.ai" in r.fix.command or "npm install -g @anthropic-ai/claude-code" in r.fix.command
    monkeypatch.setattr(ca.shutil, "which", lambda n: "/usr/local/bin/claude")
    monkeypatch.setattr(ca, "_claude_version", lambda: "2.1.0")
    assert ca.check_claude_cli().status == "ok"


def test_scheduler_from_desktop_config(monkeypatch):
    monkeypatch.setattr(desktop_config, "load", lambda: {"schedulerEnabled": False})
    r = ca.check_scheduler()
    assert r.status == "fail"
    assert "Run scheduler in-app" in r.fix.command
    monkeypatch.setattr(desktop_config, "load", lambda: {"schedulerEnabled": True})
    assert ca.check_scheduler().status == "ok"
    monkeypatch.setattr(desktop_config, "load", lambda: {})
    assert ca.check_scheduler().status == "warn"


def test_routing_mode_counts_inbox(monkeypatch, tmp_path: Path):
    vault = tmp_path / "vault"
    monkeypatch.setenv("VAULT_PATH", str(vault))
    (vault / "90-meta").mkdir(parents=True)
    (vault / "00-inbox" / "raw").mkdir(parents=True)
    (vault / "90-meta" / "config.yaml").write_text("worker:\n  routing_mode: review_only\n")
    for i in range(3):
        (vault / "00-inbox" / "raw" / f"n{i}.md").write_text("x")
    r = ca.check_routing_mode()
    assert r.status == "warn"
    assert r.data == {"mode": "review_only", "inbox_count": 3}
    assert r.fix.command == "setup go-live"
    (vault / "90-meta" / "config.yaml").write_text("worker:\n  routing_mode: live\n")
    assert ca.check_routing_mode().status == "ok"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_doctor_app_checks.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.doctor.desktop_config'`.

- [ ] **Step 3: Implement**

```python
# ghostbrain/doctor/desktop_config.py
"""Read the Electron app's settings file (app.getPath('userData')/config.json).

The sidecar never writes this file; doctor only reads `schedulerEnabled` and
`vaultPath` to explain states the app owns.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_DIR = "ghostbrain-desktop"


def _platform() -> str:
    return sys.platform


def path() -> Path:
    if _platform() == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR / "config.json"
    if _platform() == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        return base / APP_DIR / "config.json"
    return Path.home() / ".config" / APP_DIR / "config.json"


def load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
```

```python
# ghostbrain/doctor/checks_app.py
"""App, vault, contexts, claude-cli, scheduler, routing-mode checks."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from ghostbrain.doctor import CheckResult, Fix, desktop_config, register

APP_BUNDLE = Path("/Applications/Poltergeist.app")


def _platform() -> str:
    return sys.platform


def _app_installed() -> bool:
    if _platform() == "darwin":
        return APP_BUNDLE.exists()
    return True  # other platforms: the binary running doctor IS the app's sidecar


def _app_process_running() -> bool:
    if _platform() != "darwin":
        return True
    proc = subprocess.run(["pgrep", "-f", "Poltergeist.app/Contents/MacOS/Poltergeist"],
                          capture_output=True, text=True)
    return proc.returncode == 0


def _descriptor() -> dict | None:
    from ghostbrain.api import runtime

    return runtime.load_descriptor()


def _health_ok(port: int, token: str) -> bool:
    import httpx

    try:
        r = httpx.get(f"http://127.0.0.1:{port}/health",
                      headers={"Authorization": f"Bearer {token}"}, timeout=3.0)
    except httpx.HTTPError:
        return False
    return r.status_code == 200


@register("app")
def check_app() -> CheckResult:
    if not _app_installed():
        return CheckResult(
            id="app", status="fail", summary="Poltergeist.app not found in /Applications",
            fix=Fix(kind="manual", command="download the latest release from https://github.com/nikrich/poltergeist/releases/latest and drag it to Applications"),
        )
    desc = _descriptor()
    running = _app_process_running()
    if desc is None and not running:
        return CheckResult(
            id="app", status="fail", summary="Poltergeist is not running",
            fix=Fix(kind="manual", command="open Poltergeist and wait for the sidebar to load"),
        )
    if desc is None and running:
        return CheckResult(
            id="app", status="fail", summary="app is running but its sidecar is not published",
            detail="Usually the app was reopened before the previous sidecar finished shutting down; it then runs read-only with no recorder or sync.",
            fix=Fix(kind="manual", command="quit Poltergeist, wait ten seconds, reopen it"),
        )
    port, token = int(desc.get("port", 0)), str(desc.get("token", ""))
    if not _health_ok(port, token):
        return CheckResult(
            id="app", status="fail", summary=f"sidecar on port {port} is not answering",
            fix=Fix(kind="manual", command="quit Poltergeist, wait ten seconds, reopen it"),
        )
    return CheckResult(id="app", status="ok", summary=f"sidecar running on port {port}", data={"port": port})


@register("vault")
def check_vault() -> CheckResult:
    from ghostbrain.paths import vault_path

    root = vault_path()
    marker = root / "90-meta" / "routing.yaml"
    if not marker.exists():
        return CheckResult(
            id="vault", status="fail", summary=f"{root} is not bootstrapped",
            fix=Fix(kind="automated", command="setup bootstrap"),
        )
    desktop_vault = desktop_config.load().get("vaultPath")
    if isinstance(desktop_vault, str) and desktop_vault.strip():
        if Path(desktop_vault).expanduser().resolve() != root.resolve():
            return CheckResult(
                id="vault", status="warn", summary=str(root),
                detail=f"The desktop app's setting points at {desktop_vault}, but the sidecar uses {root}. Set the app's vault path back to {root} in Settings until the two are reconciled.",
                fix=Fix(kind="manual", command=f"Settings → vault path → {root}"),
            )
    return CheckResult(id="vault", status="ok", summary=str(root))


def _contexts() -> tuple[str, ...]:
    from ghostbrain.routing_config import contexts

    return contexts()


@register("contexts")
def check_contexts() -> CheckResult:
    ctx = _contexts()
    if not ctx:
        return CheckResult(
            id="contexts", status="fail", summary="no contexts configured",
            fix=Fix(kind="manual", command="add a `contexts:` list to 90-meta/routing.yaml (e.g. personal, work)"),
        )
    return CheckResult(id="contexts", status="ok", summary=", ".join(ctx), data={"contexts": list(ctx)})


def _claude_version() -> str | None:
    try:
        proc = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


@register("claude-cli")
def check_claude_cli() -> CheckResult:
    if shutil.which("claude") is None:
        return CheckResult(
            id="claude-cli", status="fail", summary="`claude` CLI not on PATH",
            detail="Every LLM call shells out to `claude -p`, billed to your Claude subscription.",
            fix=Fix(kind="manual", command="npm install -g @anthropic-ai/claude-code && claude login"),
        )
    version = _claude_version()
    if version is None:
        return CheckResult(
            id="claude-cli", status="fail", summary="`claude --version` failed",
            fix=Fix(kind="manual", command="claude login"),
        )
    return CheckResult(id="claude-cli", status="ok", summary=version)


@register("scheduler")
def check_scheduler() -> CheckResult:
    cfg = desktop_config.load()
    enabled = cfg.get("schedulerEnabled")
    if enabled is True:
        return CheckResult(id="scheduler", status="ok", summary="enabled")
    if enabled is False:
        return CheckResult(
            id="scheduler", status="fail", summary="disabled — connectors will never sync",
            fix=Fix(kind="manual", command="Settings → background → turn on 'Run scheduler in-app'"),
        )
    return CheckResult(
        id="scheduler", status="warn", summary="desktop settings not found; cannot tell",
        detail=f"expected {desktop_config.path()}",
    )


@register("routing-mode")
def check_routing_mode() -> CheckResult:
    from ghostbrain.paths import vault_path

    cfg_file = vault_path() / "90-meta" / "config.yaml"
    cfg: dict = {}
    if cfg_file.exists():
        cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    mode = str((cfg.get("worker") or {}).get("routing_mode", "review_only"))
    inbox = vault_path() / "00-inbox" / "raw"
    count = len(list(inbox.glob("*.md"))) if inbox.exists() else 0
    data = {"mode": mode, "inbox_count": count}
    if mode == "live":
        return CheckResult(id="routing-mode", status="ok", summary="live", data=data)
    return CheckResult(
        id="routing-mode", status="warn",
        summary=f"review_only — {count} item(s) held in 00-inbox/raw, nothing filed to contexts",
        detail="Review mode keeps every captured item in the inbox for you to audit. The app's meeting and calendar views only read filed notes, so it looks empty until you go live.",
        fix=Fix(kind="automated", command="setup go-live"),
        data=data,
    )
```

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_doctor_app_checks.py tests/test_doctor_core.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/doctor`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/doctor/checks_app.py ghostbrain/doctor/desktop_config.py tests/test_doctor_app_checks.py
git commit -m "feat(doctor): app, vault, contexts, claude-cli, scheduler, routing-mode checks"
```

---

### Task 5: Connector, Claude Code hook, and CLI shim checks

**Files:**
- Create: `ghostbrain/api/claude_settings.py`
- Modify: `ghostbrain/doctor/checks_connectors.py`, `ghostbrain/api/auth/providers/local_grant.py:13-34` (use the shared helpers)
- Test: `tests/test_doctor_connector_checks.py`, `tests/test_claude_settings.py`

**Interfaces:**
- Consumes: `ghostbrain.api.repo.routing.load_routing() -> dict`; `ghostbrain.api.repo.connector_probe.probe(id) -> ProbeResult(state)`.
- Produces:
  ```python
  # ghostbrain/api/claude_settings.py
  def settings_path() -> Path                          # ~/.claude/settings.json
  def load() -> dict                                   # {} when missing; raises ValueError on invalid JSON
  def write_atomic(doc: dict) -> None
  def session_end_commands(doc: dict) -> list[str]     # every hooks.SessionEnd[*].hooks[*].command
  def hook_command_exists(command: str) -> bool        # first shell word resolves to an existing file
  ```
  check ids `connectors`, `claude-hook`, `cli-shim`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_claude_settings.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.api import claude_settings as cs


def test_load_missing_is_empty_and_invalid_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cs, "settings_path", lambda: tmp_path / "settings.json")
    assert cs.load() == {}
    (tmp_path / "settings.json").write_text("{nope")
    with pytest.raises(ValueError):
        cs.load()


def test_write_atomic_roundtrip(tmp_path: Path, monkeypatch):
    p = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(cs, "settings_path", lambda: p)
    cs.write_atomic({"hooks": {}})
    assert json.loads(p.read_text()) == {"hooks": {}}
    assert not list(p.parent.glob(".settings.*"))


def test_session_end_commands_and_existence(tmp_path: Path):
    script = tmp_path / "session-end.sh"
    script.write_text("#!/bin/sh\n")
    doc = {"hooks": {"SessionEnd": [
        {"matcher": "*", "hooks": [{"type": "command", "command": f"{script} --flag"}]},
        {"matcher": "*", "hooks": [{"type": "command", "command": "/nonexistent/hook.sh"}]},
    ]}}
    cmds = cs.session_end_commands(doc)
    assert cmds == [f"{script} --flag", "/nonexistent/hook.sh"]
    assert cs.hook_command_exists(cmds[0]) is True
    assert cs.hook_command_exists(cmds[1]) is False
    assert cs.session_end_commands({}) == []
```

```python
# tests/test_doctor_connector_checks.py
from __future__ import annotations

from pathlib import Path

from ghostbrain.api import claude_settings as cs
from ghostbrain.api.repo.connector_probe import ProbeResult
from ghostbrain.doctor import checks_connectors as cc


def test_connectors_flags_on_but_empty(monkeypatch):
    monkeypatch.setattr(cc, "_routing", lambda: {
        "github": {"orgs": {}},
        "slack": {"workspaces": {"acme": {"context": "work"}}},
        "gmail": {"accounts": {}},
    })
    states = {"github": "on", "slack": "on", "gmail": "off"}
    monkeypatch.setattr(cc, "_probe", lambda cid: ProbeResult(states.get(cid, "off")))
    r = cc.check_connectors()
    assert r.status == "fail"
    assert r.data["on_but_empty"] == ["github"]
    assert r.data["configured"] == ["slack"]
    assert "github" in r.summary


def test_connectors_all_good(monkeypatch):
    monkeypatch.setattr(cc, "_routing", lambda: {"slack": {"workspaces": {"acme": {"context": "work"}}}})
    monkeypatch.setattr(cc, "_probe", lambda cid: ProbeResult("on"))
    r = cc.check_connectors()
    assert r.status == "ok"
    assert r.data["configured"] == ["slack"]


def test_connectors_none_configured_is_warn(monkeypatch):
    monkeypatch.setattr(cc, "_routing", lambda: {"github": {"orgs": {}}})
    monkeypatch.setattr(cc, "_probe", lambda cid: ProbeResult("off"))
    assert cc.check_connectors().status == "warn"


def test_claude_hook_missing_stale_and_ok(monkeypatch, tmp_path: Path):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(cs, "settings_path", lambda: p)
    r = cc.check_claude_hook()
    assert r.status == "fail"
    assert r.fix.command == "setup install-hook"

    p.write_text('{"hooks": {"SessionEnd": [{"matcher": "*", "hooks": [{"type": "command", "command": "/gone/session-end.sh"}]}]}}')
    r = cc.check_claude_hook()
    assert r.status == "fail"
    assert "/gone/session-end.sh" in r.detail

    script = tmp_path / "ok.sh"
    script.write_text("")
    p.write_text('{"hooks": {"SessionEnd": [{"matcher": "*", "hooks": [{"type": "command", "command": "%s"}]}]}}' % script)
    assert cc.check_claude_hook().status == "ok"


def test_cli_shim(monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", lambda n: None)
    r = cc.check_cli_shim()
    assert r.status == "warn"
    assert r.fix.command == "setup cli-shim"
    monkeypatch.setattr(cc.shutil, "which", lambda n: "/usr/local/bin/poltergeist")
    assert cc.check_cli_shim().status == "ok"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_claude_settings.py tests/test_doctor_connector_checks.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.api.claude_settings'`.

- [ ] **Step 3: Implement**

```python
# ghostbrain/api/claude_settings.py
"""Shared helpers for ~/.claude/settings.json (Claude Code's user settings).

Used by the Claude Code connector provider, the doctor's `claude-hook` check,
and `setup install-hook`. Only `hooks.SessionEnd` is ever touched.
"""
from __future__ import annotations

import json
import os
import shlex
import tempfile
from pathlib import Path


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def load() -> dict:
    """Return the settings document, {} if the file is missing.

    Raises ValueError when the file exists but is not valid JSON — callers
    must refuse to write over a file they cannot parse.
    """
    p = settings_path()
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("settings.json top level is not an object")
    return data


def write_atomic(doc: dict) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".settings.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def session_end_commands(doc: dict) -> list[str]:
    out: list[str] = []
    for entry in (doc.get("hooks") or {}).get("SessionEnd") or []:
        for hook in entry.get("hooks") or []:
            cmd = hook.get("command")
            if isinstance(cmd, str) and cmd.strip():
                out.append(cmd)
    return out


def hook_command_exists(command: str) -> bool:
    try:
        first = shlex.split(command)[0]
    except (ValueError, IndexError):
        return False
    return Path(first).expanduser().exists()
```

Replace the two private helpers in `ghostbrain/api/auth/providers/local_grant.py` (lines 13–34) with imports, and use them in `submit()`:

```python
from ghostbrain.api import claude_settings

def _claude_settings_path() -> Path:
    return claude_settings.settings_path()


def _write_json_atomic(path: Path, data: dict) -> None:  # kept for existing tests
    claude_settings.write_atomic(data)
```

(The `submit()` body is unchanged in this task; Task 11 rewrites it.)

```python
# ghostbrain/doctor/checks_connectors.py
"""Connector, Claude Code hook, and CLI shim checks."""
from __future__ import annotations

import shutil

from ghostbrain.api import claude_settings
from ghostbrain.doctor import CheckResult, Fix, register

# connector id -> (routing.yaml top-level key, sub-key that must be non-empty)
_BLOCKS: dict[str, tuple[str, str]] = {
    "github": ("github", "orgs"),
    "gmail": ("gmail", "accounts"),
    "calendar": ("calendar", "google"),
    "slack": ("slack", "workspaces"),
    "jira": ("jira", "sites"),
    "confluence": ("confluence", "sites"),
    "joplin": ("joplin", "token"),
    "claude_code": ("claude_code", "project_paths"),
}


def _routing() -> dict:
    from ghostbrain.api.repo.routing import load_routing

    return load_routing()


def _probe(connector_id: str):
    from ghostbrain.api.repo.connector_probe import probe

    return probe(connector_id)


def _block_non_empty(routing: dict, key: str, sub: str) -> bool:
    block = routing.get(key) or {}
    value = block.get(sub)
    if key == "calendar":
        macos = ((block.get("macos") or {}).get("accounts")) or {}
        google = ((block.get("google") or {}).get("accounts")) or {}
        return bool(macos or google)
    return bool(value)


@register("connectors")
def check_connectors() -> CheckResult:
    routing = _routing()
    configured: list[str] = []
    on_but_empty: list[str] = []
    for cid, (key, sub) in _BLOCKS.items():
        has_block = _block_non_empty(routing, key, sub)
        state = _probe(cid).state
        if has_block:
            configured.append(cid)
        elif state == "on":
            on_but_empty.append(cid)
    data = {"configured": configured, "on_but_empty": on_but_empty}
    if on_but_empty:
        return CheckResult(
            id="connectors", status="fail",
            summary=f"connected but not configured: {', '.join(on_but_empty)}",
            detail="These show 'on' in the app because a credential exists, but their routing block is empty, so every sync returns zero events. Add the org/account/calendar to 90-meta/routing.yaml or reconnect through the app.",
            fix=Fix(kind="manual", command="open the connector card in the app and finish its form, then run `poltergeist <connector>-fetch`"),
            data=data,
        )
    if not configured:
        return CheckResult(
            id="connectors", status="warn", summary="no connectors configured yet",
            fix=Fix(kind="manual", command="connect one from the app's connectors screen"),
            data=data,
        )
    return CheckResult(id="connectors", status="ok", summary=", ".join(configured), data=data)


@register("claude-hook")
def check_claude_hook() -> CheckResult:
    try:
        doc = claude_settings.load()
    except ValueError as e:
        return CheckResult(
            id="claude-hook", status="fail", summary="~/.claude/settings.json is not valid JSON",
            detail=str(e), fix=Fix(kind="manual", command="fix the JSON by hand, then re-run doctor"),
        )
    cmds = claude_settings.session_end_commands(doc)
    if not cmds:
        return CheckResult(
            id="claude-hook", status="fail", summary="no SessionEnd hook in ~/.claude/settings.json",
            detail="The hook queues each finished Claude Code session into the vault.",
            fix=Fix(kind="automated", command="setup install-hook"),
        )
    stale = [c for c in cmds if not claude_settings.hook_command_exists(c)]
    if stale:
        return CheckResult(
            id="claude-hook", status="fail", summary="SessionEnd hook points at a missing script",
            detail="\n".join(stale),
            fix=Fix(kind="automated", command="setup install-hook"),
        )
    return CheckResult(id="claude-hook", status="ok", summary=cmds[0])


@register("cli-shim")
def check_cli_shim() -> CheckResult:
    path = shutil.which("poltergeist")
    if path:
        return CheckResult(id="cli-shim", status="ok", summary=path)
    return CheckResult(
        id="cli-shim", status="warn", summary="`poltergeist` not on PATH",
        detail="Optional. Lets you run connector commands as `poltergeist <sub>` instead of the full bundle path.",
        fix=Fix(kind="automated", command="setup cli-shim"),
    )
```

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_claude_settings.py tests/test_doctor_connector_checks.py tests/test_doctor_core.py ghostbrain/api/tests -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/doctor ghostbrain/api/claude_settings.py`
Expected: all PASS (api tests cover the provider refactor), ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/api/claude_settings.py ghostbrain/api/auth/providers/local_grant.py ghostbrain/doctor/checks_connectors.py tests/test_claude_settings.py tests/test_doctor_connector_checks.py
git commit -m "feat(doctor): connector, Claude Code hook, and CLI shim checks; shared claude settings helpers"
```

---

### Task 6: `GET /v1/doctor`

**Files:**
- Create: `ghostbrain/api/routes/doctor.py`
- Modify: `ghostbrain/api/main.py` (import + `include_router`)
- Test: `ghostbrain/api/tests/test_doctor_route.py`

**Interfaces:**
- Consumes: `ghostbrain.doctor.run_checks`, `to_json`, `current_platform`.
- Produces: `GET /v1/doctor` → the same JSON document as `doctor --json`.

- [ ] **Step 1: Write the failing test** (follow the existing pattern in `ghostbrain/api/tests/` — look at how another route test builds the client with `create_app(token)` and the `Authorization: Bearer` header, and copy that fixture verbatim)

```python
# ghostbrain/api/tests/test_doctor_route.py
from __future__ import annotations

from fastapi.testclient import TestClient

from ghostbrain import doctor
from ghostbrain.api.main import create_app
from ghostbrain.doctor import CheckResult


def test_doctor_route_returns_check_document(monkeypatch):
    monkeypatch.setattr(doctor, "CHECKS", [])

    @doctor.register("vault")
    def _v() -> CheckResult:
        return CheckResult(id="vault", status="ok", summary="/tmp/vault")

    client = TestClient(create_app("tok"))
    r = client.get("/v1/doctor", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"platform", "version", "checks"}
    assert body["checks"][0]["id"] == "vault"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_doctor_route.py -q -p no:cacheprovider`
Expected: FAIL with 404.

- [ ] **Step 3: Implement**

```python
# ghostbrain/api/routes/doctor.py
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
```

In `ghostbrain/api/main.py` add `from ghostbrain.api.routes import doctor as doctor_routes` with the other route imports and `app.include_router(doctor_routes.router)` after `scheduler_routes`.

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest ghostbrain/api/tests -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/api/routes/doctor.py ghostbrain/api/main.py ghostbrain/api/tests/test_doctor_route.py
git commit -m "feat(api): GET /v1/doctor exposes the first-run checks"
```

---

### Task 7: `setup` dispatcher and `setup deps` (Homebrew installs)

**Files:**
- Create: `ghostbrain/doctor/setup.py`, `ghostbrain/doctor/fixes/__init__.py`, `ghostbrain/doctor/fixes/deps.py`
- Modify: `ghostbrain/api/__main__.py` (SUBCOMMANDS), `pyproject.toml` ([project.scripts])
- Test: `tests/test_setup_dispatch.py`, `tests/test_setup_deps.py`

**Interfaces:**
- Produces:
  ```python
  # ghostbrain/doctor/setup.py
  FIXES: dict[str, str] = {"deps": "ghostbrain.doctor.fixes.deps:main", "fetch-model": ..., "cli-shim": ..., "go-live": ..., "install-hook": ..., "audio-device": ..., "bootstrap": "ghostbrain.bootstrap:main"}
  def main(argv=None) -> int          # `setup <fix> [args]`; unknown fix → usage + exit 2
  # ghostbrain/doctor/fixes/deps.py
  PACKAGES: dict[str, tuple[str, bool]]   # name -> (brew formula/cask, is_cask)
  def main(argv=None) -> int
  ```
  Every fix module exposes `main(argv: list[str] | None = None) -> int` and only reads `argv` (never `sys.argv`), so the dispatcher can pass the remainder.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_setup_dispatch.py
from __future__ import annotations

from ghostbrain.doctor import setup


def test_setup_is_registered_subcommand():
    from ghostbrain.api.__main__ import SUBCOMMANDS

    assert SUBCOMMANDS["setup"] == "ghostbrain.doctor.setup:main"


def test_dispatch_passes_remaining_args(monkeypatch):
    seen = {}
    monkeypatch.setattr(setup, "FIXES", {"deps": "tests.test_setup_dispatch:_fake_fix"})
    monkeypatch.setattr(setup, "_load", lambda target: lambda argv: seen.setdefault("argv", argv) or 7)
    assert setup.main(["deps", "--only", "ffmpeg"]) == 7
    assert seen["argv"] == ["--only", "ffmpeg"]


def test_unknown_fix_is_usage_error(capsys):
    assert setup.main(["nope"]) == 2
    assert "available:" in capsys.readouterr().err


def test_no_args_prints_usage(capsys):
    assert setup.main([]) == 2
    assert "usage:" in capsys.readouterr().err
```

```python
# tests/test_setup_deps.py
from __future__ import annotations

from ghostbrain.doctor.fixes import deps


def _which(present: set[str]):
    return lambda name: f"/opt/homebrew/bin/{name}" if name in present else None


def test_missing_brew_is_a_manual_instruction(monkeypatch, capsys):
    monkeypatch.setattr(deps, "_brew", lambda: None)
    assert deps.main([]) == 1
    assert "https://brew.sh" in capsys.readouterr().err


def test_installs_only_missing_packages(monkeypatch):
    monkeypatch.setattr(deps, "_brew", lambda: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(deps, "_is_installed", lambda name: name == "ffmpeg")
    calls: list[list[str]] = []
    monkeypatch.setattr(deps, "_run", lambda cmd: calls.append(cmd) or 0)
    assert deps.main([]) == 0
    assert calls == [
        ["/opt/homebrew/bin/brew", "install", "whisper-cpp"],
        ["/opt/homebrew/bin/brew", "install", "switchaudio-osx"],
        ["/opt/homebrew/bin/brew", "install", "--cask", "blackhole-2ch"],
    ]


def test_only_limits_to_named_packages(monkeypatch):
    monkeypatch.setattr(deps, "_brew", lambda: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(deps, "_is_installed", lambda name: False)
    calls: list[list[str]] = []
    monkeypatch.setattr(deps, "_run", lambda cmd: calls.append(cmd) or 0)
    assert deps.main(["--only", "ffmpeg", "--only", "blackhole"]) == 0
    assert calls == [
        ["/opt/homebrew/bin/brew", "install", "ffmpeg"],
        ["/opt/homebrew/bin/brew", "install", "--cask", "blackhole-2ch"],
    ]


def test_stops_at_first_brew_failure(monkeypatch, capsys):
    monkeypatch.setattr(deps, "_brew", lambda: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(deps, "_is_installed", lambda name: False)
    monkeypatch.setattr(deps, "_run", lambda cmd: 1)
    assert deps.main([]) == 1
    assert "brew install ffmpeg failed" in capsys.readouterr().err


def test_unknown_only_name(capsys):
    assert deps.main(["--only", "vim"]) == 2
    assert "unknown dependency" in capsys.readouterr().err


def test_non_darwin_refuses(monkeypatch, capsys):
    monkeypatch.setattr(deps, "_platform", lambda: "linux")
    assert deps.main([]) == 1
    assert "macOS only" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_setup_dispatch.py tests/test_setup_deps.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.doctor.setup'`.

- [ ] **Step 3: Implement**

```python
# ghostbrain/doctor/fixes/__init__.py
"""One module per `setup <fix>`; each exposes main(argv) -> int and is idempotent."""
```

```python
# ghostbrain/doctor/setup.py
"""`ghostbrain-api setup <fix> [args]` — apply one first-run fix."""
from __future__ import annotations

import importlib
import sys
from typing import Callable

FIXES: dict[str, str] = {
    "deps": "ghostbrain.doctor.fixes.deps:main",
    "fetch-model": "ghostbrain.doctor.fixes.models:main",
    "cli-shim": "ghostbrain.doctor.fixes.cli_shim:main",
    "go-live": "ghostbrain.doctor.fixes.go_live:main",
    "install-hook": "ghostbrain.doctor.fixes.hook:main",
    "audio-device": "ghostbrain.doctor.fixes.audio_device:main",
    "bootstrap": "ghostbrain.doctor.fixes.bootstrap:main",
}


def _load(target: str) -> Callable[[list[str]], int]:
    mod_name, func_name = target.split(":")
    return getattr(importlib.import_module(mod_name), func_name)


def _usage() -> str:
    return "usage: ghostbrain-api setup <fix> [args]\navailable: " + ", ".join(sorted(FIXES))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_usage(), file=sys.stderr)
        return 2
    name, rest = argv[0], argv[1:]
    if name not in FIXES:
        print(f"unknown fix: {name!r}\n{_usage()}", file=sys.stderr)
        return 2
    rc = _load(FIXES[name])(rest)
    return rc if isinstance(rc, int) and not isinstance(rc, bool) else 0
```

```python
# ghostbrain/doctor/fixes/deps.py
"""`setup deps [--only NAME ...]` — install the macOS recorder dependencies via Homebrew.

Only installs what is missing. BlackHole is a cask whose installer prompts for
the macOS password; brew handles that prompt when run from a terminal, which is
why the doctor marks it `interactive` and the skill hands it to the user.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

# doctor name -> (brew name, is_cask). Order is install order.
PACKAGES: dict[str, tuple[str, bool]] = {
    "ffmpeg": ("ffmpeg", False),
    "whisper-cpp": ("whisper-cpp", False),
    "switchaudio-osx": ("switchaudio-osx", False),
    "blackhole": ("blackhole-2ch", True),
}

_BINARY_FOR = {
    "ffmpeg": "ffmpeg",
    "whisper-cpp": "whisper-cli",
    "switchaudio-osx": "SwitchAudioSource",
}


def _platform() -> str:
    return sys.platform


def _brew() -> str | None:
    return (shutil.which("brew") or next(
        (p for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if shutil.os.path.exists(p)), None))


def _is_installed(name: str) -> bool:
    if name == "blackhole":
        from ghostbrain.doctor.checks_recorder import BLACKHOLE_DEVICE, _outputs

        outputs = _outputs()
        return outputs is not None and BLACKHOLE_DEVICE in outputs
    return shutil.which(_BINARY_FOR[name]) is not None


def _run(cmd: list[str]) -> int:
    """Stream brew's output so a long install is visibly alive."""
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostbrain-api setup deps")
    parser.add_argument("--only", action="append", default=[], metavar="NAME",
                        help="install just this dependency (repeatable): " + ", ".join(PACKAGES))
    args = parser.parse_args([] if argv is None else argv)

    for name in args.only:
        if name not in PACKAGES:
            print(f"unknown dependency: {name!r}; choose from {', '.join(PACKAGES)}", file=sys.stderr)
            return 2
    if _platform() != "darwin":
        print("setup deps is macOS only (Homebrew); see docs/install/ for your platform", file=sys.stderr)
        return 1
    brew = _brew()
    if brew is None:
        print("Homebrew is not installed. Install it from https://brew.sh (needs your password), then re-run.",
              file=sys.stderr)
        return 1

    wanted = args.only or list(PACKAGES)
    for name in PACKAGES:  # keep canonical order regardless of --only order
        if name not in wanted:
            continue
        formula, is_cask = PACKAGES[name]
        if _is_installed(name):
            print(f"{name}: already installed")
            continue
        cmd = [brew, "install"] + (["--cask"] if is_cask else []) + [formula]
        print(f"{name}: {' '.join(cmd[1:])}")
        if _run(cmd) != 0:
            print(f"brew install {formula} failed; fix the error above and re-run", file=sys.stderr)
            return 1
        print(f"{name}: installed")
    return 0
```

Register: in `SUBCOMMANDS` add `"setup": "ghostbrain.doctor.setup:main",`; in `[project.scripts]` add `ghostbrain-setup = "ghostbrain.doctor.setup:main"`.

- [ ] **Step 4: Run tests, parity, ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_setup_dispatch.py tests/test_setup_deps.py tests/test_api_main_dispatch.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/doctor`
Expected: all PASS, ruff clean. (`ruff` may flag `shutil.os.path.exists`; if so replace with `import os` + `os.path.exists`.)

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/doctor/setup.py ghostbrain/doctor/fixes ghostbrain/api/__main__.py pyproject.toml tests/test_setup_dispatch.py tests/test_setup_deps.py
git commit -m "feat(setup): setup subcommand dispatcher and Homebrew deps installer"
```

---

### Task 8: `setup fetch-model`

**Files:**
- Create: `ghostbrain/doctor/fixes/models.py`
- Test: `tests/test_setup_fetch_model.py`

**Interfaces:**
- Consumes: `ghostbrain.recorder.transcribe.DEFAULT_MODEL_DIR`, `DEFAULT_MODEL`.
- Produces: `models.MODELS: dict[str, int]` (name → approximate bytes), `models.BASE_URL`, `models.main(argv) -> int`, `models.download(name, dest_dir, *, base_url, progress) -> Path`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_setup_fetch_model.py
from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from ghostbrain.doctor.fixes import models


@pytest.fixture
def served(tmp_path: Path):
    """Serve tmp_path/srv over HTTP; yields (base_url, srv_dir)."""
    srv = tmp_path / "srv"
    srv.mkdir()
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(srv), **k)  # noqa: E731
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", srv
    httpd.shutdown()


def test_download_writes_part_then_renames(served, tmp_path: Path):
    base, srv = served
    (srv / "ggml-base.en.bin").write_bytes(b"m" * 5000)
    dest = tmp_path / "models"
    seen: list[tuple[int, int]] = []
    out = models.download("base.en", dest, base_url=base, progress=lambda done, total: seen.append((done, total)))
    assert out == dest / "ggml-base.en.bin"
    assert out.read_bytes() == b"m" * 5000
    assert not list(dest.glob("*.part"))
    assert seen[-1] == (5000, 5000)


def test_size_mismatch_is_failure_and_leaves_no_part(served, tmp_path: Path, monkeypatch):
    base, srv = served
    (srv / "ggml-base.en.bin").write_bytes(b"m" * 100)
    monkeypatch.setattr(models, "_content_length", lambda resp: 999)
    with pytest.raises(models.FetchError):
        models.download("base.en", tmp_path / "models", base_url=base, progress=lambda d, t: None)
    assert not list((tmp_path / "models").glob("*"))


def test_main_default_is_medium_and_skips_when_present(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(models, "DEFAULT_MODEL_DIR", tmp_path)
    (tmp_path / "ggml-medium.en.bin").write_bytes(b"x")
    assert models.main([]) == 0
    assert "already present" in capsys.readouterr().out


def test_main_respects_env_override(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("GHOSTBRAIN_WHISPER_MODEL", str(tmp_path / "custom.bin"))
    assert models.main([]) == 0
    assert "GHOSTBRAIN_WHISPER_MODEL" in capsys.readouterr().out


def test_main_rejects_unknown_model(capsys):
    assert models.main(["huge"]) == 2
    assert "base.en, small.en, medium.en" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_setup_fetch_model.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.doctor.fixes.models'`.

- [ ] **Step 3: Implement**

```python
# ghostbrain/doctor/fixes/models.py
"""`setup fetch-model [base.en|small.en|medium.en]` — download a whisper.cpp ggml model."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

import httpx

from ghostbrain.recorder.transcribe import DEFAULT_MODEL_DIR  # noqa: F401 — monkeypatched in tests

BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
MODELS: dict[str, int] = {          # approximate sizes, shown before downloading
    "base.en": 142 * 1024 * 1024,
    "small.en": 466 * 1024 * 1024,
    "medium.en": 1533 * 1024 * 1024,
}
DEFAULT_NAME = "medium.en"


class FetchError(RuntimeError):
    pass


def _content_length(resp: httpx.Response) -> int | None:
    raw = resp.headers.get("content-length")
    return int(raw) if raw and raw.isdigit() else None


def download(name: str, dest_dir: Path, *, base_url: str = BASE_URL,
             progress: Callable[[int, int], None]) -> Path:
    filename = f"ggml-{name}.bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / filename
    part = dest_dir / f".{filename}.part"
    try:
        with httpx.stream("GET", f"{base_url}/{filename}", follow_redirects=True, timeout=60.0) as resp:
            if resp.status_code != 200:
                raise FetchError(f"HTTP {resp.status_code} for {filename}")
            total = _content_length(resp) or 0
            done = 0
            with part.open("wb") as f:
                for chunk in resp.iter_bytes(1024 * 1024):
                    f.write(chunk)
                    done += len(chunk)
                    progress(done, total)
        if total and done != total:
            raise FetchError(f"download incomplete: {done} of {total} bytes")
        os.replace(part, final)
    except (httpx.HTTPError, OSError) as e:
        part.unlink(missing_ok=True)
        raise FetchError(str(e)) from e
    except FetchError:
        part.unlink(missing_ok=True)
        raise
    return final


def _print_progress(done: int, total: int) -> None:
    mb = done / (1024 * 1024)
    if total:
        print(f"\r  {mb:7.0f} MB / {total / (1024 * 1024):.0f} MB ({100 * done / total:3.0f}%)", end="", flush=True)
    else:
        print(f"\r  {mb:7.0f} MB", end="", flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = [] if argv is None else argv
    name = argv[0] if argv else DEFAULT_NAME
    if name not in MODELS:
        print(f"unknown model {name!r}; choose from {', '.join(MODELS)}", file=sys.stderr)
        return 2
    env = os.environ.get("GHOSTBRAIN_WHISPER_MODEL")
    if env:
        print(f"GHOSTBRAIN_WHISPER_MODEL is set ({env}); nothing to fetch")
        return 0
    from ghostbrain.doctor.fixes import models as _self  # resolve monkeypatched DEFAULT_MODEL_DIR

    dest_dir = Path(_self.DEFAULT_MODEL_DIR)
    if (dest_dir / f"ggml-{name}.bin").exists():
        print(f"ggml-{name}.bin already present in {dest_dir}")
        return 0
    print(f"downloading ggml-{name}.bin (~{MODELS[name] // (1024 * 1024)} MB) to {dest_dir}")
    try:
        out = download(name, dest_dir, progress=_print_progress)
    except FetchError as e:
        print(f"\ndownload failed: {e}", file=sys.stderr)
        return 1
    print(f"\nsaved {out}")
    return 0
```

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_setup_fetch_model.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/doctor/fixes/models.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/doctor/fixes/models.py tests/test_setup_fetch_model.py
git commit -m "feat(setup): fetch-model downloads a whisper.cpp ggml model with progress and size check"
```

---

### Task 9: `setup cli-shim`, `setup go-live`, `setup bootstrap`

**Files:**
- Create: `ghostbrain/doctor/fixes/cli_shim.py`, `ghostbrain/doctor/fixes/go_live.py`, `ghostbrain/doctor/fixes/bootstrap.py`
- Test: `tests/test_setup_small_fixes.py`

**Interfaces:**
- Produces: `cli_shim.main(argv) -> int` (writes `poltergeist` wrapper; `cli_shim.binary_path() -> str` = `sys.executable` when frozen, else the `ghostbrain-api` console script next to the interpreter); `go_live.main(argv) -> int`; `bootstrap.main(argv) -> int` (calls `ghostbrain.bootstrap.bootstrap()` and prints the root).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_setup_small_fixes.py
from __future__ import annotations

import os
from pathlib import Path

from ghostbrain.doctor.fixes import bootstrap as bs
from ghostbrain.doctor.fixes import cli_shim, go_live


def test_cli_shim_writes_exec_wrapper_to_first_writable_dir(tmp_path: Path, monkeypatch, capsys):
    unwritable = tmp_path / "usr-local-bin"
    local = tmp_path / "local-bin"
    monkeypatch.setattr(cli_shim, "CANDIDATES", lambda: [unwritable, local])
    monkeypatch.setattr(cli_shim, "_writable", lambda d: d == local)
    monkeypatch.setattr(cli_shim, "binary_path", lambda: "/Applications/P.app/ghostbrain-api")
    monkeypatch.setenv("PATH", "/usr/bin")
    assert cli_shim.main([]) == 0
    shim = local / "poltergeist"
    assert shim.read_text() == '#!/bin/sh\nexec "/Applications/P.app/ghostbrain-api" "$@"\n'
    assert os.access(shim, os.X_OK)
    assert "add" in capsys.readouterr().out  # PATH hint because local is not on PATH


def test_cli_shim_is_idempotent(tmp_path: Path, monkeypatch, capsys):
    d = tmp_path / "bin"
    monkeypatch.setattr(cli_shim, "CANDIDATES", lambda: [d])
    monkeypatch.setattr(cli_shim, "_writable", lambda _d: True)
    monkeypatch.setattr(cli_shim, "binary_path", lambda: "/x/ghostbrain-api")
    assert cli_shim.main([]) == 0
    assert cli_shim.main([]) == 0
    assert "already" in capsys.readouterr().out


def test_go_live_replaces_only_the_mode_line_and_counts_inbox(tmp_path: Path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    monkeypatch.setenv("VAULT_PATH", str(vault))
    (vault / "90-meta").mkdir(parents=True)
    (vault / "00-inbox" / "raw").mkdir(parents=True)
    (vault / "00-inbox" / "raw" / "a.md").write_text("x")
    cfg = vault / "90-meta" / "config.yaml"
    cfg.write_text("worker:\n  poll_interval_seconds: 5\n  # keep this comment\n  routing_mode: review_only\n\nprofile:\n  x: 1\n")
    assert go_live.main([]) == 0
    text = cfg.read_text()
    assert "  routing_mode: live\n" in text
    assert "# keep this comment" in text
    assert "poll_interval_seconds: 5" in text
    assert "1 item" in capsys.readouterr().out
    assert go_live.main([]) == 0  # idempotent


def test_go_live_adds_key_when_absent(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    monkeypatch.setenv("VAULT_PATH", str(vault))
    (vault / "90-meta").mkdir(parents=True)
    cfg = vault / "90-meta" / "config.yaml"
    cfg.write_text("worker:\n  poll_interval_seconds: 5\n")
    assert go_live.main([]) == 0
    assert "  routing_mode: live\n" in cfg.read_text()


def test_bootstrap_alias(tmp_path: Path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    monkeypatch.setenv("VAULT_PATH", str(vault))
    assert bs.main([]) == 0
    assert (vault / "90-meta" / "routing.yaml").exists()
    assert str(vault) in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_setup_small_fixes.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'bootstrap' from 'ghostbrain.doctor.fixes'`.

- [ ] **Step 3: Implement**

```python
# ghostbrain/doctor/fixes/cli_shim.py
"""`setup cli-shim` — write a `poltergeist` wrapper that execs this binary.

Mirrors desktop/src/main/cli-shim.ts so the CLI can install itself when the
user never opened Settings → background → "command line tool".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def CANDIDATES() -> list[Path]:  # noqa: N802 — monkeypatched as a function in tests
    return [Path("/usr/local/bin"), Path.home() / ".local" / "bin"]


def binary_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    candidate = Path(sys.executable).parent / "ghostbrain-api"
    return str(candidate) if candidate.is_file() else sys.executable


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return os.access(d, os.W_OK)


def main(argv: list[str] | None = None) -> int:
    script = f'#!/bin/sh\nexec "{binary_path()}" "$@"\n'
    for d in CANDIDATES():
        if not _writable(d):
            continue
        target = d / "poltergeist"
        if target.exists() and target.read_text() == script:
            print(f"already installed at {target}")
        else:
            target.write_text(script)
            target.chmod(0o755)
            print(f"installed {target}")
        if str(d) not in os.environ.get("PATH", "").split(os.pathsep):
            print(f"{d} is not on your PATH; add it to your shell profile: export PATH=\"{d}:$PATH\"")
        return 0
    print("no writable install directory (tried /usr/local/bin and ~/.local/bin)", file=sys.stderr)
    return 1
```

```python
# ghostbrain/doctor/fixes/go_live.py
"""`setup go-live` — flip worker.routing_mode to live, preserving the file's comments."""
from __future__ import annotations

import re

from ghostbrain.paths import vault_path

_MODE_LINE = re.compile(r"^(\s*)routing_mode:\s*\S+.*$", re.MULTILINE)
_WORKER_HEADER = re.compile(r"^worker:\s*$", re.MULTILINE)


def main(argv: list[str] | None = None) -> int:
    cfg = vault_path() / "90-meta" / "config.yaml"
    text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    if _MODE_LINE.search(text):
        new = _MODE_LINE.sub(lambda m: f"{m.group(1)}routing_mode: live", text, count=1)
    elif _WORKER_HEADER.search(text):
        new = _WORKER_HEADER.sub("worker:\n  routing_mode: live", text, count=1)
    else:
        new = text.rstrip("\n") + ("\n\n" if text.strip() else "") + "worker:\n  routing_mode: live\n"
    if new != text:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(new, encoding="utf-8")
        print(f"routing_mode set to live in {cfg}")
    else:
        print("routing_mode is already live")
    inbox = vault_path() / "00-inbox" / "raw"
    count = len(list(inbox.glob("*.md"))) if inbox.exists() else 0
    print(f"{count} item(s) in 00-inbox/raw will be filed on the worker's next pass")
    return 0
```

```python
# ghostbrain/doctor/fixes/bootstrap.py
"""`setup bootstrap` — create the vault tree (same as the bootstrap subcommand)."""
from __future__ import annotations

import ghostbrain.bootstrap as bootstrap_mod


def main(argv: list[str] | None = None) -> int:
    root = bootstrap_mod.bootstrap()
    print(f"vault ready at {root}")
    return 0
```

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_setup_small_fixes.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/doctor/fixes`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/doctor/fixes/cli_shim.py ghostbrain/doctor/fixes/go_live.py ghostbrain/doctor/fixes/bootstrap.py tests/test_setup_small_fixes.py
git commit -m "feat(setup): cli-shim, go-live, and bootstrap fixes"
```

---

### Task 10: `session-end` subcommand (Python port of the hook script)

**Files:**
- Create: `ghostbrain/hooks/__init__.py`, `ghostbrain/hooks/session_end.py`
- Modify: `ghostbrain/api/__main__.py` (SUBCOMMANDS), `pyproject.toml` ([project.scripts])
- Test: `tests/test_session_end.py`

**Interfaces:**
- Produces: `session_end.handle(payload: dict, *, vault: Path, now: datetime) -> Path | None` (returns the queued event path, None when skipped) and `session_end.main(argv) -> int` (reads JSON from stdin). Event JSON shape is identical to `orchestration/hooks/session-end.sh`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_session_end.py
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

from ghostbrain.hooks import session_end

NOW = datetime(2026, 9, 11, 8, 30, 5, tzinfo=timezone.utc)


def test_queues_event_and_snapshots_transcript(tmp_path: Path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text('{"a":1}\n')
    vault = tmp_path / "vault"
    out = session_end.handle(
        {"session_id": "abcdef12-3456", "transcript_path": str(transcript), "cwd": "/proj", "reason": "exit"},
        vault=vault, now=NOW,
    )
    assert out == vault / "90-meta" / "queue" / "pending" / "20260911T083005Z-claude-code-abcdef12-3456.json"
    snap = vault / "90-meta" / "queue" / "transcripts" / "abcdef12-3456.jsonl"
    assert snap.read_text() == '{"a":1}\n'
    event = json.loads(out.read_text())
    assert event == {
        "id": "claudecode-abcdef12-3456",
        "source": "claude-code",
        "type": "session",
        "subtype": "exit",
        "timestamp": "2026-09-11T08:30:05Z",
        "title": "Claude Code session abcdef12",
        "rawData": {
            "session_id": "abcdef12-3456",
            "transcript_path": str(transcript),
            "transcript_snapshot": str(snap),
            "cwd": "/proj",
            "reason": "exit",
        },
        "metadata": {"projectPath": "/proj", "sessionId": "abcdef12-3456", "transcriptPath": str(snap)},
    }


def test_missing_transcript_still_queues_without_snapshot(tmp_path: Path):
    out = session_end.handle(
        {"session_id": "s1", "transcript_path": str(tmp_path / "nope.jsonl"), "cwd": "", "reason": ""},
        vault=tmp_path / "vault", now=NOW,
    )
    event = json.loads(out.read_text())
    assert event["subtype"] == "ended"
    assert event["rawData"]["transcript_snapshot"] is None
    assert event["metadata"]["transcriptPath"] == str(tmp_path / "nope.jsonl")


def test_resume_and_missing_session_id_are_skipped(tmp_path: Path):
    assert session_end.handle({"session_id": "s1", "reason": "resume"}, vault=tmp_path, now=NOW) is None
    assert session_end.handle({"reason": "exit"}, vault=tmp_path, now=NOW) is None
    assert not (tmp_path / "90-meta").exists() or not list((tmp_path / "90-meta").rglob("*.json"))


def test_main_reads_stdin_and_honors_vault_path(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "v"))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "zz", "reason": "exit"})))
    assert session_end.main([]) == 0
    assert list((tmp_path / "v" / "90-meta" / "queue" / "pending").glob("*-claude-code-zz.json"))
    assert "queued" in capsys.readouterr().err


def test_main_with_garbage_stdin_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert session_end.main([]) == 0
    assert "skipping" in capsys.readouterr().err


def test_session_end_is_registered_subcommand():
    from ghostbrain.api.__main__ import SUBCOMMANDS

    assert SUBCOMMANDS["session-end"] == "ghostbrain.hooks.session_end:main"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_session_end.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.hooks'`.

- [ ] **Step 3: Implement**

```python
# ghostbrain/hooks/__init__.py
"""Claude Code hook entry points shipped inside the bundled binary."""
```

```python
# ghostbrain/hooks/session_end.py
"""`ghostbrain-api session-end` — Claude Code SessionEnd hook.

Python port of orchestration/hooks/session-end.sh so the packaged app needs no
extra script on disk. Reads the hook payload from stdin, snapshots the
transcript (Claude Code prunes the original), and queues an event for the
worker. Always exits 0: a hook failure must never break Claude Code.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from ghostbrain.paths import vault_path


def handle(payload: dict, *, vault: Path, now: datetime) -> Path | None:
    session_id = str(payload.get("session_id") or "")
    reason = str(payload.get("reason") or "")
    if not session_id:
        print("session-end: missing session_id; skipping", file=sys.stderr)
        return None
    if reason == "resume":
        print("session-end: reason=resume, skipping", file=sys.stderr)
        return None

    transcript = str(payload.get("transcript_path") or "")
    cwd = str(payload.get("cwd") or "")
    queue_dir = vault / "90-meta" / "queue" / "pending"
    transcripts_dir = vault / "90-meta" / "queue" / "transcripts"
    queue_dir.mkdir(parents=True, exist_ok=True)
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    snapshot: str | None = None
    if transcript and Path(transcript).is_file():
        target = transcripts_dir / f"{session_id}.jsonl"
        try:
            shutil.copyfile(transcript, target)
            snapshot = str(target)
        except OSError:
            snapshot = None

    ts = now.astimezone(timezone.utc)
    out = queue_dir / f"{ts.strftime('%Y%m%dT%H%M%SZ')}-claude-code-{session_id}.json"
    event = {
        "id": f"claudecode-{session_id}",
        "source": "claude-code",
        "type": "session",
        "subtype": reason or "ended",
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": f"Claude Code session {session_id[:8]}",
        "rawData": {
            "session_id": session_id,
            "transcript_path": transcript,
            "transcript_snapshot": snapshot,
            "cwd": cwd,
            "reason": reason,
        },
        "metadata": {
            "projectPath": cwd,
            "sessionId": session_id,
            "transcriptPath": snapshot or transcript,
        },
    }
    out.write_text(json.dumps(event, indent=2), encoding="utf-8")
    print(f"session-end: queued {out} (snapshot={snapshot or 'none'})", file=sys.stderr)
    return out


def main(argv: list[str] | None = None) -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except (ValueError, OSError) as e:
        print(f"session-end: unreadable payload ({e}); skipping", file=sys.stderr)
        return 0
    try:
        handle(payload, vault=vault_path(), now=datetime.now(timezone.utc))
    except Exception as e:  # noqa: BLE001 — never fail the editor's hook
        print(f"session-end: failed ({e}); skipping", file=sys.stderr)
    return 0
```

Register: `SUBCOMMANDS["session-end"] = "ghostbrain.hooks.session_end:main"`; pyproject `ghostbrain-session-end = "ghostbrain.hooks.session_end:main"`.

- [ ] **Step 4: Run tests, parity, ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_session_end.py tests/test_api_main_dispatch.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/hooks`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/hooks ghostbrain/api/__main__.py pyproject.toml tests/test_session_end.py
git commit -m "feat(hooks): session-end subcommand ports the Claude Code SessionEnd hook into the binary"
```

---

### Task 11: `setup install-hook`, provider default, and probe hardening (P-06)

**Files:**
- Create: `ghostbrain/doctor/fixes/hook.py`
- Modify: `ghostbrain/api/auth/providers/local_grant.py:36-82` (`ClaudeCodeProvider.start/submit`), `ghostbrain/api/repo/connector_probe.py:99-109` (`_claude_code_probe`)
- Test: `tests/test_setup_install_hook.py`, plus updates to whichever existing test in `ghostbrain/api/tests/` covers `ClaudeCodeProvider` (grep `hook_script`) and `_claude_code_probe`.

**Interfaces:**
- Consumes: `ghostbrain.api.claude_settings.{load, write_atomic, session_end_commands, hook_command_exists}`; `ghostbrain.doctor.fixes.cli_shim.binary_path()`.
- Produces: `hook.hook_command() -> str` = `'"<binary_path()>" session-end'`; `hook.install(doc: dict, command: str) -> dict` (pure: removes Poltergeist entries whose command path is missing, adds `command` once); `hook.main(argv) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_setup_install_hook.py
from __future__ import annotations

import json
from pathlib import Path

from ghostbrain.api import claude_settings as cs
from ghostbrain.doctor.fixes import hook


def _entry(cmd: str) -> dict:
    return {"matcher": "*", "hooks": [{"type": "command", "command": cmd, "async": True}]}


def test_install_adds_entry_once(tmp_path: Path):
    cmd = f'"{tmp_path / "bin"}" session-end'
    (tmp_path / "bin").write_text("")
    doc = hook.install({}, cmd)
    assert doc["hooks"]["SessionEnd"] == [_entry(cmd)]
    assert hook.install(doc, cmd)["hooks"]["SessionEnd"] == [_entry(cmd)]


def test_install_drops_stale_poltergeist_entries_keeps_others(tmp_path: Path):
    ok_bin = tmp_path / "bin"
    ok_bin.write_text("")
    doc = {"hooks": {"SessionEnd": [
        _entry("/Users/dev/development/ghost-brain/orchestration/hooks/session-end.sh"),
        _entry("/usr/local/bin/my-other-hook.sh"),
    ], "PreToolUse": [_entry("keep")]}, "theme": "dark"}
    new = hook.install(doc, f'"{ok_bin}" session-end')
    cmds = cs.session_end_commands(new)
    assert cmds == ["/usr/local/bin/my-other-hook.sh", f'"{ok_bin}" session-end']
    assert new["hooks"]["PreToolUse"] == [_entry("keep")]
    assert new["theme"] == "dark"


def test_main_writes_settings_and_is_idempotent(tmp_path: Path, monkeypatch, capsys):
    p = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(cs, "settings_path", lambda: p)
    monkeypatch.setattr(hook, "hook_command", lambda: '"/App/ghostbrain-api" session-end')
    assert hook.main([]) == 0
    assert cs.session_end_commands(json.loads(p.read_text())) == ['"/App/ghostbrain-api" session-end']
    assert hook.main([]) == 0
    assert "already" in capsys.readouterr().out


def test_main_refuses_invalid_json(tmp_path: Path, monkeypatch, capsys):
    p = tmp_path / "settings.json"
    p.write_text("{broken")
    monkeypatch.setattr(cs, "settings_path", lambda: p)
    assert hook.main([]) == 1
    assert "not valid JSON" in capsys.readouterr().err
    assert p.read_text() == "{broken"


def test_hook_command_quotes_binary(monkeypatch):
    monkeypatch.setattr(hook, "binary_path", lambda: "/Applications/Poltergeist.app/x/ghostbrain-api")
    assert hook.hook_command() == '"/Applications/Poltergeist.app/x/ghostbrain-api" session-end'
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_setup_install_hook.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.doctor.fixes.hook'`.

- [ ] **Step 3: Implement**

```python
# ghostbrain/doctor/fixes/hook.py
"""`setup install-hook` — wire Claude Code's SessionEnd hook to this binary."""
from __future__ import annotations

import sys

from ghostbrain.api import claude_settings
from ghostbrain.doctor.fixes.cli_shim import binary_path  # noqa: F401 — monkeypatched in tests

POLTERGEIST_MARKERS = ("session-end", "ghostbrain-api", "poltergeist")


def hook_command() -> str:
    from ghostbrain.doctor.fixes import hook as _self

    return f'"{_self.binary_path()}" session-end'


def _is_ours(command: str) -> bool:
    return any(m in command for m in POLTERGEIST_MARKERS)


def install(doc: dict, command: str) -> dict:
    hooks = doc.setdefault("hooks", {})
    entries = hooks.get("SessionEnd") or []
    kept: list[dict] = []
    present = False
    for entry in entries:
        cmds = [h.get("command", "") for h in entry.get("hooks") or []]
        if command in cmds:
            present = True
            kept.append(entry)
            continue
        stale = any(_is_ours(c) and not claude_settings.hook_command_exists(c) for c in cmds)
        if not stale:
            kept.append(entry)
    if not present:
        kept.append({"matcher": "*", "hooks": [{"type": "command", "command": command, "async": True}]})
    hooks["SessionEnd"] = kept
    return doc


def main(argv: list[str] | None = None) -> int:
    try:
        doc = claude_settings.load()
    except ValueError as e:
        print(f"~/.claude/settings.json is not valid JSON ({e}); fix it by hand first", file=sys.stderr)
        return 1
    command = hook_command()
    before = claude_settings.session_end_commands(doc)
    doc = install(doc, command)
    after = claude_settings.session_end_commands(doc)
    if before == after:
        print(f"SessionEnd hook already installed: {command}")
        return 0
    claude_settings.write_atomic(doc)
    print(f"SessionEnd hook installed in {claude_settings.settings_path()}: {command}")
    return 0
```

Then change `ClaudeCodeProvider` in `ghostbrain/api/auth/providers/local_grant.py`:
- In `start()`, the default `hook_script` field value becomes `hook.hook_command()` (import `from ghostbrain.doctor.fixes import hook`), replacing the `~/development/ghost-brain/...` default at lines 38–40.
- In `submit()`, replace the block that builds `hooks["SessionEnd"]` and writes the file with:

```python
        try:
            doc = claude_settings.load()
        except ValueError:
            session.status = "error"
            session.error = "~/.claude/settings.json is not valid JSON; fix it by hand first"
            return NextAction(kind="need_input", fields=[])
        doc = hook.install(doc, script)
        try:
            claude_settings.write_atomic(doc)
```
  (keep the existing `except OSError` branch and everything after it).

And harden `_claude_code_probe` in `ghostbrain/api/repo/connector_probe.py`:

```python
def _claude_code_probe() -> ProbeResult:
    from ghostbrain.api import claude_settings

    try:
        doc = claude_settings.load()
    except ValueError:
        return ProbeResult("err", error="settings.json is not valid JSON")
    cmds = claude_settings.session_end_commands(doc)
    if not cmds:
        return ProbeResult("off")
    if not any(claude_settings.hook_command_exists(c) for c in cmds):
        return ProbeResult("err", error="SessionEnd hook points at a missing script; run `poltergeist setup install-hook`")
    return ProbeResult("on")
```

(`ProbeResult` fields are `state`, `account`, `error` — the message goes in `error=`.)

- [ ] **Step 4: Update existing tests, run everything touched**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && grep -rln "hook_script\|_claude_code_probe\|SessionEnd" ghostbrain/api/tests tests` — open each hit and update expectations: the default field value now contains `session-end`, and a hook whose command path does not exist now yields state `err` (previously `on`). Then:
`.venv/bin/python -m pytest tests/test_setup_install_hook.py ghostbrain/api/tests tests/test_doctor_connector_checks.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/doctor ghostbrain/api/repo/connector_probe.py ghostbrain/api/auth/providers/local_grant.py`
Expected: PASS, ruff clean on the touched files.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/doctor/fixes/hook.py ghostbrain/api/auth/providers/local_grant.py ghostbrain/api/repo/connector_probe.py tests/test_setup_install_hook.py ghostbrain/api/tests
git commit -m "feat(setup): install-hook wires SessionEnd to the bundled binary; probe reports err on a dead hook path"
```

---

### Task 12: `setup audio-device` (CoreAudio multi-output device)

**Files:**
- Create: `ghostbrain/doctor/fixes/audio_device.py`
- Modify: `pyproject.toml` (dependency), `packaging/sidecar.spec` (collect CoreAudio)
- Test: `tests/test_setup_audio_device.py`

**Interfaces:**
- Consumes: `ghostbrain.recorder.daemon.DEFAULT_AUDIO_DEVICE`, `DaemonConfig.load().audio_device`; `ghostbrain.doctor.checks_recorder.BLACKHOLE_DEVICE`.
- Produces: `audio_device.build_description(name, *, speakers_uid, blackhole_uid) -> dict` (pure), `audio_device.main(argv) -> int` with `--dry-run` (prints the description as JSON, creates nothing).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_setup_audio_device.py
from __future__ import annotations

import json

from ghostbrain.doctor.fixes import audio_device as ad


def test_description_is_a_stacked_public_aggregate_with_drift_on_blackhole():
    desc = ad.build_description("Ghost Brain", speakers_uid="BuiltInSpeakerDevice", blackhole_uid="BlackHole2ch_UID")
    assert desc == {
        "name": "Ghost Brain",
        "uid": "tech.codeship.ghostbrain.multioutput",
        "stacked": 1,
        "private": 0,
        "master": "BuiltInSpeakerDevice",
        "subdevices": [
            {"uid": "BuiltInSpeakerDevice"},
            {"uid": "BlackHole2ch_UID", "drift": 1},
        ],
    }


def test_dry_run_prints_description_and_creates_nothing(monkeypatch, capsys):
    monkeypatch.setattr(ad, "_platform", lambda: "darwin")
    monkeypatch.setattr(ad, "_configured_name", lambda: "Ghost Brain")
    monkeypatch.setattr(ad, "_find_uids", lambda: ("SpeakersUID", "BlackHoleUID"))
    monkeypatch.setattr(ad, "_existing_output_names", lambda: ["MacBook Pro Speakers"])
    monkeypatch.setattr(ad, "_create", lambda desc: (_ for _ in ()).throw(AssertionError("must not create")))
    assert ad.main(["--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["subdevices"][1] == {"uid": "BlackHoleUID", "drift": 1}


def test_existing_device_is_noop(monkeypatch, capsys):
    monkeypatch.setattr(ad, "_platform", lambda: "darwin")
    monkeypatch.setattr(ad, "_configured_name", lambda: "Ghost Brain")
    monkeypatch.setattr(ad, "_existing_output_names", lambda: ["Ghost Brain", "BlackHole 2ch"])
    assert ad.main([]) == 0
    assert "already exists" in capsys.readouterr().out


def test_missing_blackhole_is_error_with_fix(monkeypatch, capsys):
    monkeypatch.setattr(ad, "_platform", lambda: "darwin")
    monkeypatch.setattr(ad, "_configured_name", lambda: "Ghost Brain")
    monkeypatch.setattr(ad, "_existing_output_names", lambda: ["MacBook Pro Speakers"])
    monkeypatch.setattr(ad, "_find_uids", lambda: (_ for _ in ()).throw(ad.DeviceNotFound("BlackHole 2ch")))
    assert ad.main([]) == 1
    assert "setup deps --only blackhole" in capsys.readouterr().err


def test_create_failure_reports_status_and_manual_recipe(monkeypatch, capsys):
    monkeypatch.setattr(ad, "_platform", lambda: "darwin")
    monkeypatch.setattr(ad, "_configured_name", lambda: "Ghost Brain")
    monkeypatch.setattr(ad, "_existing_output_names", lambda: [])
    monkeypatch.setattr(ad, "_find_uids", lambda: ("S", "B"))
    monkeypatch.setattr(ad, "_create", lambda desc: -50)
    assert ad.main([]) == 1
    err = capsys.readouterr().err
    assert "OSStatus -50" in err and "Audio MIDI Setup" in err


def test_non_darwin(monkeypatch, capsys):
    monkeypatch.setattr(ad, "_platform", lambda: "linux")
    assert ad.main([]) == 1
    assert "macOS only" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_setup_audio_device.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.doctor.fixes.audio_device'`.

- [ ] **Step 3: Implement**

Add the dependency in `pyproject.toml` `[project] dependencies`, right after the EventKit line:

```toml
    # `setup audio-device` builds the "Ghost Brain" multi-output device via
    # AudioHardwareCreateAggregateDevice.
    "pyobjc-framework-CoreAudio>=11.0; sys_platform == 'darwin'",
```

In `packaging/sidecar.spec`, next to where EventKit is handled (grep `EventKit`; if it is collected via `collect_submodules`/`collect_all`, add the same call for `'CoreAudio'`; if EventKit is only listed in `hiddenimports`, add `'CoreAudio'` and `'CoreAudio._CoreAudio'` there). Run `uv sync --extra dev --extra api -q` afterwards so the local venv has the binding.

```python
# ghostbrain/doctor/fixes/audio_device.py
"""`setup audio-device [--dry-run]` — create the multi-output device the recorder switches to.

A macOS "Multi-Output Device" is a *stacked* aggregate device: audio is sent
to every subdevice at once. Speakers are the master clock; BlackHole gets
drift compensation because a virtual device and the built-in output run on
different clocks and would desynchronise a long transcript otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys

from ghostbrain.doctor.checks_recorder import BLACKHOLE_DEVICE

AGGREGATE_UID = "tech.codeship.ghostbrain.multioutput"


class DeviceNotFound(RuntimeError):
    pass


def _platform() -> str:
    return sys.platform


def _configured_name() -> str:
    from ghostbrain.recorder.daemon import DaemonConfig

    return DaemonConfig.load().audio_device


def _existing_output_names() -> list[str]:
    from ghostbrain.recorder import audio_switcher

    try:
        return audio_switcher.list_outputs()
    except audio_switcher.AudioSwitcherError:
        return []


def build_description(name: str, *, speakers_uid: str, blackhole_uid: str) -> dict:
    return {
        "name": name,
        "uid": AGGREGATE_UID,
        "stacked": 1,
        "private": 0,
        "master": speakers_uid,
        "subdevices": [
            {"uid": speakers_uid},
            {"uid": blackhole_uid, "drift": 1},
        ],
    }


def _find_uids() -> tuple[str, str]:
    """Return (built-in speakers UID, BlackHole UID) via CoreAudio; raise DeviceNotFound."""
    import CoreAudio as CA  # pyobjc-framework-CoreAudio

    def _prop(obj_id: int, selector: int, scope: int = CA.kAudioObjectPropertyScopeGlobal):
        addr = CA.AudioObjectPropertyAddress(selector, scope, CA.kAudioObjectPropertyElementMain)
        err, _size, value = CA.AudioObjectGetPropertyData(obj_id, addr, 0, None, None, None)
        if err != 0:
            raise DeviceNotFound(f"CoreAudio property {selector} failed: OSStatus {err}")
        return value

    device_ids = _prop(CA.kAudioObjectSystemObject, CA.kAudioHardwarePropertyDevices)
    speakers = blackhole = None
    for dev in device_ids:
        name = str(_prop(dev, CA.kAudioObjectPropertyName))
        uid = str(_prop(dev, CA.kAudioDevicePropertyDeviceUID))
        transport = _prop(dev, CA.kAudioDevicePropertyTransportType)
        if name == BLACKHOLE_DEVICE:
            blackhole = uid
        elif transport == CA.kAudioDeviceTransportTypeBuiltIn and speakers is None:
            # built-in output (not the built-in mic): must have output streams
            streams = _prop(dev, CA.kAudioDevicePropertyStreams, CA.kAudioObjectPropertyScopeOutput)
            if streams:
                speakers = uid
    if blackhole is None:
        raise DeviceNotFound(BLACKHOLE_DEVICE)
    if speakers is None:
        raise DeviceNotFound("built-in output")
    return speakers, blackhole


def _create(description: dict) -> int:
    """Create the aggregate device; return the OSStatus (0 = success)."""
    import CoreAudio as CA

    err, _device_id = CA.AudioHardwareCreateAggregateDevice(description, None)
    return int(err)


_MANUAL_RECIPE = (
    "Create it by hand: open Audio MIDI Setup → '+' → Create Multi-Output Device, tick your speakers "
    "and 'BlackHole 2ch', enable Drift Correction on BlackHole, and rename the device to match."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostbrain-api setup audio-device")
    parser.add_argument("--dry-run", action="store_true", help="print the device description, create nothing")
    args = parser.parse_args([] if argv is None else argv)
    if _platform() != "darwin":
        print("setup audio-device is macOS only", file=sys.stderr)
        return 1
    name = _configured_name()
    if name in _existing_output_names():
        print(f"output device '{name}' already exists")
        return 0
    try:
        speakers_uid, blackhole_uid = _find_uids()
    except DeviceNotFound as e:
        if str(e) == BLACKHOLE_DEVICE:
            print(f"{BLACKHOLE_DEVICE} is not installed; run: setup deps --only blackhole (in Terminal)", file=sys.stderr)
        else:
            print(f"could not find {e}; {_MANUAL_RECIPE}", file=sys.stderr)
        return 1
    except ImportError:
        print(f"CoreAudio bindings unavailable in this build; {_MANUAL_RECIPE}", file=sys.stderr)
        return 1
    desc = build_description(name, speakers_uid=speakers_uid, blackhole_uid=blackhole_uid)
    if args.dry_run:
        print(json.dumps(desc, indent=2))
        return 0
    status = _create(desc)
    if status != 0:
        print(f"AudioHardwareCreateAggregateDevice failed: OSStatus {status}. {_MANUAL_RECIPE}", file=sys.stderr)
        return 1
    print(f"created multi-output device '{name}' (speakers + {BLACKHOLE_DEVICE}, drift-corrected)")
    return 0
```

- [ ] **Step 4: Run tests, ruff, and one real dry run**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_setup_audio_device.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/doctor/fixes/audio_device.py`
Expected: PASS, ruff clean.

Then on the dev Mac (which has BlackHole and a "Ghost Brain" device already): `.venv/bin/python -m ghostbrain.api setup audio-device --dry-run` must print `output device 'Ghost Brain' already exists`. To exercise `_find_uids` for real, temporarily run `.venv/bin/python -c "from ghostbrain.doctor.fixes import audio_device as a; print(a._find_uids())"` and confirm it prints two UIDs (the BlackHole one contains `BlackHole`). If the PyObjC property-access signature differs from the code above (the `AudioObjectGetPropertyData` return tuple shape), fix `_prop` to match what the installed binding returns; the unit tests do not cover it, this manual run does. Record the printed UIDs in the PR description.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/doctor/fixes/audio_device.py pyproject.toml packaging/sidecar.spec uv.lock tests/test_setup_audio_device.py
git commit -m "feat(setup): audio-device creates the multi-output device via CoreAudio (drift-corrected BlackHole)"
```

---

### Task 13: P-01 — preflight the manual Record path; no bare 500 for a missing binary

**Files:**
- Create: `ghostbrain/recorder/prereqs.py`
- Modify: `ghostbrain/scheduler_jobs.py:344-374` (move `_model_present` + `recorder_prereqs_ok` out, re-export), `ghostbrain/api/repo/recorder.py:225-226` (`start()`), `ghostbrain/api/routes/recorder.py:27-43`
- Test: `tests/test_recorder_start_preflight.py`

**Interfaces:**
- Produces: `ghostbrain.recorder.prereqs.recorder_prereqs_ok() -> tuple[bool, list[str]]` (same body as today's `scheduler_jobs.recorder_prereqs_ok`); `ghostbrain.api.repo.recorder.RecorderPrereqsMissing(Exception)`; route maps it to 412 and `OSError` to 500 with detail.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_recorder_start_preflight.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app
from ghostbrain.api.repo import recorder as repo


@pytest.fixture
def client():
    return TestClient(create_app("tok")), {"Authorization": "Bearer tok"}


def test_missing_prereqs_are_412_with_the_preflight_text(monkeypatch, client):
    c, h = client
    monkeypatch.setattr(repo, "_ensure_supported", lambda: None)
    monkeypatch.setattr(repo, "recorder_prereqs_ok",
                        lambda: (False, ["ffmpeg not on PATH (install via Homebrew: brew install ffmpeg)"]))
    r = c.post("/v1/recorder/start", json={"context": "work"}, headers=h)
    assert r.status_code == 412
    assert "brew install ffmpeg" in r.json()["detail"]


def test_oserror_from_capture_is_500_with_detail_not_bare(monkeypatch, client):
    c, h = client
    monkeypatch.setattr(repo, "_ensure_supported", lambda: None)
    monkeypatch.setattr(repo, "recorder_prereqs_ok", lambda: (True, []))
    monkeypatch.setattr(repo, "_daemon_active", lambda: None)
    monkeypatch.setattr(repo, "_read_state", lambda: None)

    def boom(*a, **k):
        raise FileNotFoundError("[Errno 2] No such file or directory: '/opt/homebrew/bin/ffmpeg'")

    monkeypatch.setattr(repo.audio_capture, "start_capture", boom)
    r = c.post("/v1/recorder/start", json={"context": "work"}, headers=h)
    assert r.status_code == 500
    assert "/opt/homebrew/bin/ffmpeg" in r.json()["detail"]


def test_prereqs_moved_and_reexported():
    from ghostbrain import scheduler_jobs
    from ghostbrain.recorder import prereqs

    assert scheduler_jobs.recorder_prereqs_ok is prereqs.recorder_prereqs_ok
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recorder_start_preflight.py -q -p no:cacheprovider`
Expected: FAIL (`AttributeError: ... has no attribute 'recorder_prereqs_ok'` on the repo module, and no `ghostbrain.recorder.prereqs`).

- [ ] **Step 3: Implement**

Create `ghostbrain/recorder/prereqs.py` containing exactly the current `_model_present` and `recorder_prereqs_ok` from `ghostbrain/scheduler_jobs.py:344-374` (with `import shutil`). In `scheduler_jobs.py` delete those two functions and add `from ghostbrain.recorder.prereqs import recorder_prereqs_ok  # noqa: F401 — re-exported` where they were.

In `ghostbrain/api/repo/recorder.py`, add near `RecorderUnsupportedError`:

```python
class RecorderPrereqsMissing(Exception):
    """Raised when a required binary/model is absent; message is the preflight text."""
    pass
```

add the import `from ghostbrain.recorder.prereqs import recorder_prereqs_ok` at module top, and change the first lines of `start()` to:

```python
def start(title: str | None, context: str | None) -> dict:
    _ensure_supported()
    ok, missing = recorder_prereqs_ok()
    if not ok:
        raise RecorderPrereqsMissing("; ".join(missing))
    with _lock:
```

In `ghostbrain/api/routes/recorder.py` import `RecorderPrereqsMissing` from the repo and change `post_start`'s handlers to:

```python
    except RecorderUnsupportedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except RecorderBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (AudioRoutingError, RecorderPrereqsMissing) as e:
        # 412 Precondition Failed — well-formed request, system not ready; the
        # detail names the exact fix (device to select, brew formula to install).
        raise HTTPException(status_code=412, detail=str(e))
    except (RuntimeError, OSError) as e:
        log.exception("recorder start failed")
        raise HTTPException(status_code=500, detail=str(e))
```

(add `import logging` and `log = logging.getLogger("ghostbrain.api.recorder_routes")` at the top of the routes module).

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_recorder_start_preflight.py tests/test_recorder_api_platform_guard.py tests/test_recorder.py ghostbrain/api/tests -q -p no:cacheprovider`
Expected: PASS (same pre-existing darwin-only skips as before).

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/recorder/prereqs.py ghostbrain/scheduler_jobs.py ghostbrain/api/repo/recorder.py ghostbrain/api/routes/recorder.py tests/test_recorder_start_preflight.py
git commit -m "fix(recorder): preflight manual start (412 with the fix text); map OSError to 500 with detail"
```

---

### Task 14: P-02 — transcription failures reach the UI

**Files:**
- Modify: `ghostbrain/recorder/manual.py:224-233` (`recover_one`), plus its daemon-loop caller (find with `grep -n "recover_one(" ghostbrain`)
- Test: `tests/test_manual_transcribe_errors.py`

**Interfaces:**
- Changes: `recover_one` now raises `TranscribeError` on a whisper failure or an empty transcript instead of returning `None`. `None` still means "already filed / not eligible". `_transcribe_in_background` in `ghostbrain/api/repo/recorder.py` already catches `Exception` and writes `error`, so no change there.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_manual_transcribe_errors.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.api.repo import recorder as repo
from ghostbrain.recorder import manual
from ghostbrain.recorder.transcribe import TranscribeError


def _wav(tmp_path: Path) -> Path:
    wav = tmp_path / "meeting-20260911-090000-manual.wav"
    wav.write_bytes(b"RIFF" + b"\0" * 200_000)
    return wav


def test_recover_one_raises_when_whisper_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(manual, "_already_filed", lambda name: False)
    monkeypatch.setattr(manual, "transcribe", lambda wav: (_ for _ in ()).throw(TranscribeError("`whisper-cli` not found on PATH. Install via `brew install whisper-cpp`.")))
    cfg = manual.ManualConfig(enabled=True, context="work", recordings_dir=tmp_path)
    with pytest.raises(TranscribeError, match="whisper-cli"):
        manual.recover_one(_wav(tmp_path), cfg)


def test_recover_one_raises_on_empty_transcript(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(manual, "_already_filed", lambda name: False)
    txt = tmp_path / "out.txt"
    txt.write_text("   \n")
    monkeypatch.setattr(manual, "transcribe", lambda wav: txt)
    cfg = manual.ManualConfig(enabled=True, context="work", recordings_dir=tmp_path)
    with pytest.raises(TranscribeError, match="empty"):
        manual.recover_one(_wav(tmp_path), cfg)


def test_background_transcribe_persists_the_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(repo, "STATE_FILE", tmp_path / "manual.state")
    monkeypatch.setattr(repo, "recover_one", lambda *a, **k: (_ for _ in ()).throw(TranscribeError("No whisper model found. Drop a ggml-*.bin file at ~/ghostbrain/recorder/models/")))
    (tmp_path / "manual.state").write_text(json.dumps({"phase": "transcribing"}))
    repo._transcribe_in_background({"wavPath": str(tmp_path / "x.wav"), "startedAt": "2026-09-11T09:00:00+00:00"})
    state = json.loads((tmp_path / "manual.state").read_text())
    assert state["phase"] == "done"
    assert "No whisper model found" in state["error"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_manual_transcribe_errors.py -q -p no:cacheprovider`
Expected: the first two FAIL with `DID NOT RAISE`; the third passes already (it pins the plumbing that must keep working).

- [ ] **Step 3: Implement**

In `ghostbrain/recorder/manual.py` replace lines 224–233 with:

```python
    txt_path = transcribe(wav)  # TranscribeError propagates: the caller decides how to surface it

    transcript_text = txt_path.read_text(encoding="utf-8")
    if not transcript_text.strip():
        raise TranscribeError(f"empty transcript for {wav.name}")
```

Then find the daemon-loop caller (`grep -n "recover_one(" ghostbrain`); it iterates orphan WAVs. Wrap its call:

```python
        try:
            recover_one(wav, cfg)
        except TranscribeError as e:
            log.warning("transcribe failed for %s: %s", wav.name, e)
            continue
```

(keep whatever else that loop does after a successful call).

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_manual_transcribe_errors.py tests/test_recorder.py tests/test_recorder_scrub_and_routing.py -q -p no:cacheprovider`
Expected: PASS. If an existing test asserted `recover_one(...) is None` on a whisper failure, change it to `pytest.raises(TranscribeError)` — that was the bug.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/recorder/manual.py tests/test_manual_transcribe_errors.py tests
git commit -m "fix(recorder): surface whisper/model errors instead of recording a silent 'done'"
```

---

### Task 15: P-03 — new vaults default to `routing_mode: live`

**Files:**
- Modify: `ghostbrain/bootstrap.py:765-769`
- Test: `tests/test_bootstrap_routing_mode.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bootstrap_routing_mode.py
from __future__ import annotations

from pathlib import Path

import yaml

import ghostbrain.bootstrap as bootstrap_mod


def test_fresh_vault_files_notes_live(tmp_path: Path):
    root = bootstrap_mod.bootstrap(tmp_path / "vault")
    cfg = yaml.safe_load((root / "90-meta" / "config.yaml").read_text())
    assert cfg["worker"]["routing_mode"] == "live"


def test_existing_config_is_not_rewritten(tmp_path: Path):
    root = bootstrap_mod.bootstrap(tmp_path / "vault")
    cfg_file = root / "90-meta" / "config.yaml"
    cfg_file.write_text(cfg_file.read_text().replace("routing_mode: live", "routing_mode: review_only"))
    bootstrap_mod.bootstrap(tmp_path / "vault")
    assert "routing_mode: review_only" in cfg_file.read_text()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bootstrap_routing_mode.py -q -p no:cacheprovider`
Expected: first test FAILS (`'review_only' == 'live'`). If the second also fails, bootstrap overwrites existing config files — stop and report; the spec requires idempotency.

- [ ] **Step 3: Implement**

In `ghostbrain/bootstrap.py` replace lines 765–769 with:

```yaml
  # routing_mode: live | review_only
  # live files each event under 20-contexts/<ctx>/ as it is routed.
  # review_only keeps everything in 00-inbox/raw and only audit-logs the
  # routing decision — useful for auditing a new connector; the app's
  # meeting and calendar views look empty while it is on.
  routing_mode: live
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_bootstrap_routing_mode.py tests/test_pipeline.py -q -p no:cacheprovider`
Expected: PASS (`test_pipeline.py` sets the mode explicitly per test).

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/bootstrap.py tests/test_bootstrap_routing_mode.py
git commit -m "fix(bootstrap): new vaults route live by default; review_only stays opt-in"
```

---

### Task 16: P-04 — scheduler on by default; real message instead of "wired in Slice 3"

**Files:**
- Modify: `desktop/src/main/settings.ts:35`, `desktop/src/renderer/stores/settings.ts:36`, `desktop/src/renderer/screens/connectors.tsx:94-98,471-475`
- Test: `desktop/src/main/__tests__/settings-defaults.test.ts`, `desktop/src/renderer/__tests__/connectors-scheduler-off.test.tsx`

- [ ] **Step 1: Write the failing tests**

Export the defaults object from `desktop/src/main/settings.ts`: find the object literal that contains `schedulerEnabled: false` (line 35) and make sure it is exported as `DEFAULT_SETTINGS` (if it is a `const defaults = {...}`, rename/export it and update its uses in the same file).

```ts
// desktop/src/main/__tests__/settings-defaults.test.ts
import { describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({ app: { getPath: () => '/tmp/ghostbrain-desktop-test' } }));

import { DEFAULT_SETTINGS } from '../settings';

describe('settings defaults', () => {
  it('runs the scheduler in-app by default so connectors sync without a hidden toggle', () => {
    expect(DEFAULT_SETTINGS.schedulerEnabled).toBe(true);
  });
});
```

```tsx
// desktop/src/renderer/__tests__/connectors-scheduler-off.test.tsx
// Copy the render + window.gb.api.request mock setup from connectors-connect.test.tsx
// verbatim (same imports, same beforeEach), then:
import { screen, fireEvent, waitFor } from '@testing-library/react';

it('sync now with the scheduler off explains the setting instead of a dev placeholder', async () => {
  // In the request mock, make GET /v1/scheduler/status resolve { enabled: false, jobs: {} }.
  renderConnectorsScreen(); // the helper from connectors-connect.test.tsx
  fireEvent.click(await screen.findByRole('button', { name: /sync all/i }));
  await waitFor(() => {
    expect(screen.getByText(/scheduler is off/i)).toBeInTheDocument();
    expect(screen.getByText(/Run scheduler in-app/)).toBeInTheDocument();
  });
  expect(screen.queryByText(/wired in Slice/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor/desktop && npx vitest run src/main/__tests__/settings-defaults.test.ts src/renderer/__tests__/connectors-scheduler-off.test.tsx`
Expected: FAIL (`false` is not `true`; "wired in Slice 3" rendered).

- [ ] **Step 3: Implement**

- `desktop/src/main/settings.ts:35` → `schedulerEnabled: true,`
- `desktop/src/renderer/stores/settings.ts:36` → `schedulerEnabled: true,`
- In `desktop/src/renderer/screens/connectors.tsx`, add a module-level constant and use it at both sites (lines 94–98 and 471–475):

```tsx
const SCHEDULER_OFF_MESSAGE =
  'Scheduler is off — nothing syncs. Turn on "Run scheduler in-app" in Settings → background.';
...
                if (!schedulerEnabled) {
                  toast.info(SCHEDULER_OFF_MESSAGE);
                  return;
                }
```

(`toast` is already imported in that file for other calls; if only `stub` was imported, import `toast` from `../stores/toast` and drop the `stub` import if nothing else uses it — the `pause` button at line 500 still uses `stub(3)`; leave it.)

- [ ] **Step 4: Run gates**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor/desktop && npm test && npm run typecheck && npm run lint`
Expected: all green. Fix any lint warning in the files you touched.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add desktop/src/main/settings.ts desktop/src/renderer/stores/settings.ts desktop/src/renderer/screens/connectors.tsx desktop/src/main/__tests__/settings-defaults.test.ts desktop/src/renderer/__tests__/connectors-scheduler-off.test.tsx
git commit -m "fix(desktop): scheduler on by default; 'sync now' explains the setting when it is off"
```

---

### Task 17: P-10 — the sidecar uses the desktop's vault path

**Files:**
- Modify: `desktop/src/main/sidecar.ts` (options + spawn env), `desktop/src/main/index.ts:52,175-187`
- Test: `desktop/src/main/__tests__/sidecar-env.test.ts`

**Interfaces:**
- Produces: `export function buildSidecarEnv(base: NodeJS.ProcessEnv, opts: { schedulerEnabled: boolean; vaultPath: string; extraPath: string }): NodeJS.ProcessEnv` in `sidecar.ts`, used by `spawn`. `SidecarOptions` gains `vaultPath: string` and `setVaultPath(path: string)`.

- [ ] **Step 1: Write the failing test**

```ts
// desktop/src/main/__tests__/sidecar-env.test.ts
import { describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({ app: { isPackaged: false, getPath: () => '/tmp' } }));

import { buildSidecarEnv } from '../sidecar';

describe('buildSidecarEnv', () => {
  it('passes the configured vault path and scheduler flag to the sidecar', () => {
    const env = buildSidecarEnv({ PATH: '/usr/bin', HOME: '/Users/x' }, {
      schedulerEnabled: false,
      vaultPath: '/Users/x/notes/vault',
      extraPath: '/opt/homebrew/bin',
    });
    expect(env.VAULT_PATH).toBe('/Users/x/notes/vault');
    expect(env.GHOSTBRAIN_SCHEDULER_ENABLED).toBe('0');
    expect(env.PYTHONUNBUFFERED).toBe('1');
    expect(env.PATH).toBe('/opt/homebrew/bin:/usr/bin');
    expect(env.HOME).toBe('/Users/x');
  });

  it('expands a leading ~ so Python sees an absolute path', () => {
    const env = buildSidecarEnv({ HOME: '/Users/x' }, { schedulerEnabled: true, vaultPath: '~/ghostbrain/vault', extraPath: '' });
    expect(env.VAULT_PATH).toBe('/Users/x/ghostbrain/vault');
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor/desktop && npx vitest run src/main/__tests__/sidecar-env.test.ts`
Expected: FAIL (`buildSidecarEnv` is not exported).

- [ ] **Step 3: Implement**

In `desktop/src/main/sidecar.ts`:

```ts
export function buildSidecarEnv(
  base: NodeJS.ProcessEnv,
  opts: { schedulerEnabled: boolean; vaultPath: string; extraPath: string },
): NodeJS.ProcessEnv {
  const inheritedPath = base.PATH ?? '';
  const home = base.HOME ?? homedir();
  const vault = opts.vaultPath.startsWith('~/') ? join(home, opts.vaultPath.slice(2)) : opts.vaultPath;
  return {
    ...base,
    PATH: inheritedPath ? `${opts.extraPath}:${inheritedPath}` : opts.extraPath,
    PYTHONUNBUFFERED: '1',
    GHOSTBRAIN_SCHEDULER_ENABLED: opts.schedulerEnabled ? '1' : '0',
    VAULT_PATH: vault,
  };
}
```

Add `vaultPath: string` to `SidecarOptions`, a `setVaultPath(path: string): void { this.options.vaultPath = path; }` next to `setSchedulerEnabled`, and replace the inline `env: {...}` in `spawn` (lines 164–171) with `env: buildSidecarEnv(process.env, { schedulerEnabled: this.options.schedulerEnabled, vaultPath: this.options.vaultPath, extraPath })`. Import `homedir` from `node:os` and `join` from `node:path` if not already imported.

In `desktop/src/main/index.ts:52` add `vaultPath: settings.getAll().vaultPath,` to the options object; at line 175 change the restart condition to:

```ts
  if (key === 'schedulerEnabled' || key === 'vaultPath') {
    // Both are read from the sidecar's launch env, so changing either needs a restart.
    if (key === 'schedulerEnabled') sidecar.setSchedulerEnabled(parsed.data as boolean);
    if (key === 'vaultPath') sidecar.setVaultPath(parsed.data as string);
```

- [ ] **Step 4: Run gates**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor/desktop && npm test && npm run typecheck && npm run lint`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add desktop/src/main/sidecar.ts desktop/src/main/index.ts desktop/src/main/__tests__/sidecar-env.test.ts
git commit -m "fix(desktop): pass VAULT_PATH to the sidecar and restart it when the vault path changes"
```

---

### Task 18: P-11 — the macOS calendar probe reports what actually works

**Files:**
- Modify: `ghostbrain/api/repo/connector_probe.py:112-118`
- Test: `tests/test_connector_probe_calendar.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_connector_probe_calendar.py
from __future__ import annotations

from ghostbrain.api.repo import connector_probe as cp


def _routing_with_macos(accounts: dict):
    return lambda: {"calendar": {"macos": {"accounts": accounts}}}


def test_eventkit_authorized_with_accounts_is_on(monkeypatch):
    monkeypatch.setattr(cp, "_google_probe", lambda prefix: cp.ProbeResult("off"))
    monkeypatch.setattr(cp, "_platform", lambda: "darwin")
    monkeypatch.setattr(cp, "_macos_calendar_authorized", lambda: True)
    monkeypatch.setattr(cp, "_load_routing", _routing_with_macos({"Calendar": "work"}))
    assert cp.probe("calendar").state == "on"


def test_eventkit_authorized_but_no_accounts_stays_off(monkeypatch):
    monkeypatch.setattr(cp, "_google_probe", lambda prefix: cp.ProbeResult("off"))
    monkeypatch.setattr(cp, "_platform", lambda: "darwin")
    monkeypatch.setattr(cp, "_macos_calendar_authorized", lambda: True)
    monkeypatch.setattr(cp, "_load_routing", _routing_with_macos({}))
    assert cp.probe("calendar").state == "off"


def test_google_token_still_wins(monkeypatch):
    monkeypatch.setattr(cp, "_google_probe", lambda prefix: cp.ProbeResult("on"))
    monkeypatch.setattr(cp, "_platform", lambda: "linux")
    assert cp.probe("calendar").state == "on"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_connector_probe_calendar.py -q -p no:cacheprovider`
Expected: FAIL (`AttributeError: module ... has no attribute '_platform'`).

- [ ] **Step 3: Implement**

In `ghostbrain/api/repo/connector_probe.py` add:

```python
import sys


def _platform() -> str:
    return sys.platform


def _macos_calendar_authorized() -> bool | None:
    from ghostbrain.api.auth.providers.local_grant import _macos_calendar_authorized as impl

    return impl()


def _load_routing() -> dict:
    from ghostbrain.api.repo.routing import load_routing

    return load_routing()
```

and replace the `calendar` branch of `probe()`:

```python
    if connector_id == "calendar":
        google = _google_probe("google_calendar")
        if google.state == "on" or _platform() != "darwin":
            return google
        accounts = (((_load_routing().get("calendar") or {}).get("macos") or {}).get("accounts")) or {}
        if accounts and _macos_calendar_authorized():
            return ProbeResult("on")
        return google
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_connector_probe_calendar.py ghostbrain/api/tests/test_connectors.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/api/repo/connector_probe.py tests/test_connector_probe_calendar.py
git commit -m "fix(connectors): macOS calendar probe reports on when EventKit is authorized and accounts are mapped"
```

---

### Task 19: P-13 — tracebacks reach the log, noisy libraries don't

**Files:**
- Modify: `ghostbrain/api/runtime.py:123-148` (`setup_file_logging`), `ghostbrain/api/main.py` (`create_app`), `ghostbrain/api/__main__.py` (uvicorn.run call)
- Test: `tests/test_logging_setup.py`, `ghostbrain/api/tests/test_error_handler.py`

**Interfaces:**
- Produces: `runtime.QUIET_LOGGERS: tuple[str, ...]`; `main.install_error_handling(app)` (called from `create_app`), which stamps `request.state.request_id`, echoes it as `X-Request-ID`, and turns any unhandled exception into `{"detail": "Internal error", "requestId": "<id>"}` after `log.exception`; `__main__._uvicorn_kwargs(app, port) -> dict` with `log_config=None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_logging_setup.py
from __future__ import annotations

import logging

from ghostbrain.api import runtime


def test_file_logging_quiets_chatty_libraries():
    runtime.setup_file_logging()
    for name in ("httpx", "httpcore", "huggingface_hub", "transformers", "sentence_transformers", "filelock", "urllib3"):
        assert logging.getLogger(name).level == logging.WARNING, name
    assert set(runtime.QUIET_LOGGERS) >= {"httpx", "huggingface_hub"}


def test_uvicorn_is_left_to_propagate_to_root():
    from ghostbrain.api.__main__ import _uvicorn_kwargs

    kwargs = _uvicorn_kwargs(app=object(), port=1234)
    assert kwargs["log_config"] is None
    assert kwargs["access_log"] is False
    assert kwargs["port"] == 1234
```

```python
# ghostbrain/api/tests/test_error_handler.py
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app


def test_unhandled_exception_is_logged_with_request_id(caplog):
    app = create_app("tok")
    router = APIRouter()

    @router.get("/v1/boom")
    def boom():
        raise ValueError("kaboom")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="ghostbrain.api"):
        r = client.get("/v1/boom", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == "Internal error"
    rid = body["requestId"]
    assert r.headers["X-Request-ID"] == rid
    assert any("kaboom" in rec.getMessage() or "kaboom" in (rec.exc_text or "") for rec in caplog.records)
    assert any(rid in rec.getMessage() for rec in caplog.records)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_logging_setup.py ghostbrain/api/tests/test_error_handler.py -q -p no:cacheprovider`
Expected: FAIL (`QUIET_LOGGERS` missing; `_uvicorn_kwargs` missing; 500 body is plain text).

- [ ] **Step 3: Implement**

`ghostbrain/api/runtime.py` — add above `setup_file_logging`:

```python
# Libraries that log every HTTP probe at INFO and bury real findings.
QUIET_LOGGERS: tuple[str, ...] = (
    "httpx", "httpcore", "huggingface_hub", "transformers",
    "sentence_transformers", "filelock", "urllib3",
)
```

and inside `setup_file_logging`, right before `return handler` (and also in the early-return branch, so it is idempotent), add:

```python
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
```

`ghostbrain/api/main.py` — add:

```python
import logging
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger("ghostbrain.api")


def install_error_handling(app: FastAPI) -> None:
    """Request ids + a traceback in the log for every unhandled exception.

    Without this, Starlette's traceback goes to uvicorn's stderr logger, which
    never propagates to the file handler — the 500 that broke the recorder for
    a first-run user left no line in sidecar.log at all.
    """

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        rid = uuid.uuid4().hex[:12]
        request.state.request_id = rid
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 — logged with traceback, then reported
            log.exception("unhandled error request_id=%s %s %s", rid, request.method, request.url.path)
            response = JSONResponse({"detail": "Internal error", "requestId": rid}, status_code=500)
        response.headers["X-Request-ID"] = rid
        return response
```

and call `install_error_handling(app)` in `create_app` immediately after the auth middleware line. (Middleware order: this one must be registered after auth so it wraps the auth layer too; FastAPI applies later-registered `app.middleware` decorators outermost. Verify with the test: an unauthenticated request must still get the auth middleware's 401, and the boom route must return the JSON body.)

`ghostbrain/api/__main__.py` — extract the `uvicorn.run(...)` arguments (currently around line 306) into:

```python
def _uvicorn_kwargs(app, port: int) -> dict:
    return {
        "app": app,
        "host": "127.0.0.1",
        "port": port,
        # log_config=None: don't let uvicorn install its own logging config.
        # Its default config sets propagate=False on the `uvicorn` logger, so
        # ASGI tracebacks went to stderr only and never reached sidecar.log.
        "log_config": None,
        "log_level": "info",
        "access_log": False,
    }
```

and call `uvicorn.run(**_uvicorn_kwargs(app, port))`. Keep any other kwargs the existing call passes (compare against the current call and carry them into the dict). Because uvicorn no longer configures a stderr handler, make sure the root logger has one so the Electron parent's stderr tail keeps working: in `_run_api_server`, after `setup_file_logging()`, add

```python
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers):
        root.addHandler(logging.StreamHandler(sys.stderr))
```

- [ ] **Step 4: Run tests and a live check**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor && .venv/bin/python -m pytest tests/test_logging_setup.py ghostbrain/api/tests -q -p no:cacheprovider`
Expected: PASS.

Live check: `GHOSTBRAIN_RUN_DIR=$(mktemp -d) .venv/bin/python -m ghostbrain.api & sleep 5; kill %1` then `grep -c "Uvicorn running" $GHOSTBRAIN_RUN_DIR/logs/sidecar.log` prints `1` (uvicorn's own INFO lines now reach the file). Use the printed temp dir path in place of the variable if your shell does not keep it.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add ghostbrain/api/runtime.py ghostbrain/api/main.py ghostbrain/api/__main__.py tests/test_logging_setup.py ghostbrain/api/tests/test_error_handler.py
git commit -m "fix(api): log unhandled exceptions with a request id; let uvicorn reach the log file; quiet httpx/HF"
```

---

### Task 20: Docs — macOS recorder page, connectors command spellings, Windows corrections

**Files:**
- Create: `docs/install/macos.md`
- Modify: `docs/connectors.md:3-5`, `docs/install/windows.md:148-150,169-173`

No automated test; the review gate is reading the rendered markdown once and running every command in it against the packaged app path.

- [ ] **Step 1: Write `docs/install/macos.md`**

```markdown
# macOS — recorder setup

The desktop app installs itself; the **meeting recorder** needs four things the
app cannot install for you without asking. The fastest path is the setup skill:
see the README's "Set up in five minutes with Claude Code". This page is the
manual equivalent, and what the skill does under the hood.

## What the recorder needs

| Piece | Why | Install |
|---|---|---|
| `ffmpeg` | captures BlackHole + microphone into one 16 kHz mono WAV | `brew install ffmpeg` |
| `whisper-cli` | whisper.cpp's CLI, transcribes locally | `brew install whisper-cpp` |
| a ggml model | what whisper-cli loads; `medium.en` is the default | `poltergeist setup fetch-model` (or drop any `ggml-*.bin` into `~/ghostbrain/recorder/models/`) |
| `SwitchAudioSource` | flips your output device for the meeting and back | `brew install switchaudio-osx` |
| BlackHole 2ch | virtual output so ffmpeg can hear what the meeting plays | `brew install --cask blackhole-2ch` (asks for your password) |
| a multi-output device | speakers **and** BlackHole at once, so you still hear the call | `poltergeist setup audio-device` |

Run everything at once:

```
poltergeist doctor                 # what is missing
poltergeist setup deps             # brew installs (BlackHole prompts for a password)
poltergeist setup fetch-model      # ~1.5 GB; pass base.en or small.en for smaller
poltergeist setup audio-device     # creates "Ghost Brain"
poltergeist doctor                 # should be all ✔
```

`poltergeist` is the shim the app installs from Settings → background →
"command line tool". Without it, the same binary is at
`/Applications/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api`.

## The multi-output device

The recorder switches macOS output to a device named by `recorder.audio_device`
in `<vault>/90-meta/config.yaml` (default **Ghost Brain**). It must be a
*Multi-Output* device (not an Aggregate) containing your speakers and BlackHole
2ch, with **Drift Correction** ticked on BlackHole: the virtual device and the
built-in output run on separate clocks and a long transcript desynchronises
without it. `setup audio-device` builds exactly that through CoreAudio; to do it
by hand, open Audio MIDI Setup → "+" → Create Multi-Output Device.

Calendar-driven recordings switch to the device automatically and switch back
when the meeting ends. The manual **Record** button requires the device to be
selected already; if it is not, the app tells you which device to pick.

To accept a differently named device, set `GHOSTBRAIN_ALLOWED_AUDIO_OUTPUTS`
to a comma-separated list of names in the app's environment.

## Models

`transcribe` resolves, in order: `GHOSTBRAIN_WHISPER_MODEL` if set, then
`ggml-medium.en.bin` in `~/ghostbrain/recorder/models/`, then the largest
`ggml-*.bin` in that directory. Sizes: base.en ≈ 142 MB, small.en ≈ 466 MB,
medium.en ≈ 1.5 GB.

## Checking it works

Start a manual recording from the Meetings screen, talk for fifteen seconds,
stop. Within a minute a transcript note appears under
`20-contexts/<context>/calendar/transcripts/`. If the status shows an error
instead, it names the missing piece; `poltergeist doctor` gives the fix.
```

- [ ] **Step 2: Fix `docs/connectors.md`**

Replace lines 3–5 with:

```markdown
Every Poltergeist connector follows the same shape: **create a credential → authenticate → add a block to `<vault>/90-meta/routing.yaml` → fetch.** The desktop app's connector cards do the first three for most connectors; this page is the full per-connector reference. For a guided walkthrough, use the `poltergeist-setup` Claude Code skill (see the README).

> **Command names.** Commands below are written as `poltergeist <sub>`, the shim the app installs from Settings → background → "command line tool". The same subcommands are available as `ghostbrain-api <sub>` (the bundled binary, at `/Applications/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api` on macOS) and, on a `pip install` from source, as `ghostbrain-<sub>`.
```

Then rewrite every fenced command in the file from `ghostbrain-<x>` to `poltergeist <x>` (`grep -n 'ghostbrain-' docs/connectors.md` lists them; the Claude Code section's hand-written `settings.json` JSON block is replaced by one line: run `poltergeist setup install-hook`, or use the app's Claude Code card, which does the same).

- [ ] **Step 3: Correct `docs/install/windows.md`**

Lines 148–150 become:

```markdown
Recorder preflight (`poltergeist doctor`, and the 412 the Record button returns
when something is missing) checks for `pyaudiowpatch`, `whisper-cli` on PATH,
and a model file, and reports exactly which piece is missing.
```

Lines 169–173 become:

```markdown
excluded (Apple Calendar isn't an option on Windows at all — that source is
darwin-only). Exclusion reasons for every configured-but-inactive source
show up in the recorder status response as `sourceExclusions`
(`GET /v1/recorder/status`); the desktop app does not display them yet.
```

- [ ] **Step 4: Verify links and commands**

Run: `grep -n 'ghostbrain-[a-z]' docs/connectors.md | grep -v 'ghostbrain-api\|ghostbrain-<sub>\|ghostbrain-api/ghostbrain-api'` → no output. `ls docs/install/macos.md`.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add docs/install/macos.md docs/connectors.md docs/install/windows.md
git commit -m "docs: macOS recorder setup page; poltergeist <sub> command spellings; correct Windows Meetings-tab claims"
```

---

### Task 21: The `poltergeist-setup` skill and the README's first section

**Files:**
- Create: `.claude/skills/poltergeist-setup/SKILL.md`, `.claude/skills/poltergeist-setup/checks.md`
- Delete: `.claude/skills/onboarding-poltergeist/SKILL.md`, `.claude/skills/onboarding-poltergeist/connectors.md`
- Modify: `README.md` (new section before line 77 `## Quick start`; delete line 152)

**Interfaces:**
- Consumes: `doctor --json` shape from Task 2; fix commands from Tasks 7–12; `/v1/recorder/{start,stop,status}` and the descriptor at `~/ghostbrain/run/sidecar.json`.

- [ ] **Step 1: Write `SKILL.md`**

```markdown
---
name: poltergeist-setup
description: Use when setting up Poltergeist (the getpoltergeist.com desktop app) for the first time, when its meeting recorder or connectors "don't do anything", or when the user says "set up poltergeist", "poltergeist doctor", "connect <tool> to poltergeist". Runs the app's own doctor, fixes what it can with consent, and ends with a verified test recording.
---

# Poltergeist setup

You drive `doctor` and `setup` inside the Poltergeist binary; you do not
re-derive checks yourself. One step per turn. Never run `sudo`. Never batch
fixes. If the same check fails twice with the same output, stop and give the
user the output to paste into a GitHub issue.

## 1. Find the binary

Try, in order, and remember the first that exists as `$PG`:

1. `command -v poltergeist`
2. `/Applications/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api`
3. `%LOCALAPPDATA%\Programs\Poltergeist\resources\sidecar\ghostbrain-api\ghostbrain-api.exe`

None found → the app is not installed. Send the user to
https://github.com/nikrich/poltergeist/releases/latest, ask them to open it
once, and stop.

## 2. Run doctor

`"$PG" doctor --json`. Render every check as one line: ✔ ok, ✘ fail, ! warn,
- skip, then the summary. Read `checks.md` for what each id means. If nothing
is `fail`, go to step 4.

## 3. Walk the failures, one per turn, in the order doctor lists them

For each `fail` (then each `warn` the user cares about):

- One sentence: what it is and why the recorder or sync needs it.
- Show the fix command from the JSON (`fix.command`).
- `automated` → run `"$PG" <fix.command>` after the user says yes. Stream the
  output; brew installs take minutes.
- `interactive` → the command needs a macOS password. Give the user exactly
  `"$PG" <fix.command>` to paste into Terminal, wait for them to say it's done.
- `manual` → tell them the Settings path or action in `fix.command` and wait.

Re-run `"$PG" doctor --json` and confirm only that check changed before
moving on. The `app` check failing after a fix usually means the app needs a
restart: quit, wait ten seconds, reopen.

## 4. Prove it with a real recording

Read `port` and `token` from `~/ghostbrain/run/sidecar.json`. Then:

1. `curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"context":"<first context from the contexts check>"}' http://127.0.0.1:$PORT/v1/recorder/start`
   - 412 → the body names the missing piece; go back to step 3.
2. Ask the user to say a few sentences out loud for fifteen seconds.
3. `curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:$PORT/v1/recorder/stop`
4. Poll `GET /v1/recorder/status` every five seconds until `phase` is `done`.
   `error` non-null → show it verbatim and go back to step 3.
5. Open the note at `<vault>/<transcriptPath>` and show the first lines.
6. `curl -s -X POST ... /v1/recorder/clear`.

Do not tell the user setup is complete before this step succeeds.

## 5. Connectors

Ask which of these matter: Claude Code, GitHub, Jira/Confluence, Slack,
Gmail, Google Calendar, Apple Calendar, Microsoft 365, Joplin. For each:

- Point them at the app's connector card (Connectors screen) for the
  credential step. The cards work.
- Claude Code needs no credential: `"$PG" setup install-hook`.
- Verify with `"$PG" <connector>-fetch` and confirm the routing block is
  non-empty in `<vault>/90-meta/routing.yaml` (`github.orgs`, `gmail.accounts`,
  `calendar.macos.accounts`, `slack.workspaces`, ...). A connector that shows
  "on" with an empty block syncs nothing; add the org/account by hand, one
  line, and re-fetch.

## 6. Going live

If the `routing-mode` check is `warn` and `data.inbox_count` > 0: explain in
two sentences that review mode keeps everything in the inbox and the app's
views only show filed notes, then offer `"$PG" setup go-live`.

## 7. Finish

Final `"$PG" doctor`. Report what is ✔, what remains ! and why that is fine.
```

- [ ] **Step 2: Write `checks.md`**

One paragraph per id, in doctor order, each answering: what it means, what the fix does, what to say when it fails twice. Cover exactly these ids: `app`, `vault`, `contexts`, `claude-cli`, `ffmpeg`, `whisper-cli`, `whisper-model`, `switchaudio`, `blackhole`, `audio-device`, `audio-routing`, `scheduler`, `routing-mode`, `connectors`, `claude-hook`, `cli-shim`, `recorder-backend`. Source the wording from the `detail` strings in Tasks 3–5 and the spec's catalog table. For `app` include the relaunch-race explanation (read-only sidecar after a quick reopen). For `blackhole` and `deps` include that Homebrew itself needs a password to install (https://brew.sh). For `connectors` include the per-connector routing keys listed in step 5 of `SKILL.md`. Also fold in the three still-accurate gotchas from the old `onboarding-poltergeist/connectors.md` (Google consent screen expiry, Microsoft device-code scopes, per-connector block required) under a final "Connector gotchas" heading, and delete the old skill directory.

- [ ] **Step 3: README**

Insert before line 77 (`## Quick start`):

```markdown
## Set up in five minutes with Claude Code

1. [Download Poltergeist](https://github.com/nikrich/poltergeist/releases/latest) and open it once.
2. Install the setup skill:
   ```bash
   npx skills add nikrich/poltergeist
   ```
   No Node? `curl -fsSL https://github.com/nikrich/poltergeist/archive/main.tar.gz | tar -xz --strip-components=3 -C ~/.claude/skills poltergeist-main/.claude/skills/poltergeist-setup`
3. Open Claude Code anywhere and say **"set up Poltergeist"**.

It runs the app's own `doctor`, installs what is missing with your consent (ffmpeg, whisper, the audio device, the Claude Code hook), and finishes with a real test recording. Prefer to do it by hand? `poltergeist doctor` prints the same checklist; see [docs/install/macos.md](docs/install/macos.md).
```

Delete line 152 (the "connect buttons are placeholders" note).

- [ ] **Step 4: Verify both install commands against a fresh skills dir**

Run, from any directory: `export HOME_SKILLS=$(mktemp -d) && mkdir -p $HOME_SKILLS/.claude/skills`. Push the branch first (`git push -u origin feat/setup-doctor`) so the tarball URL has the files, then test the curl line with `main.tar.gz` replaced by `feat/setup-doctor.tar.gz` and `poltergeist-main` by `poltergeist-feat-setup-doctor`, targeting `$HOME_SKILLS/.claude/skills`; confirm `SKILL.md` and `checks.md` land in `poltergeist-setup/`. Then `cd $HOME_SKILLS && HOME=$HOME_SKILLS npx --yes skills add nikrich/poltergeist#feat/setup-doctor` (or the CLI's branch syntax per `npx skills add --help`); confirm it discovers `poltergeist-setup`. If the `skills` CLI cannot discover a skill under `.claude/skills/`, move the skill to `skills/poltergeist-setup/` at the repo root, keep a symlink at `.claude/skills/poltergeist-setup`, and update both README commands accordingly. Record which form worked in the commit message.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git add .claude/skills README.md
git rm -r -q .claude/skills/onboarding-poltergeist
git commit -m "feat(skill): poltergeist-setup Claude Code skill; README opens with the five-minute setup"
```

---

### Task 22: Release 1.5.0 and the clean-account acceptance run

**Files:**
- Modify: `.release-please-manifest.json`, `desktop/package.json`, `desktop/CHANGELOG.md` (all via `scripts/release.sh`)

- [ ] **Step 1: Open the PR and merge**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/setup-doctor
git push -u origin feat/setup-doctor
gh auth switch -u nikrich   # the active gh account flips to an enterprise user and 401s on this repo
gh pr create --base main --title "feat: setup doctor, setup fixes, Claude Code setup skill, first-run companion fixes" --body-file docs/superpowers/specs/2026-09-10-setup-doctor-design.md
gh pr checks --watch
```

Wait for `backend` and `desktop` to pass, then `gh pr merge --squash --delete-branch`.

- [ ] **Step 2: Cut the release**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-v133   # main is checked out here
git pull --ff-only origin main
scripts/release.sh 1.5.0
git show --stat HEAD
git push origin HEAD:main
gh run list --workflow release.yml --limit 1
```

Watch the run to completion (`gh run watch <id>`); all of `release-please`, `build-mac`, `build-win`, `build-linux` must be `success` and `gh release view v1.5.0 --json assets -q '.assets|length'` must be 12.

- [ ] **Step 3: Post-release sidecar check**

Download `Poltergeist-1.5.0-arm64-mac.zip` to a scratch dir, `ditto -x -k` it, and run
`Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api doctor --json` with `HOME` pointed at an empty temp dir. It must print a complete JSON document (every id from the Global Constraints list present, most `fail`) and exit 1. Then run `... setup audio-device --dry-run` on the dev Mac: it must print `already exists` (the device is present there), proving the CoreAudio binding is inside the frozen bundle. Remove the scratch dir.

- [ ] **Step 4: Acceptance on a clean macOS user account**

On the dev Mac, create a temporary Standard user, log in, install only `Poltergeist-1.5.0-arm64.dmg` and Claude Code. Install the skill with each README command. Say "set up Poltergeist" and follow it through the BlackHole Terminal handoff to the test recording and a transcript note. Note every place the skill's wording needed a human to improvise; each is a `checks.md`/`SKILL.md` fix for a follow-up PR. Delete the user afterwards. Paste the final `doctor` table into the release notes on GitHub.

- [ ] **Step 5: Memory note**

Append to the project memory file `release-flow-gotchas.md`: "v1.5.0 shipped <date>: doctor/setup/skill (spec 2026-09-10). Acceptance run on a clean account: <result>."
