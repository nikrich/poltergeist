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

New route `ghostbrain/api/routes/llm.py` (as built — the client's
`--json-schema` support made structured output a natural part of the
contract):

```
POST /v1/llm/run
{ "prompt": str, "system": str | null, "model": str = "sonnet",
  "jsonSchema": dict | null, "timeoutSeconds": int = 600,
  "budgetUsd": float | null }
→ { "text": str, "structured": Any | null, "error": str | null,
    "costUsd": float | null, "durationMs": int | null }
```

Runs the existing `claude -p` client (`ghostbrain/llm`) synchronously,
non-streaming; `jsonSchema` passes through to `--json-schema` and comes back
parsed in `structured`. Follows the `answer.py` pattern: all exceptions
caught and returned as a structured `error` (never a 500), traceback to the
sidecar log. Long default timeout — sweep runs are minutes-long. No vault
access, no tools: it is a pure prompt runner; the caller assembles all
context.

The desktop forwarder gained `PUT` in its allowed methods and an optional
per-call timeout override; both plugin bridges forward with a 15-minute
ceiling (the sweep's LLM call uses `timeoutSeconds: 840` to stay under it).

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

The plugin writes these notes via `PUT /v1/notes` `{path, content}` →
`{path, created}` — the path-addressed upsert this spec flagged as
in-scope-if-needed turned out to be needed (the existing notes API was
jot-id-centric for creation) and was added in Part 1. Content is written
verbatim except a trailing newline is ensured (house convention, matching
`save_note_body`); path safety reuses the house `_resolve_safe` guard.

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

**Round-trip safety (as built):** parsing anchors the
`(from [source](…), first seen …)` suffix and the status tag to the end of
the line (greedy head), and rendering sanitizes the format's own delimiter
substrings out of free-text fields (`' — owed to '` → hyphen variant,
`'(from [source]('` → spaced variant) — so LLM-authored text containing
those phrases can never silently corrupt `owedTo`/`sourcePath` on
round-trip. Review-verified against adversarial inputs.

`Familiar/decisions.md`: append-only dated list, same style, no state.

**Merge rule** (plugin code, not LLM): the LLM's returned `openLoops` is merged
against the tracker parsed fresh at write-back time. User edits (check-offs,
dismissals) made mid-run win over the model's view of that loop. `dismissed` is
UI/user-only — model output never sets or clears it.

### 2.3 UI (`renderer.mjs`)

Sidebar entry **Familiar** (ghost icon). One screen, framework-free DOM, themed
via the `theme` tokens:

- **Latest briefing** rendered as markdown via bundled `marked`, configured
  to drop raw HTML tokens (LLM/connector-derived content is untrusted;
  markdown renders, embedded HTML does not — defense-in-depth on top of the
  app CSP). All free-text UI (decisions, history, loop labels) is built with
  DOM `textContent`, never interpolated into `innerHTML`.
- **Open loops** list: checkbox (→ done), dismiss button, owed-to metadata
  (the source path lives in the tracker note's rendered line; no in-UI link
  in v1). Mutations parse-modify-regenerate `open-loops.md` via the notes API
  (through renderer `api.fetch`), then re-render.
- **Decisions** log (read-only list).
- **History**: past briefings listed by date (v1 lists them; open the note in
  the vault to read older ones — no in-place click-to-view).
- **Run now** button with live status (running / last run result / next
  scheduled), driven by `run:finished` events + a status invoke. Scheduled
  runs back off for 4h after a failed attempt; Run now is exempt.
- **Settings**: cadence day/time, model, char budget — validated in the
  `config:set` handler. Stored via plugin `settings`.
- Failure status line when the last run failed, with the error message; raw
  rejected LLM output is persisted to `dataDir/failed-<ts>.txt` for debugging
  (no in-app raw viewer in v1).

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
