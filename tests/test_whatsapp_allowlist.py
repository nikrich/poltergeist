from __future__ import annotations

import json

from ghostbrain.connectors.whatsapp import allowlist


def test_missing_file_is_empty(tmp_path):
    assert allowlist.load(tmp_path) == {}


def test_round_trip_and_atomic(tmp_path):
    chats = {"1@s.whatsapp.net": {"name": "Alex", "context": None},
             "2@g.us": {"name": "Club", "context": "work"}}
    allowlist.save(tmp_path, chats)
    assert allowlist.load(tmp_path) == chats
    assert json.loads((tmp_path / allowlist.FILENAME).read_text())["chats"] == chats
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_file_is_empty(tmp_path):
    (tmp_path / allowlist.FILENAME).write_text("{not json")
    assert allowlist.load(tmp_path) == {}
