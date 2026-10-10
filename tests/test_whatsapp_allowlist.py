from __future__ import annotations

import json

from ghostbrain.connectors.whatsapp import allowlist


def test_missing_file_is_empty(tmp_path):
    assert allowlist.load(tmp_path) == {}


def test_round_trip_leaves_no_temp_file(tmp_path):
    chats = {"1@s.whatsapp.net": {"name": "Alex", "context": None},
             "2@g.us": {"name": "Club", "context": "work"}}
    allowlist.save(tmp_path, chats)
    assert allowlist.load(tmp_path) == chats
    assert json.loads((tmp_path / allowlist.FILENAME).read_text())["chats"] == chats
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_file_is_empty(tmp_path):
    (tmp_path / allowlist.FILENAME).write_text("{not json")
    assert allowlist.load(tmp_path) == {}


def test_chats_not_a_dict_is_empty(tmp_path):
    (tmp_path / allowlist.FILENAME).write_text(json.dumps({"chats": 5}))
    assert allowlist.load(tmp_path) == {}


def test_chats_a_list_is_empty(tmp_path):
    (tmp_path / allowlist.FILENAME).write_text(json.dumps({"chats": [1]}))
    assert allowlist.load(tmp_path) == {}


def test_top_level_not_a_dict_is_empty(tmp_path):
    (tmp_path / allowlist.FILENAME).write_text(json.dumps([1, 2]))
    assert allowlist.load(tmp_path) == {}


def test_non_dict_entries_are_dropped(tmp_path):
    (tmp_path / allowlist.FILENAME).write_text(json.dumps(
        {"chats": {"a": {"name": "A", "context": None}, "b": "junk"}}))
    assert allowlist.load(tmp_path) == {"a": {"name": "A", "context": None}}


def test_unreadable_file_is_empty(tmp_path):
    (tmp_path / allowlist.FILENAME).mkdir()
    assert allowlist.load(tmp_path) == {}
