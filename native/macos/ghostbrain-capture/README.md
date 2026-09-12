# ghostbrain-capture

Native macOS meeting-capture helper for Poltergeist, built on ScreenCaptureKit.
An audio `SCStream` delivers system audio and the microphone, a second video-only `SCStream` delivers screen frames of the meeting window; the
helper writes a 16 kHz mono PCM16 WAV (system + mic mixed, `amix
duration=longest` semantics) and, optionally, deduplicated slide key frames
with OCR text. It replaces the BlackHole + ffmpeg path on macOS 15+.

This file is the **canonical CLI contract**. `ghostbrain/recorder/audio/darwin_native.py`
(Python) and `desktop/src/main/sidecar.ts` (Electron) are written against it.

## Requirements

- macOS 15 or newer at run time (`captureMicrophone` needs the macOS 15 SDK).
- Build: Xcode 16+ / Swift 6 on arm64. Zero third-party dependencies.
- Permissions (TCC): **Screen Recording** (required even for audio-only —
  ScreenCaptureKit scopes system audio to a screen content filter) and
  **Microphone** (unless `--mic-device none`).

## Build & test

```sh
cd native/macos/ghostbrain-capture
swift build -c release          # .build/release/ghostbrain-capture
swift test                      # XCTest, Core library only (no ScreenCaptureKit)

# from the repo root — stages desktop/resources/bin/ghostbrain-capture (gitignored)
scripts/build-native-macos.sh
scripts/build-native-macos.sh --install   # + ~/.local/bin, ad-hoc signed
```

Layout:

| Target | Purpose |
| --- | --- |
| `Sources/GhostbrainCaptureCore` | Pure library, unit tested: `CLIOptions`, `CheckReport`, `ExitCode`, `Protocol` (stdout encoder + stderr logger), `WavWriter`, `PCMConvert`, `Mixer`, `FrameDiff`, `SlideDetector`, `SlideLog`, `TargetResolver`. No ScreenCaptureKit import. |
| `Sources/ghostbrain-capture` | Thin executable: `main.swift`, `Permissions`, `Devices`, `ShareableContent`, `CaptureSession`, `StreamOutput`, `FrameSampler`, `OCR`, embedded `Info.plist`. |
| `Tests/GhostbrainCaptureCoreTests` | XCTest suite for Core. |

`Info.plist` is embedded with `-sectcreate __TEXT __info_plist` so the helper has
a stable `CFBundleIdentifier` (`tech.codeship.ghostbrain.capture`) and the three
usage strings even when run outside `Poltergeist.app`.

## CLI

```
ghostbrain-capture run --wav <path> [--frames-dir <dir>] [--control-file <path>] [--fps 1]
                       [--target auto|display|window]
                       [--no-window-policy ask|display|audio] [--mic-device <uid>|none]
                       [--ocr-langs en-US[,de-DE]] [--slide-threshold 0.04] [--max-frames 600]
                       [--max-duration-s 21600] [--verbose]
ghostbrain-capture check [--json] [--audio-only]
ghostbrain-capture request-permissions [--json]
ghostbrain-capture list-devices [--json]
ghostbrain-capture --version | --help
```

### `run`

| Option | Default | Meaning |
| --- | --- | --- |
| `--wav <path>` | required | Output WAV, PCM16 mono 16 kHz. Parent dir is created. Header is rewritten ~every 1 s and on close so a SIGKILL leaves a readable file. |
| `--frames-dir <dir>` | none | Enables video. Slides (`slide-NNNN-OOOOOOOO.jpg`), `slides.jsonl`, `slides.json` are written here. Omitted ⇒ no video at all, no Screen output is attached to the stream. |
| `--control-file <path>` | none | JSON file polled once a second for runtime target changes (see below). Only meaningful with `--frames-dir`. |
| `--fps N` | 1 | Frame sampling rate (1…10). SCStream delivers no frames for static content, which is fine. |
| `--target` | `auto` | `auto`: capture the frontmost meeting window (window filter), follow it, fall back per policy. `display`: always full display, never resolve windows. `window`: like `auto` but never falls back to the display (equivalent to `--no-window-policy audio`). |
| `--no-window-policy` | `ask` | What to do when no meeting window exists (see below). |
| `--mic-device` | system default | `AVCaptureDevice.uniqueID` from `list-devices`, or `none` to disable the mic lane (mic TCC then not required). |
| `--ocr-langs` | `en-US` | Comma-separated Vision recognition languages. |
| `--slide-threshold` | `0.04` | Mean-absolute-diff (0…1) on a 64×36 grayscale thumbnail vs. the last kept slide. |
| `--max-frames` | `600` | Maximum kept slides per session. |
| `--max-duration-s` | `21600` | Safety stop (6 h). Stops cleanly with `STOPPING reason=max_duration`. |
| `--verbose` | off | DEBUG lines on stderr (per-frame decisions, audio formats). |

Slide detection: a change must be stable for 2 consecutive delivered frames,
at least 3 s must have passed since the last kept slide (A/B oscillation never
settles, animations are ignored). Kept frames are scaled to a long edge of
≤ 1600 px, JPEG q≈0.7, then OCR'd with `VNRecognizeTextRequest` (`.accurate`)
on a serial queue with a backlog bound of 8 (excess frames are recorded with
`"ocr":"skipped"`).

Audio: the audio stream is always built from a **display** content filter so
system audio is everything the user hears (a window filter would only capture
that app's audio). Video runs on a separate stream with a window filter for the
meeting window (or a display filter for whole-screen capture), re-resolved
every 3 s. Both lanes are converted to Float32 mono 16 kHz, then
every 100 ms the mixer drains `elapsed_wall × 16000 − written` samples from each
lane, zero-pads shortfalls, sums, clips, and appends Int16 — the WAV length
tracks wall-clock time. Any lane backlog > 500 ms is trimmed with a WARN.

### No-window policy, control file and signals

If `TargetResolver` finds no meeting window at start (or the window disappears):

| Policy | Behaviour |
| --- | --- |
| `ask` (default) | Audio starts immediately, video stays off, stdout gets `TARGET kind=none awaiting_choice=true`. Resolution continues every 3 s — a meeting window appearing enables window video automatically. The controller answers via the control file (or SIGUSR1 / SIGUSR2). |
| `display` | Capture the full display without asking. |
| `audio` | Never capture video without a meeting window. |

**Control file** (`--control-file`): polled every second by mtime. Contents:

```json
{"target": "display"}                      // full display now (same as SIGUSR1)
{"target": "audio"}                        // audio only, stop asking (same as SIGUSR2)
{"target": "window", "window_id": 16392}   // pin a specific window
```

A pinned window is followed (moves / resizes) and never auto-switched away
from; when it disappears the no-window policy applies again. Each accepted
command emits `TARGET … reason=user_choice`.

**Window catalog**: with `--frames-dir` the helper writes
`<frames-dir>/windows.json` at start and whenever the set changes (checked on
the 3 s resolve tick), so a UI can offer a picker:

```json
{"version": 1, "generated_at": "2026-09-12T08:00:00Z",
 "windows": [{"window_id": 16392, "app": "com.googlecode.iterm2", "app_name": "iTerm2",
              "title": "shell", "width": 1200, "height": 800, "candidate": false}]}
```

Front-to-back order; layer 0, on screen, ≥ 400×300, titled; Poltergeist's own
windows excluded. `candidate` = `TargetResolver` would pick it as a meeting window.

**Signals**: **SIGUSR1** = capture the full display now (ignored if video is
already on). **SIGUSR2** = audio only, stop asking (also disables any active video).

`SIGINT` / `SIGTERM`: `STOPPING`, `stopCapture` (3 s watchdog), final mixer drain,
WAV closed, OCR finished (≤ 3 s), `slides.json` written, `DONE`, exit 0. A second
`SIGINT`/`SIGTERM` exits immediately. `SIGPIPE` is ignored and stdout write
errors are swallowed — the parent may close the pipe after `READY`.

### Meeting-window resolution

Windows from `CGWindowListCopyWindowInfo` (front-to-back) joined to
`SCShareableContent` by window id. Dropped: layer ≠ 0, off-screen, smaller than
400×300, untitled. Native apps by bundle id — `com.microsoft.teams2`,
`com.microsoft.teams`, `us.zoom.xos`, `Cisco-Systems.Spark`,
`com.webex.meetingmanager`, `com.tinyspeck.slackmacgap` — but only when the
title positively looks like a live meeting: Teams `Meeting|Call|Webinar|Town hall`
(never `Chat |`), Zoom `Meeting|Webinar` (the Zoom home window does not count),
Slack `Huddle`, Webex anything but the bare app window. Meeting apps keep
chat / home windows open all day; counting those would mean the no-window
prompt never fires. Browsers (Chrome, Safari, Firefox, Edge, Brave, Arc) match on the
title regex `Meet – |Google Meet|meet\.google\.com|Webex|Zoom Meeting|Microsoft Teams`.
The frontmost meeting app wins; within it, the best title tier, then the largest
window.

Video and audio run on **separate streams**. Audio always uses a display filter
(ScreenCaptureKit scopes system audio to the filter; a display filter means
"everything the user hears"). Video uses its own stream with either
`SCContentFilter(desktopIndependentWindow:)` — which renders that window alone,
even when other windows overlap it or it is behind the desktop app — or a
display filter for whole-screen capture. The video stream is torn down and
rebuilt when the target changes and resized when the window resizes; if it
stops on its own (window closed) the next resolve tick re-targets. An earlier
design cropped a single display stream to the window rectangle and captured
whatever was in front of the meeting window.

### `check` / `request-permissions`

`check` never prompts. It prints (text, or JSON with `--json`):

```json
{"ok":true,"code":0,"macos":"15.6.1","macos_supported":true,
 "screen_recording":"granted","microphone":"granted","audio_only":false,
 "issues":[],"version":"0.1.0"}
```

`microphone` ∈ `granted|denied|restricted|not_determined`; `screen_recording` ∈
`granted|denied`. `code` is the exit code `run` would fail with right now (3/4/5)
and is also the process exit status, so `ok == (exit status == 0)`. `--audio-only`
only changes wording: with the ScreenCaptureKit backend Screen Recording remains
fatal for system audio. `request-permissions` triggers the Screen Recording and
Microphone prompts (the former is asynchronous — the user must flip the switch in
System Settings and the helper cannot wait for it) and then behaves like `check`.

An app only appears in *System Settings › Privacy & Security › Screen & System
Audio Recording* after it has **attempted** access — that is what
`request-permissions` is for. macOS 15 re-prompts Screen Recording roughly
monthly; surface exit 4 rather than fighting it. TCC attributes the request to
the *responsible process*: `Poltergeist.app` when spawned by the sidecar,
`Terminal`/your IDE when run by hand (each has its own grant).

### `list-devices`

Audio input devices (`AVCaptureDevice`), text `id<TAB>name[<TAB>(default)]` or
`--json`: `{"devices":[{"id":"BuiltInMicrophoneDevice","name":"MacBook Pro Microphone","default":true}]}`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | ok |
| 1 | internal error |
| 2 | usage error (message + usage on stderr) |
| 3 | macOS < 15 |
| 4 | Screen Recording denied |
| 5 | Microphone denied / restricted / not yet determined (unless `--mic-device none`) |
| 6 | SCStream failed to start (or `SCShareableContent` failed) |
| 7 | output I/O error (WAV / frames dir) |
| 8 | no display to capture |
| 9 | stream stopped unexpectedly — WAV finalised, recording is partial |

Permission failures (3/4/5) always exit **before** `READY`; `run` never blocks
on a TCC prompt.

## stdout protocol (`run`)

Exactly one `KEY k=v k2="quoted value"` line per event; values containing
whitespace, quotes, `=` or that are empty are double-quoted with backslash
escapes (`\"`, `\\`, `\n`). Nothing else is ever printed to stdout. Logs go to
stderr as `[ghostbrain-capture] LEVEL message`.

```
STARTING version=0.1.0 pid=12345
TARGET kind=window app=com.microsoft.teams2 title="Weekly sync | Meeting | Microsoft Teams" window_id=10526
TARGET kind=display display=1 [reason=user_choice]
TARGET kind=none [awaiting_choice=true] [reason=window_gone|user_choice]
READY wav=/path/out.wav [frames_dir=/path/out.frames] fps=1 mic=on|off
SLIDE index=1 offset_ms=4200 image=slide-0001-00004200.jpg chars=312
STOPPING reason=sigint|sigterm|max_duration|stream_stopped|wav_io_error
DONE duration_ms=3612000 wav_bytes=115584044 slides=17
```

`TARGET` is emitted once before `READY` and again whenever the video target
changes (`reason=window_changed|window_gone|window_found|user_choice`).
`offset_ms` values are milliseconds since `READY`, on the same clock as the WAV.

## `slides.json`

Rewritten atomically every 5 s and on stop; `slides.jsonl` gets one record
appended per slide as soon as its OCR finishes (completion order, which can
differ from index order — `slides.json` is sorted by `index`). Python reads
`slides.json` and falls back to reconstructing from `slides.jsonl`.

```json
{"version":1,"wav":"out.wav","started_at":"2026-09-12T07:51:14Z","duration_ms":3612000,"fps":1,
 "target":{"kind":"window","app":"com.microsoft.teams2","title":"Weekly sync | Meeting | Microsoft Teams"},
 "slides":[{"index":1,"offset_ms":4200,"image":"slide-0001-00004200.jpg","width":1600,"height":900,
            "text":"Q3 Roadmap\n…","ocr":"accurate","confidence":0.91,"diff":0.31}]}
```

`ocr` ∈ `accurate|skipped|failed`; `confidence` is the mean Vision candidate
confidence (0…1); `diff` is the thumbnail difference against the previous kept
slide (1.0 for the first).

## Packaging notes

- `desktop/electron-builder.yml`: `mac.extraResources` copies `resources/bin` →
  `Contents/Resources/bin`; `mac.binaries` lists the helper so it is signed with
  the hardened runtime and inherits `entitlements.mac.plist`
  (`com.apple.security.device.audio-input`); `mac.extendInfo` carries the three
  usage strings (`NSScreenCaptureUsageDescription`, `NSMicrophoneUsageDescription`,
  `NSAudioCaptureUsageDescription`) because TCC reads them from the responsible app.
- Screen capture has no entitlement; it is TCC only.
- The Python side finds the helper via `GHOSTBRAIN_CAPTURE_BIN`, then the frozen
  sibling `…/Resources/bin/ghostbrain-capture`, then `PATH` (`~/.local/bin`).

## Design notes / deviations from the original plan

- **Deployment target is macOS 13, not 15.** A binary with `LSMinimumSystemVersion`/
  `minos` 15 does not launch at all on macOS 14 (dyld rejects it), which would
  make exit code 3 unreachable. All ScreenCaptureKit code is behind
  `@available(macOS 15, *)`; `run`/`list-devices` exit 3 on older systems and
  `check` reports `macos_supported:false`. The embedded `Info.plist` still
  declares `LSMinimumSystemVersion 15.0`.
- **`check --audio-only` does not relax Screen Recording** — ScreenCaptureKit
  needs it for system audio. It is accepted (and echoed as `audio_only`) so the
  Python caller can pass it; a CoreAudio-tap audio-only mode could honour it later.
- Whole package is Swift 6 language mode, including the executable.
