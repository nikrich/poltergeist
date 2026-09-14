from __future__ import annotations

import json

from ghostbrain.doctor.fixes import audio_device as ad


def test_description_is_a_stacked_public_aggregate_with_drift_on_blackhole():
    desc = ad.build_description("Ghost Brain", speakers_uid="BuiltInSpeakerDevice", blackhole_uid="BlackHole2ch_UID")
    assert desc == {
        "name": "Ghost Brain",
        "uid": "com.getpoltergeist.multioutput",
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


def test_unexpected_create_return_shape_is_one_line_failure(monkeypatch, capsys):
    monkeypatch.setattr(ad, "_platform", lambda: "darwin")
    monkeypatch.setattr(ad, "_configured_name", lambda: "Ghost Brain")
    monkeypatch.setattr(ad, "_existing_output_names", lambda: [])
    monkeypatch.setattr(ad, "_find_uids", lambda: ("S", "B"))
    monkeypatch.setattr(ad, "_create", lambda desc: (_ for _ in ()).throw(TypeError("cannot unpack non-iterable int object")))
    assert ad.main([]) == 1
    assert "audio-device failed" in capsys.readouterr().err


def test_enumeration_type_error_is_one_line_failure(monkeypatch, capsys):
    monkeypatch.setattr(ad, "_platform", lambda: "darwin")
    monkeypatch.setattr(ad, "_configured_name", lambda: "Ghost Brain")
    monkeypatch.setattr(ad, "_existing_output_names", lambda: [])
    monkeypatch.setattr(ad, "_find_uids", lambda: (_ for _ in ()).throw(TypeError("bad pointer")))
    assert ad.main([]) == 1
    assert "audio-device failed" in capsys.readouterr().err
