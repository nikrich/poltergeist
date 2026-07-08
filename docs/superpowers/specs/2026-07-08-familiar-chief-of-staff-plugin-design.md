# Familiar — Chief-of-Staff Plugin v1 — Design

**Date:** 2026-07-08
**Status:** Approved design
**Repo:** `ghost-brain` (plugin in `plugins/familiar/`, bridge + one endpoint in core)
**Depends on:** Plugin System v1 (`2026-07-06-plugin-system-design.md`, branch `feat/plugin-system`)

## Goal

A first-party plugin that acts as a personal chief of staff: on a schedule it reads
what changed in the vault, maintains a rolling memory of themes/commitments/decisions,
and produces a briefing — repeated themes, open loops ("you told X you'd…"), decisions
made, contradictions, and blind-spot questions. Open loops and decisions persist as
structured vault notes with check-off state, not just prose in a report.

This is also the proving ground for **workflow plugins**: it forces the plugin ↔
backend bridge into existence. Later specs (red-team chat mode, generic workflow-plugin
docs/hardening) build on what this ships.

## Decisions already made

- **First-party plugin**, not a core Python feature. Dogfoods the plugin system.
- **Raw passthrough bridge**: plugins get `api.fetch(...)` to the sidecar HTTP API.
  No curated capability layer; the HTTP API is the curated surface.
- **Plugin-driven sweep**: the plugin owns the timer and the workflow. The backend
  gains no job types. Runs only while the app is open (same constraint as the
  in-app scheduler); missed slots catch up on next launch.
- **Rolling memory + delta** context strategy. No full-archive map-reduce in v1 —
  the monthly "deep scan" mode is explicitly deferred.
- **Vault notes + plugin UI** for output. Briefings and trackers are real markdown
  notes (searchable, visible to chat/MCP recall); the plugin screen renders and
  edits them. Everything survives without the plugin.
- **Trackers in scope**: open-loop and decision tracking ship in this spec, since
  the sweep's extraction step produces them anyway.

## Part 1 — Foundation (core changes)

### 1.1 `api.fetch` on the plugin bridge

Add to **`PluginContext`** (main process, `src/main/plugins/types.ts`):

```ts
api: {
  fetch(method: HttpMethod, path: string, body?: unknown): Promise<ApiResult>;
}
```

Implemented over the existing `api-forwarder.ts` `forward()` — same
`ALLOWED_METHODS` gate, same sidecar port/auth resolution. Plugins never see the
port or token. `path` must start with `/` and contain no `..`; reject otherwise.

Add the renderer mirror to **`PluginApi`** (handed to `mount`): identical
signature, routed over a host IPC channel (`gb:plugins:api-fetch`) that performs
the same forward from main. One channel for all plugins; the host tags calls with
the plugin id for logging.

Failures return the forwarder's structured error result (`{ok: false, ...}`) —
they never throw across the bridge.

### 1.2 `POST /v1/llm/run` (sidecar)

New route `ghostbrain/api/routes/llm.py`:

```
POST /v1/llm/run
{ "prompt": str, "system": str | null, "timeoutSeconds": int = 600 }
→ { "text": str, "error": str | null }
```

Runs the existing `claude -p` client (`ghostbrain/llm`) synchronously,
non-streaming. Follows the `answer.py` pattern: all exceptions caught and
returned as a structured `error`, traceback to the sidecar log. Long default
timeout — sweep runs are minutes-long. No vault access, no tools: it is a pure
prompt runner; the caller assembles all context.

## Part 2 — The plugin

Lives at `plugins/familiar/` in this repo. Standard plugin package:
`manifest.json` (id `familiar`, icon `ghost`), `dist/main.cjs`, `dist/renderer.mjs`
(committed builds per the plugin rules), plus `src/` and vitest tests. Installed
through the normal Plugins screen (folder install from the repo checkout during
development).

### 2.1 Sweep engine (`main.cjs`)

**Scheduling.** A `setInterval` tick every 15 minutes asks "is a run due?":

- Schedule config in plugin settings: `{cadence: "weekly", day: "monday", hour: 7}`
  (v1 supports weekly only; the shape leaves room for daily later).
- `dataDir/state.json` records `lastSuccessfulRunAt` and `lastAttemptAt`.
- Due = the configured slot has passed since `lastSuccessfulRunAt`. A missed slot
  (app closed Monday 07:00) fires on the first tick after launch.
- **Run now** via IPC from the UI bypasses the schedule check.
- A run in progress blocks re-entry (in-memory flag + `runningSince` in state.json,
  considered stale after 30 min so a crashed run doesn't wedge the plugin).

**Delta assembly.**

1. Window = `lastSuccessfulRunAt` (or now − 7 days on first run) → now.
2. For each day in the window: `GET /v1/activity?date=D&windowMinutes=1440`,
   collect unique note `path`s. Skip paths under `Familiar/` (the plugin's own
   output must not feed itself).
3. `GET /v1/notes?path=...` for each; concatenate as
   `<note path="..." modified="...">…</note>` blocks.
4. Token budget: ~150k chars of note text per run (configurable). Over budget →
   drop whole notes oldest-first and list the dropped paths in the prompt so the
   model knows coverage was partial, and the briefing can say so.

**Rolling memory.** One plugin-owned vault note, `Familiar/memory.md`: active
themes, watch-list, condensed history of recent briefings. Read at the start of
every run, fully rewritten from the LLM's output at the end. This is how context
persists without re-reading the archive. Created on first run if absent.

**The LLM run.** One `POST /v1/llm/run` call:

- System prompt: the chief-of-staff role — skeptical, concrete, cites source
  notes by path, never invents commitments.
- User prompt: rolling memory + current open-loops/decisions tracker contents +
  delta note blocks + output instructions.
- Output contract: a single JSON object (fenced), schema:

```json
{
  "briefingMarkdown": "…full briefing, markdown…",
  "memoryMarkdown": "…replacement body for Familiar/memory.md…",
  "openLoops": [
    { "id": "loop-…stable slug…", "text": "…", "owedTo": "…|null",
      "sourcePath": "…", "firstSeen": "YYYY-MM-DD",
      "status": "open|done|stale" }
  ],
  "decisions": [
    { "date": "YYYY-MM-DD", "text": "…", "sourcePath": "…" }
  ]
}
```

  `openLoops` is the **complete** current list: the model receives the existing
  tracker and returns it updated (new loops appended with new ids; loops it can
  see were completed flipped to `done`; untouched loops passed through
  unchanged). Loops the user dismissed in the UI are marked `dismissed` in the
  tracker and passed to the model as read-only context — the model must not
  resurrect or modify them; the merge step enforces this regardless of what the
  model returns.
- Parse failure → one retry with the parse error appended to the prompt.
  Second failure → run failed; raw output saved to `dataDir/failed-<ts>.txt`.

**Write-back** (all via the notes/vault API):

- `Familiar/briefings/YYYY-MM-DD.md` ← `briefingMarkdown` (+ frontmatter: window,
  note count, dropped-note count).
- `Familiar/memory.md` ← `memoryMarkdown`.
- `Familiar/open-loops.md` and `Familiar/decisions.md` ← regenerated from the
  merged structured data (§2.2).
- `dataDir/runs.jsonl` ← one line per run: timestamps, status, window, note/char
  counts, error.
- On completion, `ipc.send('run:finished', {...})` so an open UI refreshes.

The plugin writes these notes via note create/update endpoints addressed by
path. If the current notes API turns out to be jot-id-centric only for updates,
extending it with path-addressed upsert (`PUT /v1/notes?path=…`) is in scope for
Part 1 — the implementation plan verifies this before building.

### 2.2 Tracker notes (data model)

Markdown with a machine-parseable line format, human-readable in any viewer:

`Familiar/open-loops.md`:

```markdown
# Open loops

- [ ] <!--id:loop-send-pieter-doc--> Send Pieter the pricing doc — owed to Pieter
      (from [meeting](20-.../note.md), first seen 2026-07-01)
- [x] <!--id:loop-review-pr-42--> Review PR #42 …
```

Checkbox = status (`[ ]` open, `[x]` done; `stale`/`dismissed` as a trailing
tag). The plugin parses/regenerates this file; the id comment is the stable key.
Editing it by hand is allowed — parse errors on a line demote that line to an
"unparsed" section rather than being lost.

`Familiar/decisions.md`: append-only dated list, same style, no state.

**Merge rule** (plugin code, not LLM): the LLM's returned `openLoops` is merged
against the tracker parsed fresh at write-back time. User edits (check-offs,
dismissals) made mid-run win over the model's view of that loop. `dismissed` is
UI/user-only — model output never sets or clears it.

### 2.3 UI (`renderer.mjs`)

Sidebar entry **Familiar** (ghost icon). One screen, framework-free DOM, themed
via the `theme` tokens:

- **Latest briefing** rendered as markdown (self-contained tiny md renderer or
  pre-rendered HTML from marked bundled into the plugin — bundling is fine,
  plugins commit dist).
- **Open loops** list: checkbox (→ done), dismiss button, owed-to/source-link
  metadata. Mutations parse-modify-regenerate `open-loops.md` via the notes API
  (through renderer `api.fetch`), then re-render.
- **Decisions** log (read-only list).
- **History**: past briefings by date, click to view.
- **Run now** button with live status (running / last run result / next
  scheduled), driven by `run:finished` events + a status invoke.
- **Settings**: cadence day/time, char budget. Stored via plugin `settings`.
- Failure banner when the last run failed, with the error and a "view raw
  output" affordance.

### 2.4 Error handling

- Sidecar unreachable at tick time → skip silently, retry next tick.
- Any IPC handler throw rejects only that call (plugin-system semantics); the
  UI surfaces it inline.
- A failed run never corrupts trackers: write-back is all-or-nothing per file
  and happens only after a successful parse+merge.
- `runs.jsonl` is the audit trail; the UI's status line reads from it.

## Testing

- **Python:** route test for `/v1/llm/run` with the LLM client mocked (success,
  client error, timeout).
- **Desktop:** unit test that `api.fetch` on both bridges forwards
  method/path/body and rejects bad paths; existing plugin-host tests extended
  for the new context/api fields.
- **Plugin (vitest, `plugins/familiar/`):** pure-logic tests — schedule
  due-check math, delta window/day iteration, token-budget trimming, JSON
  parse/retry, tracker parse/regenerate round-trip, merge rules (user check-off
  beats model, dismissed never resurrected).
- **Manual E2E:** install from folder, Run now against the real vault, verify
  briefing + trackers appear in the vault and in search/chat.

## Out of scope (v1)

- Monthly/on-demand full-archive deep scan (map-reduce) — later spec.
- Daily cadence, multiple profiles/workspaces, notification on new briefing.
- Generic workflow-plugin capability docs/hardening — later spec, informed by this.
- Red-team chat mode — separate spec (core chat, not this plugin).
- Sandboxing (unchanged trusted-code model from Plugin System v1).
