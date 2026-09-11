from __future__ import annotations

from ghostbrain.doctor.fixes import deps


def _which(present: set[str]):
    return lambda name: f"/opt/homebrew/bin/{name}" if name in present else None


def test_missing_brew_is_a_manual_instruction(monkeypatch, capsys):
    monkeypatch.setattr(deps, "_brew", lambda: None)
    assert deps.main([]) == 1
    assert "https://brew.sh" in capsys.readouterr().err


def test_installs_only_missing_packages(monkeypatch):
    monkeypatch.setattr(deps, "_brew", lambda: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(deps, "_is_installed", lambda name: name == "ffmpeg")
    calls: list[list[str]] = []
    monkeypatch.setattr(deps, "_run", lambda cmd: calls.append(cmd) or 0)
    assert deps.main([]) == 0
    assert calls == [
        ["/opt/homebrew/bin/brew", "install", "whisper-cpp"],
        ["/opt/homebrew/bin/brew", "install", "switchaudio-osx"],
        ["/opt/homebrew/bin/brew", "install", "--cask", "blackhole-2ch"],
    ]


def test_only_limits_to_named_packages(monkeypatch):
    monkeypatch.setattr(deps, "_brew", lambda: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(deps, "_is_installed", lambda name: False)
    calls: list[list[str]] = []
    monkeypatch.setattr(deps, "_run", lambda cmd: calls.append(cmd) or 0)
    assert deps.main(["--only", "ffmpeg", "--only", "blackhole"]) == 0
    assert calls == [
        ["/opt/homebrew/bin/brew", "install", "ffmpeg"],
        ["/opt/homebrew/bin/brew", "install", "--cask", "blackhole-2ch"],
    ]


def test_stops_at_first_brew_failure(monkeypatch, capsys):
    monkeypatch.setattr(deps, "_brew", lambda: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(deps, "_is_installed", lambda name: False)
    monkeypatch.setattr(deps, "_run", lambda cmd: 1)
    assert deps.main([]) == 1
    assert "brew install ffmpeg failed" in capsys.readouterr().err


def test_unknown_only_name(capsys):
    assert deps.main(["--only", "vim"]) == 2
    assert "unknown dependency" in capsys.readouterr().err


def test_non_darwin_refuses(monkeypatch, capsys):
    monkeypatch.setattr(deps, "_platform", lambda: "linux")
    assert deps.main([]) == 1
    assert "macOS only" in capsys.readouterr().err
