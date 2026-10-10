from __future__ import annotations

from pathlib import Path

from ghostbrain.worker import note_generator, router


def ev(name="Alex Example", jid="27820000001@s.whatsapp.net", ctx=None, day="2026-10-09"):
    return {
        "id": f"whatsapp:day:{jid}:{day}", "source": "whatsapp", "type": "chat_day",
        "timestamp": f"{day}T08:00:00+00:00", "title": f"{name} — {day}", "body": "x",
        "metadata": {"chatJid": jid, "chatName": name, "chatKind": "direct", "day": day,
                     "participants": ["Alex Example", "Me"], "messageCount": 3,
                     "voiceNotes": 1, "context": ctx},
    }


def _contexts(vault: Path, *names: str) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.write_text("contexts:\n" + "".join(f"  - {n}\n" for n in names), encoding="utf-8")


def test_override_then_default_then_personal(vault: Path):
    _contexts(vault, "personal", "work")
    assert router._fast_route(ev(ctx="work"), {}).context == "work"
    d = router._fast_route(ev(), {"whatsapp": {"default_context": "work"}})
    assert d.context == "work" and d.method == "path"
    assert router._fast_route(ev(), {}).context == "personal"


def test_unknown_contexts_fall_back_to_first_configured(vault: Path):
    _contexts(vault, "home", "work")
    assert router._fast_route(ev(ctx="gone"), {}).context == "home"


def test_filename_stable_across_rebuilds_and_unique_per_jid():
    a1 = note_generator._filename_for(ev(), "whatsapp:day:x")
    a2 = note_generator._filename_for({**ev(), "timestamp": "2026-10-09T22:00:00+00:00"}, "id")
    assert a1 == a2 == "2026-10-09-alex-example-27820000001.md"
    g1 = note_generator._filename_for(ev("Club", "120363000000000001@g.us"), "i")
    g2 = note_generator._filename_for(ev("Club", "120363999900000001@g.us"), "i")
    assert g1 != g2
    assert note_generator._filename_for(ev("😀😀"), "i").startswith("2026-10-09-chat-")


def test_frontmatter_keys():
    from ghostbrain.worker.router import RoutingDecision
    front = note_generator._build_frontmatter(
        ev(), RoutingDecision("personal", 1.0, "r", "path"), note_id="whatsapp:day:x")
    for key in ("chatJid", "chatName", "chatKind", "day", "participants", "messageCount",
                "voiceNotes"):
        assert key in front
