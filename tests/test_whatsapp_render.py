from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ghostbrain.connectors.whatsapp.render import render_day
from ghostbrain.connectors.whatsapp.store import Message

TZ = ZoneInfo("Africa/Johannesburg")


def msg(pk, t, *, text=None, caption=None, sender="Alex", me=False, hh=9, mm=0, path=None):
    return Message(pk=pk, stanza_id=f"S{pk}", at=datetime(2026, 10, 9, hh, mm, tzinfo=TZ),
                   sender="Me" if me else sender, is_from_me=me, type_code=t, text=text,
                   caption=caption, media_path=path)


def no_voice(m):
    raise AssertionError("voice not expected")


def test_type_mapping():
    msgs = [
        msg(1, 0, text="hello"),
        msg(2, 1), msg(3, 1, caption="sunset"),
        msg(4, 2), msg(5, 2, caption="clip"),
        msg(6, 4), msg(7, 5),
        msg(8, 7, text="look https://example.com"),
        msg(9, 8, text="report.pdf"), msg(10, 8),
        msg(11, 11),
        msg(12, 14), msg(13, 15), msg(14, 59), msg(15, 66), msg(16, 10, text="x joined"),
        msg(17, 0, text="   "),
    ]
    out = render_day(msgs, no_voice)
    assert out.body.splitlines() == [
        "**09:00 Alex:** hello",
        "**09:00 Alex:** [image]",
        "**09:00 Alex:** [image: sunset]",
        "**09:00 Alex:** [video]",
        "**09:00 Alex:** [video: clip]",
        "**09:00 Alex:** [contact card]",
        "**09:00 Alex:** [location]",
        "**09:00 Alex:** look https://example.com",
        "**09:00 Alex:** [document: report.pdf]",
        "**09:00 Alex:** [document]",
        "**09:00 Alex:** [gif]",
    ]
    assert out.lines == 11


def test_multiline_text_is_indented():
    out = render_day([msg(1, 0, text="line one\nline two")], no_voice)
    assert out.body == "**09:00 Alex:** line one\n  line two"


def test_voice_lines_and_pending_flag():
    calls = []

    def voice(m):
        calls.append(m.pk)
        return ("🎙 hi there", False) if m.pk == 1 else ("[voice note — transcription pending]", True)

    out = render_day([msg(1, 3, me=True, mm=5), msg(2, 3, mm=6)], voice)
    assert calls == [1, 2]
    assert out.body.splitlines() == [
        "**09:05 Me:** 🎙 hi there",
        "**09:06 Alex:** [voice note — transcription pending]",
    ]
    assert out.voice_notes == 2 and out.pending is True


def test_participants_sorted_unique_and_empty_day():
    out = render_day([msg(1, 0, text="a", sender="Zed"), msg(2, 0, text="b", me=True),
                      msg(3, 0, text="c", sender="Zed")], no_voice)
    assert out.participants == ["Me", "Zed"]
    empty = render_day([msg(1, 15)], no_voice)
    assert empty.lines == 0 and empty.body == "" and empty.participants == []
