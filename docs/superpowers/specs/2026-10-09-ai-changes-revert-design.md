# AI Changes + Revert — Design

- **Date:** 2026-10-09
- **Status:** Draft — awaiting review
- **Repo:** ghost-brain (poltergeist)
- **Depends on:** the page-history store from the editor spec (`2026-10-09-confluence-editor-design.md`, slice A3).
- **Needed by:** editor inline AI (A5) and AI-generated templates (`2026-10-09-smart-templates-design.md`, slice C4).
- **Author:** brainstormed with Jannik

## Goal & intent

**What the user asked for** (the Brainstead item they wanted pulled in):
- No AI writes to your notes behind your back.
- Every change an assistant makes goes through the app and shows up on a Changes screen with a Revert button.
- Riskier changes (templates, anything that adds code that runs) wait until you say yes.
- Saves never overwrite a note changed elsewhere in the meantime.
- Saves never reformat anything you didn't touch.

**Assumptions (correct me):**

- "AI" means every **non-user** writer: the docs assistant and inline AI, the MCP `poltergeist_write_doc` tool, plugins (Familiar writes notes through `PUT /v1/notes`), and the worker's LLM jobs that **modify existing notes** (`worker/reversal.py` adds `contradicts` / `reversed_by`, `profile/apply.py` edits `80-profile`).
- Connector **ingest** isn't "AI changing my notes". The worker creates thousands of new notes from Gmail, Jira, calendar and transcripts. Listing each one would bury the screen. Ingest creations stay in the existing audit log (`90-meta/audit/*.jsonl`) and are **not** listed. See Open question 1.
- Plain user edits get page history (spec A3) but don't appear on the Changes screen.

## Scope

In scope:

- **One vault write path** (`ghostbrain/vault_write/`). Every create, modify, move or delete of a vault file by an API route, MCP tool, plugin or worker LLM job goes through it.
- **Optimistic concurrency:** reads return an `etag`; writes carry it, and a mismatch is refused.
- **Minimal-diff writes:** the body is replaced without re-dumping frontmatter, and frontmatter fields are edited line-level. Nothing untouched is reformatted.
- **A change log and a Changes screen,** with a per-change diff, Revert, and actor filters.
- **A risk policy:** risky non-user changes are held as **pending** until approved.

Non-goals:

- Undoing external edits (Obsidian, sync tools). The write path can't see them. Page history only covers writes made through the app.
- Multi-file transactions. Each change is per file. A routed jot move is recorded as one change with `op: move`.
- A full sandbox for plugins. Plugins are trusted code, and actor attribution for them is best-effort.

## Architecture

### 1. The write path (`ghostbrain/vault_write/__init__.py`, new)

```python
def write(
    rel_path: str,
    *,
    content: str | None = None,          # full replacement (create / plugin upsert)
    body: str | None = None,             # body-only replacement, frontmatter kept byte-for-byte
    fields: dict[str, Any] | None = None,  # frontmatter field updates
    op: Literal["create", "modify", "delete", "move"] = "modify",
    dest: str | None = None,             # for op="move"
    actor: Actor,                        # user | assistant | mcp | plugin:<id> | worker:<job>
    reason: str = "",                    # human sentence shown on the Changes screen
    base_etag: str | None = None,        # required for actor != worker when op != create
) -> WriteResult  # {status: applied|pending, change_id, etag, path}
```

Steps, under a per-path `threading.Lock`. One sidecar process owns all writes; the scheduler and worker run in-process.

1. `_resolve_safe(rel_path)`: the existing house guard (vault containment, no traversal).
2. Read the current bytes and compute `etag = sha256(bytes)[:16]`. If `base_etag` is given and differs, raise `WriteConflict(current_etag)`, which becomes **409**.
3. Compute the new bytes:
   - `content`: verbatim, plus a trailing newline.
   - `body`: **splice**. Keep the original frontmatter block's exact text (from the opening `---` through the closing `---\n`) and replace only what follows.
   - `fields`: for each key that exists as a single-line scalar (`key: value`), rewrite that one line. For a missing key, insert a line before the closing `---`. Only when the key is a multi-line structure (a list or map) is that key's block re-serialised; the rest of the frontmatter stays byte-identical.
   - `updated` is bumped only when the key already exists, as today.
4. **Risk check** (§3). If held: store a pending change with the proposed bytes and return `status: pending`. Nothing is written.
5. `history.snapshot(rel_path, actor, reason)` (spec A3). For non-user actors, a snapshot failure **aborts the write**, because an AI write must be revertible. For the user actor it is logged and the write proceeds.
6. Write atomically: temp file in the same directory, then `os.replace`.
7. Append a change record (§2), skipped for `actor == user`. Return the new etag.

Every current writer is moved onto this path:

| Writer | Today | Becomes |
|---|---|---|
| `note.save_note_body`, `PATCH /v1/notes/body` | `frontmatter.dumps` (reformats YAML) | `write(body=…, actor from header)` |
| `notes_manual.update_jot_body`, `set_frontmatter_fields`, `move_jot`, `mark_manual_review` | `frontmatter.dumps` | `write(body=…/fields=…/op="move")` |
| `note.save_note_at_path`, `PUT /v1/notes` (plugins) | verbatim write | `write(content=…, actor=plugin:<id>)` |
| `generated_docs.write_doc` (MCP / agent) | verbatim `.html` write | `write(content=…, op="create", actor=mcp)` |
| `worker/reversal.py`, `profile/apply.py` | direct edits | `write(fields=…/body=…, actor=worker:<job>)` |
| worker / connector **creations** | direct | unchanged in this spec. Audit log only, not listed (non-goal; Open question 1) |

### 2. Actor attribution

- The sidecar reads a `X-Poltergeist-Actor` request header. A missing header means `user`.
- **Renderer** (`main/api-forwarder.ts`) passes through `assistant` when the renderer sets it. Spec A's inline AI and the docs panel's Accept set it. Anything else is forced to `user`.
- **Plugins:** `gb:plugins:sidecar` and plugin `api.fetch` in main stamp `plugin:<id>`. That requires threading the plugin id through the preload `plugin(id).sidecar.request` closure (`desktop/src/main/plugins/ipc.ts` today calls `sidecarBridge(method, path, body)` with no id). Best-effort: renderer-side plugin code shares the renderer and could forge the id.
- **MCP:** `ghostbrain/mcp/client.py` (the `SidecarClient`) always sends `mcp`.
- **Worker jobs:** they call `vault_write.write` in-process with `worker:<job>`.

### 3. Risk policy (`ghostbrain/vault_write/risk.py`)

A non-user change is **held for approval** when any rule matches:

- **Path rules:**
  - `90-meta/**`: config, routing, prompts, templates, accounts. These change app behaviour or steer the LLMs.
  - `80-profile/**` *Stable* layer files (`working-style`, `preferences`), consistent with `profile/apply.py`'s existing "never auto-apply Stable" rule.
  - Anything under the templates folder (spec C).
- **Content rules** (only lines the change adds are checked):
  - HTML `<script`, `on…=` handlers, `javascript:` URLs (generated docs are HTML rendered in the app);
  - template expressions (spec C's `{{ … }}` blocks), since they run queries when a note is made;
  - fenced code blocks marked executable (`dataviewjs`, `js`/`javascript` inside a template file).
- **Deletes and moves** of files the actor didn't create.

Plain prose edits to notes and new notes created by the assistant or plugins are applied immediately and remain revertible. Approving a pending change re-runs steps 2, 5, 6 and 7 against the **current** file. If the file changed since the proposal, the approval shows a conflict diff instead of writing.

### 4. Change log (`~/.ghostbrain/changes.db`, SQLite via the stdlib)

Table `changes`:
- identity and attribution: `id`, `ts`, `actor`, `rel_path`, `dest_path`, `op`, `reason`;
- content: `before_blob`, `after_blob` (blob ids in the history store; null for create / delete respectively), `pending_bytes_blob`;
- state: `status` (`applied | pending | reverted | rejected | conflicted`), `risk_reasons` (JSON).

It's indexed by `ts` and `status`. SQLite rather than JSONL because status updates (revert, approve) are frequent in-place edits. Retention: 1 year, pruned by the history-pruning job.

### 5. Routes (`ghostbrain/api/routes/changes.py`, new)

- `GET /v1/changes?status=&actor=&since=&limit=`: newest first.
- `GET /v1/changes/{id}`: includes a unified diff (before vs after, or vs pending bytes).
- `POST /v1/changes/{id}/revert`: only if the current file's etag equals `after_blob`. Otherwise **409**, with the diff of what changed since; the client can resend with `force: true`, which snapshots the current file first. A revert is itself recorded as a `user` write; the original row becomes `reverted`.
- `POST /v1/changes/{id}/approve` and `POST /v1/changes/{id}/reject`.
- Read routes (`GET /v1/notes?path=`, the jot read) gain an `etag` field.

### 6. Changes screen (renderer)

- A new nav item, **Changes**, with a badge showing the pending count (polled every 30 s via React Query).
- **Pending** section at the top: each card shows the actor, path, reason, risk reasons and a diff, with **Approve** / **Reject**.
- **History** list grouped by day: an actor chip (✦ assistant, ⚙ worker, ⧉ plugin name, ⌁ MCP), path, op, reason, an expandable diff (reusing spec A's `HistoryDrawer` diff component), and **Revert**. A reverted row shows "reverted · undo", where undo reverts the revert.
- Filter chips by actor and a path search.
- Clicking a path opens the note in `NoteView`.

### 7. Editor conflict handling

- Autosave sends the etag from the last read or save as `If-Match`; the server maps it to `base_etag`.
- On 409 the editor **stops autosaving** and shows a banner: "This note changed outside the editor." The options:
  - **View changes:** a diff of theirs against yours.
  - **Keep theirs:** reload.
  - **Keep mine:** overwrite with a fresh `base_etag`, which snapshots theirs first, so it's revertible.
- The user's unsaved text is never discarded silently.

## Data flow (assistant edit → revert)

```
Accept in editor → PATCH /v1/notes/body  (If-Match: e1, X-Poltergeist-Actor: assistant)
  → vault_write.write(body, actor=assistant, base_etag=e1)
     etag check ✓ → risk ✓ (prose) → history.snapshot(before=b1) → atomic write (after=b2)
     → changes row {id:42, actor:assistant, before:b1, after:b2, status:applied}
Changes screen → Revert #42 → current etag == b2 ✓ → write(content=b1, actor=user) → row 42 = reverted
```

## Error handling

- **Etag mismatch → 409:** the editor shows the conflict banner (§7); the MCP tool returns "note changed since you read it — re-read and retry"; plugins get the 409 body.
- **History snapshot fails for a non-user write:** the write is refused (500 with `history unavailable`), the file is untouched, and a toast appears.
- **Change-log insert fails after a successful write:** the write stands (the snapshot already exists, so a restore is possible via page history). The failure is logged and the Changes screen shows a banner: "some changes may be missing; see page history".
- **Approving a stale pending change:** a conflict diff, never a blind write.
- **Revert of a deleted file:** recreates it from `before_blob`.

## Testing

- **Pytest:**
  - Write-path unit tests: the body splice keeps frontmatter bytes identical, including key order, quoting, comments and unknown keys; a field edit touches exactly one line; a multi-line field re-serialises only its own block; atomic write; per-path lock under concurrent threads; etag 409.
  - Risk rules: each path and content rule, plus prose that must *not* be held.
  - Change log: record, revert (happy path, 409 when changed since, force), approve or reject pending, stale approve.
  - Every migrated writer: a golden test that the bytes written equal the previous behaviour, except for the intended no-reformat fix.
  - Actor header mapping, including that a missing header means user.
- **Vitest:** Changes screen (pending approve or reject, revert, conflict prompt, filters, badge count); editor conflict banner (autosave paused, the three choices); the forwarder only passes allowed actor values; plugin calls are stamped.
- **Manual:** let Familiar run a sweep and check its notes appear under ⧉ familiar and revert cleanly. Ask chat to write a doc and check it appears under ⌁ MCP. Edit a note in Obsidian while it's open in Poltergeist and check the conflict banner.

## Slices (build order)

1. **B1 Write path + etags:** `vault_write` (splice, fields, atomic, lock, etag), migration of the API writers, editor `If-Match` and the conflict banner. On its own this delivers "never overwrite" and "never reformat".
2. **B2 Change log + Changes screen:** actor attribution end to end (header, forwarder, plugin stamping, MCP), the changes DB, routes, screen, revert.
3. **B3 Risk policy + approvals:** `risk.py`, the pending flow, approve or reject, nav badge.
4. **B4 Worker modifications:** move `reversal.py` and `profile/apply.py` onto the write path as `worker:<job>`.

## Decisions (approved by the user 2026-10-09)

1. **Connector ingest on the Changes screen?** → **No.** New ingested notes stay audit-only.
2. **Should assistant-created *new* notes need approval?** → **No:** apply immediately, revert in one click (Brainstead's model). Only the risk rules hold changes.
3. **Should plugins be allowed to edit `90-meta`?** → **Allowed but always pending.** That's the risk path rule; there's no hard block.
