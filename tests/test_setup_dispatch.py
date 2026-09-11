from __future__ import annotations

from ghostbrain.doctor import setup


def test_setup_is_registered_subcommand():
    from ghostbrain.api.__main__ import SUBCOMMANDS

    assert SUBCOMMANDS["setup"] == "ghostbrain.doctor.setup:main"


def test_dispatch_passes_remaining_args(monkeypatch):
    seen = {}

    def fake_fix(argv):
        seen["argv"] = argv
        return 7

    monkeypatch.setattr(setup, "FIXES", {"deps": "tests.test_setup_dispatch:_fake_fix"})
    monkeypatch.setattr(setup, "_load", lambda target: fake_fix)
    assert setup.main(["deps", "--only", "ffmpeg"]) == 7
    assert seen["argv"] == ["--only", "ffmpeg"]


def test_unknown_fix_is_usage_error(capsys):
    assert setup.main(["nope"]) == 2
    assert "available:" in capsys.readouterr().err


def test_no_args_prints_usage(capsys):
    assert setup.main([]) == 2
    assert "usage:" in capsys.readouterr().err
