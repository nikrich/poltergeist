# macOS — recorder setup

The desktop app installs itself; the **meeting recorder** needs four things the
app cannot install for you without asking. The fastest path is the setup skill:
see the README's "Set up in five minutes with Claude Code". This page is the
manual equivalent, and what the skill does under the hood.

## What the recorder needs

| Piece | Why | Install |
|---|---|---|
| `ffmpeg` | captures BlackHole + microphone into one 16 kHz mono WAV | `brew install ffmpeg` |
| `whisper-cli` | whisper.cpp's CLI, transcribes locally | `brew install whisper-cpp` |
| a ggml model | what whisper-cli loads; `medium.en` is the default | `poltergeist setup fetch-model` (or drop any `ggml-*.bin` into `~/ghostbrain/recorder/models/`) |
| `SwitchAudioSource` | flips your output device for the meeting and back | `brew install switchaudio-osx` |
| BlackHole 2ch | virtual output so ffmpeg can hear what the meeting plays | `brew install --cask blackhole-2ch` (asks for your password) |
| a multi-output device | speakers **and** BlackHole at once, so you still hear the call | `poltergeist setup audio-device` |

Run everything at once:

```
poltergeist doctor                 # what is missing
poltergeist setup deps             # brew installs (BlackHole prompts for a password)
poltergeist setup fetch-model      # ~1.5 GB; pass base.en or small.en for smaller
poltergeist setup audio-device     # creates "Ghost Brain"
poltergeist doctor                 # should be all ✔
```

`poltergeist` is the shim the app installs from Settings → background →
"command line tool". Without it, the same binary is at
`/Applications/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api`.

## The multi-output device

The recorder switches macOS output to a device named by `recorder.audio_device`
in `<vault>/90-meta/config.yaml` (default **Ghost Brain**). It must be a
*Multi-Output* device (not an Aggregate) containing your speakers and BlackHole
2ch, with **Drift Correction** ticked on BlackHole: the virtual device and the
built-in output run on separate clocks and a long transcript desynchronises
without it. `setup audio-device` builds exactly that through CoreAudio; to do it
by hand, open Audio MIDI Setup → "+" → Create Multi-Output Device.

Calendar-driven recordings switch to the device automatically and switch back
when the meeting ends. The manual **Record** button requires the device to be
selected already; if it is not, the app tells you which device to pick.

To accept a differently named device, set `GHOSTBRAIN_ALLOWED_AUDIO_OUTPUTS`
to a comma-separated list of names in the app's environment.

## Models

`transcribe` resolves, in order: `GHOSTBRAIN_WHISPER_MODEL` if set, then
`ggml-medium.en.bin` in `~/ghostbrain/recorder/models/`, then the largest
`ggml-*.bin` in that directory. Sizes: base.en ≈ 142 MB, small.en ≈ 466 MB,
medium.en ≈ 1.5 GB.

## Checking it works

Start a manual recording from the Meetings screen, talk for fifteen seconds,
stop. Within a minute a transcript note appears under
`20-contexts/<context>/calendar/transcripts/`. If the status shows an error
instead, it names the missing piece; `poltergeist doctor` gives the fix.
