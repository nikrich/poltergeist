# Doctor checks

One paragraph per check, in the order `doctor` runs and reports them.

## app

Confirms the desktop app is installed and its sidecar is up and answering `/health`. If `Poltergeist.app` isn't in `/Applications`, the fix is to download the latest release and drag it in. If the app isn't running, open it and wait for the sidebar to load. The failure worth knowing by name is "running but its sidecar is not published": this is a relaunch race — the app was reopened before the previous sidecar finished shutting down, so the new instance comes up read-only with no recorder or sync. The fix is the same for that case and for "sidecar on port N is not answering": quit Poltergeist, wait ten seconds so the old process fully exits, then reopen. If `app` still fails the same way after a clean quit-wait-reopen cycle, stop and ask the user to paste both the doctor output and Console.app logs for Poltergeist into a GitHub issue.

## vault

Confirms `<vault>/90-meta/routing.yaml` exists, which is how doctor knows the vault has been bootstrapped. Missing it fails with an automated fix, `setup bootstrap`, which is idempotent and safe to re-run. A second condition is a mismatch: the desktop app's Settings vault path points somewhere other than the sidecar's vault, so the two disagree about where notes live. This is reported as a `warn`, not a `fail`, since the sidecar's vault is still fully usable — set the app's vault path back to the sidecar's vault in Settings until the two are reconciled. If it fails twice, run `"$PG" setup bootstrap` once more and paste its output; if the path it prints is not where the user expects their vault, the desktop Settings vault path and the sidecar disagree.

## contexts

Confirms `routing.yaml` has at least one entry in its `contexts:` list — these are the buckets (e.g. `work`, `personal`) that filed notes route into, and the value doctor reports back is exactly that list. An empty list fails with a manual fix: add a `contexts:` list to `90-meta/routing.yaml`. If it fails twice, open the file directly and check for a YAML indentation error under `contexts:` rather than retrying the same edit.

## claude-cli

Confirms the `claude` CLI is on PATH and `claude --version` succeeds. Every LLM call in Poltergeist — chat, digests, routing — shells out to `claude -p`, billed to the user's existing Claude subscription rather than a separate API key. The fix is manual: `npm install -g @anthropic-ai/claude-code && claude login`. If it fails twice after that, run `claude` interactively to see whether login is actually completing, since a half-finished device-code flow leaves `--version` working but `-p` calls failing later.

## scheduler

Reads the desktop app's `schedulerEnabled` setting. `false` fails outright — connectors will never sync without it — with a manual fix pointing at Settings → background → "Run scheduler in-app". If the desktop settings file can't be found at all, this is a `warn`, not a `fail`, because doctor genuinely can't tell; say so plainly rather than guessing. If it fails twice after being turned on, check that the app was fully restarted after the toggle, since the scheduler only starts at launch.

## routing-mode

Reads `worker.routing_mode` from `<vault>/90-meta/config.yaml` (default `review_only`) and counts markdown files sitting in `00-inbox/raw`. Anything other than `live` is a `warn`, not a `fail`: review mode is a deliberate, valid state that keeps every captured item in the inbox for the user to audit before it's filed. The catch worth surfacing is that the app's meeting and calendar views only read *filed* notes, so a healthy review-mode vault can look empty in the UI. The fix is automated, `setup go-live`, and should only be offered, never forced — see SKILL.md step 6. If the inbox count keeps growing after going live, the worker isn't running, not routing-mode.

## ffmpeg

macOS only (`skip` elsewhere). Confirms `ffmpeg` is on PATH — it captures BlackHole and the microphone together into the meeting WAV file, so without it recording can't start. The fix is automated, `setup deps --only ffmpeg`, which installs via Homebrew; if Homebrew itself isn't installed yet, the command stops and tells the user to install it from https://brew.sh first, which itself needs their macOS password. If it fails twice after a brew install reports success, check that a shell restart or `PATH` refresh happened, since a fresh Homebrew install doesn't always land on PATH for the current session.

## whisper-cli

Runs on macOS and Windows (`skip` on Linux). Confirms `whisper-cli` is on PATH — whisper.cpp's CLI transcribes recordings locally, with no audio leaving the machine. On macOS the fix is automated, `setup deps --only whisper-cpp`. On Windows there's no Homebrew, so the fix is manual: install whisper.cpp and add `whisper-cli` to PATH, following `docs/install/windows.md`. If it fails twice on Windows, the usual cause is the binary being installed but not on the PATH the app's sidecar process actually sees — confirm from the same shell that will launch the app.

## whisper-model

Runs on macOS and Windows (`skip` on Linux). Confirms a `ggml-*.bin` whisper model resolves in the recorder's model directory; without one, transcription has nothing to run. On macOS the fix is automated, `setup fetch-model`, which downloads `ggml-medium.en.bin` (~1.5 GB) by default — pass `base.en` or `small.en` for a smaller download on a slow connection. On Windows the fix is manual: download a `ggml-*.bin` file into `~/ghostbrain/recorder/models/` by hand, per `docs/install/windows.md`, since scripted downloads are unreliable behind corporate proxies. If it fails twice, check the filename actually starts with `ggml-` and sits directly in that directory, not a subfolder.

## switchaudio

macOS only. Confirms `SwitchAudioSource` is on PATH — it's what flips the Mac's audio output to the multi-output device for a meeting and switches it back afterward. The fix is automated, `setup deps --only switchaudio-osx`. If it fails twice, check the same Homebrew-on-PATH issue as `ffmpeg`.

## blackhole

macOS only, and skipped (not failed) if `switchaudio` hasn't succeeded yet, since it needs `SwitchAudioSource` to list audio devices. Confirms the "BlackHole 2ch" virtual audio device is installed — it's what lets `ffmpeg` capture whatever the meeting app is playing. The fix is `interactive`, `setup deps --only blackhole`: BlackHole installs as a Homebrew cask, and the cask installer itself prompts for the macOS password mid-install, so this one has to be run directly in Terminal rather than driven silently. This is separate from Homebrew's own install password — if Homebrew isn't present at all, that first password prompt happens at https://brew.sh before this check can even try. If it fails twice after a password was entered, check Activity Monitor for a stuck `installer` process and re-run once it clears.

## audio-device

macOS only, skipped if `switchaudio` hasn't succeeded. Confirms the configured multi-output device (speakers + BlackHole, so the user still hears the meeting while it's captured) actually exists among the system's audio outputs. The fix is automated, `setup audio-device`, which creates it. If it fails twice, open Audio MIDI Setup and check whether a device with that name already exists but is misconfigured — the fix won't overwrite an existing device with the same name.

## audio-routing

macOS only, skipped if `switchaudio` hasn't succeeded. Confirms the Mac's *current* output is already set to the configured multi-output device. This is a `warn`, not a `fail`, because calendar-triggered recordings switch the output automatically — it only matters for the manual Record button, which needs the output set first. The fix is manual: Sound menu → Output → the named device. If it keeps reverting, another app (or a Bluetooth device reconnecting) is likely changing the output after doctor runs; re-check right before starting a manual recording rather than trusting an earlier doctor run.

## recorder-backend

Windows only (`skip` everywhere else). Runs the WASAPI recorder backend's own preflight instead of the macOS ffmpeg/BlackHole chain, and reports every missing prerequisite it finds in one `detail` block. The fix is manual: work through the dependencies section of `docs/install/windows.md`. If it fails twice with the same missing items, the most common cause is a corporate proxy blocking one of the downloads that step calls for — see `docs/install/windows.md` for a manual download fallback.

## connectors

Compares each connector's `routing.yaml` block against whether the app reports it "on" (has a stored credential). A connector that's "on" but whose block is empty or missing its key sub-field is a `fail`, reported as "connected but not configured": it has a credential but syncs zero events every run, silently. If nothing is configured yet, that's a `warn`, not a `fail` — it's a valid starting state. Either way the fix is manual: open the connector card in the app to finish its form (or add the missing block to `routing.yaml` by hand), then run `poltergeist <connector>-fetch` to verify. The blocks and their non-empty sub-keys are `github.orgs`, `gmail.accounts`, `calendar.google.accounts` or `calendar.macos.accounts`, `slack.workspaces`, `jira.sites`, `confluence.sites`, `joplin.token`, and `claude_code.project_paths`. If the same connector fails twice after editing `routing.yaml`, re-fetch with `--dry-run` first to see whether the block is even being read, since a YAML indentation slip under the wrong key is the usual cause.

## claude-hook

Confirms `~/.claude/settings.json` is valid JSON, has a `SessionEnd` hook, and that the hook's command still points at a script that exists. A JSON parse failure is manual to fix — the user has to repair the file by hand before doctor can check anything else in it. A missing or stale hook has an automated fix, `setup install-hook`, which is safe to re-run. This hook is what queues each finished Claude Code session into the vault, so it matters even for users who don't touch any other connector. If it fails twice after reinstalling, check whether another tool (an editor extension, another Claude Code plugin) is also writing to the same `SessionEnd` array and clobbering the entry.

## cli-shim

Confirms `poltergeist` is on PATH. This is optional and only ever a `warn`: without it, the same commands still work via the full sidecar binary path, just longer to type. The fix is automated, `setup cli-shim`. There's nothing to escalate here even on a second failure — mention it once and move on unless the user specifically wants the shortcut.

## Windows note

On Windows, `ffmpeg`, `switchaudio`, `blackhole`, `audio-device`, and `audio-routing` all report `skip` — they're the macOS-only pieces of the ffmpeg + BlackHole capture chain. `whisper-cli` and `whisper-model` still run and matter on Windows, but their fixes are manual (no Homebrew), pointing at `docs/install/windows.md`. In their place, `recorder-backend` runs the WASAPI backend's own preflight and is the one check that actually verifies Windows recording is ready to go.

## Connector gotchas

- **Google consent-screen expiry.** Gmail and Google Calendar share one Desktop OAuth client. If that client's OAuth consent screen is still in "External + Testing" mode, refresh tokens silently expire roughly weekly and the connector goes from "on" to failing auth with no config change on the user's side. Publish the consent screen, or be ready to re-run the `-auth` command again.
- **Microsoft device-code scopes.** Microsoft auth is delegated device-code, not application-only — `getAllTranscripts`-style application permissions don't work here. Set `microsoft.scopes` in `routing.yaml` to exactly the scopes that were actually consented during sign-in; requesting more than was consented breaks silent token refresh. Calendar auto-discovery of Teams meetings additionally needs `Calendars.Read`; to avoid that, list meetings explicitly under `microsoft.teams_meetings.meetings` instead.
- **Per-connector block required.** Every connector reads only its own block in `routing.yaml`. A connector with a valid credential but no block (or an empty one) doesn't error — it just reports "skipped (not configured)" or, per the `connectors` check above, shows "on" while syncing nothing. There's no global on/off switch; each connector's block has to be added explicitly.
