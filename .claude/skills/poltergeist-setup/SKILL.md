---
name: poltergeist-setup
description: Use when setting up Poltergeist (the getpoltergeist.com desktop app) for the first time, when its meeting recorder or connectors "don't do anything", or when the user says "set up poltergeist", "poltergeist doctor", "connect <tool> to poltergeist". Runs the app's own doctor, fixes what it can with consent, and ends with a verified test recording.
---

# Poltergeist setup

You drive `doctor` and `setup` inside the Poltergeist binary; you do not
re-derive checks yourself. One step per turn. Never run `sudo`. Never batch
fixes. If the same check fails twice with the same output, stop and give the
user the output to paste into a GitHub issue.

## 1. Find the binary

Try, in order, and remember the first that exists as `$PG`:

1. `command -v poltergeist`
2. `/Applications/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api`
3. `%LOCALAPPDATA%\Programs\Poltergeist\resources\sidecar\ghostbrain-api\ghostbrain-api.exe`

None found → the app is not installed. Send the user to
https://github.com/nikrich/poltergeist/releases/latest, ask them to open it
once, and stop.

## 2. Run doctor

`"$PG" doctor --json`. Render every check as one line: ✔ ok, ✘ fail, ! warn,
- skip, then the summary. Read `checks.md` for what each id means. If nothing
is `fail`, go to step 4.

## 3. Walk the failures, one per turn, in the order doctor lists them

For each `fail` (then each `warn` the user cares about):

- One sentence: what it is and why the recorder or sync needs it.
- Show the fix command from the JSON (`fix.command`).
- `automated` → run `"$PG" <fix.command>` after the user says yes. Stream the
  output; brew installs take minutes.
- `interactive` → the command needs a macOS password. Give the user exactly
  `"$PG" <fix.command>` to paste into Terminal, wait for them to say it's done.
- `manual` → tell them the Settings path or action in `fix.command` and wait.

Re-run `"$PG" doctor --json` and confirm only that check changed before
moving on. The `app` check failing after a fix usually means the app needs a
restart: quit, wait ten seconds, reopen.

## 4. Prove it with a real recording

Read `port` and `token` from `~/ghostbrain/run/sidecar.json`. Then:

1. `curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"context":"<first context from the contexts check>"}' http://127.0.0.1:$PORT/v1/recorder/start`
   - 412 → the body names the missing piece; go back to step 3.
2. Ask the user to say a few sentences out loud for fifteen seconds.
3. `curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:$PORT/v1/recorder/stop`
4. Poll `GET /v1/recorder/status` every five seconds until `phase` is `done`.
   `error` non-null → show it verbatim and go back to step 3.
5. Open the note at `<vault>/<transcriptPath>` and show the first lines.
6. `curl -s -X POST ... /v1/recorder/clear`.

Do not tell the user setup is complete before this step succeeds.

## 5. Connectors

Ask which of these matter: Claude Code, GitHub, Jira/Confluence, Slack,
Gmail, Google Calendar, Apple Calendar, Microsoft 365, Joplin. For each:

- Point them at the app's connector card (Connectors screen) for the
  credential step. The cards work.
- Claude Code needs no credential: `"$PG" setup install-hook`.
- Verify with `"$PG" <connector>-fetch` (Microsoft 365 is `outlook-mail-fetch`,
  `teams-chat-fetch`, `teams-meetings-fetch`; Google Calendar and Apple
  Calendar are both `calendar-fetch`) and confirm the routing block is
  non-empty in `<vault>/90-meta/routing.yaml` (`github.orgs`, `gmail.accounts`,
  `calendar.macos.accounts`, `slack.workspaces`, ...). A connector that shows
  "on" with an empty block syncs nothing; add the org/account by hand, one
  line, and re-fetch.

## 6. Going live

If the `routing-mode` check is `warn` and `data.inbox_count` > 0: explain in
two sentences that review mode keeps everything in the inbox and the app's
views only show filed notes, then offer `"$PG" setup go-live`.

## 7. Finish

Final `"$PG" doctor`. Report what is ✔, what remains ! and why that is fine.
