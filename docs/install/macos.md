# Installing Poltergeist on macOS

> The desktop app is self-contained — it auto-bootstraps the vault on first
> launch and bundles the whole CLI as `ghostbrain-api <subcommand>` (no
> Python install needed). Most of this page covers the headless/pip setup:
> everything below is for running Poltergeist from source instead of the
> packaged app, where `ghostbrain-api <subcommand>` is replaced by the
> pip-installed `ghostbrain-<subcommand>` scripts. The **Meeting recorder**
> section applies to both.

## Prerequisites

- **macOS 15 (Sequoia) or newer** for native meeting capture. Older macOS
  still works with the BlackHole fallback described below.
- **Python 3.11+** — `brew install python@3.12` (or newer).
- **Obsidian** — [obsidian.md](https://obsidian.md/download).
- **Claude Code CLI** — required for the LLM backend. See [installing Claude Code](https://claude.ai/docs/download).
- **Xcode Command Line Tools** — only if you build the native capture helper
  yourself (`xcode-select --install`, Xcode 16+ / macOS 15 SDK).

## Clone and install

```bash
git clone <repository-url> ghost-brain
cd ghost-brain
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,api]"
```

The `[api]` extra is needed if you want the desktop app to spawn the sidecar from your venv during development.

## Bootstrap the vault

```bash
ghostbrain-bootstrap
export VAULT_PATH="$HOME/ghostbrain/vault"   # add to ~/.zshrc
```

## Install Obsidian plugins

Open the vault in Obsidian, then **Settings → Community plugins** and install
Dataview, Templater, Periodic Notes and Local REST API.

## Configure routing

Edit `<vault>/90-meta/routing.yaml` to map your sources to context names.
The README covers routing in detail. For Apple Calendar, the keys under
`calendar.macos.accounts` are Calendar.app **calendar names**, not account
names.

## Always-on scheduler

Use the desktop app's built-in scheduler (**Settings → Background → run
scheduler in-app**). The legacy launchd templates are documented in
[macos-launchd.md](./macos-launchd.md).

## Meeting recorder

The recorder captures **system audio + your microphone** into a 16 kHz mono
WAV, transcribes it locally with whisper.cpp, and files the transcript under
`20-contexts/<ctx>/calendar/transcripts/`, linked to the matching calendar
event note. On macOS there are two capture methods, selected by
`recorder.capture_backend` in `<vault>/90-meta/config.yaml` (or **Settings →
meetings → capture method** in the desktop app):

| `capture_backend` | What it uses | Needs |
|---|---|---|
| `auto` (default) | native when available, else blackhole | — |
| `native` | ScreenCaptureKit via the bundled `ghostbrain-capture` helper | macOS 15+, Screen Recording + Microphone permission |
| `blackhole` | ffmpeg reading a BlackHole virtual device + mic, SwitchAudioSource to flip your output | Homebrew: ffmpeg, blackhole-2ch, switchaudio-osx; a Multi-Output device |

Whichever method you use, transcription needs whisper.cpp (see below).

### Native capture (macOS 15+, default)

One helper process (`ghostbrain-capture`, Swift, ScreenCaptureKit) records
everything you hear plus the mic — no virtual audio device, no output
switching, no ffmpeg. Because the same stream carries the screen, it also
captures **slides**: it samples the meeting window at ~1 fps, keeps only
frames that changed, OCRs them with Apple Vision, and appends a `## Slides`
section (timestamp, image, recognised text) to the transcript note. Images
land under `90-meta/assets/transcripts/<YYYY>/<MM>/<note>/`. No video is
kept.

**Where the helper comes from**

- The packaged desktop app bundles it at
  `Poltergeist.app/Contents/Resources/bin/ghostbrain-capture`. Nothing to do.
- From source, build it once (needs Xcode 16+):

  ```bash
  scripts/build-native-macos.sh --install   # → ~/.local/bin/ghostbrain-capture
  ```

  The recorder finds it via `GHOSTBRAIN_CAPTURE_BIN`, then the app bundle,
  then `PATH`. If it is missing, `auto` quietly falls back to `blackhole` and
  the preflight message tells you why.

**Permissions**

The helper needs **Screen Recording** (this single permission covers system
audio *and* slides on macOS) and **Microphone**. macOS only lists an app under
Screen Recording after it has *tried* to capture once, so:

1. In the desktop app: **Settings → meetings → native capture → grant access**.
   It triggers the prompts, then opens the right System Settings pane.
2. From a terminal: `ghostbrain-capture request-permissions`. Note that when
   you run the helper from Terminal/iTerm, macOS attributes the permission to
   *that* app, not to Poltergeist.

macOS 15 re-asks for Screen Recording roughly monthly; the diagnostics rows in
Settings show the current state, and a recording that cannot start returns a
412 with the reason instead of silently recording nothing.

Check readiness at any time:

```bash
ghostbrain-capture check --json; echo "exit=$?"
```

| exit | meaning |
|---|---|
| 0 | ready |
| 3 | macOS older than 15 — use `capture_backend: blackhole` |
| 4 | Screen Recording not granted |
| 5 | Microphone not granted |

**No meeting window found**

Slides are cropped to the frontmost Teams / Zoom / Webex / Slack-huddle window,
or a browser tab running Meet, Teams or Zoom. If none is on screen when the
recording starts, audio is captured immediately and `recorder.slide_fallback`
decides the rest:

- `ask` (default) — the desktop app shows a prompt (and an OS notification)
  listing the windows on screen: pick the one to sample for slides, choose
  **Entire screen** (handy for pair programming), or **Audio only** to skip
  slides. Headless runs with nobody to answer simply stay audio-only.
- `display` — always capture the whole display without asking.
- `audio` — never capture video unless a meeting window appears.

**Config keys**

```yaml
recorder:
  capture_backend: auto     # auto | native | blackhole
  capture_slides: true      # native only
  slide_fps: 1              # native only, 1–5
  slide_fallback: ask       # native only: ask | display | audio
  slide_min_words: 8        # drop slides whose OCR text is shorter than this
```

### BlackHole capture (fallback, macOS ≤ 14)

```bash
brew install ffmpeg blackhole-2ch switchaudio-osx
```

1. Open **Audio MIDI Setup**, create a **Multi-Output Device** containing your
   speakers/headphones **and** `BlackHole 2ch`, and name it `Ghost Brain`
   (or set `recorder.audio_device` to the name you chose).
2. While recording, the recorder switches your default output to that device
   (so you still hear the meeting) and ffmpeg reads BlackHole + the mic. It
   restores your previous output when the meeting ends.
3. If the output is not routed through BlackHole when a recording starts you
   get a 412 "switch output to Ghost Brain" error rather than a silent
   recording. `GHOSTBRAIN_ALLOWED_AUDIO_OUTPUTS` (comma-separated device
   names) widens the allow-list if your device is named differently.

Force this path with `recorder.capture_backend: blackhole`.

### Install whisper.cpp

```bash
brew install whisper-cpp
mkdir -p ~/ghostbrain/recorder/models
```

Download a `ggml-*.bin` model (e.g. `ggml-medium.en.bin`) with your browser
or your organisation's approved channel and place it in
`~/ghostbrain/recorder/models/`. **On corporate networks with TLS-intercepting
proxies, do not `curl` the model — it hangs silently.** Set
`GHOSTBRAIN_WHISPER_MODEL` to use a model stored elsewhere.

### Verify

```bash
ghostbrain-recorder-recover --show-config     # effective recorder config
tail -f "$VAULT_PATH/90-meta/audit/"*.jsonl   # look for recording_started, transcript_linked, slides_linked
```

In the desktop app, **Meetings** shows the active capture method, and
**Settings → meetings** shows helper / macOS / permission diagnostics.

## Claude Code SessionEnd hook

Add to `~/.claude/settings.json`:

```json
"hooks": {
  "SessionEnd": [{
    "matcher": "*",
    "hooks": [{ "type": "command", "command": "/path/to/ghost-brain/orchestration/hooks/session-end.sh" }]
  }]
}
```
