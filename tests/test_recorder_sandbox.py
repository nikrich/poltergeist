"""Guard: no recorder path may point at the real home directory in tests.

A test once stopped a live meeting recording because the manual-recording
state file was resolved from the real home at import time (2026-10-09).
"""
from __future__ import annotations

import os
from pathlib import Path

from ghostbrain.api.repo import recorder as repo
from ghostbrain.recorder import config, daemon, manual, transcribe


def _paths() -> dict[str, Path]:
    return {
        "config.DEFAULT_RECORDINGS_DIR": config.DEFAULT_RECORDINGS_DIR,
        "daemon.DEFAULT_RECORDINGS_DIR": daemon.DEFAULT_RECORDINGS_DIR,
        "manual.DEFAULT_RECORDINGS_DIR": manual.DEFAULT_RECORDINGS_DIR,
        "repo.RECORDINGS_DIR": repo.RECORDINGS_DIR,
        "repo.STATE_FILE": repo.STATE_FILE,
        "transcribe.DEFAULT_MODEL_DIR": transcribe.DEFAULT_MODEL_DIR,
    }


def test_no_recorder_path_points_at_the_real_home() -> None:
    real_home = Path(os.environ["REAL_HOME_FOR_TEST"]).resolve()
    leaks = {
        name: p for name, p in _paths().items()
        if p.resolve().is_relative_to(real_home)
    }
    assert not leaks, f"recorder paths escape the test sandbox: {leaks}"


def test_every_home_derived_module_constant_is_covered() -> None:
    """A new module-level ``Path.home()`` in the recorder must be sandboxed."""
    root = Path(__file__).resolve().parents[1] / "ghostbrain"
    known = {"config.py", "transcribe.py"}  # both overridden in conftest.py
    offenders = []
    for path in [*root.joinpath("recorder").glob("*.py"), root / "api" / "repo" / "recorder.py"]:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line[0].isspace() and "Path.home()" in line and path.name not in known:
                offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, offenders
