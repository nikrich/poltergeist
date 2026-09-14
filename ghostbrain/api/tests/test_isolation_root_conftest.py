"""Verify that the root conftest isolation fixture covers API tests."""
from __future__ import annotations

import os
from pathlib import Path


def test_api_tree_uses_root_conftest_isolation():
    """Confirm the root conftest's _isolate_user_state fixture sandboxes API tests."""
    assert Path.home() != Path(os.environ["REAL_HOME_FOR_TEST"])
