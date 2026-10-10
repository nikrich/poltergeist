"""Spoken-command detection for the live design session."""
from __future__ import annotations

import pytest

from ghostbrain.design import commands
from ghostbrain.design.commands import Command


class FakeResult:
    def __init__(self, data):
        self._data = data

    def as_json(self):
        return self._data


def fake_run(answer, calls):
    def run(prompt, **kw):
        calls.append((prompt, kw))
        return FakeResult(answer)
    return run


@pytest.mark.parametrize("text", [
    "let's kick off a frontend prototype",
    "can we look at the front end",
    "the UI needs a second screen",
    "a quick mockup would help",
    "let's focus on the backend now",
    "time for some event storming",
    "let's stop prototyping",
    "park the design stuff",
    "let's pick the prototype back up",
    "switch to the board",
])
def test_prefilter_matches_meeting_direction_phrases(text):
    assert commands.PREFILTER.search(text)


@pytest.mark.parametrize("text", [
    "how was your weekend",
    "the quarterly numbers look fine",
    "I'll send the invoice tomorrow",
    "building a guide for the team",  # "ui" only inside a word
])
def test_prefilter_ignores_small_talk(text):
    assert not commands.PREFILTER.search(text)


def test_detect_skips_llm_when_prefilter_misses():
    calls: list = []
    run = fake_run({"command": "start_ui", "canvas": "ui", "text": None}, calls)
    assert commands.detect("", "how was your weekend", focus=None, states={}, run=run) is None
    assert calls == []


def test_detect_returns_command_with_default_canvas():
    calls: list = []
    run = fake_run({"command": "start_ui", "canvas": None, "text": None}, calls)
    cmd = commands.detect(
        "we need a claims screen", "let's kick off a frontend prototype",
        focus=None, states={"ui": "off", "board": "off"}, run=run,
    )
    assert cmd == Command("start_ui", "ui", None)
    prompt, kw = calls[0]
    assert kw["model"] == "haiku"
    assert kw["json_schema"]["properties"]["command"]["enum"]
    assert "let's kick off a frontend prototype" in prompt
    assert "we need a claims screen" in prompt


def test_detect_none_is_none():
    run = fake_run({"command": "none", "canvas": None, "text": None}, [])
    assert commands.detect("", "let's grab lunch", focus=None, states={}, run=run) is None


def test_detect_nudge_needs_text_and_an_active_canvas():
    run = fake_run({"command": "nudge", "canvas": None, "text": "make the table sortable"}, [])
    assert commands.detect("", "make that design table sortable", focus=None,
                           states={"ui": "off", "board": "off"}, run=run) is None
    cmd = commands.detect("", "make that design table sortable", focus="ui",
                          states={"ui": "active", "board": "off"}, run=run)
    assert cmd == Command("nudge", "ui", "make the table sortable")
    empty = fake_run({"command": "nudge", "canvas": "ui", "text": ""}, [])
    assert commands.detect("", "design it", focus="ui", states={"ui": "active"}, run=empty) is None


def test_detect_pause_defaults_to_both():
    run = fake_run({"command": "pause", "canvas": None, "text": None}, [])
    cmd = commands.detect("", "let's stop prototyping", focus="ui",
                          states={"ui": "active", "board": "off"}, run=run)
    assert cmd == Command("pause", "both", None)


def test_detect_swallows_llm_failure():
    def boom(prompt, **kw):
        raise RuntimeError("claude missing")
    assert commands.detect("", "let's focus on the backend", focus=None, states={}, run=boom) is None


def test_detect_rejects_unknown_command():
    run = fake_run({"command": "delete_everything", "canvas": "ui", "text": None}, [])
    assert commands.detect("", "let's design", focus=None, states={}, run=run) is None


def test_prompt_accepts_split_sentences_questions_and_misheard_names():
    prompt = commands.PROMPT.lower()
    assert "split" in prompt
    assert "are you going to start the front end prototype" in prompt
    assert "polter guys" in prompt
    assert "when in doubt, answer none" not in prompt


# -- codebase hint -------------------------------------------------------------

def test_detect_returns_codebase_hint_for_start_ui():
    run = fake_run({"command": "start_ui", "canvas": "ui", "text": None, "codebase": "Atlas frontend"}, [])
    cmd = commands.detect("", "today we're working on Atlas, use our existing frontend",
                          focus=None, states={}, run=run)
    assert cmd == Command("start_ui", "ui", None, "Atlas frontend")


def test_codebase_dropped_for_other_commands():
    run = fake_run({"command": "focus_board", "canvas": "board", "text": None, "codebase": "Atlas"}, [])
    assert commands.detect("", "let's focus on the backend", focus="ui", states={}, run=run).codebase is None


def test_blank_codebase_is_none():
    run = fake_run({"command": "start_ui", "canvas": "ui", "text": None, "codebase": "  "}, [])
    assert commands.detect("", "let's kick off a prototype", focus=None, states={}, run=run).codebase is None


def test_schema_and_prompt_mention_codebase():
    assert "codebase" in commands.SCHEMA["required"]
    assert "existing" in commands.PROMPT and "codebase" in commands.PROMPT


@pytest.mark.parametrize("text", [
    "use our existing app",
    "work in the repository",
    "extend the claims portal",
    "open the codebase",
])
def test_prefilter_matches_codebase_phrases(text):
    assert commands.PREFILTER.search(text)


def test_update_command_defaults_to_the_focused_active_canvas():
    run = fake_run({"command": "update", "canvas": None, "text": None, "codebase": None}, [])
    cmd = commands.detect("", "please do the update as we discussed", focus="ui",
                          states={"ui": "active", "board": "off"}, run=run)
    assert cmd == Command("update", "ui", None)
    assert commands.detect("", "update it", focus=None, states={"ui": "off"}, run=run) is None


def test_prefilter_catches_update_complaints():
    assert commands.PREFILTER.search("Why are you not updating?")
    assert commands.PREFILTER.search("please do the update")
