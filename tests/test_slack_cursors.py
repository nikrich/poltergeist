"""Tests for the Slack per-channel cursor state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.connectors.slack.cursors import (
    CursorState,
    cursor_path,
    load_cursors,
)


def test_load_cursors_empty_when_no_file(tmp_path: Path) -> None:
    state = load_cursors(tmp_path, "sft")
    assert isinstance(state, CursorState)
    assert state.channels == {}
    assert state.get("C1") is None
    assert state.path == cursor_path(tmp_path, "sft")


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    state = load_cursors(tmp_path, "sft")
    state.set("C1", last_ts="1778250000.000001", name="engineering")
    state.set("C2", last_ts="1778250001.123456", name="sanlam-ops")
    state.save()

    reloaded = load_cursors(tmp_path, "sft")
    assert reloaded.get("C1") == "1778250000.000001"
    assert reloaded.get("C2") == "1778250001.123456"
    assert reloaded.channels["C1"]["name"] == "engineering"


def test_corrupt_file_returns_empty_state(tmp_path: Path) -> None:
    path = cursor_path(tmp_path, "sft")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not valid json {", encoding="utf-8")

    state = load_cursors(tmp_path, "sft")
    assert state.channels == {}
    assert state.get("C1") is None


def test_workspaces_have_separate_files(tmp_path: Path) -> None:
    a = load_cursors(tmp_path, "sft")
    a.set("C1", last_ts="111", name="x")
    a.save()
    b = load_cursors(tmp_path, "codeship")
    b.set("C1", last_ts="222", name="y")
    b.save()

    assert load_cursors(tmp_path, "sft").get("C1") == "111"
    assert load_cursors(tmp_path, "codeship").get("C1") == "222"


def test_save_is_atomic(tmp_path: Path) -> None:
    """Save writes to .tmp and renames, so a partial write never corrupts
    a previously-good file."""
    state = load_cursors(tmp_path, "sft")
    state.set("C1", last_ts="1", name="x")
    state.save()

    # Ensure the .tmp sibling is cleaned up.
    siblings = list(state.path.parent.iterdir())
    tmps = [p for p in siblings if p.name.endswith(".tmp")]
    assert not tmps, f"leftover tmp file: {tmps}"

    payload = json.loads(state.path.read_text())
    assert payload["version"] == 1
    assert payload["channels"]["C1"]["last_ts"] == "1"
