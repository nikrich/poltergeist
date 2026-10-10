# C2 Smart Templates — Live Queries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ` ```query ` block in a note renders as a live list of matching notes inside Poltergeist. Each row has a checkbox: ticking it writes `status: done` into that note's frontmatter, and the list refreshes. A Freeze action replaces the block with a static markdown list. Outside Poltergeist, the block stays a readable code fence.

**Architecture:** On the backend, `ghostbrain/templates/query.py` parses the block with a closed, line-based grammar. Its keys come from a new `QUERY_KEYS` group in C1's registry (`functions.py`), and errors are C1 `Diagnostic`s. It runs the query against A2's in-memory `LinkIndex`, with hard bounds on rows, body reads and time. `ghostbrain/api/repo/vault_query.py` backs two routes in `routes/vault.py`: `POST /v1/vault/query` returns results plus diagnostics, and `PATCH /v1/vault/status` writes through B1's `vault_write.write(fields={"status": …}, actor=USER, base_etag=If-Match)`. On the desktop, `lib/editor/query-view.ts` is a vanilla ProseMirror NodeView. It plugs into A1's single `GbCodeBlock` node-view dispatch in `lib/editor/code-block.ts` as the `language === 'query'` branch, next to Mermaid. Clicking a result goes out through a typed editor event to `RichMarkdownEditor`'s existing `onWikilinkClick`, so NoteView's unsaved-changes guard still applies.

**Tech Stack:** Python 3.11+ (CI runs 3.11), FastAPI, pydantic v2, PyYAML (through A2's `split_frontmatter` only), `ghostbrain.vault_index` (A2), `ghostbrain.vault_write` (B1), `ghostbrain.templates` (C1). Desktop: Tiptap 2.27.2 with tiptap-markdown 0.8.10, vanilla ProseMirror NodeViews, Vitest 2 + jsdom + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-09-smart-templates-design.md`. This plan covers slice **C2 Live queries** only: link-index fields for queries, `/v1/vault/query`, and the query NodeView with tick-to-done and Freeze. The template editor and query-key completions (C3) and AI templates (C4) are out of scope.

## Global Constraints

- **C2 builds on a branch that contains C1** (`docs/superpowers/plans/2026-10-09-c1-templates-engine.md`). It needs `ghostbrain/templates/{lang,functions,parse,render,starters}.py`, `tests/test_templates_functions.py`, `ghostbrain/api/tests/test_templates_routes.py`, and the `TemplateDiagnostic` / `TemplateFunctionSpec` / `TemplateFunctionsResponse` types in `desktop/src/shared/api-types.ts`.
- **C2 builds on a branch that contains A1** (`docs/superpowers/plans/2026-10-09-a1-editor-blocks.md`). It needs `desktop/src/renderer/lib/editor/code-block.ts` (`GbCodeBlock` and its `addNodeView` dispatch, Task 6), `lib/editor/events.ts` (`GbEditorEvents`, `emitGb`, `onGb`, Task 3) and `__tests__/helpers/editor.ts` (`makeEditor`, `markdownOf`, Task 1).
- Before Task 1, verify both are present: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && ls ghostbrain/templates/functions.py ghostbrain/templates/parse.py ghostbrain/templates/lang.py desktop/src/renderer/lib/editor/code-block.ts desktop/src/renderer/lib/editor/events.ts desktop/src/renderer/__tests__/helpers/editor.ts`. If any file is missing, stop and rebase onto a branch that has merged C1 and A1.
- A2 (`ghostbrain/vault_index`) and B1 (`ghostbrain/vault_write`) are on main. Use them as they are.
- **User-approved decisions:** results stay **live only**, and the only way to get a static copy is the manual **Freeze** action. Ticking an item writes **`status: done`** into that note's frontmatter.
- Ticking goes through `vault_write.write(path, fields={"status": <value>}, actor=USER, reason=…, base_etag=<If-Match>)` and nothing else. That is a single-line, byte-preserving frontmatter edit. A stale etag returns **409** with `currentEtag`, and nothing is written.
- `status: open` means frontmatter `status` is neither `done` nor `closed`, compared case-insensitively. A note with no `status` key counts as open.
- Query keys come from the spec: `type`, `context`, `tag`, `mentions`, `status`, `since` (`7d`, `2026-10-01`), `sort` (`created|updated` + `asc|desc`), and `limit` (**default 20, max 100**). They are defined **once**, as `functions.QUERY_KEYS`, and the parser's whitelist is built from that tuple.
- **Query text is untrusted input** (templates may be AI-written in C4). The parser and runner never evaluate anything: no `eval`, no dynamic imports, no YAML loading of the block, and user text reaches a regex only through `re.escape`. Every run is bounded: at most `MAX_QUERY_CHARS = 2000` characters and `MAX_QUERY_LINES = 40` lines per block, `MAX_LIMIT = 100` rows, `MAX_TEXT_READS = 2000` body reads, and `DEADLINE_S = 2.0` seconds. Past a bound, the run stops and returns `partial: true`. C1's static guard `test_sec_engine_source_has_no_dynamic_execution` scans `ghostbrain/templates/*.py`, so it covers `query.py` automatically.
- **No new node type, no new on-disk form.** A query block is a plain ` ```query ` fence handled by A1's `GbCodeBlock`. Its markdown must round-trip byte-stable (fixture in `markdown-roundtrip.test.ts`). `extensions.ts` does not change.
- The link index stays memory-only. C2 adds **no** `NoteEntry` fields (see Decision 1).
- `ghostbrain/templates/__init__.py` stays import-free. `query.py` is imported only by the API route, which runs under `[api]` and has pydantic.
- Backend CI installs only `[dev,api]`. Every new `tests/*.py` file is added to the fixed list in `.github/workflows/ci.yml`. Files under `ghostbrain/api/tests/` are already covered by the directory entry.
- Python commands run from the repo root: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && python -m pytest …`.
- Desktop commands run from `desktop/`: `cd /Users/jannik/development/nikrich/ghost-brain-plans3/desktop && …`. The gates are `npm run typecheck` (`tsc -b`, **never** `tsc --noEmit`), `npx vitest run`, and `npm run lint` (`eslint . --max-warnings 0`).
- Windows release builds rerun the desktop tests. Tests must not depend on the timezone, POSIX paths or real timers, so use `vi.useFakeTimers()`. Dates in desktop fixtures are fixed strings.
- UI copy is lower-case, matching the app (`live query`, `edit query`, `freeze`, `results unavailable — retry`).
- Use neutral example content only: the person is "Alex" (or "Robin" for a name with no page), and the context is "work". The CI guard `tests/test_no_hardcoded_contexts.py` scans `ghostbrain/`, `docs/` and `desktop/src`.

## Review Focus

1. **Action items made before C2 have no `status` key.** `status: open` must list them. Ticking one must add exactly one `status: done` line and leave every other byte alone, including YAML comments. Pinned in Task 3 (`test_open_includes_notes_without_status_and_excludes_done_or_closed`) and Task 4 (`test_tick_adds_one_status_line_and_preserves_every_other_byte`).
2. **The note changed after the list loaded.** A connector re-wrote it, or the user edited it in NoteView. The tick must not overwrite: it gets a 409, writes nothing, shows an inline "changed elsewhere" notice and refreshes the list. Pinned in Task 4 (`test_tick_with_a_stale_etag_is_409_and_writes_nothing`) and Task 7 (`a 409 shows the changed-elsewhere notice and refreshes`).
3. **A person with no page yet.** A 1-1 made from a typed name has `mentions: "[[Alex]]"`, and many action items name "Alex" only in body text. Both must still match, but "Alexander" must not, and neither must text inside another note's ` ```query ` fence. Pinned in Task 3 (`test_mentions_matches_links_then_body_text`, `test_mentions_a_name_with_no_page_falls_back_to_text`).
4. **First launch with a cold index, or the sidecar down.** The note still opens. The block shows a "results unavailable — retry" chip, which retries on its own while the index builds and on click. Pinned in Task 4 (`test_cold_index_reports_indexing`) and Task 6 (`shows the retry chip when the sidecar fails…`, `retries automatically while the index is building`).
5. **A pathological block.** Examples: a 2,000-line paste, `limit: 999999`, or `mentions:` of a word that appears nowhere in a 30k-note vault. The run must stay bounded: a capped limit with a warning, size errors, and `partial: true` instead of a long scan. Pinned in Task 2 (`test_size_caps`, `test_limit_over_the_cap_is_capped_with_a_warning`) and Task 3 (`test_text_scan_is_bounded_and_reports_partial`, `test_limit_and_cap`).

## Decisions taken where the spec was silent or ambiguous

1. **Link-index fields.** The spec says the index "is extended to carry `artifactType, type, status, context, tags, created, updated`". A2's `NoteEntry` already has all of them, plus `hashtags`, `mtime_ns` and `links`, so **C2 adds no index fields**. The result columns the index lacks (a readable title, a snippet and the etag) are read from the at most 100 result files at query time. That keeps the 30k-note index small, and it means the etag and status a row shows are the file's current ones, not the index's.
2. **Block grammar.** One `key: value` per line. Keys are case-insensitive. Values may be wrapped in `'…'` or `"…"`. Lines that start with `#` are comments. Each key appears once and takes one value. The block is never YAML-loaded, so anchors, tags and nesting do not exist. An empty block is an error (`empty-query`), so a new block shows guidance instead of 20 random notes.
3. **`mentions`** takes a wikilink (`[[target]]`, `[[target|alias]]`, `[[target#heading]]`) or a bare name (`Alex`, `@Alex`). A note matches if one of its links resolves to the same page. The comparison is case-insensitive for bare names, so `[[Alex]]` and `[[alex]]` both reach `30-cross-context/people/alex.md`. Otherwise, it matches if its body contains the alias, the target's file stem or the page's title as a whole word, case-insensitively. Text inside ` ```query ` fences is ignored for that text match. The person's own page is never a result. Links inside other notes' query fences still count as links, because A2 indexes them. Queries normally filter by `type`, so this is accepted.
4. **`since`** compares against `created`. It accepts `Nd`, `Nw` (weeks) or `YYYY-MM-DD`. A missing or unparseable `created` falls back to the file's mtime. `sort: updated` falls back to the mtime the same way. A timestamp without a timezone is read as UTC. Ties sort by path, ascending.
5. **`status`** takes one word. `open` is special (Global Constraints). Any other word matches exactly, case-insensitively. **Unticking** a done row writes `status: open`, an explicit value, rather than deleting the key.
6. **`limit`** is a whole number. Above 100, it is capped to 100 with a `limit-capped` **warning**, and the query still runs. Below 1, it is an error.
7. **Route shapes.** `POST /v1/vault/query` takes `{query: <the fence's text>}` and **always answers 200** with `{results, diagnostics, indexing, partial}`, so the block can show diagnostics inline. An oversize body (over 8,000 characters) returns 422. `PATCH /v1/vault/status` takes `{path, status: "done" | "open"}` and an optional `If-Match`, and returns `{path, status, etag}`. It accepts only `.md` paths.
8. **`run_query` returns `QueryRun(rows, partial)`** instead of the `list[dict]` that C1's extension note sketched, because the caller needs the `partial` flag. `QueryRow.to_json()` gives the dict.
9. **Refresh cadence.** Results are fetched on mount (deferred one tick, so the throwaway `parsesAsRich` probe editor never sends a request), when the window gains focus, every 60 s while the block is on screen and the document is not hidden, 500 ms after the query text stops changing, and after every tick. While the index is cold, the block retries up to 5 times, 2 s apart.
10. **Freeze** writes the rows currently on screen as a GFM task list: `- [ ] [[path-without-.md|Title]]`, with `- [x]` for done or closed rows. Brackets and pipes in titles become spaces. Zero rows freeze to the paragraph `no matching notes`. Freeze is a normal editor transaction, so Cmd+Z undoes it. It is disabled while the query has errors or no results have loaded yet.
11. **Read-only editors** (synced notes, history previews) disable ticking and Freeze. "Edit query" still toggles the source view.
12. **Opening a result** emits `gb:query:open {path}`. `RichMarkdownEditor` forwards it to `onWikilinkClick(noteTarget(path))`, the same path a clicked `[[wikilink]]` takes, so NoteView's unsaved-changes guard applies.
13. **No `/query` slash item in C2.** The spec does not list one. Typing ` ```query ` plus Enter already creates the block, and templates insert it. Query-key completions arrive in C3 through `queryKeys` in `GET /v1/templates/functions`.

---

## Interfaces

```python
# ghostbrain/templates/functions.py (C1, extended in Task 1)
Kind = Literal["variable", "field", "filter", "prompt_type", "query_key"]
QUERY_KEYS: tuple[FunctionSpec, ...]      # names, in order: type, context, tag, mentions, status, since, sort, limit
def find_spec(kind: Kind, name: str, owner: str | None = None) -> FunctionSpec | None   # now also searches QUERY_KEYS
def registry_json() -> dict[str, list[dict[str, Any]]]   # + "queryKeys"

# ghostbrain/templates/query.py (Tasks 2-3)
MAX_QUERY_CHARS = 2_000; MAX_QUERY_LINES = 40; MAX_VALUE_CHARS = 200
DEFAULT_LIMIT = 20; MAX_LIMIT = 100; MAX_TEXT_READS = 2_000; MAX_NOTE_BYTES = 2_000_000; DEADLINE_S = 2.0
CLOSED_STATUSES = frozenset({"done", "closed"}); QUERY_KEY_NAMES: tuple[str, ...]
@dataclass(frozen=True) class Mention: target: str; name: str        # target = normalized ".md" key
@dataclass(frozen=True) class Query:
    type: str | None = None; context: str | None = None; tag: str | None = None
    mentions: Mention | None = None; status: str | None = None; since: date | None = None
    sort: Literal["created", "updated"] = "created"; descending: bool = True; limit: int = DEFAULT_LIMIT
def parse_query_block(text: str, *, today: date | None = None) -> tuple[Query | None, list[Diagnostic]]
@dataclass(frozen=True) class QueryRow:
    path: str; title: str; context: str; status: str | None; created: str | None; snippet: str; etag: str | None
    def to_json(self) -> dict[str, Any]
@dataclass(frozen=True) class QueryRun: rows: tuple[QueryRow, ...]; partial: bool
def run_query(query: Query, index: LinkIndex, *, clock: Callable[[], float] = time.monotonic,
              deadline_s: float = DEADLINE_S, max_text_reads: int = MAX_TEXT_READS) -> QueryRun

# ghostbrain/api/repo/vault_query.py (Task 4)
INDEX_WAIT_S = 0.25
def query_vault(source: str, *, index: LinkIndex | None = None, today: date | None = None) -> dict
def set_note_status(path: str, status: str, *, base_etag: str | None) -> dict   # raises B1 errors
```

HTTP (bearer auth like every route; B1's handlers map `InvalidPath`→400, `FileMissing`→404, `WriteConflict`→409 `{detail, currentEtag}`, `MalformedNote`→422):

| Route | Body | 2xx | Errors |
|---|---|---|---|
| `POST /v1/vault/query` | `{query: str}` (≤ 8000 chars) | 200 `{results: [{path, title, context, status, created, snippet, etag}], diagnostics: [{line, col, severity, message, code}], indexing: bool, partial: bool}` | 422 oversize body |
| `PATCH /v1/vault/status` | `{path: str, status: "done" \| "open"}` + optional `If-Match` | 200 `{path, status, etag}` | 400 bad path / not `.md` · 404 missing · 409 stale etag · 422 bad status or frontmatter that is not a mapping |

```ts
// desktop/src/shared/api-types.ts (Task 5)
export interface VaultQueryRow { path: string; title: string; context: string; status: string | null; created: string | null; snippet: string; etag: string | null }
export interface VaultQueryResponse { results: VaultQueryRow[]; diagnostics: TemplateDiagnostic[]; indexing: boolean; partial: boolean }
export type NoteStatusValue = 'done' | 'open';
export interface NoteStatusResponse { path: string; status: NoteStatusValue; etag: string | null }
// TemplateFunctionSpec.kind gains 'query_key'; TemplateFunctionsResponse gains queryKeys: TemplateFunctionSpec[]

// desktop/src/renderer/lib/editor/query-api.ts (Task 5)
export function runVaultQuery(source: string): Promise<VaultQueryResponse>
export function setNoteStatus(path: string, status: NoteStatusValue, etag: string | null): Promise<NoteStatusResponse>
// desktop/src/renderer/lib/editor/query-format.ts (Task 5)
export function isClosedStatus(status: string | null): boolean
export function frozenItem(row: VaultQueryRow): string
export function freezeMarkdown(rows: VaultQueryRow[]): string
// desktop/src/renderer/lib/editor/query-view.ts (Tasks 6-7)
export const QUERY_POLL_MS = 60_000; QUERY_EDIT_DEBOUNCE_MS = 500; QUERY_INDEX_RETRY_MS = 2_000; QUERY_INDEX_RETRIES = 5
export function createQueryView(initial: PMNode, editor: Editor, getPos: unknown): NodeView
// desktop/src/renderer/lib/editor/events.ts (A1, extended in Task 6)
GbEditorEvents['gb:query:open'] = { path: string }
```

**Query block DOM contract (Tasks 6–7):** `div.gb-query[data-editing]` contains:

- `div.gb-query-bar` (contenteditable false), holding:
  - `span.gb-query-label` "live query";
  - `button[aria-label="refresh query"]`;
  - `button[aria-label="query options"]`;
  - `div[role="menu"]`, with `button[role="menuitem"]` items "edit query" / "done editing" and "freeze".
- `div.gb-query-results` (contenteditable false). It holds one of the following, plus an optional `p.gb-query-notice[role="status"]`:
  - `p.gb-query-status` ("loading…", "no matching notes", or the partial notice);
  - `button.gb-query-chip` "results unavailable — retry";
  - `div.gb-query-error[role="alert"]`, with one `p` per error ("line N: message") and a `pre` of the source;
  - `p.gb-query-warning`, followed by `ul.gb-query-list`. Each `li.gb-query-row` holds `input[type=checkbox][aria-label="mark <title> done|open"]`, `button.gb-query-link`, `span.gb-query-meta` and an optional `div.gb-query-snippet`.
- `pre > code.language-query` (the contentDOM).

---

## File Structure

Backend (new):
- `ghostbrain/templates/query.py`: block grammar (`parse_query_block`) and bounded runner (`run_query`). It is pure apart from reading result files under the index root.
- `ghostbrain/api/models/vault_query.py`: request and response models for the two routes.
- `ghostbrain/api/repo/vault_query.py`: `query_vault` (parse, index freshness, run) and `set_note_status` (the B1 write).
- Tests: `tests/test_templates_query.py` (parser and runner), `ghostbrain/api/tests/test_vault_query_routes.py`.

Backend (modify):
- `ghostbrain/templates/functions.py`: `Kind` gets `"query_key"`; add `QUERY_KEYS`, extend `find_spec` and `registry_json`.
- `tests/test_templates_functions.py`, `ghostbrain/api/tests/test_templates_routes.py`: registry expectations.
- `ghostbrain/api/routes/vault.py`: the two routes.
- `.github/workflows/ci.yml`: add `tests/test_templates_query.py`.

Desktop (new, under `desktop/src/renderer/`):
- `lib/editor/query-api.ts`: the two sidecar calls (vanilla, no React).
- `lib/editor/query-format.ts`: pure Freeze markdown and the status helper.
- `lib/editor/query-view.ts`: the NodeView (fetch, states, cadence, tick, Freeze).
- Tests: `__tests__/query-format.test.ts`, `__tests__/query-view.test.ts`, `__tests__/query-actions.test.ts`.

Desktop (modify):
- `desktop/src/shared/api-types.ts`: query types; the C1 registry type gets `query_key` and `queryKeys`.
- `lib/editor/code-block.ts` (A1): add the `query` branch to `GbCodeBlock`'s node-view dispatch.
- `lib/editor/events.ts` (A1): add `'gb:query:open'`.
- `components/RichMarkdownEditor.tsx`: forward `gb:query:open` to `onWikilinkClick`.
- `styles.css`: append query-block styles.
- `__tests__/markdown-roundtrip.test.ts`: query-fence and frozen-list fixtures. `__tests__/RichMarkdownEditor.test.tsx`: append one test.

---

### Task 1: Query keys in the template registry

**Files:**
- Modify: `ghostbrain/templates/functions.py`
- Modify: `tests/test_templates_functions.py`
- Modify: `ghostbrain/api/tests/test_templates_routes.py`

**Interfaces:**
- Consumes: C1's `FunctionSpec`, `Kind`, `VARIABLES`, `FIELDS`, `FILTERS`, `PROMPT_TYPES`, `find_spec`, `registry_json` (`ghostbrain/templates/functions.py`).
- Produces: `QUERY_KEYS: tuple[FunctionSpec, ...]`, with names in this order: `type, context, tag, mentions, status, since, sort, limit`. Each has `kind="query_key"`, a doc and an example that starts with `"<name>:"`. `find_spec("query_key", name)` works. `registry_json()["queryKeys"]` exists. Task 2 builds its key whitelist from `QUERY_KEYS`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_templates_functions.py`, change the key-set assertion in the existing `test_every_spec_is_documented_and_json_ready`:

```python
    assert set(data) == {"variables", "fields", "filters", "promptTypes", "queryKeys"}
```

Append:

```python
def test_query_keys_registry():
    from ghostbrain.templates.functions import QUERY_KEYS

    assert [s.name for s in QUERY_KEYS] == [
        "type", "context", "tag", "mentions", "status", "since", "sort", "limit",
    ]
    for spec in QUERY_KEYS:
        assert spec.kind == "query_key"
        assert spec.doc and spec.example.startswith(f"{spec.name}:")
    assert find_spec("query_key", "mentions") is QUERY_KEYS[3]
    assert find_spec("variable", "mentions") is None
    assert find_spec("query_key", "date") is None
    assert [s["name"] for s in registry_json()["queryKeys"]] == [s.name for s in QUERY_KEYS]
    assert registry_json()["queryKeys"][0]["kind"] == "query_key"
```

In `ghostbrain/api/tests/test_templates_routes.py`, append to `test_functions_registry`:

```python
    assert [k["name"] for k in data["queryKeys"]] == [
        "type", "context", "tag", "mentions", "status", "since", "sort", "limit",
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && python -m pytest tests/test_templates_functions.py ghostbrain/api/tests/test_templates_routes.py::test_functions_registry -v`
Expected: FAIL. `test_query_keys_registry` fails with `ImportError: cannot import name 'QUERY_KEYS'`, and the other two fail with `KeyError: 'queryKeys'` or a set mismatch.

- [ ] **Step 3: Implement**

In `ghostbrain/templates/functions.py`, change the `Kind` line to:

```python
Kind = Literal["variable", "field", "filter", "prompt_type", "query_key"]
```

Append after the `PROMPT_VALUE_TYPES` line, before `find_spec`:

```python
# Keys of a ```query``` block (spec C2). query.py builds its whitelist from
# this tuple, so the parser, the docs and C3's completions cannot drift apart.
QUERY_KEYS: tuple[FunctionSpec, ...] = (
    FunctionSpec("type", "query_key", "text",
                 "Notes whose frontmatter `artifactType` or `type` equals this, e.g. action_item, "
                 "decision or meeting.", "type: action_item"),
    FunctionSpec("context", "query_key", "text",
                 "Notes in this context: the 20-contexts/<name> folder, or frontmatter `context`.",
                 "context: work"),
    FunctionSpec("tag", "query_key", "text",
                 "Notes with this tag, in frontmatter `tags` or as #tag in the text.", "tag: roadmap"),
    FunctionSpec("mentions", "query_key", "text",
                 "Notes that link to this page, or else name it in their text. A wikilink or a name.",
                 'mentions: "[[30-cross-context/people/alex]]"'),
    FunctionSpec("status", "query_key", "text",
                 "`open` = status is not done or closed (notes with no status count as open). "
                 "Any other word matches exactly.", "status: open"),
    FunctionSpec("since", "query_key", "text",
                 "Created on or after: `7d`, `2w`, or a date like 2026-10-01.", "since: 7d"),
    FunctionSpec("sort", "query_key", "text",
                 "`created` or `updated`, then `asc` or `desc`. Default: created desc.",
                 "sort: created desc"),
    FunctionSpec("limit", "query_key", "number",
                 "How many notes to show: default 20, at most 100.", "limit: 20"),
)
```

Replace `find_spec` and `registry_json` with:

```python
def find_spec(kind: Kind, name: str, owner: str | None = None) -> FunctionSpec | None:
    for spec in (*VARIABLES, *FIELDS, *FILTERS, *PROMPT_TYPES, *QUERY_KEYS):
        if spec.kind == kind and spec.name == name and (owner is None or spec.owner == owner):
            return spec
    return None


def registry_json() -> dict[str, list[dict[str, Any]]]:
    return {
        "variables": [s.to_json() for s in VARIABLES],
        "fields": [s.to_json() for s in FIELDS],
        "filters": [s.to_json() for s in FILTERS],
        "promptTypes": [s.to_json() for s in PROMPT_TYPES],
        "queryKeys": [s.to_json() for s in QUERY_KEYS],
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && python -m pytest tests/test_templates_functions.py tests/test_templates_security.py ghostbrain/api/tests/test_templates_routes.py -v`
Expected: PASS. The security static guard still passes.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans3
git add ghostbrain/templates/functions.py tests/test_templates_functions.py ghostbrain/api/tests/test_templates_routes.py
git commit -m "feat(templates): query keys in the function registry"
```

---

### Task 2: Query block parser

**Files:**
- Create: `ghostbrain/templates/query.py`
- Create: `tests/test_templates_query.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `QUERY_KEYS` (Task 1); C1's `Diagnostic(line, col, severity, message, code)` from `ghostbrain.templates.parse`, and `tokenize`, `Placeholder` and `TemplateLimitError` from `ghostbrain.templates.lang`; A2's `normalize_target` from `ghostbrain.vault_index.parse`.
- Produces: the constants, `Mention`, `Query` and `parse_query_block` from the Interfaces block. Line and column numbers are 1-based within the block text. A key error points at the key (col = indent + 1). A value error points at the value's first character. Any error returns `(None, diagnostics)`. Warnings (`limit-capped`) still return a `Query`. Diagnostic codes are `syntax`, `unknown-key`, `duplicate-key`, `empty-value`, `value-too-long`, `unresolved-placeholder`, `bad-value`, `empty-query`, `query-too-long` and `limit-capped`.

- [ ] **Step 1: Write the failing tests**

`tests/test_templates_query.py`:

```python
"""Live ```query``` blocks (smart templates C2): grammar and runner."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import pytest

from ghostbrain.templates.query import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_QUERY_CHARS,
    MAX_QUERY_LINES,
    Mention,
    Query,
    parse_query_block,
)

TODAY = date(2026, 10, 10)


def _parse(text: str):
    return parse_query_block(text, today=TODAY)


def _codes(diags):
    return [(d.line, d.col, d.severity, d.code) for d in diags]


def test_one_on_one_block_parses():
    q, diags = _parse(
        'type: action_item\nmentions: "[[30-cross-context/people/alex]]"\n'
        "status: open\nsort: created desc\n"
    )
    assert diags == []
    assert q == Query(
        type="action_item",
        mentions=Mention("30-cross-context/people/alex.md", "alex"),
        status="open",
        sort="created",
        descending=True,
        limit=DEFAULT_LIMIT,
    )


def test_defaults_comments_quotes_and_case():
    q, diags = _parse("# open decisions\n\n  Type: 'Decision'\nCONTEXT: \"Work\"\n")
    assert diags == []
    assert q == Query(type="decision", context="work")
    assert (q.sort, q.descending, q.limit) == ("created", True, 20)


@pytest.mark.parametrize("value, expected", [
    ("Alex", Mention("Alex.md", "Alex")),
    ("@Alex", Mention("Alex.md", "Alex")),
    ('"[[Alex]]"', Mention("Alex.md", "Alex")),
    ("[[30-cross-context/people/alex|@Alex]]", Mention("30-cross-context/people/alex.md", "Alex")),
    ("[[30-cross-context/people/alex#Notes]]", Mention("30-cross-context/people/alex.md", "alex")),
])
def test_mentions_forms(value, expected):
    q, diags = _parse(f"mentions: {value}")
    assert diags == []
    assert q.mentions == expected


def test_tag_and_status_are_normalised():
    q, diags = _parse("tag: #Roadmap\nstatus: Open")
    assert diags == []
    assert (q.tag, q.status) == ("roadmap", "open")


@pytest.mark.parametrize("value, expected", [
    ("7d", date(2026, 10, 3)),
    ("2w", date(2026, 9, 26)),
    ("0d", TODAY),
    ("2026-10-01", date(2026, 10, 1)),
])
def test_since_forms(value, expected):
    q, diags = _parse(f"type: decision\nsince: {value}")
    assert diags == []
    assert q.since == expected


def test_sort_and_limit():
    q, diags = _parse("type: decision\nsort: updated asc\nlimit: 5")
    assert diags == []
    assert (q.sort, q.descending, q.limit) == ("updated", False, 5)
    q, _ = _parse("type: decision\nsort: Updated")
    assert (q.sort, q.descending) == ("updated", True)


def test_limit_over_the_cap_is_capped_with_a_warning():
    q, diags = _parse("type: decision\nlimit: 999999")
    assert q is not None and q.limit == MAX_LIMIT == 100
    assert _codes(diags) == [(2, 8, "warning", "limit-capped")]


@pytest.mark.parametrize("text, expected", [
    ("type: decision\nowner: alex", [(2, 1, "error", "unknown-key")]),
    ("type: decision\ntype: meeting", [(2, 1, "error", "duplicate-key")]),
    ("type decision", [(1, 1, "error", "syntax")]),
    ("type:", [(1, 6, "error", "empty-value")]),
    ("", [(1, 1, "error", "empty-query")]),
    ("# only a comment\n", [(1, 1, "error", "empty-query")]),
    ("since: yesterday", [(1, 8, "error", "bad-value")]),
    ("since: 2026-13-40", [(1, 8, "error", "bad-value")]),
    ("sort: title", [(1, 7, "error", "bad-value")]),
    ("limit: 0", [(1, 8, "error", "bad-value")]),
    ("limit: ten", [(1, 8, "error", "bad-value")]),
    ("status: not done", [(1, 9, "error", "bad-value")]),
    ("mentions: [[90-meta/assets/x.png]]", [(1, 11, "error", "bad-value")]),
    ("mentions: Alex [[b]]", [(1, 11, "error", "bad-value")]),
    ('mentions: "{{person.link}}"', [(1, 11, "error", "unresolved-placeholder")]),
    ("  tag: '#'", [(1, 8, "error", "bad-value")]),
])
def test_errors_carry_line_and_column(text, expected):
    q, diags = _parse(text)
    assert q is None
    assert _codes(diags) == expected


def test_unknown_key_message_lists_the_keys():
    _, diags = _parse("owner: alex")
    assert "use one of: type, context, tag, mentions, status, since, sort, limit" in diags[0].message


def test_size_caps():
    q, diags = _parse("type: decision\n" + "#\n" * MAX_QUERY_LINES)
    assert q is None and [d.code for d in diags] == ["query-too-long"]
    q, diags = _parse("type: " + "x" * MAX_QUERY_CHARS)
    assert q is None and [d.code for d in diags] == ["query-too-long"]
    q, diags = _parse("type: " + "x" * 201)
    assert q is None and [d.code for d in diags] == ["value-too-long"]


def test_rendered_one_on_one_starter_query_parses():
    """The C1 starter's fence, after rendering, is a valid C2 query."""
    from ghostbrain.templates.parse import parse_template
    from ghostbrain.templates.render import RenderEnv, render
    from ghostbrain.templates.starters import STARTER_TEMPLATES

    env = RenderEnv(now=datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2))),
                    default_context="work", contexts=("work", "personal"))
    template = parse_template(STARTER_TEMPLATES["one-on-one.md"], "one-on-one").template
    body = render(template, {"person": "Alex"}, env).body
    fences = re.findall(r"^```query\n(.*?)^```", body, flags=re.MULTILINE | re.DOTALL)
    assert len(fences) == 1
    q, diags = _parse(fences[0])
    assert diags == []
    assert q == Query(type="action_item", mentions=Mention("Alex.md", "Alex"), status="open")
```

In `.github/workflows/ci.yml`, add `tests/test_templates_query.py \` to the fixed pytest list, on the line after the last `tests/test_templates_*.py` entry that C1 added.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && python -m pytest tests/test_templates_query.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.templates.query'`.

- [ ] **Step 3: Implement the parser**

`ghostbrain/templates/query.py`:

```python
"""Live ```query``` blocks (smart-templates spec, slice C2).

A query block is a closed grammar: one ``key: value`` per line, keys from
``functions.QUERY_KEYS``, ``#`` lines are comments. It is never YAML-loaded
and never evaluated, and user text reaches a regex only through re.escape.
Runs are bounded (rows, body reads, wall time); past a bound the run stops
and reports ``partial``. Templates may be AI-written (C4): treat every block
as untrusted input.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal

from ghostbrain.templates.functions import QUERY_KEYS
from ghostbrain.templates.lang import Placeholder, TemplateLimitError, tokenize
from ghostbrain.templates.parse import Diagnostic
from ghostbrain.vault_index.parse import normalize_target

MAX_QUERY_CHARS = 2_000
MAX_QUERY_LINES = 40
MAX_VALUE_CHARS = 200
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_TEXT_READS = 2_000
MAX_NOTE_BYTES = 2_000_000
DEADLINE_S = 2.0
MIN_NAME_CHARS = 2
CLOSED_STATUSES = frozenset({"done", "closed"})
QUERY_KEY_NAMES: tuple[str, ...] = tuple(s.name for s in QUERY_KEYS)

_LINE_RE = re.compile(r"([A-Za-z][A-Za-z0-9_]*)[ \t]*:[ \t]*(.*)")
_WIKILINK_VALUE_RE = re.compile(r"\[\[([^\[\]|#\n]+)(?:#[^\[\]|\n]*)?(?:\|([^\[\]\n]*))?\]\]")
_SINCE_REL_RE = re.compile(r"(\d{1,4})([dw])")
_SORT_RE = re.compile(r"(created|updated)(?:[ \t]+(asc|desc))?")
_STATUS_RE = re.compile(r"[a-z0-9_-]{1,32}")
_LIMIT_RE = re.compile(r"\d{1,9}")

SortField = Literal["created", "updated"]


@dataclass(frozen=True)
class Mention:
    target: str  # normalized vault key as written, e.g. "30-cross-context/people/alex.md" or "Alex.md"
    name: str    # body-text fallback: the alias, else the target's file stem


@dataclass(frozen=True)
class Query:
    type: str | None = None
    context: str | None = None
    tag: str | None = None
    mentions: Mention | None = None
    status: str | None = None
    since: date | None = None
    sort: SortField = "created"
    descending: bool = True
    limit: int = DEFAULT_LIMIT


def _diag(line: int, col: int, message: str, code: str, severity: str = "error") -> Diagnostic:
    return Diagnostic(line=line, col=col, severity=severity, message=message, code=code)  # type: ignore[arg-type]


def _unquote(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1].strip()
    return v


def _has_placeholder(value: str) -> bool:
    """Same `{{ … }}` grammar as C1: a hand-typed block can't be filled in."""
    if "{{" not in value:
        return False
    try:
        return any(isinstance(seg, Placeholder) for seg in tokenize(value))
    except TemplateLimitError:
        return True


def _parse_mention(value: str) -> Mention | None:
    m = _WIKILINK_VALUE_RE.fullmatch(value)
    if m is None and ("[" in value or "]" in value):
        return None
    raw, alias = (m.group(1), m.group(2) or "") if m else (value.lstrip("@"), "")
    target = normalize_target(raw)
    if target is None:
        return None
    name = alias.strip().lstrip("@").strip() or PurePosixPath(target).stem
    return Mention(target=target, name=name)


def _parse_since(value: str, today: date) -> date | None:
    m = _SINCE_REL_RE.fullmatch(value)
    if m:
        days = int(m.group(1)) * (7 if m.group(2) == "w" else 1)
        return today - timedelta(days=days)
    if len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _apply(
    key: str, value: str, line: int, col: int, today: date,
    fields: dict[str, Any], diags: list[Diagnostic],
) -> None:
    low = value.lower()
    if key in ("type", "context"):
        fields[key] = low
    elif key == "tag":
        tag = low.lstrip("#").strip()
        if not tag:
            diags.append(_diag(line, col, "`tag` needs a tag name", "bad-value"))
            return
        fields["tag"] = tag
    elif key == "mentions":
        mention = _parse_mention(value)
        if mention is None:
            diags.append(_diag(line, col, "`mentions` takes a note link like "
                               "[[30-cross-context/people/alex]] or a name", "bad-value"))
            return
        fields["mentions"] = mention
    elif key == "status":
        if not _STATUS_RE.fullmatch(low):
            diags.append(_diag(line, col, "`status` takes one word, such as open or done", "bad-value"))
            return
        fields["status"] = low
    elif key == "since":
        since = _parse_since(low, today)
        if since is None:
            diags.append(_diag(line, col, "`since` takes 7d, 2w or a date like 2026-10-01", "bad-value"))
            return
        fields["since"] = since
    elif key == "sort":
        m = _SORT_RE.fullmatch(low)
        if m is None:
            diags.append(_diag(line, col, "`sort` takes created or updated, then asc or desc", "bad-value"))
            return
        fields["sort"] = m.group(1)
        fields["descending"] = m.group(2) != "asc"
    elif key == "limit":
        if not _LIMIT_RE.fullmatch(low) or int(low) < 1:
            diags.append(_diag(line, col, f"`limit` takes a whole number from 1 to {MAX_LIMIT}", "bad-value"))
            return
        n = int(low)
        if n > MAX_LIMIT:
            diags.append(_diag(line, col, f"limit capped at {MAX_LIMIT}", "limit-capped", "warning"))
            n = MAX_LIMIT
        fields["limit"] = n


def parse_query_block(text: str, *, today: date | None = None) -> tuple[Query | None, list[Diagnostic]]:
    """Parse the text inside a ```query``` fence. Any error → (None, diagnostics)."""
    if len(text) > MAX_QUERY_CHARS:
        return None, [_diag(1, 1, f"query is too long (max {MAX_QUERY_CHARS} characters)", "query-too-long")]
    lines = text.split("\n")
    if len(lines) > MAX_QUERY_LINES:
        return None, [_diag(MAX_QUERY_LINES + 1, 1, f"query has too many lines (max {MAX_QUERY_LINES})",
                            "query-too-long")]
    today = today or date.today()
    diags: list[Diagnostic] = []
    seen: set[str] = set()
    fields: dict[str, Any] = {}
    for n, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        m = _LINE_RE.fullmatch(line)
        if m is None:
            diags.append(_diag(n, indent + 1, "expected `key: value`", "syntax"))
            continue
        key = m.group(1).lower()
        col = indent + m.start(2) + 1
        if key not in QUERY_KEY_NAMES:
            diags.append(_diag(n, indent + 1, f"unknown key `{key}`; use one of: {', '.join(QUERY_KEY_NAMES)}",
                               "unknown-key"))
            continue
        if key in seen:
            diags.append(_diag(n, indent + 1, f"`{key}` is set twice", "duplicate-key"))
            continue
        seen.add(key)
        value = _unquote(m.group(2))
        if not value:
            diags.append(_diag(n, col, f"`{key}` needs a value", "empty-value"))
            continue
        if len(value) > MAX_VALUE_CHARS:
            diags.append(_diag(n, col, f"`{key}` value is too long (max {MAX_VALUE_CHARS} characters)",
                               "value-too-long"))
            continue
        if _has_placeholder(value):
            diags.append(_diag(n, col, "placeholders such as {{person.link}} are filled in only when a note "
                                       "is made from a template", "unresolved-placeholder"))
            continue
        _apply(key, value, n, col, today, fields, diags)
    if not seen and not diags:
        diags.append(_diag(1, 1, "empty query; add a filter such as `type: action_item`", "empty-query"))
    if any(d.severity == "error" for d in diags):
        return None, diags
    return Query(**fields), diags
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && python -m pytest tests/test_templates_query.py tests/test_templates_security.py -v`
Expected: PASS. The static guard scans `query.py`, and `re.compile` is allowed.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans3
git add ghostbrain/templates/query.py tests/test_templates_query.py .github/workflows/ci.yml
git commit -m "feat(templates): query block grammar with line-numbered diagnostics"
```

---

### Task 3: Bounded query runner over the link index

**Files:**
- Modify: `ghostbrain/templates/query.py`
- Modify: `tests/test_templates_query.py`

**Interfaces:**
- Consumes: `Query`, `Mention`, the constants and `parse_query_block` (Task 2); A2's `LinkIndex` (`entries()`, `get()`, `resolve()`, `root`), `NoteEntry`, `split_frontmatter` and `SNIPPET_MAX`; B1's `compute_etag(bytes) -> str`.
- Produces: `QueryRow`, `QueryRun` and `run_query` as in the Interfaces block. Row order is the sort key (with `mtime` fallback), then path ascending. `QueryRow.to_json()` keys are `path, title, context, status, created, snippet, etag`. `title` is frontmatter `title`, else the first `# ` H1, else the index title. `status` and `etag` come from the file's current bytes. Notes deleted since indexing are skipped. Files over `MAX_NOTE_BYTES` give index-only rows with `etag=None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates_query.py`:

```python
import os  # noqa: E402
from pathlib import Path  # noqa: E402

from ghostbrain.templates.query import QueryRow, QueryRun, run_query  # noqa: E402
from ghostbrain.vault_index.links import LinkIndex  # noqa: E402
from ghostbrain.vault_write.etag import compute_etag  # noqa: E402

AI = "20-contexts/work/calendar/artifacts/action_items"
PEOPLE = "30-cross-context/people"
OLD_MTIME = 1_700_000_000  # 2023-11-14


def _ts(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


def _note(root: Path, rel: str, text: str, mtime: int = OLD_MTIME) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


def _item(title: str, *, created: str = "2026-10-01T09:00:00+00:00", status: str | None = None,
          body: str = "") -> str:
    """An action item shaped like worker/extractor.py writes them."""
    lines = ["---", "type: artifact", "artifactType: action_item", f"created: '{created}'"]
    if status is not None:
        lines.append(f"status: {status}")
    lines += ["---", "", f"# {title}", "", body or f"{title}.", ""]
    return "\n".join(lines)


def _index(root: Path) -> LinkIndex:
    index = LinkIndex(root, refresh_interval=0)
    index.refresh()
    return index


def _run(root: Path, text: str, **kw) -> QueryRun:
    q, diags = parse_query_block(text, today=TODAY)
    assert q is not None, diags
    return run_query(q, _index(root), **kw)


def _paths(run: QueryRun) -> list[str]:
    return [r.path for r in run.rows]


def test_type_matches_artifact_type_or_type(tmp_path):
    _note(tmp_path, f"{AI}/a.md", _item("Send the budget"))
    _note(tmp_path, "20-contexts/work/meetings/m.md", "---\ntype: meeting\n---\n# Planning\n")
    _note(tmp_path, "20-contexts/work/d.md", "---\ntype: artifact\nartifactType: decision\n---\nx")
    assert _paths(_run(tmp_path, "type: action_item")) == [f"{AI}/a.md"]
    assert _paths(_run(tmp_path, "type: meeting")) == ["20-contexts/work/meetings/m.md"]
    assert len(_run(tmp_path, "type: artifact").rows) == 2


def test_open_includes_notes_without_status_and_excludes_done_or_closed(tmp_path):
    _note(tmp_path, f"{AI}/none.md", _item("No status", created="2026-10-04"))
    _note(tmp_path, f"{AI}/open.md", _item("Open", status="open", created="2026-10-03"))
    _note(tmp_path, f"{AI}/done.md", _item("Done", status="Done", created="2026-10-02"))
    _note(tmp_path, f"{AI}/closed.md", _item("Closed", status="closed", created="2026-10-01"))
    _note(tmp_path, f"{AI}/blocked.md", _item("Blocked", status="blocked", created="2026-09-30"))
    assert _paths(_run(tmp_path, "type: action_item\nstatus: open")) == [
        f"{AI}/none.md", f"{AI}/open.md", f"{AI}/blocked.md",
    ]
    assert _paths(_run(tmp_path, "type: action_item\nstatus: done")) == [f"{AI}/done.md"]


def test_context_and_tag(tmp_path):
    _note(tmp_path, "20-contexts/work/a.md", "---\ntags: [Roadmap]\n---\nx")
    _note(tmp_path, "20-contexts/personal/b.md", "plan #roadmap")
    _note(tmp_path, "20-contexts/personal/c.md", "nothing")
    assert sorted(_paths(_run(tmp_path, "tag: roadmap"))) == [
        "20-contexts/personal/b.md", "20-contexts/work/a.md",
    ]
    assert sorted(_paths(_run(tmp_path, "context: personal"))) == [
        "20-contexts/personal/b.md", "20-contexts/personal/c.md",
    ]


def _mention_vault(root: Path) -> None:
    _note(root, f"{PEOPLE}/alex.md", "---\ntitle: Alex\n---\nperson page")
    _note(root, f"{AI}/link.md", _item("Linked", created="2026-10-05",
                                       body="ask [[30-cross-context/people/alex|@Alex]]"))
    _note(root, f"{AI}/bare.md", _item("Bare link", created="2026-10-04", body="ask [[alex]]"))
    _note(root, f"{AI}/text.md", _item("Text only", created="2026-10-03", body="Alex to send the numbers."))
    _note(root, f"{AI}/longer.md", _item("Other name", created="2026-10-02", body="Alexander will check."))
    _note(root, f"{AI}/fence.md", _item("Fence only", created="2026-10-01",
                                        body="```query\nmentions: Alex\n```"))
    _note(root, f"{AI}/nobody.md", _item("Nobody", created="2026-09-30"))


def test_mentions_matches_links_then_body_text(tmp_path):
    _mention_vault(tmp_path)
    expected = [f"{AI}/link.md", f"{AI}/bare.md", f"{AI}/text.md"]
    assert _paths(_run(tmp_path, 'type: action_item\nmentions: "[[30-cross-context/people/alex]]"')) == expected
    assert _paths(_run(tmp_path, "type: action_item\nmentions: Alex")) == expected
    assert _paths(_run(tmp_path, 'type: action_item\nmentions: "[[Alex]]"')) == expected


def test_mentions_excludes_the_person_page_itself(tmp_path):
    _note(tmp_path, f"{PEOPLE}/alex.md", "---\ntitle: Alex\n---\nAlex works on [[alex]]")
    _note(tmp_path, "20-contexts/work/n.md", "met Alex today")
    assert _paths(_run(tmp_path, "mentions: Alex")) == ["20-contexts/work/n.md"]


def test_mentions_a_name_with_no_page_falls_back_to_text(tmp_path):
    _note(tmp_path, f"{AI}/a.md", _item("Call", created="2026-10-02", body="Robin to call the vendor"))
    _note(tmp_path, f"{AI}/b.md", _item("Ask", created="2026-10-01", body="ask [[Robin]] later"))
    _note(tmp_path, f"{AI}/c.md", _item("Robinson", created="2026-09-30", body="Robinson owns it"))
    assert _paths(_run(tmp_path, 'type: action_item\nmentions: "[[Robin]]"')) == [f"{AI}/a.md", f"{AI}/b.md"]


def test_mentions_value_is_literal_not_a_pattern(tmp_path):
    _note(tmp_path, "20-contexts/work/a.md", "abc and a.c")
    _note(tmp_path, "20-contexts/work/b.md", "abc only")
    assert _paths(_run(tmp_path, "mentions: a.c")) == ["20-contexts/work/a.md"]


def test_since_uses_created_then_file_time(tmp_path):
    _note(tmp_path, f"{AI}/new.md", _item("New", created="2026-10-08"))
    _note(tmp_path, f"{AI}/old.md", _item("Old", created="2026-09-01"))
    _note(tmp_path, "20-contexts/work/plain.md", "no frontmatter", mtime=_ts(2026, 10, 9))
    _note(tmp_path, "20-contexts/work/stale.md", "no frontmatter", mtime=_ts(2026, 1, 1))
    assert _paths(_run(tmp_path, "since: 7d")) == ["20-contexts/work/plain.md", f"{AI}/new.md"]


def test_sort_orders_and_mixed_date_formats(tmp_path):
    w = "20-contexts/work"
    _note(tmp_path, f"{w}/a.md", "---\ncreated: 2026-10-02\nupdated: 2026-10-09T08:00:00Z\n---\na")
    _note(tmp_path, f"{w}/b.md", "---\ncreated: 2026-10-03 10:00:00\n---\nb")
    _note(tmp_path, f"{w}/c.md", "---\ncreated: 'not a date'\n---\nc", mtime=_ts(2026, 9, 1))
    _note(tmp_path, f"{w}/d.md", "---\ncreated: '2026-10-01T23:00:00-05:00'\n---\nd")
    assert _paths(_run(tmp_path, "context: work")) == [f"{w}/b.md", f"{w}/d.md", f"{w}/a.md", f"{w}/c.md"]
    assert _paths(_run(tmp_path, "context: work\nsort: created asc")) == [
        f"{w}/c.md", f"{w}/a.md", f"{w}/d.md", f"{w}/b.md",
    ]
    assert _paths(_run(tmp_path, "context: work\nsort: updated")) == [
        f"{w}/a.md", f"{w}/c.md", f"{w}/b.md", f"{w}/d.md",
    ]


def test_limit_and_cap(tmp_path):
    for i in range(130):
        _note(tmp_path, f"20-contexts/work/n{i:03}.md", "x")
    assert len(_run(tmp_path, "context: work").rows) == DEFAULT_LIMIT
    run = _run(tmp_path, "context: work\nlimit: 500")
    assert len(run.rows) == MAX_LIMIT
    assert run.rows[0].path == "20-contexts/work/n000.md"  # equal times → path order


def test_rows_carry_title_snippet_fresh_status_and_etag(tmp_path):
    rel = f"{AI}/send-the-budget-1a2b3c4d.md"
    p = _note(tmp_path, rel, _item("Send Alex the budget", body="Alex to review the numbers by Friday."))
    _note(tmp_path, "20-contexts/work/titled.md",
          "---\ntitle: Planning\ncreated: '2026-09-01'\n---\n# Ignored heading\n\nfirst line")
    _note(tmp_path, "20-contexts/work/bare-stem.md", "```\ncode\n```\n\n## Sub\nprose here")
    rows = {r.path: r for r in _run(tmp_path, "context: work").rows}
    item = rows[rel]
    assert item == QueryRow(
        path=rel, title="Send Alex the budget", context="work", status=None,
        created="2026-10-01T09:00:00+00:00", snippet="Alex to review the numbers by Friday.",
        etag=compute_etag(p.read_bytes()),
    )
    assert item.to_json() == {
        "path": rel, "title": "Send Alex the budget", "context": "work", "status": None,
        "created": "2026-10-01T09:00:00+00:00", "snippet": "Alex to review the numbers by Friday.",
        "etag": compute_etag(p.read_bytes()),
    }
    assert (rows["20-contexts/work/titled.md"].title, rows["20-contexts/work/titled.md"].snippet) == (
        "Planning", "first line")
    assert (rows["20-contexts/work/bare-stem.md"].title, rows["20-contexts/work/bare-stem.md"].snippet) == (
        "bare-stem", "prose here")


def test_row_status_and_etag_are_read_from_the_file_not_the_index(tmp_path):
    p = _note(tmp_path, f"{AI}/a.md", _item("A"))
    q, _ = parse_query_block("type: action_item", today=TODAY)
    index = _index(tmp_path)
    p.write_text(_item("A", status="done"), encoding="utf-8")  # changed after indexing
    row = run_query(q, index).rows[0]
    assert row.status == "done"
    assert row.etag == compute_etag(p.read_bytes())


def test_note_deleted_after_indexing_is_skipped(tmp_path):
    gone = _note(tmp_path, f"{AI}/gone.md", _item("Gone", created="2026-10-02"))
    _note(tmp_path, f"{AI}/kept.md", _item("Kept", created="2026-10-01"))
    q, _ = parse_query_block("type: action_item", today=TODAY)
    index = _index(tmp_path)
    gone.unlink()
    assert _paths(run_query(q, index)) == [f"{AI}/kept.md"]


def test_text_scan_is_bounded_and_reports_partial(tmp_path):
    for i in range(10):
        _note(tmp_path, f"20-contexts/work/n{i}.md", "nothing here")
    run = _run(tmp_path, "mentions: Alex", max_text_reads=3)
    assert run.rows == () and run.partial is True
    ticks = iter([0.0] + [5.0] * 20)
    run = _run(tmp_path, "mentions: Alex", clock=lambda: next(ticks))
    assert run.rows == () and run.partial is True
    assert _run(tmp_path, "mentions: Alex").partial is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && python -m pytest tests/test_templates_query.py -v`
Expected: the Task 2 tests pass. The new tests fail with `ImportError: cannot import name 'QueryRow'`.

- [ ] **Step 3: Implement the runner**

In `ghostbrain/templates/query.py`, replace the import block with:

```python
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal

from ghostbrain.templates.functions import QUERY_KEYS
from ghostbrain.templates.lang import Placeholder, TemplateLimitError, tokenize
from ghostbrain.templates.parse import Diagnostic
from ghostbrain.vault_index.links import LinkIndex
from ghostbrain.vault_index.parse import SNIPPET_MAX, NoteEntry, normalize_target, split_frontmatter
from ghostbrain.vault_write.etag import compute_etag
```

Add these two patterns next to the other module-level regexes:

```python
_H1_RE = re.compile(r"#[ \t]+(.+?)[ \t#]*")
_QUERY_FENCE_RE = re.compile(r"^```query[^\n]*\n.*?^```[ \t]*$", re.MULTILINE | re.DOTALL)
```

Append at the end of the file:

```python
@dataclass(frozen=True)
class QueryRow:
    path: str
    title: str
    context: str
    status: str | None
    created: str | None
    snippet: str
    etag: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path, "title": self.title, "context": self.context, "status": self.status,
            "created": self.created, "snippet": self.snippet, "etag": self.etag,
        }


@dataclass(frozen=True)
class QueryRun:
    rows: tuple[QueryRow, ...]
    partial: bool


@dataclass(frozen=True)
class _Target:
    page: str | None                  # the mentioned note's own path, if it exists
    key: str                          # _link_key of the resolved target
    pattern: re.Pattern[str] | None   # whole-word names for the body-text fallback


def _opt(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _timestamp(value: str | None, mtime_ns: int) -> float:
    if value:
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (ValueError, OverflowError, OSError):
            pass
    return mtime_ns / 1_000_000_000


def _day(value: str | None, mtime_ns: int) -> date:
    try:
        return datetime.fromtimestamp(_timestamp(value, mtime_ns), tz=timezone.utc).date()
    except (ValueError, OverflowError, OSError):
        return date.min


def _matches_fields(q: Query, e: NoteEntry) -> bool:
    if q.type is not None and q.type not in {(e.artifact_type or "").lower(), (e.type or "").lower()}:
        return False
    if q.context is not None and e.context.lower() != q.context:
        return False
    if q.tag is not None and q.tag not in {t.lower().lstrip("#") for t in (*e.tags, *e.hashtags)}:
        return False
    if q.status is not None:
        status = (e.status or "").lower()
        if q.status == "open":
            if status in CLOSED_STATUSES:
                return False
        elif status != q.status:
            return False
    if q.since is not None and _day(e.created, e.mtime_ns) < q.since:
        return False
    return True


def _sort_key(e: NoteEntry, q: Query) -> tuple[float, str]:
    ts = _timestamp(e.created if q.sort == "created" else e.updated, e.mtime_ns)
    return (-ts if q.descending else ts, e.path)


def _link_key(target: str) -> str:
    """Bare names resolve case-insensitively (same rule as LinkIndex)."""
    return target if "/" in target else target.lower()


def _resolve_mention(mention: Mention, index: LinkIndex) -> _Target:
    resolved = index.resolve(mention.target)
    page = index.get(resolved)
    names = {mention.name.strip()}
    if page is not None:
        names.add(page.title.strip())
    usable = sorted((n for n in names if len(n) >= MIN_NAME_CHARS), key=len, reverse=True)
    pattern = (
        re.compile(r"(?<!\w)(?:" + "|".join(re.escape(n) for n in usable) + r")(?!\w)", re.IGNORECASE)
        if usable else None
    )
    return _Target(page=resolved if page is not None else None, key=_link_key(resolved), pattern=pattern)


def _links_to(e: NoteEntry, target: _Target, index: LinkIndex) -> bool:
    return any(_link_key(index.resolve(link.target)) == target.key for link in e.links)


def _read_bytes(root: Path, rel: str) -> bytes | None:
    """Bytes of an indexed note; None if gone, unreadable or over MAX_NOTE_BYTES."""
    try:
        path = root / rel
        if path.stat().st_size > MAX_NOTE_BYTES:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _body_text(root: Path, rel: str) -> str | None:
    data = _read_bytes(root, rel)
    if data is None:
        return None
    _, body = split_frontmatter(data.decode("utf-8", errors="replace"))
    return _QUERY_FENCE_RE.sub("", body)


def _first_heading(body: str) -> str | None:
    for line in body.splitlines()[:50]:
        m = _H1_RE.fullmatch(line.strip())
        if m:
            return m.group(1).strip()
    return None


def _first_line(body: str) -> str:
    in_fence = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s or s.startswith("#"):
            continue
        return s[:SNIPPET_MAX]
    return ""


def _row(root: Path, e: NoteEntry) -> QueryRow | None:
    if not (root / e.path).is_file():
        return None  # deleted since it was indexed
    data = _read_bytes(root, e.path)
    if data is None:  # too large (or vanished mid-read): index data only, no etag
        return QueryRow(e.path, e.title, e.context, e.status, e.created, "", None)
    meta, body = split_frontmatter(data.decode("utf-8", errors="replace"))
    title = _opt(meta.get("title")) or _first_heading(body) or e.title
    return QueryRow(
        path=e.path, title=title, context=e.context, status=_opt(meta.get("status")),
        created=e.created, snippet=_first_line(body), etag=compute_etag(data),
    )


def run_query(
    query: Query,
    index: LinkIndex,
    *,
    clock: Callable[[], float] = time.monotonic,
    deadline_s: float = DEADLINE_S,
    max_text_reads: int = MAX_TEXT_READS,
) -> QueryRun:
    """Filter → sort → (mentions) → first ``query.limit`` rows. Bounded:
    body reads for the name fallback stop at ``max_text_reads`` or
    ``deadline_s`` and the run reports ``partial``."""
    started = clock()
    candidates = [e for e in index.entries() if _matches_fields(query, e)]
    candidates.sort(key=lambda e: _sort_key(e, query))
    target = _resolve_mention(query.mentions, index) if query.mentions is not None else None
    picked: list[NoteEntry] = []
    reads = 0
    partial = False
    for entry in candidates:
        if len(picked) >= query.limit:
            break
        if target is not None:
            if entry.path == target.page:
                continue
            if not _links_to(entry, target, index):
                if target.pattern is None:
                    continue
                if reads >= max_text_reads or clock() - started > deadline_s:
                    partial = True
                    break
                reads += 1
                body = _body_text(index.root, entry.path)
                if body is None or not target.pattern.search(body):
                    continue
        picked.append(entry)
    rows = tuple(row for row in (_row(index.root, e) for e in picked) if row is not None)
    return QueryRun(rows=rows, partial=partial)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && python -m pytest tests/test_templates_query.py tests/test_templates_security.py tests/test_vault_index_links.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans3
git add ghostbrain/templates/query.py tests/test_templates_query.py
git commit -m "feat(templates): bounded query runner over the link index"
```

---

### Task 4: `POST /v1/vault/query` and `PATCH /v1/vault/status`

**Files:**
- Create: `ghostbrain/api/models/vault_query.py`
- Create: `ghostbrain/api/repo/vault_query.py`
- Modify: `ghostbrain/api/routes/vault.py`
- Create: `ghostbrain/api/tests/test_vault_query_routes.py`

**Interfaces:**
- Consumes: `parse_query_block`, `run_query`, `MAX_QUERY_CHARS` (Tasks 2–3); `get_link_index()`, `LinkIndex.ensure_fresh(wait)` (A2); `vault_write.write`, `USER`, `InvalidPath` (B1); `if_match` from `ghostbrain.api.vault_http`. B1's error handlers are already installed by `create_app`.
- Produces: the two routes and response shapes from the Interfaces table. `query_vault` returns `{"results", "diagnostics", "indexing", "partial"}`. `set_note_status` returns `{"path", "status", "etag"}`. Task 5's TS types mirror these exactly.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_vault_query_routes.py`:

```python
"""POST /v1/vault/query and PATCH /v1/vault/status (smart templates C2)."""
from __future__ import annotations

from pathlib import Path

import pytest

import ghostbrain.api.repo.vault_query as repo
from ghostbrain.vault_index.links import LinkIndex, get_link_index
from ghostbrain.vault_write import compute_etag

AI = "20-contexts/work/calendar/artifacts/action_items"
REL = f"{AI}/send-budget-1a2b3c4d.md"
ITEM = (
    "---\n"
    "id: 1a2b3c4d\n"
    "context: work\n"
    "type: artifact\n"
    "artifactType: action_item\n"
    "source: calendar\n"
    "created: '2026-10-01T09:00:00+00:00'\n"
    "parent: '[[20-contexts/work/calendar/planning]]'\n"
    "tags: []  # from the extractor\n"
    "---\n"
    "\n"
    "# Send Alex the budget\n"
    "\n"
    "Alex to review the numbers.\n"
)


def _write(vault: Path, rel: str, text: str) -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))
    return p


def _query(client, auth_headers, source: str, *, refresh: bool = True):
    if refresh:
        get_link_index().refresh()
    return client.post("/v1/vault/query", json={"query": source}, headers=auth_headers)


def _tick(client, auth_headers, path: str, status: str, etag: str | None = None):
    headers = dict(auth_headers)
    if etag:
        headers["If-Match"] = f'"{etag}"'
    return client.patch("/v1/vault/status", json={"path": path, "status": status}, headers=headers)


def test_query_returns_rows(client, auth_headers, tmp_vault):
    p = _write(tmp_vault, REL, ITEM)
    r = _query(client, auth_headers, 'type: action_item\nmentions: "[[Alex]]"\nstatus: open\n')
    assert r.status_code == 200, r.text
    assert r.json() == {
        "results": [{
            "path": REL, "title": "Send Alex the budget", "context": "work", "status": None,
            "created": "2026-10-01T09:00:00+00:00", "snippet": "Alex to review the numbers.",
            "etag": compute_etag(p.read_bytes()),
        }],
        "diagnostics": [],
        "indexing": False,
        "partial": False,
    }


def test_bad_query_returns_diagnostics_with_200(client, auth_headers, tmp_vault):
    r = _query(client, auth_headers, "type: action_item\nowner: alex")
    assert r.status_code == 200
    body = r.json()
    assert body["results"] == [] and body["indexing"] is False and body["partial"] is False
    assert body["diagnostics"] == [{
        "line": 2, "col": 1, "severity": "error", "code": "unknown-key",
        "message": "unknown key `owner`; use one of: type, context, tag, mentions, status, since, sort, limit",
    }]


def test_warning_is_returned_alongside_results(client, auth_headers, tmp_vault):
    _write(tmp_vault, REL, ITEM)
    body = _query(client, auth_headers, "type: action_item\nlimit: 500").json()
    assert len(body["results"]) == 1
    assert [d["code"] for d in body["diagnostics"]] == ["limit-capped"]


def test_cold_index_reports_indexing(client, auth_headers, tmp_vault, monkeypatch):
    monkeypatch.setattr(LinkIndex, "ensure_fresh", lambda self, wait=0.25: False)
    r = _query(client, auth_headers, "type: action_item", refresh=False)
    assert r.json() == {"results": [], "diagnostics": [], "indexing": True, "partial": False}


def test_oversized_query_body_is_rejected(client, auth_headers, tmp_vault):
    r = _query(client, auth_headers, "x" * 8_001, refresh=False)
    assert r.status_code == 422


def test_tick_adds_one_status_line_and_preserves_every_other_byte(client, auth_headers, tmp_vault):
    p = _write(tmp_vault, REL, ITEM)
    r = _tick(client, auth_headers, REL, "done", compute_etag(p.read_bytes()))
    assert r.status_code == 200, r.text
    assert p.read_bytes().decode("utf-8") == ITEM.replace(
        "tags: []  # from the extractor\n", "tags: []  # from the extractor\nstatus: done\n"
    )
    assert r.json() == {"path": REL, "status": "done", "etag": compute_etag(p.read_bytes())}


def test_untick_rewrites_only_the_status_line(client, auth_headers, tmp_vault):
    done = ITEM.replace("tags: []", "status: done  # ticked\ntags: []")
    p = _write(tmp_vault, REL, done)
    r = _tick(client, auth_headers, REL, "open", compute_etag(p.read_bytes()))
    assert r.status_code == 200, r.text
    assert p.read_bytes().decode("utf-8") == done.replace("status: done  # ticked", "status: open  # ticked")


def test_tick_with_a_stale_etag_is_409_and_writes_nothing(client, auth_headers, tmp_vault):
    p = _write(tmp_vault, REL, ITEM)
    before = p.read_bytes()
    r = _tick(client, auth_headers, REL, "done", "0123456789abcdef")
    assert r.status_code == 409
    assert r.json()["currentEtag"] == compute_etag(before)
    assert p.read_bytes() == before


def test_tick_note_without_frontmatter_gets_one(client, auth_headers, tmp_vault):
    p = _write(tmp_vault, "20-contexts/work/todo.md", "call the vendor\n")
    assert _tick(client, auth_headers, "20-contexts/work/todo.md", "done").status_code == 200
    assert p.read_text(encoding="utf-8") == "---\nstatus: done\n---\n\ncall the vendor\n"


def test_tick_then_query_drops_the_done_item(client, auth_headers, tmp_vault):
    _write(tmp_vault, REL, ITEM)
    rows = _query(client, auth_headers, "type: action_item\nstatus: open").json()["results"]
    assert [r["path"] for r in rows] == [REL]
    assert _tick(client, auth_headers, REL, "done", rows[0]["etag"]).status_code == 200
    # No explicit refresh: the write path re-indexes the note (A2 note_written).
    again = _query(client, auth_headers, "type: action_item\nstatus: open", refresh=False).json()
    assert again["results"] == []


def test_tick_writes_as_user_with_the_if_match_etag(client, auth_headers, tmp_vault, monkeypatch):
    p = _write(tmp_vault, REL, ITEM)
    seen = {}
    real = repo.write

    def spy(path, **kw):
        seen.update(kw, path=path)
        return real(path, **kw)

    monkeypatch.setattr(repo, "write", spy)
    etag = compute_etag(p.read_bytes())
    assert _tick(client, auth_headers, REL, "done", etag).status_code == 200
    assert seen["path"] == REL and seen["actor"] == "user"
    assert seen["fields"] == {"status": "done"} and seen["base_etag"] == etag


@pytest.mark.parametrize("path, code", [
    ("20-contexts/work/missing.md", 404),
    ("../outside.md", 400),
    ("/etc/passwd.md", 400),
    ("20-contexts/work/page.html", 400),
])
def test_tick_rejects_bad_targets(client, auth_headers, tmp_vault, path, code):
    assert _tick(client, auth_headers, path, "done").status_code == code


def test_tick_rejects_other_status_values(client, auth_headers, tmp_vault):
    _write(tmp_vault, REL, ITEM)
    assert _tick(client, auth_headers, REL, "blocked").status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && python -m pytest ghostbrain/api/tests/test_vault_query_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.api.repo.vault_query'`.

- [ ] **Step 3: Implement the models, repo and routes**

`ghostbrain/api/models/vault_query.py`:

```python
"""Payloads for POST /v1/vault/query and PATCH /v1/vault/status (C2)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ghostbrain.templates.query import MAX_QUERY_CHARS

# Transport cap. The parser reports anything over MAX_QUERY_CHARS as an
# inline diagnostic; only absurd bodies are refused outright.
MAX_QUERY_BODY_CHARS = MAX_QUERY_CHARS * 4


class VaultQueryRequest(BaseModel):
    query: str = Field(..., max_length=MAX_QUERY_BODY_CHARS)


class VaultQueryRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    path: str
    title: str
    context: str
    status: str | None
    created: str | None
    snippet: str
    etag: str | None


class VaultQueryDiagnostic(BaseModel):
    line: int
    col: int
    severity: Literal["error", "warning", "info"]
    message: str
    code: str


class VaultQueryResponse(BaseModel):
    results: list[VaultQueryRow]
    diagnostics: list[VaultQueryDiagnostic]
    indexing: bool
    partial: bool


class NoteStatusRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    status: Literal["done", "open"]


class NoteStatusResponse(BaseModel):
    path: str
    status: Literal["done", "open"]
    etag: str | None
```

`ghostbrain/api/repo/vault_query.py`:

```python
"""Live query blocks (smart templates C2): run a ```query``` block against
the link index, and tick a result done through the single write path."""
from __future__ import annotations

from datetime import date

from ghostbrain.templates.query import parse_query_block, run_query
from ghostbrain.vault_index.links import LinkIndex, get_link_index
from ghostbrain.vault_write import USER, InvalidPath, write

INDEX_WAIT_S = 0.25


def query_vault(source: str, *, index: LinkIndex | None = None, today: date | None = None) -> dict:
    query, diagnostics = parse_query_block(source, today=today)
    diags = [d.to_json() for d in diagnostics]
    if query is None:
        return {"results": [], "diagnostics": diags, "indexing": False, "partial": False}
    index = index or get_link_index()
    if not index.ensure_fresh(wait=INDEX_WAIT_S):
        return {"results": [], "diagnostics": diags, "indexing": True, "partial": False}
    run = run_query(query, index)
    return {
        "results": [row.to_json() for row in run.rows],
        "diagnostics": diags,
        "indexing": False,
        "partial": run.partial,
    }


def set_note_status(path: str, status: str, *, base_etag: str | None) -> dict:
    """One-line frontmatter edit as the user. B1 raises InvalidPath (400),
    FileMissing (404), WriteConflict (409) or MalformedNote (422)."""
    rel = path.strip()
    if not rel.lower().endswith(".md"):
        raise InvalidPath("only markdown notes (.md) have a status")
    result = write(
        rel,
        fields={"status": status},
        actor=USER,
        reason=f"query block: mark {status}",
        base_etag=base_etag,
    )
    return {"path": result.path, "status": status, "etag": result.etag}
```

In `ghostbrain/api/routes/vault.py`, change the docstring's first line to `"""GET /v1/vault/stats, /graph, /contexts, /suggest, /backlinks; POST /query; PATCH /status."""`. Change `from fastapi import APIRouter, HTTPException, Query` to `from fastapi import APIRouter, Depends, HTTPException, Query`, and add after the existing model imports:

```python
from ghostbrain.api.models.vault_query import (
    NoteStatusRequest,
    NoteStatusResponse,
    VaultQueryRequest,
    VaultQueryResponse,
)
from ghostbrain.api.repo.vault_query import query_vault, set_note_status
from ghostbrain.api.vault_http import if_match
```

Append at the end of the file:

```python
@router.post("/query", response_model=VaultQueryResponse)
def vault_query(body: VaultQueryRequest) -> dict:
    """Run a ```query``` block. Always 200: parse problems come back as
    `diagnostics` so the editor can show them inline; `indexing: true` = cold
    index, retry soon."""
    return query_vault(body.query)


@router.patch("/status", response_model=NoteStatusResponse)
def vault_set_status(body: NoteStatusRequest, base_etag: str | None = Depends(if_match)) -> dict:
    """Tick-to-done from a query block: sets frontmatter `status` via the
    write path as the user. `If-Match` → 409 when the note changed since."""
    return set_note_status(body.path, body.status, base_etag=base_etag)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && python -m pytest ghostbrain/api/tests/test_vault_query_routes.py ghostbrain/api/tests/test_vault_suggest.py ghostbrain/api/tests/test_vault_backlinks.py tests/test_templates_query.py -v`
Expected: PASS.

Run the CI list as CI does: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && python -m pytest ghostbrain/api/tests/ tests/test_templates_query.py tests/test_templates_functions.py tests/test_templates_security.py tests/test_no_hardcoded_contexts.py tests/test_vault_index_parse.py tests/test_vault_index_links.py tests/test_vault_write_text.py tests/test_vault_write_writer.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans3
git add ghostbrain/api/models/vault_query.py ghostbrain/api/repo/vault_query.py ghostbrain/api/routes/vault.py ghostbrain/api/tests/test_vault_query_routes.py
git commit -m "feat(api): live vault query and tick-to-done status routes"
```

---

### Task 5: Desktop query types, sidecar calls and Freeze markdown

**Files:**
- Modify: `desktop/src/shared/api-types.ts`
- Create: `desktop/src/renderer/lib/editor/query-api.ts`
- Create: `desktop/src/renderer/lib/editor/query-format.ts`
- Create: `desktop/src/renderer/__tests__/query-format.test.ts`

**Interfaces:**
- Consumes: `post`, `patch` and `ApiError` (`lib/api/client.ts`), where `patch` sends `If-Match` only when `ifMatch` is truthy; `noteTarget(path)` (`lib/editor/link-suggest.ts`); C1's `TemplateDiagnostic`, `TemplateFunctionSpec` and `TemplateFunctionsResponse` (`shared/api-types.ts`).
- Produces: `VaultQueryRow`, `VaultQueryResponse`, `NoteStatusValue`, `NoteStatusResponse`, `runVaultQuery(source)`, `setNoteStatus(path, status, etag)`, `isClosedStatus(status)`, `frozenItem(row)` and `freezeMarkdown(rows)`, exactly as in the Interfaces block. Tasks 6–7 use all of them.

- [ ] **Step 1: Write the failing tests**

`desktop/src/renderer/__tests__/query-format.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { VaultQueryRow } from '../../shared/api-types';
import { freezeMarkdown, frozenItem, isClosedStatus } from '../lib/editor/query-format';
import { runVaultQuery, setNoteStatus } from '../lib/editor/query-api';

function row(over: Partial<VaultQueryRow> = {}): VaultQueryRow {
  return {
    path: '20-contexts/work/a.md',
    title: 'Send Alex the budget',
    context: 'work',
    status: null,
    created: '2026-10-08T09:00:00+00:00',
    snippet: '',
    etag: 'aaaaaaaaaaaaaaaa',
    ...over,
  };
}

describe('isClosedStatus', () => {
  it('treats done and closed (any case) as closed, everything else as open', () => {
    expect(isClosedStatus('done')).toBe(true);
    expect(isClosedStatus('Closed')).toBe(true);
    expect(isClosedStatus('open')).toBe(false);
    expect(isClosedStatus('blocked')).toBe(false);
    expect(isClosedStatus(null)).toBe(false);
  });
});

describe('freezeMarkdown', () => {
  it('writes one task item per row with a titled wikilink', () => {
    expect(freezeMarkdown([row(), row({ path: '20-contexts/work/b.md', title: 'Book the room', status: 'done' })])).toBe(
      '- [ ] [[20-contexts/work/a|Send Alex the budget]]\n- [x] [[20-contexts/work/b|Book the room]]',
    );
  });

  it('turns brackets and pipes in titles into spaces', () => {
    expect(frozenItem(row({ title: 'Plan [draft] | v2' }))).toBe('- [ ] [[20-contexts/work/a|Plan draft v2]]');
  });

  it('uses a bare link when the title is empty or the target itself', () => {
    expect(frozenItem(row({ title: '[]' }))).toBe('- [ ] [[20-contexts/work/a]]');
    expect(frozenItem(row({ title: '20-contexts/work/a' }))).toBe('- [ ] [[20-contexts/work/a]]');
  });

  it('says no matching notes for zero rows', () => {
    expect(freezeMarkdown([])).toBe('no matching notes');
  });
});

describe('query-api', () => {
  const apiRequest = vi.fn();
  beforeEach(() => {
    apiRequest.mockReset();
    window.gb = { ...window.gb, api: { request: apiRequest } } as typeof window.gb;
  });

  it('posts the block text to /v1/vault/query', async () => {
    const data = { results: [], diagnostics: [], indexing: false, partial: false };
    apiRequest.mockResolvedValue({ ok: true, data });
    await expect(runVaultQuery('type: action_item')).resolves.toEqual(data);
    expect(apiRequest).toHaveBeenCalledWith('POST', '/v1/vault/query', { query: 'type: action_item' });
  });

  it('patches the status with If-Match when there is an etag', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { path: 'a.md', status: 'done', etag: 'bbbbbbbbbbbbbbbb' } });
    await setNoteStatus('a.md', 'done', 'aaaaaaaaaaaaaaaa');
    expect(apiRequest).toHaveBeenCalledWith(
      'PATCH',
      '/v1/vault/status',
      { path: 'a.md', status: 'done' },
      { ifMatch: 'aaaaaaaaaaaaaaaa' },
    );
  });

  it('sends no If-Match without an etag', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { path: 'a.md', status: 'open', etag: null } });
    await setNoteStatus('a.md', 'open', null);
    expect(apiRequest.mock.calls[0]).toHaveLength(3);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3/desktop && npx vitest run src/renderer/__tests__/query-format.test.ts`
Expected: FAIL with "Failed to resolve import ../lib/editor/query-format".

- [ ] **Step 3: Implement**

In `desktop/src/shared/api-types.ts`, change C1's `TemplateFunctionSpec.kind` line to:

```ts
  kind: 'variable' | 'field' | 'filter' | 'prompt_type' | 'query_key';
```

Add `queryKeys: TemplateFunctionSpec[];` as the last member of `TemplateFunctionsResponse`, then append at the end of the file:

```ts
// ── Live queries (C2) ─────────────────────────────────────────────────────

export interface VaultQueryRow {
  path: string;
  title: string;
  context: string;
  status: string | null;
  created: string | null;
  snippet: string;
  /** sha256(file bytes)[:16] at query time — sent as If-Match when ticking. */
  etag: string | null;
}

export interface VaultQueryResponse {
  results: VaultQueryRow[];
  diagnostics: TemplateDiagnostic[];
  /** Cold link index: no results yet, retry shortly. */
  indexing: boolean;
  /** A scan bound was hit: the list may be incomplete. */
  partial: boolean;
}

export type NoteStatusValue = 'done' | 'open';

export interface NoteStatusResponse {
  path: string;
  status: NoteStatusValue;
  etag: string | null;
}
```

`desktop/src/renderer/lib/editor/query-api.ts`:

```ts
import type { NoteStatusResponse, NoteStatusValue, VaultQueryResponse } from '../../../shared/api-types';
import { patch, post } from '../api/client';

/** Sidecar calls for the ```query``` NodeView. Plain functions (no React):
 * the node view is vanilla ProseMirror. */
export function runVaultQuery(source: string): Promise<VaultQueryResponse> {
  return post<VaultQueryResponse>('/v1/vault/query', { query: source });
}

export function setNoteStatus(
  path: string,
  status: NoteStatusValue,
  etag: string | null,
): Promise<NoteStatusResponse> {
  return patch<NoteStatusResponse>('/v1/vault/status', { path, status }, { ifMatch: etag });
}
```

`desktop/src/renderer/lib/editor/query-format.ts`:

```ts
import type { VaultQueryRow } from '../../../shared/api-types';
import { noteTarget } from './link-suggest';

const CLOSED = new Set(['done', 'closed']);

/** Same rule as the sidecar's `status: open`: done/closed are closed, anything else (or none) is open. */
export function isClosedStatus(status: string | null): boolean {
  return CLOSED.has((status ?? '').toLowerCase());
}

function linkLabel(title: string): string {
  return title.replace(/[[\]|]/g, ' ').replace(/\s+/g, ' ').trim();
}

/** One frozen row: a GFM task item holding a titled wikilink. */
export function frozenItem(row: VaultQueryRow): string {
  const target = noteTarget(row.path);
  const label = linkLabel(row.title);
  const link = label && label !== target ? `[[${target}|${label}]]` : `[[${target}]]`;
  return `- [${isClosedStatus(row.status) ? 'x' : ' '}] ${link}`;
}

/** Markdown that replaces a ```query``` block on Freeze. */
export function freezeMarkdown(rows: VaultQueryRow[]): string {
  if (rows.length === 0) return 'no matching notes';
  return rows.map(frozenItem).join('\n');
}
```

- [ ] **Step 4: Run tests, typecheck and lint**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3/desktop && npx vitest run src/renderer/__tests__/query-format.test.ts && npm run typecheck && npx eslint --max-warnings 0 src/renderer/lib/editor/query-api.ts src/renderer/lib/editor/query-format.ts src/renderer/__tests__/query-format.test.ts src/shared/api-types.ts`
Expected: PASS, with no type or lint errors.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans3/desktop
git add src/shared/api-types.ts src/renderer/lib/editor/query-api.ts src/renderer/lib/editor/query-format.ts src/renderer/__tests__/query-format.test.ts
git commit -m "feat(desktop): live query types, sidecar calls and freeze markdown"
```

---

### Task 6: Query block NodeView (live results, states, refresh cadence)

**Files:**
- Create: `desktop/src/renderer/lib/editor/query-view.ts`
- Modify: `desktop/src/renderer/lib/editor/code-block.ts` (A1)
- Modify: `desktop/src/renderer/lib/editor/events.ts` (A1)
- Create: `desktop/src/renderer/__tests__/query-view.test.ts`
- Modify: `desktop/src/renderer/__tests__/markdown-roundtrip.test.ts`
- Modify: `desktop/src/renderer/styles.css` (append)

**Interfaces:**
- Consumes: `runVaultQuery`, `VaultQueryResponse` and `VaultQueryRow` (Task 5), `isClosedStatus` (Task 5); `emitGb` and `GbEditorEvents` (A1 `events.ts`); `GbCodeBlock.addNodeView` (A1 `code-block.ts`); `makeEditor` and `markdownOf` (A1 test helpers).
- Produces: `createQueryView(initial, editor, getPos): NodeView`, the four `QUERY_*` constants, and the DOM contract from the Interfaces section. The `gb:query:open` `{ path }` event is emitted when a result title is clicked. In this task, checkboxes render **disabled** and the "freeze" menu item is always disabled. Task 7 enables both by replacing `canFreeze` and `rowEl` and adding `toggle` and `freeze`.

- [ ] **Step 1: Write the failing tests**

`desktop/src/renderer/__tests__/query-view.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import type { VaultQueryResponse, VaultQueryRow } from '../../shared/api-types';

const { runVaultQuery, setNoteStatus } = vi.hoisted(() => ({ runVaultQuery: vi.fn(), setNoteStatus: vi.fn() }));
vi.mock('../lib/editor/query-api', () => ({ runVaultQuery, setNoteStatus }));

import { onGb } from '../lib/editor/events';
import { QUERY_EDIT_DEBOUNCE_MS, QUERY_INDEX_RETRY_MS, QUERY_POLL_MS } from '../lib/editor/query-view';
import { makeEditor, markdownOf } from './helpers/editor';

const SRC = '```query\ntype: action_item\nstatus: open\n```';
const ROWS: VaultQueryRow[] = [
  {
    path: '20-contexts/work/a.md',
    title: 'Send Alex the budget',
    context: 'work',
    status: null,
    created: '2026-10-08T09:00:00+00:00',
    snippet: 'Alex to review the numbers',
    etag: 'aaaaaaaaaaaaaaaa',
  },
  {
    path: '20-contexts/work/b.md',
    title: 'Book the room',
    context: 'work',
    status: 'done',
    created: '2026-10-07',
    snippet: '',
    etag: 'bbbbbbbbbbbbbbbb',
  },
];

function ok(results: VaultQueryRow[] = ROWS, extra: Partial<VaultQueryResponse> = {}): VaultQueryResponse {
  return { results, diagnostics: [], indexing: false, partial: false, ...extra };
}

async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function q<T extends Element = HTMLElement>(editor: Editor, selector: string): T | null {
  return editor.view.dom.querySelector<T>(selector);
}

function menuItem(editor: Editor, label: string): HTMLButtonElement {
  const items = Array.from(editor.view.dom.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
  const found = items.find((b) => b.textContent === label);
  if (!found) throw new Error(`menu item not found: ${label}`);
  return found;
}

describe('query block view', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    runVaultQuery.mockReset();
    setNoteStatus.mockReset();
    runVaultQuery.mockResolvedValue(ok());
  });
  afterEach(() => vi.useRealTimers());

  it('renders live rows and keeps the markdown unchanged', async () => {
    const editor = makeEditor(SRC);
    await flush();
    expect(runVaultQuery).toHaveBeenCalledWith('type: action_item\nstatus: open');
    const rows = editor.view.dom.querySelectorAll('li.gb-query-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]!.querySelector('.gb-query-link')!.textContent).toBe('Send Alex the budget');
    expect(rows[0]!.querySelector('.gb-query-meta')!.textContent).toBe('work · 2026-10-08');
    expect(rows[0]!.querySelector('.gb-query-snippet')!.textContent).toBe('Alex to review the numbers');
    expect(rows[1]!.querySelector('.gb-query-snippet')).toBeNull();
    const boxes = editor.view.dom.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    expect([boxes[0]!.checked, boxes[1]!.checked]).toEqual([false, true]);
    expect(boxes[0]!.getAttribute('aria-label')).toBe('mark Send Alex the budget done');
    expect(boxes[1]!.getAttribute('aria-label')).toBe('mark Book the room open');
    expect(q(editor, '.gb-query')!.dataset.editing).toBe('false');
    expect(markdownOf(editor)).toBe(SRC);
    editor.destroy();
  });

  it('clicking a title emits gb:query:open with the path', async () => {
    const editor = makeEditor(SRC);
    await flush();
    const spy = vi.fn();
    onGb(editor, 'gb:query:open', spy);
    fireEvent.click(q(editor, '.gb-query-link')!);
    expect(spy).toHaveBeenCalledWith({ path: '20-contexts/work/a.md' });
    editor.destroy();
  });

  it('shows no matching notes for an empty result', async () => {
    runVaultQuery.mockResolvedValue(ok([]));
    const editor = makeEditor(SRC);
    await flush();
    expect(q(editor, '.gb-query-status')!.textContent).toBe('no matching notes');
    editor.destroy();
  });

  it('shows query errors inline with the source, and no list', async () => {
    runVaultQuery.mockResolvedValue(
      ok([], {
        diagnostics: [{ line: 2, col: 1, severity: 'error', message: 'unknown key `owner`', code: 'unknown-key' }],
      }),
    );
    const editor = makeEditor('```query\ntype: action_item\nowner: alex\n```');
    await flush();
    const box = q(editor, '.gb-query-error')!;
    expect(box.getAttribute('role')).toBe('alert');
    expect(box.textContent).toContain('line 2: unknown key `owner`');
    expect(box.querySelector('pre')!.textContent).toBe('type: action_item\nowner: alex');
    expect(q(editor, '.gb-query-list')).toBeNull();
    editor.destroy();
  });

  it('shows warnings above the rows and the partial notice below', async () => {
    runVaultQuery.mockResolvedValue(
      ok(ROWS, {
        partial: true,
        diagnostics: [{ line: 3, col: 8, severity: 'warning', message: 'limit capped at 100', code: 'limit-capped' }],
      }),
    );
    const editor = makeEditor(SRC);
    await flush();
    expect(q(editor, '.gb-query-warning')!.textContent).toBe('limit capped at 100');
    expect(editor.view.dom.querySelectorAll('li.gb-query-row')).toHaveLength(2);
    expect(editor.view.dom.textContent).toContain('showing the first matches only — narrow the query');
    editor.destroy();
  });

  it('shows the retry chip when the sidecar fails, and retries on click', async () => {
    runVaultQuery.mockRejectedValueOnce(new Error('sidecar down'));
    const editor = makeEditor(SRC);
    await flush();
    const chip = q<HTMLButtonElement>(editor, '.gb-query-chip')!;
    expect(chip.textContent).toBe('results unavailable — retry');
    fireEvent.click(chip);
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(2);
    expect(editor.view.dom.querySelectorAll('li.gb-query-row')).toHaveLength(2);
    editor.destroy();
  });

  it('treats a malformed response as unavailable', async () => {
    runVaultQuery.mockResolvedValue(null);
    const editor = makeEditor(SRC);
    await flush();
    expect(q(editor, '.gb-query-chip')).not.toBeNull();
    editor.destroy();
  });

  it('retries automatically while the index is building', async () => {
    runVaultQuery.mockResolvedValueOnce(ok([], { indexing: true }));
    const editor = makeEditor(SRC);
    await flush();
    expect(q(editor, '.gb-query-chip')).not.toBeNull();
    await flush(QUERY_INDEX_RETRY_MS);
    expect(runVaultQuery).toHaveBeenCalledTimes(2);
    expect(editor.view.dom.querySelectorAll('li.gb-query-row')).toHaveLength(2);
    editor.destroy();
  });

  it('refreshes every 60 s, on window focus and on the refresh button; stops after destroy', async () => {
    const editor = makeEditor(SRC);
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(1);
    await flush(QUERY_POLL_MS);
    expect(runVaultQuery).toHaveBeenCalledTimes(2);
    window.dispatchEvent(new Event('focus'));
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(3);
    fireEvent.click(q(editor, '[aria-label="refresh query"]')!);
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(4);
    editor.destroy();
    await flush(QUERY_POLL_MS * 2);
    window.dispatchEvent(new Event('focus'));
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(4);
  });

  it('edit query toggles the source and re-runs after typing stops', async () => {
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(q(editor, '[aria-label="query options"]')!);
    expect(q(editor, '[role="menu"]')!.hidden).toBe(false);
    fireEvent.click(menuItem(editor, 'edit query'));
    expect(q(editor, '.gb-query')!.dataset.editing).toBe('true');
    expect(q(editor, '[role="menu"]')!.hidden).toBe(true);
    act(() => {
      const end = editor.state.doc.content.size - 1; // end of the code text
      // insertText, not insertContent: tiptap-markdown would parse a string as markdown.
      editor.view.dispatch(editor.state.tr.insertText('\nlimit: 5', end));
    });
    await flush(QUERY_EDIT_DEBOUNCE_MS - 1);
    expect(runVaultQuery).toHaveBeenCalledTimes(1);
    await flush(1);
    expect(runVaultQuery).toHaveBeenLastCalledWith('type: action_item\nstatus: open\nlimit: 5');
    fireEvent.click(q(editor, '[aria-label="query options"]')!);
    expect(menuItem(editor, 'done editing')).toBeDefined();
    editor.destroy();
  });

  it('a new empty block starts in edit mode', async () => {
    runVaultQuery.mockResolvedValue(ok([]));
    const editor = makeEditor('```query\n```');
    expect(q(editor, '.gb-query')!.dataset.editing).toBe('true');
    editor.destroy();
  });

  it('only the latest response is painted', async () => {
    let resolveFirst: (v: VaultQueryResponse) => void = () => {};
    runVaultQuery
      .mockImplementationOnce(() => new Promise((r) => { resolveFirst = r; }))
      .mockResolvedValue(ok([ROWS[1]!]));
    const editor = makeEditor(SRC);
    await flush(); // first request in flight
    fireEvent.click(q(editor, '[aria-label="refresh query"]')!);
    await flush();
    resolveFirst(ok());
    await flush();
    const titles = Array.from(editor.view.dom.querySelectorAll('.gb-query-link')).map((n) => n.textContent);
    expect(titles).toEqual(['Book the room']);
    editor.destroy();
  });

  it('an editor destroyed at once (the parse probe) sends no request', async () => {
    makeEditor(SRC).destroy();
    await flush(QUERY_POLL_MS);
    expect(runVaultQuery).not.toHaveBeenCalled();
  });

  it('other code blocks keep their own views', () => {
    const editor = makeEditor('```python\nx = 1\n```');
    expect(q(editor, '.gb-query')).toBeNull();
    expect(q(editor, 'pre > code.language-python')!.textContent).toBe('x = 1');
    editor.destroy();
  });
});
```

Add to `FIXTURES` in `markdown-roundtrip.test.ts`:

```ts
  'live query block':
    '```query\ntype: action_item\nmentions: "[[30-cross-context/people/alex]]"\nstatus: open\nsort: created desc\n```',
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3/desktop && npx vitest run src/renderer/__tests__/query-view.test.ts src/renderer/__tests__/markdown-roundtrip.test.ts`
Expected: query-view FAILS with "Failed to resolve import ../lib/editor/query-view". The round-trip fixture already passes, because A1's plain code view handles it. It stays as the gate for this task.

- [ ] **Step 3: Add the event to `events.ts`**

In A1's `GbEditorEvents` interface, add a member:

```ts
  'gb:query:open': { path: string };
```

- [ ] **Step 4: Implement `query-view.ts`**

`desktop/src/renderer/lib/editor/query-view.ts`:

```ts
import type { Editor } from '@tiptap/core';
import type { Node as PMNode } from '@tiptap/pm/model';
import type { NodeView } from '@tiptap/pm/view';
import type { VaultQueryResponse, VaultQueryRow } from '../../../shared/api-types';
import { emitGb } from './events';
import { runVaultQuery } from './query-api';
import { isClosedStatus } from './query-format';

export const QUERY_POLL_MS = 60_000;
export const QUERY_EDIT_DEBOUNCE_MS = 500;
export const QUERY_INDEX_RETRY_MS = 2_000;
export const QUERY_INDEX_RETRIES = 5;

type Phase =
  | { kind: 'loading' }
  | { kind: 'ready'; data: VaultQueryResponse }
  | { kind: 'unavailable' };

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(className: string, text: string, ariaLabel?: string): HTMLButtonElement {
  const b = el('button', className, text);
  b.type = 'button';
  if (ariaLabel) b.setAttribute('aria-label', ariaLabel);
  return b;
}

function isResponse(value: unknown): value is VaultQueryResponse {
  if (!value || typeof value !== 'object') return false;
  const v = value as Partial<VaultQueryResponse>;
  return Array.isArray(v.results) && Array.isArray(v.diagnostics);
}

/**
 * Live view for a ```query``` code block (smart templates C2). The fence text
 * stays the source of truth (contentDOM); results live in non-editable chrome.
 * Fetch: deferred on mount (a throwaway probe editor never fetches), on window
 * focus, every QUERY_POLL_MS while on screen, after edits, after ticks.
 */
export function createQueryView(initial: PMNode, editor: Editor, getPos: unknown): NodeView {
  let node = initial;
  let editing = node.textContent.trim() === '';
  let phase: Phase = { kind: 'loading' };
  let notice: string | null = null;
  let menuOpen = false;
  let seq = 0;
  let destroyed = false;
  let indexRetries = 0;
  let visible = true;
  let editTimer: ReturnType<typeof setTimeout> | null = null;
  const timers = new Set<ReturnType<typeof setTimeout>>();
  const busy = new Set<string>();

  const dom = el('div', 'gb-query');
  const bar = el('div', 'gb-query-bar');
  bar.contentEditable = 'false';
  const refreshBtn = button('gb-query-btn', '↻', 'refresh query');
  const menuBtn = button('gb-query-btn', '⋯', 'query options');
  menuBtn.setAttribute('aria-haspopup', 'menu');
  const menu = el('div', 'gb-query-menu');
  menu.setAttribute('role', 'menu');
  const editItem = button('gb-query-menuitem', 'edit query');
  editItem.setAttribute('role', 'menuitem');
  const freezeItem = button('gb-query-menuitem', 'freeze');
  freezeItem.setAttribute('role', 'menuitem');
  menu.append(editItem, freezeItem);
  bar.append(el('span', 'gb-query-label', 'live query'), refreshBtn, menuBtn, menu);
  const results = el('div', 'gb-query-results');
  results.contentEditable = 'false';
  const pre = el('pre');
  const code = el('code', 'language-query');
  pre.appendChild(code);
  dom.append(bar, results, pre);

  const later = (fn: () => void, ms: number): void => {
    const t = setTimeout(() => {
      timers.delete(t);
      fn();
    }, ms);
    timers.add(t);
  };

  function canWrite(): boolean {
    return editor.isEditable;
  }

  function canFreeze(): boolean {
    return false; // Task 7 enables Freeze
  }

  function paintChrome(): void {
    dom.dataset.editing = String(editing);
    editItem.textContent = editing ? 'done editing' : 'edit query';
    menu.hidden = !menuOpen;
    menuBtn.setAttribute('aria-expanded', String(menuOpen));
    freezeItem.disabled = !canFreeze();
  }

  function rowEl(row: VaultQueryRow): HTMLElement {
    const li = el('li', 'gb-query-row');
    const done = isClosedStatus(row.status);
    const box = el('input');
    box.type = 'checkbox';
    box.checked = done;
    box.setAttribute('aria-label', `mark ${row.title} ${done ? 'open' : 'done'}`);
    box.disabled = true; // Task 7 wires tick-to-done
    const link = button('gb-query-link', row.title);
    link.addEventListener('click', (e) => {
      e.preventDefault();
      emitGb(editor, 'gb:query:open', { path: row.path });
    });
    const meta = el('span', 'gb-query-meta', [row.context, row.created?.slice(0, 10) ?? ''].filter(Boolean).join(' · '));
    li.append(box, link, meta);
    if (row.snippet) li.appendChild(el('div', 'gb-query-snippet', row.snippet));
    return li;
  }

  function paint(): void {
    paintChrome();
    const parts: HTMLElement[] = [];
    if (phase.kind === 'loading') {
      parts.push(el('p', 'gb-query-status', 'loading…'));
    } else if (phase.kind === 'unavailable') {
      const chip = button('gb-query-chip', 'results unavailable — retry');
      chip.addEventListener('click', (e) => {
        e.preventDefault();
        indexRetries = 0;
        void refresh();
      });
      parts.push(chip);
    } else {
      const { data } = phase;
      const errors = data.diagnostics.filter((d) => d.severity === 'error');
      if (errors.length > 0) {
        const box = el('div', 'gb-query-error');
        box.setAttribute('role', 'alert');
        for (const d of errors) box.appendChild(el('p', undefined, `line ${d.line}: ${d.message}`));
        box.appendChild(el('pre', undefined, node.textContent));
        parts.push(box);
      } else {
        for (const d of data.diagnostics) parts.push(el('p', 'gb-query-warning', d.message));
        if (data.results.length === 0) {
          parts.push(el('p', 'gb-query-status', 'no matching notes'));
        } else {
          const list = el('ul', 'gb-query-list');
          for (const row of data.results) list.appendChild(rowEl(row));
          parts.push(list);
        }
        if (data.partial) parts.push(el('p', 'gb-query-status', 'showing the first matches only — narrow the query'));
      }
    }
    if (notice) {
      const n = el('p', 'gb-query-notice', notice);
      n.setAttribute('role', 'status');
      parts.push(n);
    }
    results.replaceChildren(...parts);
  }

  async function refresh(): Promise<void> {
    if (destroyed) return;
    const mine = ++seq;
    let next: Phase;
    let retry = false;
    try {
      const data: unknown = await runVaultQuery(node.textContent);
      if (!isResponse(data)) {
        next = { kind: 'unavailable' };
      } else if (data.indexing) {
        next = { kind: 'unavailable' };
        retry = indexRetries < QUERY_INDEX_RETRIES;
      } else {
        indexRetries = 0;
        next = { kind: 'ready', data };
      }
    } catch {
      next = { kind: 'unavailable' };
    }
    if (destroyed || mine !== seq) return; // superseded by a newer request
    phase = next;
    paint();
    if (retry) {
      indexRetries += 1;
      later(() => void refresh(), QUERY_INDEX_RETRY_MS);
    }
  }

  refreshBtn.addEventListener('click', (e) => {
    e.preventDefault();
    void refresh();
  });
  menuBtn.addEventListener('click', (e) => {
    e.preventDefault();
    menuOpen = !menuOpen;
    paintChrome();
  });
  editItem.addEventListener('click', (e) => {
    e.preventDefault();
    editing = !editing;
    menuOpen = false;
    paintChrome();
  });

  const onFocus = (): void => void refresh();
  window.addEventListener('focus', onFocus);
  const poll = setInterval(() => {
    if (visible && document.visibilityState !== 'hidden') void refresh();
  }, QUERY_POLL_MS);
  const observer =
    typeof IntersectionObserver === 'undefined'
      ? null
      : new IntersectionObserver((entries) => {
          visible = entries.some((entry) => entry.isIntersecting);
        });
  observer?.observe(dom);

  paint();
  later(() => void refresh(), 0);

  return {
    dom,
    contentDOM: code,
    update(next) {
      if (next.type !== node.type || next.attrs.language !== 'query') return false;
      const changed = next.textContent !== node.textContent;
      node = next;
      if (changed) {
        if (editTimer) clearTimeout(editTimer);
        editTimer = setTimeout(() => {
          editTimer = null;
          void refresh();
        }, QUERY_EDIT_DEBOUNCE_MS);
      }
      return true;
    },
    stopEvent: (event) => {
      const t = event.target as globalThis.Node | null;
      return !!t && (bar.contains(t) || results.contains(t));
    },
    ignoreMutation: (mutation) =>
      mutation.type !== 'selection' && !code.contains(mutation.target as globalThis.Node),
    destroy() {
      destroyed = true;
      seq++;
      if (editTimer) clearTimeout(editTimer);
      for (const t of timers) clearTimeout(t);
      timers.clear();
      clearInterval(poll);
      window.removeEventListener('focus', onFocus);
      observer?.disconnect();
    },
  };
}
```

At this point `getPos`, `busy` and `canWrite` are unused. If `npm run lint` flags them (`@typescript-eslint/no-unused-vars`), prefix the parameter as `_getPos` and drop `busy` and `canWrite` for now. Task 7 adds them back.

- [ ] **Step 5: Plug the view into A1's code-block dispatch**

In `desktop/src/renderer/lib/editor/code-block.ts`, add `import { createQueryView } from './query-view';` and replace the `GbCodeBlock` definition with:

```ts
/** StarterKit's codeBlock with per-language node views; markdown handling is
 * tiptap-markdown's default, so every fence round-trips unchanged. */
export const GbCodeBlock = CodeBlock.extend({
  addNodeView() {
    const prefix = this.options.languageClassPrefix;
    return ({ node, editor, getPos }) => {
      const language = (node.attrs.language as string | null) ?? null;
      if (language === 'mermaid') return createMermaidView(node, editor);
      if (language === 'query') return createQueryView(node, editor, getPos);
      return createPlainCodeView(node, prefix);
    };
  },
});
```

- [ ] **Step 6: Append the styles**

Append to `desktop/src/renderer/styles.css`:

```css
.gb-query {
  border: 1px solid var(--hairline);
  border-radius: 6px;
  margin: 0 0 1em;
  background: var(--vellum);
}
.gb-query-bar {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px 0;
  font-family: var(--font-mono, monospace);
  font-size: 10px;
  color: var(--ink-2);
}
.gb-query-label { margin-right: auto; }
.gb-query-btn,
.gb-query-menuitem,
.gb-query-link,
.gb-query-chip {
  background: transparent;
  border: 0;
  cursor: pointer;
  color: inherit;
  font: inherit;
  padding: 0 2px;
}
.gb-query-btn:hover,
.gb-query-menuitem:hover,
.gb-query-link:hover { color: var(--ink-0); }
.gb-query-menu {
  position: absolute;
  right: 6px;
  top: 20px;
  z-index: 5;
  display: flex;
  flex-direction: column;
  padding: 4px;
  border: 1px solid var(--hairline);
  border-radius: 4px;
  background: var(--vellum);
}
.gb-query-menu[hidden] { display: none; }
.gb-query-menuitem { text-align: left; padding: 2px 6px; }
.gb-query-menuitem:disabled { opacity: 0.4; cursor: default; }
.gb-query-results { padding: 6px 12px 8px; font-size: 13px; }
.gb-query-list { list-style: none; margin: 0; padding: 0; }
.gb-query-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; padding: 2px 0; }
.gb-query-link { color: var(--ink-0); text-align: left; text-decoration: underline; text-decoration-color: var(--hairline); }
.gb-query-meta { font-family: var(--font-mono, monospace); font-size: 10px; color: var(--ink-3); }
.gb-query-snippet { flex-basis: 100%; padding-left: 22px; font-size: 12px; color: var(--ink-2); }
.gb-query-status,
.gb-query-warning,
.gb-query-notice { margin: 4px 0 0; font-size: 12px; color: var(--ink-2); }
.gb-query-chip {
  border: 1px solid var(--hairline);
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 11px;
  color: var(--ink-1);
}
.gb-query-error { color: var(--pill-oxblood-fg); font-size: 12px; }
.gb-query-error p { margin: 0; }
.gb-query-error pre { margin: 6px 0 0; color: var(--ink-1); }
.gb-query[data-editing='false'] > pre { display: none; }
.gb-query > pre { margin: 0; border: 0; border-top: 1px solid var(--hairline); border-radius: 0 0 6px 6px; }
```

- [ ] **Step 7: Run tests, typecheck and lint**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3/desktop && npx vitest run src/renderer/__tests__/query-view.test.ts src/renderer/__tests__/mermaid-view.test.ts src/renderer/__tests__/markdown-roundtrip.test.ts src/renderer/__tests__/RichMarkdownEditor.test.tsx && npm run typecheck && npx eslint --max-warnings 0 src/renderer/lib/editor src/renderer/__tests__/query-view.test.ts`
Expected: PASS, with no type or lint errors. The Mermaid view tests still pass through the shared dispatch.

- [ ] **Step 8: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans3/desktop
git add src/renderer/lib/editor/query-view.ts src/renderer/lib/editor/code-block.ts src/renderer/lib/editor/events.ts src/renderer/__tests__/query-view.test.ts src/renderer/__tests__/markdown-roundtrip.test.ts src/renderer/styles.css
git commit -m "feat(editor): live query block view for query code fences"
```

---

### Task 7: Tick-to-done, Freeze, and opening results

**Files:**
- Modify: `desktop/src/renderer/lib/editor/query-view.ts`
- Modify: `desktop/src/renderer/components/RichMarkdownEditor.tsx`
- Create: `desktop/src/renderer/__tests__/query-actions.test.ts`
- Modify: `desktop/src/renderer/__tests__/RichMarkdownEditor.test.tsx`
- Modify: `desktop/src/renderer/__tests__/markdown-roundtrip.test.ts`

**Interfaces:**
- Consumes: `createQueryView` internals from Task 6 (`phase`, `busy`, `notice`, `paint`, `refresh`, `canWrite`, `getPos`, `freezeItem`, `menuOpen`, `paintChrome`); `setNoteStatus` and `freezeMarkdown` (Task 5); `ApiError` (`lib/api/client.ts`); `onGb` (A1); `noteTarget` (`lib/editor/link-suggest.ts`).
- Produces: checkboxes call `setNoteStatus(path, 'done' | 'open', row.etag)` and then refresh. A 409 sets the notice "<title> changed elsewhere — list refreshed, try again". Any other failure sets "could not update <title>: <message>". "freeze" replaces the block with `freezeMarkdown(rows)` in one transaction. Ticks and Freeze are disabled when the editor is not editable. `RichMarkdownEditor` forwards `gb:query:open` to `onWikilinkClick(noteTarget(path))`.

- [ ] **Step 1: Write the failing tests**

`desktop/src/renderer/__tests__/query-actions.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import type { VaultQueryResponse, VaultQueryRow } from '../../shared/api-types';

const { runVaultQuery, setNoteStatus } = vi.hoisted(() => ({ runVaultQuery: vi.fn(), setNoteStatus: vi.fn() }));
vi.mock('../lib/editor/query-api', () => ({ runVaultQuery, setNoteStatus }));

import { ApiError } from '../lib/api/client';
import { makeEditor, markdownOf } from './helpers/editor';

const SRC = '```query\ntype: action_item\n```';
const OPEN: VaultQueryRow = {
  path: '20-contexts/work/a.md',
  title: 'Send Alex the budget',
  context: 'work',
  status: null,
  created: '2026-10-08',
  snippet: '',
  etag: 'aaaaaaaaaaaaaaaa',
};
const DONE: VaultQueryRow = { ...OPEN, path: '20-contexts/work/b.md', title: 'Book the room', status: 'done', etag: 'bbbbbbbbbbbbbbbb' };

function ok(results: VaultQueryRow[] = [OPEN, DONE], extra: Partial<VaultQueryResponse> = {}): VaultQueryResponse {
  return { results, diagnostics: [], indexing: false, partial: false, ...extra };
}

async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function boxes(editor: Editor): HTMLInputElement[] {
  return Array.from(editor.view.dom.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
}

function freezeItem(editor: Editor): HTMLButtonElement {
  fireEvent.click(editor.view.dom.querySelector('[aria-label="query options"]')!);
  const items = Array.from(editor.view.dom.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
  return items.find((b) => b.textContent === 'freeze')!;
}

describe('query block actions', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    runVaultQuery.mockReset();
    setNoteStatus.mockReset();
    runVaultQuery.mockResolvedValue(ok());
    setNoteStatus.mockResolvedValue({ path: OPEN.path, status: 'done', etag: 'cccccccccccccccc' });
  });
  afterEach(() => vi.useRealTimers());

  it('ticking an open row marks it done with its etag, then refreshes', async () => {
    const editor = makeEditor(SRC);
    await flush();
    runVaultQuery.mockResolvedValue(ok([DONE]));
    fireEvent.click(boxes(editor)[0]!);
    await flush();
    expect(setNoteStatus).toHaveBeenCalledWith('20-contexts/work/a.md', 'done', 'aaaaaaaaaaaaaaaa');
    expect(runVaultQuery).toHaveBeenCalledTimes(2);
    expect(boxes(editor)).toHaveLength(1);
    expect(editor.view.dom.querySelector('.gb-query-notice')).toBeNull();
    editor.destroy();
  });

  it('unticking a done row writes status open', async () => {
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(boxes(editor)[1]!);
    await flush();
    expect(setNoteStatus).toHaveBeenCalledWith('20-contexts/work/b.md', 'open', 'bbbbbbbbbbbbbbbb');
    editor.destroy();
  });

  it('a 409 shows the changed-elsewhere notice and refreshes', async () => {
    setNoteStatus.mockRejectedValue(new ApiError('note changed since you read it', 409));
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(boxes(editor)[0]!);
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(2);
    const notice = editor.view.dom.querySelector('.gb-query-notice')!;
    expect(notice.getAttribute('role')).toBe('status');
    expect(notice.textContent).toBe('Send Alex the budget changed elsewhere — list refreshed, try again');
    editor.destroy();
  });

  it('other failures say what went wrong', async () => {
    setNoteStatus.mockRejectedValue(new ApiError('Note not found: a.md', 404));
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(boxes(editor)[0]!);
    await flush();
    expect(editor.view.dom.querySelector('.gb-query-notice')!.textContent).toBe(
      'could not update Send Alex the budget: Note not found: a.md',
    );
    editor.destroy();
  });

  it('a row is disabled while its write is in flight', async () => {
    let finish: () => void = () => {};
    setNoteStatus.mockImplementation(() => new Promise<void>((r) => { finish = r; }));
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(boxes(editor)[0]!);
    expect(boxes(editor)[0]!.disabled).toBe(true);
    fireEvent.click(boxes(editor)[0]!);
    expect(setNoteStatus).toHaveBeenCalledTimes(1);
    finish();
    await flush();
    editor.destroy();
  });

  it('freeze replaces the block with a static task list', async () => {
    const editor = makeEditor(`${SRC}\n\nafter`);
    await flush();
    const item = freezeItem(editor);
    expect(item.disabled).toBe(false);
    fireEvent.click(item);
    expect(markdownOf(editor)).toBe(
      '- [ ] [[20-contexts/work/a|Send Alex the budget]]\n- [x] [[20-contexts/work/b|Book the room]]\n\nafter',
    );
    expect(editor.view.dom.querySelector('.gb-query')).toBeNull();
    editor.destroy();
  });

  it('freezing zero rows leaves a plain sentence', async () => {
    runVaultQuery.mockResolvedValue(ok([]));
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(freezeItem(editor));
    expect(markdownOf(editor)).toBe('no matching notes');
    editor.destroy();
  });

  it('freeze is disabled while the query has errors or has not loaded', async () => {
    let resolve: (v: VaultQueryResponse) => void = () => {};
    runVaultQuery.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    const editor = makeEditor(SRC);
    await flush();
    expect(freezeItem(editor).disabled).toBe(true);
    resolve(ok([], { diagnostics: [{ line: 1, col: 1, severity: 'error', message: 'bad', code: 'bad-value' }] }));
    await flush();
    expect(freezeItem(editor).disabled).toBe(true);
    editor.destroy();
  });

  it('a read-only editor disables ticking and freeze', async () => {
    const editor = makeEditor(SRC, false);
    await flush();
    expect(boxes(editor).every((b) => b.disabled)).toBe(true);
    fireEvent.click(boxes(editor)[0]!);
    await flush();
    expect(setNoteStatus).not.toHaveBeenCalled();
    expect(freezeItem(editor).disabled).toBe(true);
    editor.destroy();
  });
});
```

Append inside the top-level `describe('RichMarkdownEditor', …)` in `RichMarkdownEditor.test.tsx`, and add `import { emitGb } from '../lib/editor/events';` to the imports:

```tsx
  it('opens a query result through onWikilinkClick', () => {
    const onWikilinkClick = vi.fn();
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="text"
        onSave={() => {}}
        jotId="test"
        onWikilinkClick={onWikilinkClick}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    act(() => emitGb(editor!, 'gb:query:open', { path: '20-contexts/work/a.md' }));
    expect(onWikilinkClick).toHaveBeenCalledWith('20-contexts/work/a');
  });
```

Add to `FIXTURES` in `markdown-roundtrip.test.ts`:

```ts
  'frozen query list':
    '- [ ] [[20-contexts/work/a|Send Alex the budget]]\n- [x] [[20-contexts/work/b|Book the room]]',
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3/desktop && npx vitest run src/renderer/__tests__/query-actions.test.ts src/renderer/__tests__/RichMarkdownEditor.test.tsx src/renderer/__tests__/markdown-roundtrip.test.ts`
Expected: FAIL. The tick tests fail because `setNoteStatus` is never called (checkboxes are disabled). The freeze tests fail on `disabled` being `true`. The RichMarkdownEditor test fails because `onWikilinkClick` is not called. `frozen query list` round-trips already and stays as a gate.

- [ ] **Step 3: Wire tick-to-done and Freeze in `query-view.ts`**

Change the imports at the top to:

```ts
import type { Editor } from '@tiptap/core';
import type { Node as PMNode } from '@tiptap/pm/model';
import type { NodeView } from '@tiptap/pm/view';
import type { VaultQueryResponse, VaultQueryRow } from '../../../shared/api-types';
import { ApiError } from '../api/client';
import { emitGb } from './events';
import { runVaultQuery, setNoteStatus } from './query-api';
import { freezeMarkdown, isClosedStatus } from './query-format';
```

If Task 6 renamed the parameter to `_getPos` or dropped `busy` or `canWrite` for lint, restore them: the parameter `getPos: unknown`, `const busy = new Set<string>();`, and `function canWrite(): boolean { return editor.isEditable; }`.

Replace `canFreeze` with:

```ts
  function canFreeze(): boolean {
    return (
      canWrite() &&
      phase.kind === 'ready' &&
      !phase.data.diagnostics.some((d) => d.severity === 'error')
    );
  }
```

Replace `rowEl` with:

```ts
  function rowEl(row: VaultQueryRow): HTMLElement {
    const li = el('li', 'gb-query-row');
    const done = isClosedStatus(row.status);
    const box = el('input');
    box.type = 'checkbox';
    box.checked = done;
    box.setAttribute('aria-label', `mark ${row.title} ${done ? 'open' : 'done'}`);
    box.disabled = !canWrite() || busy.has(row.path);
    box.addEventListener('change', () => void toggle(row, box.checked));
    const link = button('gb-query-link', row.title);
    link.addEventListener('click', (e) => {
      e.preventDefault();
      emitGb(editor, 'gb:query:open', { path: row.path });
    });
    const meta = el('span', 'gb-query-meta', [row.context, row.created?.slice(0, 10) ?? ''].filter(Boolean).join(' · '));
    li.append(box, link, meta);
    if (row.snippet) li.appendChild(el('div', 'gb-query-snippet', row.snippet));
    return li;
  }
```

Add these two functions directly after `refresh`:

```ts
  async function toggle(row: VaultQueryRow, done: boolean): Promise<void> {
    if (!canWrite() || busy.has(row.path)) return;
    busy.add(row.path);
    notice = null;
    paint();
    try {
      await setNoteStatus(row.path, done ? 'done' : 'open', row.etag);
    } catch (err) {
      notice =
        err instanceof ApiError && err.status === 409
          ? `${row.title} changed elsewhere — list refreshed, try again`
          : `could not update ${row.title}: ${err instanceof Error ? err.message : String(err)}`;
    } finally {
      busy.delete(row.path);
    }
    await refresh();
  }

  function freeze(): void {
    if (!canFreeze() || phase.kind !== 'ready') return;
    const pos = typeof getPos === 'function' ? (getPos as () => number | undefined)() : undefined;
    if (typeof pos !== 'number') return;
    // tiptap-markdown parses a string passed to insertContentAt as markdown.
    editor.commands.insertContentAt({ from: pos, to: pos + node.nodeSize }, freezeMarkdown(phase.data.results));
  }
```

Add this listener after the `editItem` listener:

```ts
  freezeItem.addEventListener('click', (e) => {
    e.preventDefault();
    menuOpen = false;
    paintChrome();
    freeze();
  });
```

- [ ] **Step 4: Forward `gb:query:open` in `RichMarkdownEditor.tsx`**

Add `noteTarget` to the imports: `import { noteTarget } from '../lib/editor/link-suggest';`. `onGb` is already imported by A1. Add this effect next to A1's `gb:diagram:open` effect:

```tsx
  // A live query result was clicked: open it the way a [[wikilink]] opens,
  // so the host's unsaved-changes guard applies.
  useEffect(() => {
    if (!editor) return;
    return onGb(editor, 'gb:query:open', ({ path }) => onWikilinkClickRef.current?.(noteTarget(path)));
  }, [editor]);
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3/desktop && npx vitest run src/renderer/__tests__/query-actions.test.ts src/renderer/__tests__/query-view.test.ts src/renderer/__tests__/RichMarkdownEditor.test.tsx src/renderer/__tests__/markdown-roundtrip.test.ts`
Expected: PASS.

- [ ] **Step 6: Full desktop gate**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans3/desktop && npx vitest run && npm run typecheck && npm run lint`
Expected: the whole suite passes, including `NoteView`, `jots`, `mermaid-view` and the template tests, and typecheck and lint are clean.

Run the backend CI list once more: `cd /Users/jannik/development/nikrich/ghost-brain-plans3 && python -m pytest ghostbrain/api/tests/ tests/test_templates_query.py tests/test_templates_functions.py tests/test_templates_security.py tests/test_no_hardcoded_contexts.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans3/desktop
git add src/renderer/lib/editor/query-view.ts src/renderer/components/RichMarkdownEditor.tsx src/renderer/__tests__/query-actions.test.ts src/renderer/__tests__/RichMarkdownEditor.test.tsx src/renderer/__tests__/markdown-roundtrip.test.ts
git commit -m "feat(editor): tick-to-done, freeze and open for live query results"
```

---

## Self-review

**Spec coverage (C2 rows):**
- "Link-index fields": `artifactType, type, status, context, tags, created, updated` are already on A2's `NoteEntry`, so no index change is needed (Decision 1). Query-time file reads add the title, snippet and etag (Task 3).
- `query.py` "runs a query against spec A2's link index … returns `[{path, title, context, status, created, snippet}]`": Tasks 2–3, plus `etag` for If-Match.
- The query keys `type` (artifactType or type), `context`, `tag`, `mentions` (link, else body text), `status` (`open` semantics), `since` (`7d`, date), `sort` (`created|updated` + `asc|desc`) and `limit` (default 20, max 100): Task 2 (grammar) and Task 3 (behaviour).
- `POST /v1/vault/query {query}`: Task 4.
- The query NodeView "renders results as a list of links with status checkboxes": Task 6. "Ticking one calls the write path to set `status: done` (a `fields` write, actor user), and the list refreshes": Task 4 (route through `vault_write.write`) and Task 7 (UI).
- "Fetched on mount and on focus, and every 60 s while visible": Task 6.
- The "⋯" menu with "Edit query (toggles to source)" is Task 6. "Freeze, which replaces the block with a static markdown list" is Tasks 5 and 7.
- Error handling:
  - A query error shows inline with the source, and the note still opens: Tasks 4 and 6.
  - Query index unavailable shows "results unavailable — retry": Tasks 4 and 6.
- Testing rows:
  - The query engine for each key, `open` with a missing status, mentions via link versus text, sort and limit, and the 100 cap: Task 3.
  - The query NodeView render, tick sets done and refreshes, freeze gives a static list, and the error state: Tasks 6–7.
  - The round-trip fixture keeps a ` ```query ` block byte-stable: Task 6. The frozen-list fixture is Task 7.
- C1 alignment:
  - Query keys live in C1's registry, and `registry_json()["queryKeys"]` serves C3 (Task 1).
  - Diagnostics reuse C1's `Diagnostic` and TS `TemplateDiagnostic`.
  - Unresolved `{{…}}` is detected with C1's `tokenize` (Task 2).
  - The rendered 1-1 starter's fence parses (Task 2).
- A1 alignment: the query view is one branch of `GbCodeBlock`'s dispatch, and its open event goes through A1's `events.ts` (Task 6).

**Security and bounds:**
- No evaluation: the grammar is line-based, and C1's static guard covers `query.py`.
- Regex input is escaped (`test_mentions_value_is_literal_not_a_pattern`).
- Size caps are tested in `test_size_caps` and the transport cap in `test_oversized_query_body_is_rejected`.
- Row cap: `test_limit_and_cap`. Read and time caps: `test_text_scan_is_bounded_and_reports_partial`.
- Writes go only through B1's `resolve_safe`, tested in `test_tick_rejects_bad_targets`.

**Placeholder scan:** every step carries code or an exact command. The two "Task 7 enables" comments in Task 6 mark concrete lines that Task 7 replaces in full.

**Type consistency:**
- `QueryRow.to_json()` keys = `VaultQueryRow` = the `VaultQueryRow` pydantic model = the test expectations.
- `Diagnostic.to_json()` = `VaultQueryDiagnostic` = `TemplateDiagnostic`.
- `NoteStatusValue` (`'done' | 'open'`) = `NoteStatusRequest.status`.
- `setNoteStatus(path, status, etag)` is the same in Tasks 5 and 7.
- `createQueryView(initial, editor, getPos)` is the same in Task 6 (dispatch) and Task 7.
- `gb:query:open { path }` is the same in `events.ts`, the view and `RichMarkdownEditor`.
- The `QUERY_*` constant names are the same in the view and the tests.
