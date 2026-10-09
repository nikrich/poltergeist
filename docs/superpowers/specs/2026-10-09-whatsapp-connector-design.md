# WhatsApp Connector — Design

**Status:** Approved in conversation 2026-10-09
**Origin:** The user wants their personal WhatsApp conversations in the vault for recall. There is no
official API for reading a personal account, so the connector reads the macOS WhatsApp desktop
app's local database.

## Decisions (from the conversation)

- **Source:** the macOS WhatsApp app's local Core Data store,
  `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` (WAL mode).
  Read-only, polled. No unofficial protocol libraries (ToS / ban risk), no Business Cloud API
  (cannot see personal chats).
- **Purpose:** personal memory. Notes route to the `personal` context by default.
- **Scope:** opt-in allowlist. Nothing is ingested until the user ticks chats in a picker.
- **Backfill:** the first run for a newly allowed chat covers the last 90 days, then it syncs
  incrementally.
- **Granularity:** one note per chat per local day, rebuilt from the database on each change.
- **Voice notes:** transcribed locally with the existing whisper pipeline.

## Non-goals

- Windows or Linux. A chat-export (`.txt`/zip) import is a separate follow-up.
- Sending messages, reactions, read receipts or anything that writes to WhatsApp.
- Images, video or documents beyond a one-line placeholder (no OCR or captioning in v1).
- Downloading media WhatsApp hasn't already stored locally. Missing voice notes get a placeholder.
- Status updates, channels, broadcast lists and calls (`CallHistory.sqlite`).
- A relevance gate. Choosing the chats is the filter.
- Multi-account support (one WhatsApp install per Mac).

## Facts about the store (checked on the user's Mac, 2026-10-09)

- 797 chats, 45,660 messages, dating from 2012. `PRAGMA journal_mode` is `wal`.
- It can be opened with `file:…ChatStorage.sqlite?mode=ro` while the app is running.
- Timestamps (`ZMESSAGEDATE`) are Core Data seconds since 2001-01-01 UTC: add `978307200` to get
  Unix time.
- `ZWACHATSESSION.ZSESSIONTYPE`: `0` one-to-one, `1` group, others (broadcast, status, community)
  are ignored. `ZCONTACTJID` is the stable chat key; `ZPARTNERNAME` is the display name.
- `ZWAMESSAGE` fields used: `Z_PK` (increases monotonically), `ZCHATSESSION`, `ZMESSAGEDATE`,
  `ZISFROMME`, `ZTEXT`, `ZMESSAGETYPE`, `ZFROMJID`, `ZPUSHNAME`, `ZGROUPMEMBER`, `ZPARENTMESSAGE`,
  `ZMEDIAITEM`, `ZSTANZAID`.
- `ZMESSAGETYPE` handling in v1:
  - `0` text: rendered.
  - `1` image, `2` video, `8` document: placeholder line, plus the caption if `ZTEXT` is set.
  - `3` voice/audio: transcribed.
  - `7` link: text plus URL.
  - `5` location: placeholder.
  - `14` deleted, `15` sticker, `6` and `10` group/system events, and everything else: dropped.
- **Type codes to confirm first:** `0`, `1`, `2`, `3` and `7` are confirmed by media paths and
  counts. `5` (location) and `8` (document) are from memory. `59` (625 rows), `66` (205), `42`
  and `46` are unknown. The first implementation task samples `ZMEDIAITEM` and `ZTEXT` presence for
  each unknown type, aggregate shape only, and settles each code as keep, placeholder or drop
  before the renderer is written. The fixture encodes the confirmed mapping.
- Voice files: `ZWAMEDIAITEM.ZMEDIALOCALPATH`, e.g. `Media/…/x.opus`, relative to
  `<container>/Message/`. A NULL path means the note was never downloaded. 307 of 331 voice notes
  from the last 90 days are on disk.
- Sender names, in order: `ZWAGROUPMEMBER.ZCONTACTNAME` / `ZFIRSTNAME`, then
  `ZWAPROFILEPUSHNAME.ZPUSHNAME` by JID, then `ZWAMESSAGE.ZPUSHNAME`, then the JID's phone number.
  Messages with `ZISFROMME = 1` are labelled `Me`.

## Design

### 1. Store reader — `ghostbrain/connectors/whatsapp/store.py`

All WhatsApp-specific SQL lives here. No other module touches the schema.

- `default_store_path() -> Path` returns the path above. `GHOSTBRAIN_WHATSAPP_STORE` overrides it
  (used by tests).
- `open_store(path) -> sqlite3.Connection` opens with `mode=ro` via a URI, sets
  `PRAGMA query_only=1` and a 5 s busy timeout. Every run opens and closes its own connection.
- `check_schema(conn)` asserts the tables and columns listed above exist. If any is missing it
  raises `StoreSchemaError`, naming them. This is the loud failure when WhatsApp changes its schema.
- `list_chats(conn) -> list[Chat]` returns
  `Chat(jid, name, kind: "direct"|"group", last_message_at, message_count)`, limited to session
  types 0 and 1 and not removed (`ZREMOVED = 0`).
- `max_message_pk(conn) -> int`.
- `dirty_days(conn, jids, after_pk, since_ts) -> set[tuple[jid, date]]` returns the chat/local-day
  pairs that have messages with `Z_PK > after_pk` and `ZMESSAGEDATE >= since_ts`.
- `messages_for_day(conn, jid, day, tz) -> list[Message]` returns
  `Message(pk, stanza_id, at, sender, is_from_me, kind, text, reply_to_text, media_path)`, ordered
  by date. `reply_to_text` is the parent message's text truncated to 80 characters.
- Local days use the system timezone (`tzlocal`, as calendar notes already do).

### 2. Connector — `ghostbrain/connectors/whatsapp/connector.py`

`WhatsAppConnector(Connector)`, `name = "whatsapp"`.

- **State:** `state/whatsapp.cursor.json`:

  ```json
  {"max_pk": 0, "chats": {"<jid>": {"first_synced_at": "…"}}, "pending_days": [["<jid>", "YYYY-MM-DD"]]}
  ```

  The base class's `last_run` is not used.
- **`fetch(since)`:**
  1. Load the allowlist (§4). If it's empty, return `[]` and log one info line.
  2. For each allowed chat with no `first_synced_at`, mark every day with messages in the last
     `initial_lookback_days` (default 90) as dirty.
  3. Add `dirty_days(conn, allowed, cursor.max_pk, …)` and the cursor's `pending_days` (§3).
  4. Build one event per dirty `(jid, day)` from the full `messages_for_day`. Skip days that
     render to zero lines.
  5. Write `max_pk = max_message_pk()` and the new `first_synced_at` stamps only after every event
     is enqueued, so a crash replays instead of losing days.
- **Event shape:**

  ```python
  {
    "id": f"whatsapp:day:{jid}:{day.isoformat()}",
    "source": "whatsapp", "type": "chat_day",
    "timestamp": <last message time, ISO>,
    "title": f"{chat.name} — {day:%Y-%m-%d}",
    "body": <rendered transcript>,
    "metadata": {"chatJid": jid, "chatName": name, "chatKind": "direct"|"group",
                 "day": "YYYY-MM-DD", "participants": [...], "messageCount": n,
                 "voiceNotes": n, "context": <per-chat override or None>},
  }
  ```

- **Body rendering:** one line per message, `**HH:MM Sender:** text`.
  - A reply is prefixed with a `> ↪ <reply_to_text>` line.
  - Placeholders look like `[image]`, `[image: caption]`, `[video 0:42]`, `[document: name.pdf]`,
    `[location]`.
  - A voice note becomes `🎙 <transcript>`, `[voice note — not downloaded]`, or
    `[voice note — transcription pending]`.
- **`normalize`** passes events through unchanged. **`health_check`** checks that the store opens
  and `check_schema` passes.

### 3. Voice transcription — `ghostbrain/connectors/whatsapp/voice.py`

- `transcript_for(message, store_dir) -> str | None`. The cache is
  `state/whatsapp/voice/<stanza_id>.txt`; a hit returns it straight away.
- On a miss: ffmpeg converts the `.opus` file to a 16 kHz mono WAV in a temp dir, then
  `ghostbrain.recorder.transcribe.transcribe(wav)` runs (existing model resolution and language
  setting). The `.txt` result is moved into the cache and the temp files are deleted.
- **Per-run budget:** `voice_max_per_run` (default 40), so the 90-day backfill doesn't block one
  run for a long time. Over budget returns `None` and the line renders as *pending*.
- **Re-dirtying:** a day with pending voice notes is recorded in the cursor's `pending_days`, and
  the next run treats it as dirty again. That run re-renders it once transcripts exist.
- **Failures:** ffmpeg missing, whisper error or timeout are logged and return `None` (pending). A
  failure never blocks the day note. After three failures for one stanza, a
  `state/whatsapp/voice/<stanza_id>.failed` marker stops retries, and the line renders as
  `[voice note — transcription failed]`.

### 4. Allowlist and chat picker

- **Storage:** `state/whatsapp.allowed_chats.json`:

  ```json
  {"chats": {"<jid>": {"name": "…", "context": null}}}
  ```

  `context` is an optional per-chat override.
- **API** (`ghostbrain/api/routes/connectors.py`):
  - `GET /v1/connectors/whatsapp/chats` returns `list_chats` merged with the allowlist:
    `[{jid, name, kind, lastMessageAt, messageCount, allowed, context}]`, sorted by
    `lastMessageAt` descending. It returns 409 with a reason if the store can't be opened
    (permission / not installed / schema).
  - `PUT /v1/connectors/whatsapp/chats` accepts `{chats: {jid: {allowed, context}}}`, writes the
    file atomically and returns the merged list.
- **UI** (`desktop/src/renderer/components/WhatsAppChatPicker.tsx`, shown in the WhatsApp
  connector's detail pane):
  - A search box, a Direct/Groups filter and checkbox rows (name, kind, last active).
  - A per-row context select showing the configured contexts, default "personal".
  - A Save button. Ticking a chat's box queues its first sync on the next run, and the hint text
    says so: "first sync pulls the last 90 days".

### 5. Routing and notes

- **Router** (`ghostbrain/worker/router.py`, a new `_fast_route` branch before `_account_route`):
  - `source == "whatsapp"` routes to `metadata.context`, then
    `routing.yaml` `whatsapp.default_context`, then `"personal"`, using `method="path"`.
  - No LLM routing call, so rewrites cost nothing.
- **Note generator** (`ghostbrain/worker/note_generator.py`):
  - **Filename:** `_filename_for` returns `<YYYY-MM-DD>-<chat-slug≤40>-<jid-digits≤12>.md` for
    `whatsapp`, with no run timestamp. The same chat-day therefore overwrites the same file in
    `00-inbox/raw/whatsapp/` and `20-contexts/<ctx>/whatsapp/`, as gdrive notes already do.
  - A chat rename changes the slug and leaves the old day notes under their old names. That's
    acceptable, since the JID suffix keeps them traceable.
  - **Frontmatter:** `_build_frontmatter` adds a `whatsapp` branch copying `chatJid`, `chatName`,
    `chatKind`, `day`, `participants`, `messageCount` and `voiceNotes`.
- **Downstream (index, embeddings):** same as for gdrive in-place updates, nothing new. Changing a
  per-chat context override doesn't move notes already written; it applies from the next rebuild
  of each day.

### 6. Wiring

- `ghostbrain/connectors/whatsapp/runner.py` and `__main__.py`: `run_connector("whatsapp", build=_build)`.
  - `_build` returns `None` (not configured) off macOS or when the store file doesn't exist.
  - Config keys: `routing.yaml` `whatsapp.initial_lookback_days`, `whatsapp.voice_max_per_run`
    and `whatsapp.default_context`, all optional.
- `ghostbrain/scheduler_jobs.py`: `add_job("whatsapp", Interval(hours=1), runner.run, "every 1h")`.
- `ghostbrain/api/routes/connectors.py` and `ghostbrain/api/routes/scheduler.py`: add
  `"whatsapp"` to `SYNCABLE`.
- `ghostbrain/api/repo/connectors.py`: a `_DISPLAY` entry.
- `ghostbrain/api/repo/connector_probe.py`, a `whatsapp` branch:
  - `off`: not macOS, the store is missing, or the allowlist is empty.
  - `err`: the store can't be opened, or `StoreSchemaError`.
  - `on`: otherwise.
- **Permission** (`ghostbrain/api/auth/providers/local_grant.py`):
  - A `WhatsAppStoreProvider`, registered in `register_all.py`.
  - Its check tries `open_store` and `check_schema`. A `PermissionError` or "authorization denied"
    (TCC App Data / Full Disk Access) yields `need_grant` with instructions to enable Poltergeist
    under *System Settings → Privacy & Security → Full Disk Access*, plus a deep link
    (`x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles`). Re-check works
    as it does for macOS calendar.
- `desktop/src/renderer/lib/connector-catalog.ts`: a WhatsApp card marked macOS-only.
- Onboarding skill (`onboarding-poltergeist`): a short WhatsApp section covering installing and
  signing in to WhatsApp for Mac, granting access, and picking chats.

### 7. Error handling summary

| Condition | Behaviour |
|---|---|
| Not macOS / WhatsApp not installed | Connector not configured; probe `off`; card hidden or greyed |
| Permission denied | Probe `err`; `need_grant` message with a Settings deep link; run fails health check |
| Schema changed | `StoreSchemaError` naming the missing columns; probe `err`; scheduler notifies once |
| Database busy / locked | 5 s busy timeout, then the run errors; next hourly run retries; cursor untouched |
| Empty allowlist | Run succeeds with 0 events; probe `off` |
| ffmpeg / whisper failure | Line renders pending; retried up to 3 times; never blocks the note |
| Crash mid-run | Cursor saved last, so dirty days replay; notes overwrite idempotently |

## Testing

- **Fixture store:** `tests/connectors/whatsapp/fixtures/make_store.py` builds a temporary
  SQLite database with the real `CREATE TABLE` statements for the tables used, copied from
  `.schema` with no real data. It fills it with synthetic chats and messages: a direct chat, a
  group with members and push names, a reply, an image with a caption, a deleted message, a
  sticker, voice notes with and without a local path, and messages around local midnight.
- **Store tests:**
  - date conversion and local-day bucketing;
  - name resolution order;
  - which types are dropped or kept;
  - `check_schema` failing when a column is removed;
  - `dirty_days` respecting `after_pk`.
- **Connector tests:**
  - first sync limited to 90 days for new chats;
  - incremental sync only rebuilding changed days;
  - a rebuilt day containing the whole day, not just new messages;
  - the cursor not advancing when enqueueing raises;
  - days with no renderable lines skipped;
  - non-allowlisted chats ignored.
- **Voice tests:** with ffmpeg and `transcribe` stubbed, cover cache hit, miss, budget exhaustion
  (pending, then the day re-dirtied on the next run), the failure marker after 3 attempts, and the
  not-downloaded placeholder.
- **Router and note generator tests:** override, then `default_context`, then `personal`;
  filename stability across rebuilds; frontmatter keys.
- **API tests:** the GET merge, the PUT round-trip, and 409 when the store is missing.
- **Renderer test:** the picker filters, toggles, and saves the correct payload.
- **Manual smoke before release:** tick two real chats; run `python -m ghostbrain.connectors.whatsapp`;
  check the notes in the vault, a voice transcript, and an hourly incremental run after new
  messages arrive.
