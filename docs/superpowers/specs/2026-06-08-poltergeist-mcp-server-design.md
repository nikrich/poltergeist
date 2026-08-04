# Poltergeist MCP Server — Design

**Date:** 2026-06-08
**Status:** Draft, awaiting implementation plan

## Problem

The vault can already answer questions about the user's work (`POST /v1/answer`),
search semantically (`POST /v1/search`), and return any note (`GET /v1/notes`).
But that intelligence is only reachable from the desktop app. The user lives in
Claude Code and Claude Desktop, and there's no way to query the brain from there
— mid-task, where the recall is most valuable.

**The ask:** expose the vault's retrieval surface as MCP tools so Claude Code /
Desktop can ask the brain, search it, and read individual notes, using the
already-running sidecar (warm embedding model, no cold start).

## Goals

1. **Query the vault from any MCP client** — `ask`, `search`, `get_note`,
   exposed as well-described MCP tools.
2. **Reuse the warm daemon** — forward to the running sidecar so the embedding
   model is already loaded; tool calls don't pay a cold-start cost.
3. **Zero new retrieval logic** — the shim is a transport adapter, not a second
   implementation of search/answer.
4. **Clear failure UX** — if Poltergeist isn't running, every tool returns a
   plain, actionable error rather than a stack trace.
5. **Ship an installable skill** — `poltergeist-recall`: a Claude skill that
   both wires/verifies the MCP connection and teaches Claude when and how to
   query the brain during work.

## Non-goals

- **No `capture`/write tool in v1.** Writing a note is the Jots write path
  (`POST /v1/notes`), which is specced and planned but not merged. `capture`
  is a fast follow-on once Jots lands — see [[2026-05-14-poltergeist-jots-design]].
  This spec is read-only.
- **Not a standalone retrieval engine.** The shim does not load the embedding
  model or call `claude -p` itself. If the sidecar is down, the tools error;
  they do not fall back to a local implementation.
- **No multi-user / auth / remote.** Single-user, local-first, 127.0.0.1 only —
  consistent with the rest of Poltergeist.
- **No streaming.** Tools are request/response, matching the underlying
  `/v1/answer` (~5–15s for a typical ask).

## Architecture overview

```
   Claude Code / Claude Desktop
          │  stdio  (MCP protocol, JSON-RPC)
          ▼
   ghostbrain-mcp  ── thin shim (Python, `mcp` SDK)
          │  1. read  ~/ghostbrain/run/sidecar.json → {port, token, pid}
          │  2. validate pid is alive (stale file ⇒ "not running")
          │  3. httpx → 127.0.0.1:{port} with `Authorization: Bearer {token}`
          ▼
   sidecar (already-running FastAPI daemon, embedding model warm)
     POST /v1/answer · POST /v1/search · GET /v1/notes?path=
```

The shim holds **no retrieval logic**. It discovers the sidecar, forwards each
call, and maps the JSON response into an MCP tool result. All embedding/LLM work
stays in the warm daemon — a tool call is one local HTTP round-trip plus whatever
the endpoint already costs.

The flow reuses existing infrastructure end-to-end:
- **Retrieval:** `ghostbrain.api.repo.search.search` and `…repo.answer.answer`
  are unchanged; the shim hits their HTTP endpoints.
- **Notes:** `ghostbrain.api.repo.note.get_note` via `GET /v1/notes`.
- **Auth:** the sidecar already requires `Authorization: Bearer {token}` and
  binds 127.0.0.1 (see `ghostbrain/api/auth.py`).

## The one backend change: runtime descriptor

Today the sidecar picks a **random free port** and generates a **random 256-bit
token** on every boot (`ghostbrain/api/__main__.py`), then prints them in a READY
banner to stdout that the Electron parent captures. Nothing is persisted to disk.
Claude Code spawns the MCP shim independently of Electron, so the shim has no way
to discover the running sidecar.

**Fix:** the sidecar writes a runtime descriptor file on boot and removes it on
graceful exit. The shim reads it.

### New module: `ghostbrain/api/runtime.py`

Single source of truth for the descriptor's location, schema, write, and read —
imported by both the sidecar boot path and the shim.

- **Path:** `~/ghostbrain/run/sidecar.json` (directory created if absent).
  Resolved via `ghostbrain.paths` so it honours a relocated home/vault root.
- **Schema:**
  ```json
  {
    "port": 51234,
    "token": "…64 hex chars…",
    "pid": 4242,
    "version": "1.0.0",
    "started_at": "2026-06-08T09:30:15+02:00"
  }
  ```
- **Write:** atomic (write temp file, `chmod 600`, `os.replace`). `chmod 600`
  because the file contains the bearer token. Called from `__main__.py` right
  after `port`/`token` are chosen, before the READY banner.
- **Remove on exit:** registered via `atexit` and a `SIGTERM`/`SIGINT` handler.
  Best-effort — a hard crash leaves a stale file, handled on the read side.
- **Read (`load_descriptor()`):** parse the JSON, then **liveness-check the pid**
  (`os.kill(pid, 0)`). If the file is missing, unparseable, or the pid is dead,
  return `None`. This makes crash-leftover descriptors look like "not running".

This is the only change outside the new `ghostbrain/mcp/` package.

## Tool surface (read-only v1)

Three tools. Names are prefixed `poltergeist_` so they read clearly in a client
that has many MCP servers connected.

### `poltergeist_ask`

- **Maps to:** `POST /v1/answer`.
- **Input:** `question: str` (1–500 chars), `limit: int = 8` (1–20).
- **Output:** the markdown `answer` (with `[N]` citation markers) plus a
  `sources` list (`path`, `title`, `snippet`, `score`).
- **Description (agent-facing):** "Ask a natural-language question about the
  user's own work, history, and decisions across all their contexts. Returns a
  synthesized answer with citations. Costs an LLM call (~5–15s) — prefer
  `poltergeist_search` when you just need to locate notes."

### `poltergeist_search`

- **Maps to:** `POST /v1/search`.
- **Input:** `query: str` (1–500 chars), `limit: int = 10` (1–50).
- **Output:** `total` and `items` — ranked hits (`path`, `title`, `snippet`,
  `score`). No LLM synthesis.
- **Description:** "Semantic search across the user's vault. Cheap and fast (no
  LLM). Returns ranked note paths with snippets; follow up with
  `poltergeist_get_note` to read a full note."

### `poltergeist_get_note`

- **Maps to:** `GET /v1/notes?path=<vault-relative>`.
- **Input:** `path: str` (vault-relative, 1–500 chars).
- **Output:** the note's frontmatter + full body (the existing `Note` model).
- **Description:** "Fetch the full content and metadata of one vault note by its
  vault-relative path (as returned by `poltergeist_search` or a citation from
  `poltergeist_ask`)."

Tool *descriptions* are first-class: they're what makes Claude Code choose the
right tool and chain them well (search → get_note; ask for synthesis). They are
part of the deliverable, not an afterthought.

## Code layout

New package `ghostbrain/mcp/`:

- `__main__.py` — builds the MCP server (Python `mcp` SDK), registers the three
  tools, runs the **stdio** transport. This is the `ghostbrain-mcp` entrypoint.
- `client.py` — sidecar discovery + calls: `load_descriptor()` (re-exported from
  `ghostbrain/api/runtime.py`), an httpx client that injects the Bearer token,
  and the `SidecarNotRunning` error. One place owns the "is it up?" logic.
- `tools.py` — the three tool definitions (schemas + the request/response mapping
  to `client.py`).

Console entrypoint in `pyproject.toml`:
```toml
[project.scripts]
ghostbrain-mcp = "ghostbrain.mcp.__main__:main"
```

## Claude Code / Desktop wiring

```json
{ "mcpServers": { "poltergeist": { "command": "ghostbrain-mcp" } } }
```

- **Dev / `pip install -e ".[dev]"`** puts `ghostbrain-mcp` on PATH directly —
  works immediately.
- **Packaged app (PyInstaller):** the entrypoint must be shipped or pathed for
  end users who never `pip install`. Out of scope for v1; tracked as a known
  follow-up.

The `poltergeist-recall` skill (below) is the supported way to write this config
and verify the connection — the user shouldn't hand-edit `.mcp.json`.

## Installable skill: `poltergeist-recall`

A Claude skill shipped at `.claude/skills/poltergeist-recall/`, following the
same shape as the existing `onboarding-poltergeist` skill (`SKILL.md` with
`name` + `description` frontmatter, plus supporting `.md` files). It does two
jobs — **install** and **use**.

### Frontmatter

- **name:** `poltergeist-recall`
- **description:** triggers on "connect Poltergeist to Claude Code", "set up the
  Poltergeist MCP", "query my brain / second brain / vault from here", and on
  any moment where recalling the user's own prior decisions/history would help.

### Install half (`SKILL.md`)

Step-by-step the skill walks:
1. Confirm `ghostbrain-mcp` resolves (dev: on PATH after `pip install -e`;
   otherwise point at the venv/packaged entrypoint).
2. Add the `poltergeist` server to the target `.mcp.json` (project or user
   scope, ask which) — exact snippet above.
3. Verify the sidecar is up: check `~/ghostbrain/run/sidecar.json` exists and its
   pid is alive; if not, tell the user to open the Poltergeist app.
4. Smoke-test: call `poltergeist_search` with a throwaway query and confirm a
   structured response (or the clean "not running" error).

### Use half (supporting `.md`, e.g. `using.md`)

Guidance Claude loads when deciding to query the brain:
- **When to reach for it:** before starting non-trivial work, to recall prior
  decisions, past incidents, why something was built a certain way, or what the
  user already concluded — instead of asking the user to re-explain.
- **Which tool:** `poltergeist_ask` for a synthesized answer to a real question
  (costs an LLM call); `poltergeist_search` → `poltergeist_get_note` to locate
  and read source notes cheaply when you want the raw material.
- **How to use results:** cite the note path when acting on recalled context, so
  the user can trace it; treat vault content as the user's ground truth.
- **What not to do:** don't spam `ask` for things in the current conversation;
  don't treat a "not running" error as a reason to invent facts.

## Failure modes

- **Sidecar not running / stale descriptor** (`load_descriptor()` returns
  `None`): every tool returns a clear MCP tool error — *"Poltergeist isn't
  running — open the Poltergeist app to start it."* No retry, no fallback.
- **Sidecar reachable but returns 5xx / error body:** relay the structured error
  verbatim. `POST /v1/answer` already returns `{answer, sources, error}` on
  internal failure (model load, missing index, LLM timeout) rather than a 500 —
  the shim surfaces `error` as the tool error when present.
- **Connection refused after a valid descriptor read** (sidecar died between
  read and call): same "not running" message as a missing descriptor.
- **Bad `path` to `get_note`:** the endpoint already returns 400 (invalid path)
  / 404 (not found); the shim maps these to a descriptive tool error.

## Testing

- **Unit**
  - `runtime.py`: descriptor round-trips (write → read); `chmod 600` applied;
    stale-pid detection returns `None`; missing/unparseable file returns `None`.
  - `tools.py`: each tool maps request args → the right HTTP call and maps the
    response/error correctly (httpx mocked).
  - `client.py`: `SidecarNotRunning` raised when descriptor is `None`; Bearer
    token injected on every request.
- **Integration**
  - Boot a real sidecar app via FastAPI `TestClient` (or a live uvicorn on a
    random port), write a descriptor pointing at it, and drive the three tools
    through the `mcp` SDK's in-memory transport. Assert `ask`/`search` return
    hits for a seeded vault and `get_note` returns a known note's body.
  - "Not running" path: no descriptor present → all three tools return the
    actionable error.

## Build sequence

1. `ghostbrain/api/runtime.py` — descriptor schema, atomic write (`chmod 600`),
   `load_descriptor()` with pid liveness check. Unit tests.
2. Wire descriptor write + exit-cleanup into `ghostbrain/api/__main__.py`.
3. `ghostbrain/mcp/client.py` — discovery, httpx-with-token, `SidecarNotRunning`.
4. `ghostbrain/mcp/tools.py` — three tools + descriptions.
5. `ghostbrain/mcp/__main__.py` — server + stdio transport + `main()`.
6. `ghostbrain-mcp` entrypoint in `pyproject.toml`.
7. Integration tests through the mcp SDK in-memory transport.
8. `.claude/skills/poltergeist-recall/` — `SKILL.md` (install/verify) +
   `using.md` (when/how to query). Mirror the `onboarding-poltergeist` shape.
9. README + `.mcp.json` snippet; note the packaged-app entrypoint follow-up.

## Future (not this spec)

- **`poltergeist_capture`** once Jots' `POST /v1/notes` write path merges.
- **Packaged-app entrypoint** wiring via `onboarding-poltergeist`.
- These same tools are the reusable core the planned **in-app chat** surface will
  call — designing them cleanly here is deliberate.
