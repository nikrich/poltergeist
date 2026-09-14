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
