# C3 Smart Templates — Template Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users edit template files in a CodeMirror editor that completes placeholders, prompt types and query keys, shows hover docs and lint markers, all driven by C1's single function registry, and has a Test run pane that renders the template with sample answers (the last real ones first) without writing anything.

**Architecture:** On the backend, `ghostbrain/templates/lint.py` adds registry checks of every `{{ placeholder }}` to C1's parse diagnostics. The checks use `functions.find_spec` and mirror `render.evaluate` exactly (a parity test pins it), and when C2 is on the branch the linter runs C2's `parse_query_block` over every ```query fence. `testrun.py` renders template *source* with sample answers and reports the path `write_new` would pick, writing nothing. `source.py` reads a template with its etag, saves it through B1's `vault_write.write` (If-Match), creates a blank template and ranks query value hints from A2's link index. Six routes join C1's router. On the desktop, `lib/template-editor/` holds pure text analysis plus three CodeMirror pieces (completion source, hover tooltip, linter) that read `GET /v1/templates/functions` (C1's `registry_json()`, with C2's `queryKeys`). `TemplateSourceEditor` hosts them with explicit save and a conflict banner, `TemplateTestRun` renders through the normal `RichMarkdownEditor` read-only (so C2's live query blocks run), and `TemplatesPanel` is the Templates tab of the Jots screen.

**Tech Stack:** Python 3.11+ (CI runs 3.11), FastAPI, pydantic v2, `ghostbrain.templates` (C1, C2), `ghostbrain.vault_write` (B1), `ghostbrain.vault_index` (A2). Desktop: React 18, TanStack Query 5, CodeMirror 6 through `@uiw/react-codemirror` 4.25.10 with `@codemirror/autocomplete` 6.20.3, `@codemirror/lint` 6.9.7, `@codemirror/state` 6.6.0 and `@codemirror/view` 6.43.1, Vitest 2 + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-09-smart-templates-design.md`. This plan covers slice **C3 Template editor** only: completions, hover docs, lint, Test run, and the Templates tab (list, create blank, open the editor). "Make one with AI" is C4 (`docs/superpowers/plans/2026-10-10-c4-ai-templates.md`), which adds its button to this tab.

## Global Constraints

- **C3 builds on a branch that contains C1** (`docs/superpowers/plans/2026-10-09-c1-templates-engine.md`, all 11 tasks) **and main's navigation guard** (`registerNavigationGuard` in `desktop/src/renderer/stores/navigation.ts`). Export the worktree root once per shell, `export C3=/absolute/path/to/your/c3/worktree`; every command below is `cd "$C3" && …` (Python) or `cd "$C3/desktop" && …` (desktop). Before Task 1 run `cd "$C3" && python -c "from ghostbrain.templates.functions import registry_json, find_spec; from ghostbrain.templates.env import build_env; from ghostbrain.templates.create import preview_from_template; from ghostbrain.api.routes.templates import router; print('ok')" && grep -q registerNavigationGuard desktop/src/renderer/stores/navigation.ts && test -f desktop/src/renderer/components/TemplatePicker.tsx`. If it fails, stop and rebase onto a branch that has C1 and current main.
- **C2 is needed for query-block completions, hover and lint** (`functions.QUERY_KEYS` / `registry_json()["queryKeys"]` and `ghostbrain/templates/query.py`, `docs/superpowers/plans/2026-10-10-c2-live-queries.md`). Build on a branch that also has C2 when it is merged. **If C2 is not on the branch, query support switches off behind a feature check and everything else works:** the backend's `lint.query_parser()` returns `None` when `ghostbrain.templates.query` does not import (query fences are then not linted), and the editor reads `registry.queryKeys ?? []`, so with no `queryKeys` there are no query-key or query-value completions and no query-key hover. `TemplateRegistry = TemplateFunctionsResponse & { queryKeys?: TemplateFunctionSpec[] }` typechecks with or without C2's type change. The one test that needs the real C2 parser uses `pytest.importorskip("ghostbrain.templates.query")`.
- **Single registry.** Every completion, hover text and lint rule about names comes from C1's registry: `registry_json()` over HTTP for the editor, `find_spec(kind, name, owner)` / `FIELDS` / `FILTERS` / `VARIABLES` / `PROMPT_VALUE_TYPES` in the linter. No name, field, filter or prompt type is hardcoded in C3. The only fixed lists are the query `sort` values (`created|updated` × `asc|desc`, from the spec's grammar) and `open` for `status`.
- **Template content is a security boundary** (C4 lets the AI write templates). Lint and Test run treat the source as untrusted text: nothing is evaluated (C1's static guard `test_sec_engine_source_has_no_dynamic_execution` scans every `ghostbrain/templates/*.py`, so new modules must not contain `eval(`, `exec(`, `getattr(`, `importlib`, `subprocess`, `__import__`, `pickle`, `jinja2` or non-safe YAML loads, not even in comments). Test run never writes, and reports a folder that escapes the vault (including through a symlink) as an inline error. Request bodies are capped at `MAX_TEMPLATE_CHARS` (256,000) characters, answers at 50 keys. Hover tooltips build DOM with `textContent` only.
- **Writes go through the B1 write path.** Saving a template is `vault_write.write(path, content=…, actor=…, base_etag=<If-Match>)`; a stale etag is **409** with `currentEtag` (B1's handler) and writes nothing. A new blank template is `vault_write.write_new`, which never overwrites. The actor is B2's `request_actor` dependency when B2 is on the branch (`from ghostbrain.api.vault_http import request_actor`), otherwise `user`, behind an `ImportError` check in the route module.
- **Pin new CodeMirror packages exactly**, at the versions already in `desktop/package-lock.json`, so npm keeps one copy of each (two copies of `@codemirror/state` break every extension): `@codemirror/autocomplete@6.20.3`, `@codemirror/lint@6.9.7`, `@codemirror/state@6.6.0`, `@codemirror/view@6.43.1`. `@codemirror/lang-markdown` and `@uiw/react-codemirror` are already direct dependencies; leave them as they are.
- The spec's `POST /v1/templates/render {source, answers, dry_run: true}` is the Test run route; C1's `POST /v1/templates/{id}/render {answers}` stays as it is (different path depth).
- Python tests run with `python -m pytest` from the repo root. Every new `tests/test_templates_*.py` goes into the fixed list in `.github/workflows/ci.yml`; files under `ghostbrain/api/tests/` are covered by the directory entry. Backend CI installs only `[dev,api]`.
- Desktop gates: `npm run typecheck` (`tsc -b`, never `tsc --noEmit`), `npx vitest run`, `npm run lint` (`eslint . --max-warnings 0`). Windows release builds rerun the desktop tests, so tests must not depend on POSIX paths, the time zone or real timers beyond Testing Library's `findBy*`. Node 25 ships a bare global `localStorage` that shadows jsdom's: tests stub it (`helpers/memory-storage.ts`, Task 5).
- JSX text must not contain a raw `'` or `"` (`react/no-unescaped-entities`); put such copy in `{`…`}` expressions. UI copy is lower-case, like the rest of the app.
- Neutral example content only: person "Alex" (or "Robin"), context "work", project "Alpha", user "Sam". The CI guard `tests/test_no_hardcoded_contexts.py` scans `ghostbrain/`, `docs/` and `desktop/src`.

## Review Focus

1. **Remembered answers from an older version of the template.** The user renamed or removed a prompt, and the Test run sends last week's answers. It must still render, dropping keys the template no longer has, instead of failing with "unknown answer". Pinned in Task 2 (`test_given_answers_win_and_stale_keys_are_dropped`).
2. **The template file changed on disk while it is open** (edited in Obsidian, or an approved C4 change landed). Save must not overwrite it: 409, a banner with "reload theirs" / "keep mine", nothing written until the user picks. Pinned in Task 4 (`test_save_with_a_stale_etag_is_409_and_writes_nothing`) and Task 10 (`on 409 shows the conflict banner; keep mine overwrites without an etag`, `reload theirs replaces the text with the file on disk`).
3. **A template saved mid-edit with errors, or one that was already broken.** It must save (that is how it gets fixed), show ⚠ in the list, and still open in the editor, even though the picker disables it. Pinned in Task 3 (`test_save_keeps_a_broken_template_so_it_can_be_fixed`) and Task 11 (`lists templates, broken ones too, and opens one in the editor`).
4. **The sidecar is down or slow while typing.** Lint must show no markers rather than stale or invented ones, and the editor keeps working. Pinned in Task 8 (`lints the current document and shows nothing when the request fails`).
5. **A hostile or broken folder in a template under Test run** (`../../outside`, a symlinked context folder). The Test run must show the error inline and write nothing anywhere. Pinned in Task 2 (`test_escaping_folder_is_reported_and_nothing_written`, `test_symlinked_folder_out_of_the_vault_is_reported`) and Task 4 (`test_test_run_renders_and_writes_nothing`).

## Decisions taken where the spec was silent or ambiguous

1. **What lint checks.** C1's parse diagnostics always come back. Placeholder checks run only when the template parses, because they need the prompt ids and types. A placeholder is flagged exactly when `render.evaluate` would leave it literal: unknown name (`unknown-name`, with a "did you mean" from the registry and prompt ids), unknown field for the value type (`unknown-field`, listing that type's fields), unknown filter (`unknown-filter`), a missing or unexpected filter argument (`filter-arg`), or not an expression at all (`malformed`). All are **warnings**, because C1 renders them literally and never fails. A parity test over 18 expressions pins lint against render.
2. **Positions.** The linter tokenizes the whole file, so a placeholder inside `file.name` gets its real line and column. YAML escapes inside quoted strings are not decoded first; a `\"` inside a quoted filter argument is linted as written, which can only make an argument look present, never invent a warning.
3. **Query lint** runs C2's `parse_query_block` on each ```query fence of the body and maps its lines to file lines. C2's `unresolved-placeholder` complaint is dropped: in a template the placeholder is filled in at creation. An unclosed ```query fence is an `unclosed-query` warning. Diagnostics are sorted by position and capped at 100 plus a `truncated` info line.
4. **Test run route.** `POST /v1/templates/render {source, answers, id?, dry_run: true}` always answers 200 with `{ok, prompts, answers, rendered, wouldBeFiledAt, diagnostics, error}`, so the pane can show errors next to the source. `dry_run` must be `true` (422 otherwise). `id` only sets `fromTemplate` in the preview. Blank required prompts get samples server-side: the first option of a choice, today for a date, the default context, the first project, "Sample Person", or `[<id>]` for text. Optional and defaulted prompts stay blank so the renderer applies their default.
5. **"The most recent real values (last person, today)."** The desktop remembers the answers of every successful create (`useCreateFromTemplate`'s `onSuccess`) in localStorage, per template and per prompt id across templates. A Test run starts from this template's last answers, else the latest answer to a prompt with the same id anywhere (so a new template's `person` starts from the last person picked), else the server's samples. "Today" is the server's default for an unanswered date.
6. **Saving** is explicit (the save button or Mod-S), not autosave: a half-typed template should not replace a working one. `PATCH /v1/templates/{id}/source` with `If-Match`. "Keep mine" re-sends without `If-Match`, which B1 allows for the user actor.
7. **New blank template:** `POST /v1/templates {name}` → id = `slugify(name, 60)`, `-2`, `-3`… on collision (`write_new`). It seeds the starters first, because creating the folder would otherwise stop them from ever being seeded.
8. **Query value hints.** `GET /v1/templates/query-values` ranks the most common `artifactType`/`type` values and statuses in A2's link index (30 each). Contexts come from the existing `useContexts`. While the index is cold it answers `indexing: true` and the editor re-asks every 3 s.
9. **Templates tab.** A "templates" button in the Jots top bar swaps the screen to `TemplatesPanel` (asking first if a jot has an unresolved conflict, like every jots navigation); "jots" swaps back. The panel lists every template, broken ones included, with ⚠.
10. **Prompt ids on the client** are read from the frontmatter text with a small block-or-flow YAML scan, used only for completions, hover and the first Test run's answers. The server stays authoritative: lint and Test run parse with C1.

---

## Interfaces

```python
# ghostbrain/templates/lint.py (Task 1)
MAX_LINT_DIAGNOSTICS = 100
QueryParser = Callable[[str], tuple[object, list[Diagnostic]]]
def query_parser() -> QueryParser | None            # C2's parse_query_block, or None without C2
def lint(source: str, template_id: str = "draft") -> list[Diagnostic]
#   codes: C1 parse codes + malformed | unknown-name | unknown-field | unknown-filter | filter-arg
#          | unclosed-query | C2 query codes | truncated

# ghostbrain/templates/testrun.py (Task 2)
SAMPLE_PERSON = "Sample Person"; MAX_NAME_ATTEMPTS = 100
def sample_answers(template: Template, answers: Mapping[str, Any], env: RenderEnv) -> dict[str, str]
def would_be_path(rel_path: str) -> str               # raises InvalidPath / RenderError
@dataclass(frozen=True) class DryRunResult:
    prompts: tuple[Prompt, ...]; answers: dict[str, str]; note: RenderedNote | None
    would_be_filed_at: str | None; diagnostics: tuple[Diagnostic, ...]; error: str | None
    ok (property); def to_json(self) -> dict[str, Any]
def dry_run(source: str, answers: Mapping[str, Any], *, template_id: str = "draft",
            env: RenderEnv | None = None) -> DryRunResult

# ghostbrain/templates/source.py (Task 3)
MAX_NAME_CHARS = 80; NEW_ID_MAX = 60; MAX_HINTS = 30; BLANK_TEMPLATE: str
class SourceTooLarge(ValueError)
@dataclass(frozen=True) class TemplateSource: id: str; path: str; source: str; etag: str  # .to_json()
@dataclass(frozen=True) class SavedTemplate: id: str; path: str; etag: str | None; status: str; change_id: str | None  # .to_json() → changeId
def read_source(template_id: str) -> TemplateSource
def save_source(template_id: str, source: str, *, actor: Actor, base_etag: str | None) -> SavedTemplate
def blank_template(name: str) -> str
def create_blank(name: str, *, actor: Actor) -> SavedTemplate
def query_values() -> dict[str, Any]                  # {types: [str], statuses: [str], indexing: bool}
```

HTTP (bearer auth like every route; C1's `_http_error` maps `TemplateNotFound`→404, `TemplateInvalid`→422; B1 maps `WriteConflict`→409 `{detail, currentEtag}`, `InvalidPath`→400):

| Route | Body | 2xx | Errors |
|---|---|---|---|
| `POST /v1/templates/lint` | `{source}` (≤ 256,000 chars) | 200 `{diagnostics: [{line, col, severity, message, code}]}` | 422 oversize |
| `POST /v1/templates/render` | `{source, answers?, id?, dry_run: true}` | 200 `DryRunResult.to_json()` | 422 oversize / `dry_run` not true / bad id |
| `GET /v1/templates/query-values` | — | 200 `{types, statuses, indexing}` | — |
| `GET /v1/templates/{id}/source` | — | 200 `{id, path, source, etag}` | 404 · 422 unreadable |
| `PATCH /v1/templates/{id}/source` | `{source}` + optional `If-Match` | 200 `{id, path, etag, status, changeId}` | 404 · 409 stale · 422 oversize |
| `POST /v1/templates` | `{name}` (1–80 chars, one line) | 201 `{id, path, etag, status, changeId}` | 422 bad name |

```ts
// desktop/src/shared/api-types.ts (Task 5)
export type TemplateRegistry = TemplateFunctionsResponse & { queryKeys?: TemplateFunctionSpec[] };
export interface TemplateLintResponse { diagnostics: TemplateDiagnostic[] }
export interface TemplateSourceResponse { id: string; path: string; source: string; etag: string }
export interface TemplateSaveResponse { id: string; path: string; etag: string | null; status: 'applied' | 'pending'; changeId: string | null }
export interface TemplateQueryValues { types: string[]; statuses: string[]; indexing: boolean }
export interface TemplateDryRunRequest { source: string; answers: Record<string, string>; id?: string; dry_run: true }
export interface TemplateDryRunResponse { ok: boolean; prompts: TemplatePrompt[]; answers: Record<string, string>; rendered: (TemplateRenderResponse & { markdown: string }) | null; wouldBeFiledAt: string | null; diagnostics: TemplateDiagnostic[]; error: string | null }

// desktop/src/renderer/lib/api/template-editor.ts (Task 5)
export function useTemplateFunctions(): UseQueryResult<TemplateRegistry>           // ['templates','functions']
export function useTemplateQueryValues(): UseQueryResult<TemplateQueryValues>      // ['templates','query-values']
export function useTemplateSource(id: string | null): UseQueryResult<TemplateSourceResponse>  // ['templates','source',id]
export function lintTemplate(source: string): Promise<TemplateDiagnostic[]>
export function saveTemplateSource(id: string, source: string, etag: string | null): Promise<TemplateSaveResponse>
export function useCreateBlankTemplate(): UseMutationResult<TemplateSaveResponse, Error, string>
export function useTemplateDryRun(): UseMutationResult<TemplateDryRunResponse, Error, Omit<TemplateDryRunRequest, 'dry_run'>>

// desktop/src/renderer/lib/templates/last-answers.ts (Task 5)
export const LAST_ANSWERS_KEY = 'gb.templates.lastAnswers.v1'; MAX_REMEMBERED_TEMPLATES = 50; MAX_REMEMBERED_PROMPTS = 100; MAX_REMEMBERED_CHARS = 500
export function rememberAnswers(templateId: string, answers: Record<string, string>): void
export function initialAnswers(templateId: string, promptIds: string[]): Record<string, string>

// desktop/src/renderer/lib/template-editor/analyze.ts (Task 6)
export interface PromptInfo { id: string; type: string }
export interface FrontmatterRange { innerStart: number; innerEnd: number; bodyStart: number }
export type CursorContext =
  | { kind: 'variable'; from: number; prefix: string }
  | { kind: 'field'; from: number; prefix: string; ownerPath: string[] }
  | { kind: 'filter'; from: number; prefix: string }
  | { kind: 'prompt-type'; from: number; prefix: string }
  | { kind: 'query-key'; from: number; prefix: string }
  | { kind: 'query-value'; from: number; prefix: string; key: string };
export function frontmatterRange(text: string): FrontmatterRange | null
export function promptsSection(text: string): { start: number; end: number } | null
export function extractPrompts(text: string): PromptInfo[]
export function inQueryFence(text: string, pos: number): boolean
export function cursorContext(text: string, pos: number): CursorContext | null

// desktop/src/renderer/lib/template-editor/completions.ts (Task 7)
export interface QueryValueHints { types: string[]; statuses: string[]; contexts: string[] }
export interface TemplateEditorData { registry: TemplateRegistry | null; hints: QueryValueHints }
export const EMPTY_HINTS: QueryValueHints; export const SORT_VALUES: string[]
export function specInfo(spec: TemplateFunctionSpec): string
export function valueTypeOf(path: string[], prompts: PromptInfo[], reg: TemplateRegistry): string | null
export function optionsFor(cur: CursorContext, text: string, reg: TemplateRegistry, hints: QueryValueHints): Completion[]
export function templateCompletions(getData: () => TemplateEditorData): CompletionSource

// desktop/src/renderer/lib/template-editor/hover.ts, lint.ts, extensions.ts (Task 8)
export interface HoverHit { from: number; to: number; title: string; info: string }
export function hoverAt(text: string, pos: number, reg: TemplateRegistry): HoverHit | null
export function hoverDom(h: HoverHit): HTMLElement
export function templateHover(getData: () => TemplateEditorData): Extension
export const TEMPLATE_LINT_DELAY_MS = 500
export type FetchLint = (source: string) => Promise<TemplateDiagnostic[]>
export function toCmDiagnostics(doc: Text, diags: TemplateDiagnostic[]): Diagnostic[]
export function templateLintSource(fetchLint: FetchLint): (view: Pick<EditorView, 'state'>) => Promise<Diagnostic[]>
export function templateLinter(fetchLint: FetchLint): Extension
export function templateEditorExtensions(getData: () => TemplateEditorData, fetchLint: FetchLint): Extension[]

// components (Tasks 9–11)
export function TemplateTestRun(props: { templateId: string; source: string }): JSX.Element
export const DISCARD_TEMPLATE_PROMPT: string
export function TemplateSourceEditor(props: { templateId: string; onDirtyChange?: (dirty: boolean) => void; onCreateEditor?: (view: EditorView) => void }): JSX.Element
export function TemplatesPanel(props: { onBack: () => void }): JSX.Element   // screens/templates.tsx
```

---

## File Structure

Backend (new):
- `ghostbrain/templates/lint.py`: parse diagnostics + registry checks of placeholders + C2 query-fence checks.
- `ghostbrain/templates/testrun.py`: render source with sample answers, would-be path, no writes.
- `ghostbrain/templates/source.py`: read with etag, save through the write path, blank create, query value hints.

Backend (modify):
- `ghostbrain/api/routes/templates.py`: six editor routes (imports at the top, routes appended).
- `.github/workflows/ci.yml`: three new test files.

Backend tests (new): `tests/test_templates_lint.py`, `tests/test_templates_testrun.py`, `tests/test_templates_source.py`, `ghostbrain/api/tests/test_templates_editor_routes.py`.

Desktop (new):
- `desktop/src/renderer/lib/api/template-editor.ts`: editor queries and calls.
- `desktop/src/renderer/lib/templates/last-answers.ts`: remembered answers.
- `desktop/src/renderer/lib/template-editor/analyze.ts`, `completions.ts`, `hover.ts`, `lint.ts`, `extensions.ts`.
- `desktop/src/renderer/components/TemplateTestRun.tsx`, `TemplateSourceEditor.tsx`.
- `desktop/src/renderer/screens/templates.tsx` (`TemplatesPanel`).
- Tests: `template-editor-hooks.test.tsx`, `template-editor-analyze.test.ts`, `template-editor-completions.test.ts`, `template-editor-hover-lint.test.ts`, `TemplateTestRun.test.tsx`, `TemplateSourceEditor.test.tsx`, `TemplatesPanel.test.tsx`, helpers `__tests__/helpers/template-registry.ts` and `__tests__/helpers/memory-storage.ts`.

Desktop (modify):
- `desktop/package.json`, `desktop/package-lock.json`: four exact pins.
- `desktop/src/shared/api-types.ts`: append the C3 types.
- `desktop/src/renderer/lib/api/hooks.ts`: `useCreateFromTemplate` remembers answers.
- `desktop/src/renderer/screens/jots.tsx`: the Templates tab.
- `desktop/src/renderer/__tests__/jots.test.tsx`: append one test.

---

### Task 1: Template linter (`lint.py`)

**Files:**
- Create: `ghostbrain/templates/lint.py`
- Test: `tests/test_templates_lint.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: C1 `parse_template`, `Diagnostic`, `Template` (`body`, `body_line`, `prompts`) from `ghostbrain.templates.parse`; `tokenize`, `Placeholder`, `TemplateLimitError` from `ghostbrain.templates.lang`; `find_spec`, `FIELDS`, `FILTERS`, `VARIABLES`, `PROMPT_VALUE_TYPES` from `ghostbrain.templates.functions`. C2 (optional) `parse_query_block(text) -> (Query | None, list[Diagnostic])` from `ghostbrain.templates.query`.
- Produces: `lint(source, template_id="draft") -> list[Diagnostic]`, `query_parser()`, `MAX_LINT_DIAGNOSTICS`. Tasks 2 and 4 call `lint`.

- [ ] **Step 1: Write the failing tests**

`tests/test_templates_lint.py`:

```python
"""lint(): parse diagnostics plus registry checks of every placeholder."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ghostbrain.templates import lint as lint_mod
from ghostbrain.templates.lint import MAX_LINT_DIAGNOSTICS, lint
from ghostbrain.templates.parse import Diagnostic, parse_template
from ghostbrain.templates.render import RenderEnv, render
from ghostbrain.templates.starters import STARTER_TEMPLATES
from ghostbrain.templates.values import ProjectValue

HEAD = """---
template:
  name: T
  prompts:
    - id: person
      ask: Who?
      type: person
    - id: topic
      ask: What?
      type: text
    - id: when
      ask: When?
      type: date
      optional: true
---
"""
BODY_LINE = 16
ENV = RenderEnv(
    now=datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2))),
    default_context="work",
    contexts=("work",),
    projects={"work/alpha": ProjectValue("work/alpha", "Alpha", "alpha", "work")},
    user_name="Sam",
)
ANSWERS = {"person": "Alex", "topic": "Planning"}


def found(src: str) -> list[tuple[int, int, str, str]]:
    return [(d.line, d.col, d.severity, d.code) for d in lint(src, "t")]


@pytest.fixture
def no_query_parser(monkeypatch):
    monkeypatch.setattr(lint_mod, "query_parser", lambda: None)


def test_starter_templates_lint_clean():
    for name, src in STARTER_TEMPLATES.items():
        assert lint(src, name.removesuffix(".md")) == [], name


def test_known_names_fields_and_filters_are_clean():
    src = HEAD + (
        "{{person.link}} {{topic | upper}} {{date | format: D MMM}} {{now.date.iso}}\n"
        "{{user.name}} {{title}} {{project.name | default: none}} {{when.iso}} {{time}}\n"
    )
    assert lint(src, "t") == []


def test_unknown_name_is_a_warning_at_its_position_with_a_suggestion():
    src = HEAD + "line one\n  {{persn.name}}\n"
    [d] = lint(src, "t")
    assert (d.line, d.col, d.severity, d.code) == (BODY_LINE + 1, 3, "warning", "unknown-name")
    assert "`persn`" in d.message and "did you mean `person`?" in d.message


def test_unknown_field_lists_the_fields_of_the_owner():
    [d] = lint(HEAD + "{{person.email}}\n", "t")
    assert d.code == "unknown-field"
    assert "`person` has no field `email`; fields: link, name, path" in d.message


def test_field_of_a_text_value():
    [d] = lint(HEAD + "{{topic.name}}\n", "t")
    assert (d.code, d.message) == ("unknown-field", "`topic` has no fields")


def test_nested_field_owner_is_named_by_its_path():
    [d] = lint(HEAD + "{{now.date.year}}\n", "t")
    assert "`now.date` has no field `year`; fields: iso" in d.message


def test_filter_problems():
    src = HEAD + "{{topic | shout}}\n{{date | format}}\n{{topic | upper: x}}\n"
    assert found(src) == [
        (BODY_LINE, 1, "warning", "unknown-filter"),
        (BODY_LINE + 1, 1, "warning", "filter-arg"),
        (BODY_LINE + 2, 1, "warning", "filter-arg"),
    ]
    msgs = [d.message for d in lint(src, "t")]
    assert msgs[1] == "`format` needs an argument, e.g. {{date | format: D MMM YYYY}}"
    assert msgs[2] == "`upper` takes no argument"


def test_malformed_placeholder_is_flagged():
    [d] = lint(HEAD + "{{ topic + 1 }}\n", "t")
    assert (d.code, d.severity) == ("malformed", "warning")


def test_frontmatter_placeholders_use_whole_file_positions():
    src = '---\ntemplate:\n  name: T\n  file:\n    name: "{{date | format: YYYY}} {{persn}}"\n---\nbody\n'
    assert found(src) == [(5, 36, "warning", "unknown-name")]


def test_parse_errors_come_back_and_skip_placeholder_checks():
    src = "---\ntemplate:\n  name: [unclosed\n---\n{{nope}}\n"
    diags = lint(src, "t")
    assert diags and all(d.code == "yaml" for d in diags)


def test_crlf_source_keeps_line_numbers():
    src = (HEAD + "x\n{{nope}}\n").replace("\n", "\r\n")
    assert found(src) == [(BODY_LINE + 1, 1, "warning", "unknown-name")]


def test_output_is_capped(no_query_parser):
    src = HEAD + "{{nope}}\n" * (MAX_LINT_DIAGNOSTICS + 5)
    diags = lint(src, "t")
    assert len(diags) == MAX_LINT_DIAGNOSTICS + 1
    assert diags[-1].code == "truncated" and "5 more" in diags[-1].message


@pytest.mark.parametrize(
    "expr",
    [
        "person", "person.link", "person.nope", "topic.name", "nope", "date.iso", "date.nope",
        "now.date.iso", "user.name", "project.slug", "when.iso", "topic | shout",
        "date | format", "topic | upper: x", "topic | default: x", "topic | slug | upper",
        "context.name", "time | lower",
    ],
)
def test_lint_flags_exactly_what_render_leaves_literal(expr, no_query_parser):
    src = HEAD + "{{" + expr + "}}\n"
    flagged = bool(lint(src, "t"))
    note = render(parse_template(src, "t").template, ANSWERS, ENV)
    assert flagged == ("{{" + expr + "}}" in note.body), expr


# ── query blocks (C2) ──────────────────────────────────────────────────────


def _stub_parser(text: str):
    diags = []
    for n, line in enumerate(text.split("\n"), start=1):
        if line.startswith("bogus"):
            diags.append(Diagnostic(n, 1, "error", "unknown key `bogus`", "unknown-key"))
        if "{{" in line:
            diags.append(Diagnostic(n, 11, "error", "placeholder", "unresolved-placeholder"))
    return None, diags


def test_query_block_diagnostics_map_to_file_lines(monkeypatch):
    monkeypatch.setattr(lint_mod, "query_parser", lambda: _stub_parser)
    src = HEAD + "intro\n```query\ntype: action_item\nmentions: \"{{person.link}}\"\nbogus: 1\n```\n"
    assert found(src) == [(BODY_LINE + 4, 1, "error", "unknown-key")]


def test_unclosed_query_fence_is_a_warning(monkeypatch):
    monkeypatch.setattr(lint_mod, "query_parser", lambda: _stub_parser)
    assert found(HEAD + "```query\ntype: x\n") == [(BODY_LINE, 1, "warning", "unclosed-query")]


def test_other_fences_are_not_query_linted(monkeypatch):
    monkeypatch.setattr(lint_mod, "query_parser", lambda: _stub_parser)
    assert found(HEAD + "```text\nbogus: 1\n```\n") == []


def test_query_blocks_are_skipped_without_c2(no_query_parser):
    assert found(HEAD + "```query\nbogus: 1\n```\n") == []


def test_real_query_parser_flags_a_bad_key_in_a_template():
    pytest.importorskip("ghostbrain.templates.query")
    src = HEAD + '```query\ntype: action_item\nmentions: "{{person.link}}"\ncolour: red\n```\n'
    assert [(d.line, d.code) for d in lint(src, "t")] == [(BODY_LINE + 3, "unknown-key")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$C3" && python -m pytest tests/test_templates_lint.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.templates.lint'`.

- [ ] **Step 3: Write the implementation**

`ghostbrain/templates/lint.py`:

```python
"""Template linter (spec C3): parse diagnostics, then a registry check of
every ``{{ placeholder }}`` and every ```query``` block.

The placeholder checks mirror ``render.evaluate`` exactly: anything this
module flags renders as its literal text, and anything it passes renders
(pinned by a parity test). Nothing here evaluates template text.
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterable

from ghostbrain.templates.functions import FIELDS, FILTERS, PROMPT_VALUE_TYPES, VARIABLES, find_spec
from ghostbrain.templates.lang import Placeholder, TemplateLimitError, tokenize
from ghostbrain.templates.parse import Diagnostic, Template, parse_template

MAX_LINT_DIAGNOSTICS = 100
_FENCE_OPEN_RE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*).*")
_FENCE_CLOSE_RE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*")
# The query parser's own complaint about {{ }} in a value: in a template the
# placeholder is filled in at creation, so it is expected there.
_TEMPLATE_ONLY_QUERY_CODES = frozenset({"unresolved-placeholder"})

QueryParser = Callable[[str], "tuple[object, list[Diagnostic]]"]


def query_parser() -> QueryParser | None:
    """C2's ``parse_query_block`` when the branch has it, else None (query
    blocks are then not linted)."""
    try:
        from ghostbrain.templates.query import parse_query_block
    except ImportError:
        return None
    return parse_query_block


def _warn(ph: Placeholder, message: str, code: str) -> Diagnostic:
    return Diagnostic(ph.line, ph.col, "warning", message, code)


def _suggest(name: str, known: Iterable[str]) -> str:
    close = difflib.get_close_matches(name, sorted(set(known)), n=1, cutoff=0.6)
    return f" — did you mean `{close[0]}`?" if close else ""


def _root_type(name: str, prompt_types: dict[str, str]) -> str | None:
    if name in prompt_types:
        return prompt_types[name]
    spec = find_spec("variable", name)
    return spec.type if spec is not None else None


def _check(ph: Placeholder, prompt_types: dict[str, str]) -> Diagnostic | None:
    if ph.path is None:
        return _warn(ph, f"`{ph.raw}` is not a placeholder (a name, optional .fields and "
                         "| filters); it renders as literal text", "malformed")
    root = ph.path[0]
    current = _root_type(root, prompt_types)
    if current is None:
        known = [*prompt_types, *(s.name for s in VARIABLES)]
        return _warn(ph, f"unknown name `{root}`; it renders as literal text{_suggest(root, known)}",
                     "unknown-name")
    owner = root
    for name in ph.path[1:]:
        spec = find_spec("field", name, current)
        if spec is None:
            fields = sorted(s.name for s in FIELDS if s.owner == current)
            if not fields:
                return _warn(ph, f"`{owner}` has no fields", "unknown-field")
            return _warn(ph, f"`{owner}` has no field `{name}`; fields: {', '.join(fields)}"
                             f"{_suggest(name, fields)}", "unknown-field")
        current, owner = spec.type, f"{owner}.{name}"
    for call in ph.filters:
        spec = find_spec("filter", call.name)
        if spec is None:
            known = [s.name for s in FILTERS]
            return _warn(ph, f"unknown filter `{call.name}`{_suggest(call.name, known)}",
                         "unknown-filter")
        if spec.arg_required and call.arg is None:
            return _warn(ph, f"`{call.name}` needs an argument, e.g. {spec.example}", "filter-arg")
        if spec.arg is None and call.arg is not None:
            return _warn(ph, f"`{call.name}` takes no argument", "filter-arg")
    return None


def _placeholder_diagnostics(source: str, template: Template) -> list[Diagnostic]:
    prompt_types = {p.id: PROMPT_VALUE_TYPES[p.type] for p in template.prompts}
    try:
        segments = tokenize(source)
    except TemplateLimitError:
        return []  # parse_template already reported the limit
    out = []
    for seg in segments:
        if isinstance(seg, Placeholder):
            diag = _check(seg, prompt_types)
            if diag is not None:
                out.append(diag)
    return out


def _query_diagnostics(template: Template, parser: QueryParser) -> list[Diagnostic]:
    lines = template.body.split("\n")
    out: list[Diagnostic] = []
    i = 0
    while i < len(lines):
        m = _FENCE_OPEN_RE.fullmatch(lines[i])
        if m is None:
            i += 1
            continue
        fence, is_query = m.group(1), m.group(2).lower() == "query"
        end = i + 1
        while end < len(lines):
            close = _FENCE_CLOSE_RE.fullmatch(lines[end])
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= len(fence):
                break
            end += 1
        fence_line = template.body_line + i
        if is_query:
            if end >= len(lines):
                out.append(Diagnostic(fence_line, 1, "warning",
                                      "this ```query block is never closed", "unclosed-query"))
            else:
                _query, diags = parser("\n".join(lines[i + 1:end]))
                out.extend(
                    Diagnostic(fence_line + d.line, d.col, d.severity, d.message, d.code)
                    for d in diags if d.code not in _TEMPLATE_ONLY_QUERY_CODES
                )
        i = end + 1
    return out


def lint(source: str, template_id: str = "draft") -> list[Diagnostic]:
    """Every problem in ``source``, ordered by position, at most
    MAX_LINT_DIAGNOSTICS (+1 summary). Lines and columns are 1-based, whole file."""
    result = parse_template(source, template_id)
    diags = list(result.diagnostics)
    if result.template is not None:
        diags += _placeholder_diagnostics(source.replace("\r\n", "\n"), result.template)
        parser = query_parser()
        if parser is not None:
            diags += _query_diagnostics(result.template, parser)
    diags.sort(key=lambda d: (d.line, d.col))
    if len(diags) > MAX_LINT_DIAGNOSTICS:
        rest = len(diags) - MAX_LINT_DIAGNOSTICS
        last = diags[MAX_LINT_DIAGNOSTICS]
        diags = [*diags[:MAX_LINT_DIAGNOSTICS],
                 Diagnostic(last.line, last.col, "info", f"…and {rest} more problems", "truncated")]
    return diags
```

In `.github/workflows/ci.yml`, add `tests/test_templates_lint.py \` to the fixed pytest list on the line after `tests/test_templates_create.py \` (the last C1 entry; if C2 added `tests/test_templates_query.py \` after it, go after that one).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$C3" && python -m pytest tests/test_templates_lint.py tests/test_templates_security.py -v`
Expected: PASS. Without C2 on the branch, `test_real_query_parser_flags_a_bad_key_in_a_template` is SKIPPED; with C2 it passes and `test_starter_templates_lint_clean` also runs the starters' query blocks through C2's parser. The static guard in `test_templates_security.py` still passes.

- [ ] **Step 5: Commit**

```bash
cd "$C3"
git add ghostbrain/templates/lint.py tests/test_templates_lint.py .github/workflows/ci.yml
git commit -m "feat(templates): registry-driven template linter with query-block checks"
```

---

### Task 2: Test run (`testrun.py`)

**Files:**
- Create: `ghostbrain/templates/testrun.py`
- Test: `tests/test_templates_testrun.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 `lint`; C1 `parse_template`, `SHADOWABLE`, `Prompt`, `Template`; `render`, `RenderEnv`, `RenderedNote` (`path`, `markdown()`), `AnswerError` (`.field`), `RenderError` from `ghostbrain.templates.render`; `build_env()` from `ghostbrain.templates.env` (imported lazily, only when no env is passed); B1 `vault_write.resolve_safe`, `vault_write.InvalidPath`.
- Produces: `dry_run(...) -> DryRunResult`, `sample_answers`, `would_be_path`, `SAMPLE_PERSON`. Task 4's `POST /v1/templates/render` returns `dry_run(...).to_json()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_templates_testrun.py`:

```python
"""dry_run(): render template source with sample answers; never write."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ghostbrain.templates.render import RenderEnv
from ghostbrain.templates.starters import ONE_ON_ONE
from ghostbrain.templates.testrun import SAMPLE_PERSON, dry_run, would_be_path
from ghostbrain.templates.values import ProjectValue

ENV = RenderEnv(
    now=datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2))),
    default_context="work",
    contexts=("work", "personal"),
    projects={"work/alpha": ProjectValue("work/alpha", "Alpha", "alpha", "work")},
    user_name="Sam",
)
CHOICE = """---
template:
  name: Review
  prompts:
    - id: kind
      ask: Kind?
      type: choice
      options: [weekly, monthly]
    - id: proj
      ask: Project?
      type: project
    - id: note
      ask: Note?
      type: text
    - id: extra
      ask: Extra?
      type: text
      optional: true
  file:
    folder: "20-contexts/{{context}}/reviews"
    name: "{{date | format: YYYY-MM-DD}} {{kind}} review"
---
# {{kind}} for {{proj.name}}: {{note}} {{extra | default: none}}
"""


@pytest.fixture
def vault(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(root))
    return root


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def test_renders_one_on_one_with_a_sample_person_and_writes_nothing(vault):
    before = _files(vault)
    res = dry_run(ONE_ON_ONE, {}, template_id="one-on-one", env=ENV)
    assert res.ok and res.error is None
    assert res.answers == {"person": SAMPLE_PERSON}
    assert res.would_be_filed_at == "20-contexts/work/one-on-ones/2026-10-09-sample-person-1-1.md"
    assert res.note.body.startswith("# 1-1 with [[Sample Person]] — 9 Oct 2026\n")
    assert 'mentions: "[[Sample Person]]"' in res.note.body
    assert _files(vault) == before


def test_given_answers_win_and_stale_keys_are_dropped(vault):
    res = dry_run(ONE_ON_ONE, {"person": "Alex", "gone": "x", "focus": " "}, env=ENV)
    assert res.answers == {"person": "Alex"}
    assert "# 1-1 with [[Alex]]" in res.note.body


def test_samples_by_prompt_type(vault):
    res = dry_run(CHOICE, {}, env=ENV)
    assert res.ok, res.error
    assert res.answers == {"kind": "weekly", "proj": "work/alpha", "note": "[note]"}
    assert res.note.body == "# weekly for Alpha: [note] none\n"
    assert [p.id for p in res.prompts] == ["kind", "proj", "note", "extra"]


def test_would_be_path_skips_taken_names(vault):
    folder = vault / "20-contexts/work/one-on-ones"
    folder.mkdir(parents=True)
    (folder / "2026-10-09-alex-1-1.md").write_text("x", encoding="utf-8")
    (folder / "2026-10-09-alex-1-1-2.md").write_text("x", encoding="utf-8")
    res = dry_run(ONE_ON_ONE, {"person": "Alex"}, env=ENV)
    assert res.would_be_filed_at == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1-3.md"
    assert would_be_path("20-contexts/work/new.md") == "20-contexts/work/new.md"


def test_broken_source_reports_the_first_error(vault):
    res = dry_run("---\ntemplate:\n  name: [x\n---\n", {}, env=ENV)
    assert not res.ok and res.note is None
    assert res.error.startswith("template has errors: line 4: frontmatter is not valid YAML")
    assert res.diagnostics and res.prompts == ()


def test_bad_answer_is_reported_inline(vault):
    res = dry_run(CHOICE, {"kind": "daily"}, env=ENV)
    assert not res.ok and res.error == "kind: pick one of: weekly, monthly"
    assert [p.id for p in res.prompts] == ["kind", "proj", "note", "extra"]


def test_escaping_folder_is_reported_and_nothing_written(vault):
    src = '---\ntemplate:\n  name: Evil\n  file:\n    folder: "../../outside"\n---\nx\n'
    before = _files(vault.parent)
    res = dry_run(src, {}, env=ENV)
    assert not res.ok and "not allowed" in res.error
    assert _files(vault.parent) == before


def test_symlinked_folder_out_of_the_vault_is_reported(vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "20-contexts").mkdir()
    try:
        (vault / "20-contexts" / "work").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    res = dry_run(ONE_ON_ONE, {"person": "Alex"}, env=ENV)
    assert not res.ok and "escapes the vault" in res.error


def test_json_shape(vault):
    data = dry_run(ONE_ON_ONE, {"person": "Alex"}, env=ENV).to_json()
    assert set(data) == {"ok", "prompts", "answers", "rendered", "wouldBeFiledAt", "diagnostics", "error"}
    assert set(data["rendered"]) == {"path", "folder", "filename", "title", "frontmatter", "body", "markdown"}
    assert data["rendered"]["markdown"].startswith("---\ntitle: 2026-10-09 Alex 1-1\n")
    assert data["prompts"][0] == {"id": "person", "ask": "Who's this 1-1 with?", "type": "person",
                                  "optional": False, "default": None, "options": []}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$C3" && python -m pytest tests/test_templates_testrun.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.templates.testrun'`.

- [ ] **Step 3: Write the implementation**

`ghostbrain/templates/testrun.py`:

```python
"""Test run (spec C3): render a template's *source* with sample answers and
report where the note would be filed. Nothing is written, ever."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from ghostbrain import vault_write
from ghostbrain.templates.lint import lint
from ghostbrain.templates.parse import SHADOWABLE, Diagnostic, Prompt, Template, parse_template
from ghostbrain.templates.render import AnswerError, RenderedNote, RenderEnv, RenderError, render

SAMPLE_PERSON = "Sample Person"
MAX_NAME_ATTEMPTS = 100


def _sample_for(prompt: Prompt, env: RenderEnv) -> str:
    if prompt.type == "choice":
        return prompt.options[0]
    if prompt.type == "date":
        return env.now.date().isoformat()
    if prompt.type == "context":
        return env.default_context
    if prompt.type == "project":
        return next(iter(env.projects), "")
    if prompt.type == "person":
        return SAMPLE_PERSON
    return f"[{prompt.id}]"


def sample_answers(template: Template, answers: Mapping[str, Any], env: RenderEnv) -> dict[str, str]:
    """The caller's answers for this template's prompts (stale keys from an
    older version of the template are dropped), plus a sample for every
    required prompt left blank. Optional or defaulted prompts stay blank so
    the renderer applies their default."""
    ids = {p.id for p in template.prompts} | set(SHADOWABLE)
    out = {k: v for k, v in answers.items() if k in ids and isinstance(v, str) and v.strip()}
    for p in template.prompts:
        if p.id not in out and p.default is None and not p.optional:
            out[p.id] = _sample_for(p, env)
    return out


def would_be_path(rel_path: str) -> str:
    """The path ``vault_write.write_new`` would pick right now: ``rel_path``,
    else ``<stem>-2``, ``-3``, … Raises InvalidPath for a path outside the vault."""
    p = PurePosixPath(rel_path)
    for n in range(1, MAX_NAME_ATTEMPTS + 1):
        candidate = rel_path if n == 1 else str(p.with_name(f"{p.stem}-{n}{p.suffix}"))
        if not vault_write.resolve_safe(candidate).exists():
            return candidate
    raise RenderError(f"no free file name near {rel_path}")


@dataclass(frozen=True)
class DryRunResult:
    prompts: tuple[Prompt, ...]
    answers: dict[str, str]
    note: RenderedNote | None
    would_be_filed_at: str | None
    diagnostics: tuple[Diagnostic, ...]
    error: str | None

    @property
    def ok(self) -> bool:
        return self.note is not None and self.error is None

    def to_json(self) -> dict[str, Any]:
        n = self.note
        return {
            "ok": self.ok,
            "prompts": [p.to_json() for p in self.prompts],
            "answers": self.answers,
            "rendered": None if n is None else {
                "path": n.path, "folder": n.folder, "filename": n.filename, "title": n.title,
                "frontmatter": n.frontmatter, "body": n.body, "markdown": n.markdown(),
            },
            "wouldBeFiledAt": self.would_be_filed_at,
            "diagnostics": [d.to_json() for d in self.diagnostics],
            "error": self.error,
        }


def dry_run(
    source: str,
    answers: Mapping[str, Any],
    *,
    template_id: str = "draft",
    env: RenderEnv | None = None,
) -> DryRunResult:
    diagnostics = tuple(lint(source, template_id))
    parsed = parse_template(source, template_id)
    if parsed.template is None:
        first = next((d for d in parsed.diagnostics if d.severity == "error"), None)
        message = f"line {first.line}: {first.message}" if first else "the template has errors"
        return DryRunResult((), {}, None, None, diagnostics, f"template has errors: {message}")
    template = parsed.template
    if env is None:
        from ghostbrain.templates.env import build_env

        env = build_env()
    used = sample_answers(template, answers, env)
    try:
        note = render(template, used, env)
        target = would_be_path(note.path)
    except AnswerError as e:
        return DryRunResult(template.prompts, used, None, None, diagnostics, f"{e.field}: {e}")
    except (RenderError, vault_write.InvalidPath) as e:
        return DryRunResult(template.prompts, used, None, None, diagnostics, str(e))
    return DryRunResult(template.prompts, used, note, target, diagnostics, None)
```

In `.github/workflows/ci.yml`, add `tests/test_templates_testrun.py \` after `tests/test_templates_lint.py \`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$C3" && python -m pytest tests/test_templates_testrun.py tests/test_templates_security.py -v`
Expected: PASS (`test_symlinked_folder_out_of_the_vault_is_reported` is skipped only where symlinks are unavailable).

- [ ] **Step 5: Commit**

```bash
cd "$C3"
git add ghostbrain/templates/testrun.py tests/test_templates_testrun.py .github/workflows/ci.yml
git commit -m "feat(templates): test run renders template source with sample answers, writes nothing"
```

---

### Task 3: Template source, blank templates and query hints (`source.py`)

**Files:**
- Create: `ghostbrain/templates/source.py`
- Test: `tests/test_templates_source.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: C1 `read_template_source` (`TemplateNotFound` for unknown, symlinked or badly named ids; `TemplateInvalid` for unreadable files), `TEMPLATES_REL`, `seed_starter_templates`, `slugify`, `MAX_TEMPLATE_CHARS`; B1 `vault_write.write`, `write_new`, `compute_etag`, `Actor`, `WriteConflict`; A2 `get_link_index()` (`ready`, `ensure_fresh`, `entries()`, `wait_until_ready`; `NoteEntry.type`, `.artifact_type`, `.status`).
- Produces: `read_source`, `save_source`, `blank_template`, `create_blank`, `query_values`, `SourceTooLarge`, `TemplateSource`, `SavedTemplate`, `MAX_NAME_CHARS`. Task 4 wraps them in routes.

- [ ] **Step 1: Write the failing tests**

`tests/test_templates_source.py`:

```python
"""Template source: read with etag, save via the write path, blank create, query hints."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.templates.parse import parse_template
from ghostbrain.templates.registry import TemplateNotFound, list_templates
from ghostbrain.templates.source import (
    SourceTooLarge,
    blank_template,
    create_blank,
    query_values,
    read_source,
    save_source,
)
from ghostbrain.vault_write import USER, WriteConflict

OK = "---\ntemplate:\n  name: Weekly review\n---\n# Week {{date | format: D MMM}}\n"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "vault"
    (root / "90-meta/templates").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(root))
    return root


def _put(vault: Path, name: str, text: str) -> Path:
    p = vault / "90-meta/templates" / name
    p.write_text(text, encoding="utf-8")
    return p


def test_read_source_returns_text_and_the_write_path_etag(vault):
    _put(vault, "weekly.md", OK)
    src = read_source("weekly")
    assert (src.id, src.path, src.source) == ("weekly", "90-meta/templates/weekly.md", OK)
    assert src.etag == vault_write.current_etag("90-meta/templates/weekly.md")
    assert src.to_json() == {"id": "weekly", "path": src.path, "source": OK, "etag": src.etag}


def test_read_source_refuses_symlinks_and_bad_ids(vault, tmp_path):
    outside = tmp_path / "secret.md"
    outside.write_text(OK, encoding="utf-8")
    try:
        (vault / "90-meta/templates/link.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    for tid in ("link", "../secret", "Weekly", "missing"):
        with pytest.raises(TemplateNotFound):
            read_source(tid)


def test_save_replaces_the_file_with_the_matching_etag(vault):
    _put(vault, "weekly.md", OK)
    etag = read_source("weekly").etag
    new = OK.replace("Week", "Week of")
    res = save_source("weekly", new, actor=USER, base_etag=etag)
    assert res.status == "applied" and res.etag == read_source("weekly").etag
    assert (vault / "90-meta/templates/weekly.md").read_text(encoding="utf-8") == new
    assert res.to_json()["changeId"] is None


def test_save_with_a_stale_etag_conflicts_and_writes_nothing(vault):
    _put(vault, "weekly.md", OK)
    with pytest.raises(WriteConflict):
        save_source("weekly", "changed\n", actor=USER, base_etag="0000000000000000")
    assert (vault / "90-meta/templates/weekly.md").read_text(encoding="utf-8") == OK


def test_save_keeps_a_broken_template_so_it_can_be_fixed(vault):
    _put(vault, "weekly.md", OK)
    broken = "---\ntemplate:\n  name: [x\n---\n"
    save_source("weekly", broken, actor=USER, base_etag=None)
    [info] = [i for i in list_templates() if i.id == "weekly"]
    assert not info.valid


def test_save_refuses_unknown_ids_and_oversize_source(vault):
    with pytest.raises(TemplateNotFound):
        save_source("nope", OK, actor=USER, base_etag=None)
    _put(vault, "weekly.md", OK)
    with pytest.raises(SourceTooLarge):
        save_source("weekly", "x" * 256_001, actor=USER, base_etag=None)


def test_blank_template_parses_and_quotes_the_name():
    for name in ("Weekly review", 'Say "hi": now', "Ünïcödé ✓", "1-1"):
        result = parse_template(blank_template(name), "x")
        assert result.ok, result.diagnostics
        assert result.template.name == name
        assert result.diagnostics == ()


def test_create_blank_slugs_the_id_and_never_overwrites(vault):
    first = create_blank("Weekly Review", actor=USER)
    second = create_blank("Weekly review", actor=USER)
    assert (first.id, first.path) == ("weekly-review", "90-meta/templates/weekly-review.md")
    assert second.id == "weekly-review-2"
    assert parse_template(read_source("weekly-review").source, "weekly-review").ok


def test_create_blank_seeds_the_starters_when_the_folder_is_missing(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(root))
    create_blank("Retro", actor=USER)
    ids = sorted(i.id for i in list_templates())
    assert ids == ["decision-record", "meeting-notes", "one-on-one", "retro"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 81, "two\nlines"])
def test_create_blank_rejects_bad_names(vault, name):
    with pytest.raises(ValueError):
        create_blank(name, actor=USER)


def _note(vault: Path, rel: str, fm: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{fm}\n---\nbody\n", encoding="utf-8")


def test_query_values_ranks_types_and_statuses_from_the_index(vault):
    from ghostbrain.vault_index.links import get_link_index

    _note(vault, "20-contexts/work/a.md", "type: action_item\nstatus: Done")
    _note(vault, "20-contexts/work/b.md", "artifactType: action_item")
    _note(vault, "20-contexts/work/c.md", "type: decision\nstatus: open")
    _note(vault, "20-contexts/work/d.md", "type: meeting")
    assert query_values()["indexing"] is True  # cold: starts the build
    assert get_link_index().wait_until_ready(5.0)
    data = query_values()
    assert data["indexing"] is False
    assert data["types"][0] == "action_item" and set(data["types"]) == {"action_item", "decision", "meeting"}
    assert sorted(data["statuses"]) == ["done", "open"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$C3" && python -m pytest tests/test_templates_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.templates.source'`.

- [ ] **Step 3: Write the implementation**

`ghostbrain/templates/source.py`:

```python
"""Template files as editable source (spec C3, template editor): read with
an etag, save through the B1 write path, start a blank template, and the
value hints the editor's query completions offer."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from ghostbrain import vault_write
from ghostbrain.paths import vault_path
from ghostbrain.templates.lang import MAX_TEMPLATE_CHARS
from ghostbrain.templates.registry import read_template_source
from ghostbrain.templates.starters import TEMPLATES_REL, seed_starter_templates
from ghostbrain.templates.values import slugify
from ghostbrain.vault_write import Actor

MAX_NAME_CHARS = 80
NEW_ID_MAX = 60  # leaves room for write_new's "-NN" suffix inside TEMPLATE_ID_RE's 64
MAX_HINTS = 30
_BAD_NAME_RE = re.compile(r"[\x00-\x1f\x7f\x85  ]")

BLANK_TEMPLATE = """---
template:
  name: {name}
  description: ""
  prompts:
    - id: topic
      ask: "What is this note about?"
      type: text
  file:
    folder: "20-contexts/{{{{context}}}}/notes"
    name: "{{{{date | format: YYYY-MM-DD}}}} {{{{topic}}}}"
---
# {{{{topic}}}}

"""


class SourceTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class TemplateSource:
    id: str
    path: str
    source: str
    etag: str

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "path": self.path, "source": self.source, "etag": self.etag}


@dataclass(frozen=True)
class SavedTemplate:
    id: str
    path: str
    etag: str | None
    status: str
    change_id: str | None

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "path": self.path, "etag": self.etag, "status": self.status,
                "changeId": self.change_id}


def _rel(template_id: str) -> str:
    return f"{TEMPLATES_REL}/{template_id}.md"


def read_source(template_id: str) -> TemplateSource:
    """Raises TemplateNotFound, or TemplateInvalid (read/limit/encoding)."""
    source = read_template_source(template_id)
    etag = vault_write.compute_etag(source.encode("utf-8"))
    return TemplateSource(template_id, _rel(template_id), source, etag)


def save_source(template_id: str, source: str, *, actor: Actor, base_etag: str | None) -> SavedTemplate:
    """Replace an existing template file. A template with errors may be
    saved (that is how it gets fixed); the list shows it with ⚠."""
    read_template_source(template_id)  # exists, is a plain file, not a symlink
    if len(source) > MAX_TEMPLATE_CHARS:
        raise SourceTooLarge(f"template is larger than {MAX_TEMPLATE_CHARS} characters")
    res = vault_write.write(_rel(template_id), content=source, actor=actor, base_etag=base_etag,
                            reason=f"edit template {template_id}")
    return SavedTemplate(template_id, res.path, res.etag, res.status, res.change_id)


def blank_template(name: str) -> str:
    # json.dumps is a valid YAML double-quoted scalar (ASCII-escaped).
    return BLANK_TEMPLATE.format(name=json.dumps(name))


def create_blank(name: str, *, actor: Actor) -> SavedTemplate:
    bad = bool(_BAD_NAME_RE.search(name))
    name = " ".join(name.split())
    if bad or not name or len(name) > MAX_NAME_CHARS:
        raise ValueError(f"a template name is 1-{MAX_NAME_CHARS} characters on one line")
    # Creating the folder ourselves would stop the starters from ever seeding.
    seed_starter_templates(vault_path())
    stem = slugify(name, NEW_ID_MAX)
    res = vault_write.write_new(_rel(stem), blank_template(name), actor=actor,
                                reason=f"new template {name}")
    return SavedTemplate(PurePosixPath(res.path).stem, res.path, res.etag, res.status, res.change_id)


def query_values() -> dict[str, Any]:
    """Known values for query completions, from A2's link index: the most
    common note types and statuses. Empty while the index is cold."""
    from ghostbrain.vault_index.links import get_link_index

    index = get_link_index()
    if not index.ready:
        index.ensure_fresh(wait=0)
        return {"types": [], "statuses": [], "indexing": True}
    types: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    for entry in index.entries():
        kind = entry.artifact_type or entry.type
        if kind:
            types[kind] += 1
        if entry.status:
            statuses[entry.status.strip().lower()] += 1
    return {
        "types": [k for k, _ in types.most_common(MAX_HINTS)],
        "statuses": [k for k, _ in statuses.most_common(MAX_HINTS)],
        "indexing": False,
    }
```

`read_source` hashes the decoded text re-encoded as UTF-8. That equals the file's bytes for every file `read_template_source` accepts (strict UTF-8; a BOM survives as U+FEFF), so the etag matches `vault_write.current_etag` and the next save's `If-Match` check.

In `.github/workflows/ci.yml`, add `tests/test_templates_source.py \` after `tests/test_templates_testrun.py \`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$C3" && python -m pytest tests/test_templates_source.py tests/test_templates_registry.py tests/test_templates_security.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$C3"
git add ghostbrain/templates/source.py tests/test_templates_source.py .github/workflows/ci.yml
git commit -m "feat(templates): template source read/save via the write path, blank templates, query hints"
```

---

### Task 4: Editor routes

**Files:**
- Modify: `ghostbrain/api/routes/templates.py`
- Test: `ghostbrain/api/tests/test_templates_editor_routes.py`

**Interfaces:**
- Consumes: Tasks 1–3; C1's `router`, `_http_error`, `TemplateNotFound`, `TemplateInvalid`; B1's `if_match` dependency (`ghostbrain/api/vault_http.py`); B2's `request_actor` dependency when present.
- Produces: the six routes in the HTTP table above. Task 5's client calls them.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_templates_editor_routes.py`:

```python
"""/v1/templates editor routes (C3): lint, Test run, source read/save, new, query values."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ghostbrain.templates.starters import ONE_ON_ONE

NOW = datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2)))
REL = "90-meta/templates/one-on-one.md"


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr("ghostbrain.templates.env._now", lambda: NOW)


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def _seed(client, auth_headers) -> None:
    assert client.get("/v1/templates", headers=auth_headers).status_code == 200


def test_lint_returns_positioned_diagnostics(client, auth_headers):
    src = "---\ntemplate:\n  name: T\n---\n# {{persn}}\n"
    r = client.post("/v1/templates/lint", headers=auth_headers, json={"source": src})
    assert r.status_code == 200
    [d] = r.json()["diagnostics"]
    assert (d["line"], d["col"], d["severity"], d["code"]) == (5, 3, "warning", "unknown-name")


def test_lint_rejects_oversize_source(client, auth_headers):
    r = client.post("/v1/templates/lint", headers=auth_headers, json={"source": "x" * 256_001})
    assert r.status_code == 422


def test_test_run_renders_and_writes_nothing(client, auth_headers, tmp_vault):
    _seed(client, auth_headers)
    before = _files(tmp_vault)
    r = client.post("/v1/templates/render", headers=auth_headers,
                    json={"source": ONE_ON_ONE, "answers": {"person": "Alex"}, "id": "one-on-one",
                          "dry_run": True})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True and data["error"] is None
    assert data["wouldBeFiledAt"] == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md"
    assert data["rendered"]["title"] == "2026-10-09 Alex 1-1"
    assert data["rendered"]["frontmatter"]["fromTemplate"] == "one-on-one"
    assert [p["id"] for p in data["prompts"]] == ["person", "focus"]
    assert _files(tmp_vault) == before


def test_test_run_of_broken_source_is_200_with_the_error(client, auth_headers):
    r = client.post("/v1/templates/render", headers=auth_headers,
                    json={"source": "---\ntemplate:\n  name: [x\n---\n", "answers": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False and data["rendered"] is None
    assert data["error"].startswith("template has errors: line 4")


def test_test_run_requires_dry_run_true(client, auth_headers):
    r = client.post("/v1/templates/render", headers=auth_headers,
                    json={"source": ONE_ON_ONE, "answers": {}, "dry_run": False})
    assert r.status_code == 422


def test_source_round_trip_with_etag(client, auth_headers, tmp_vault):
    _seed(client, auth_headers)
    got = client.get("/v1/templates/one-on-one/source", headers=auth_headers)
    assert got.status_code == 200
    body = got.json()
    assert body["path"] == REL and body["source"] == ONE_ON_ONE and body["etag"]
    new = ONE_ON_ONE.replace("# 1-1 with", "# Weekly 1-1 with")
    r = client.patch("/v1/templates/one-on-one/source", headers={**auth_headers, "If-Match": body["etag"]},
                     json={"source": new})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["status"] == "applied" and saved["etag"] != body["etag"]
    assert (tmp_vault / REL).read_text(encoding="utf-8") == new


def test_save_with_a_stale_etag_is_409_and_writes_nothing(client, auth_headers, tmp_vault):
    _seed(client, auth_headers)
    r = client.patch("/v1/templates/one-on-one/source",
                     headers={**auth_headers, "If-Match": "0000000000000000"}, json={"source": "x\n"})
    assert r.status_code == 409 and r.json()["currentEtag"]
    assert (tmp_vault / REL).read_text(encoding="utf-8") == ONE_ON_ONE


@pytest.mark.parametrize("tid", ["nope", "..secret", "UPPER"])
def test_unknown_template_source_is_404(client, auth_headers, tmp_vault, tid):
    _seed(client, auth_headers)
    assert client.get(f"/v1/templates/{tid}/source", headers=auth_headers).status_code == 404
    r = client.patch(f"/v1/templates/{tid}/source", headers=auth_headers, json={"source": "x"})
    assert r.status_code == 404


def test_new_blank_template_is_listed(client, auth_headers, tmp_vault):
    r = client.post("/v1/templates", headers=auth_headers, json={"name": "Weekly review"})
    assert r.status_code == 201, r.text
    assert r.json()["id"] == "weekly-review" and r.json()["status"] == "applied"
    names = [t["name"] for t in client.get("/v1/templates", headers=auth_headers).json()["templates"]]
    assert "Weekly review" in names and "1-1" in names


def test_new_template_rejects_a_bad_name(client, auth_headers):
    assert client.post("/v1/templates", headers=auth_headers, json={"name": ""}).status_code == 422
    r = client.post("/v1/templates", headers=auth_headers, json={"name": "a\nb"})
    assert r.status_code == 422


def test_query_values_shape(client, auth_headers):
    data = client.get("/v1/templates/query-values", headers=auth_headers).json()
    assert set(data) == {"types", "statuses", "indexing"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$C3" && python -m pytest ghostbrain/api/tests/test_templates_editor_routes.py -v`
Expected: FAIL. `/v1/templates/lint`, `/source` and `/query-values` return 404 or 405, and `POST /v1/templates` returns 405.

- [ ] **Step 3: Write the implementation**

In `ghostbrain/api/routes/templates.py`, extend the module docstring by adding these lines before its closing `"""`:

```text

Slice C3 (template editor):
POST  /v1/templates/lint            diagnostics for template source
POST  /v1/templates/render          Test run: render source with sample answers, write nothing
GET   /v1/templates/query-values    known note types and statuses for query completions
GET   /v1/templates/{id}/source     the file's text and etag
PATCH /v1/templates/{id}/source     save (If-Match), through the write path
POST  /v1/templates                 new blank template
```

Replace the import block (everything from `from typing import Any` through `from ghostbrain.templates.render import AnswerError, RenderError`) with:

```python
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ghostbrain.api.vault_http import if_match
from ghostbrain.templates.create import create_from_template, preview_from_template
from ghostbrain.templates.functions import registry_json
from ghostbrain.templates.lang import MAX_TEMPLATE_CHARS
from ghostbrain.templates.lint import lint
from ghostbrain.templates.registry import TemplateInvalid, TemplateNotFound, list_templates
from ghostbrain.templates.render import AnswerError, RenderError
from ghostbrain.templates.source import (
    MAX_NAME_CHARS,
    SourceTooLarge,
    create_blank,
    query_values,
    read_source,
    save_source,
)
from ghostbrain.templates.testrun import dry_run
from ghostbrain.vault_write import USER, Actor

try:  # B2 attributes HTTP writes from the X-Poltergeist-Actor header.
    from ghostbrain.api.vault_http import request_actor
except ImportError:  # Before B2 every HTTP write is the user's.
    def request_actor() -> Actor:
        return USER
```

If B2 already changed this import block (for example to import `request_actor` directly), keep its lines and add only the ones above that are missing. Then append to the end of the file:

```python
# ── C3: template editor ───────────────────────────────────────────────────


class SourceBody(BaseModel):
    source: str = Field(max_length=MAX_TEMPLATE_CHARS)


class DryRunBody(BaseModel):
    source: str = Field(max_length=MAX_TEMPLATE_CHARS)
    answers: dict[str, str] = Field(default_factory=dict, max_length=50)
    id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    dry_run: Literal[True] = True


class NewTemplateBody(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)


@router.post("/lint")
def lint_source(body: SourceBody) -> dict[str, Any]:
    return {"diagnostics": [d.to_json() for d in lint(body.source)]}


@router.post("/render")
def dry_run_source(body: DryRunBody) -> dict[str, Any]:
    """Test run. Always 200: problems come back in ``error``/``diagnostics``
    so the editor can show them next to the source."""
    return dry_run(body.source, body.answers, template_id=body.id or "draft").to_json()


@router.get("/query-values")
def get_query_values() -> dict[str, Any]:
    return query_values()


@router.get("/{template_id}/source")
def get_source(template_id: str) -> dict[str, Any]:
    try:
        return read_source(template_id).to_json()
    except (TemplateNotFound, TemplateInvalid) as e:
        raise _http_error(template_id, e) from e


@router.patch("/{template_id}/source")
def patch_source(
    template_id: str,
    body: SourceBody,
    base_etag: str | None = Depends(if_match),
    actor: Actor = Depends(request_actor),
) -> dict[str, Any]:
    try:
        saved = save_source(template_id, body.source, actor=actor, base_etag=base_etag)
    except (TemplateNotFound, TemplateInvalid) as e:
        raise _http_error(template_id, e) from e
    except SourceTooLarge as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return saved.to_json()


@router.post("", status_code=201)
def new_template(body: NewTemplateBody, actor: Actor = Depends(request_actor)) -> dict[str, Any]:
    try:
        return create_blank(body.name, actor=actor).to_json()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
```

The static `"/lint"`, `"/render"` and `"/query-values"` paths have one segment and C1's `"/{template_id}/create"` / `"/{template_id}/render"` have two, so none of them shadow each other.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$C3" && python -m pytest ghostbrain/api/tests/test_templates_editor_routes.py ghostbrain/api/tests/test_templates_routes.py -v`
Expected: PASS. Then run the backend CI list once: `cd "$C3" && python -m pytest ghostbrain/api/tests/ tests/test_templates_*.py tests/test_no_hardcoded_contexts.py -q` and expect PASS.

- [ ] **Step 5: Commit**

```bash
cd "$C3"
git add ghostbrain/api/routes/templates.py ghostbrain/api/tests/test_templates_editor_routes.py
git commit -m "feat(api): template editor routes: lint, test run, source, new, query values"
```

---

### Task 5: Desktop dependencies, types, editor calls and remembered answers

**Files:**
- Modify: `desktop/package.json`, `desktop/package-lock.json`
- Modify: `desktop/src/shared/api-types.ts` (append)
- Create: `desktop/src/renderer/lib/api/template-editor.ts`
- Create: `desktop/src/renderer/lib/templates/last-answers.ts`
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (`useCreateFromTemplate`)
- Create: `desktop/src/renderer/__tests__/helpers/memory-storage.ts`
- Test: `desktop/src/renderer/__tests__/template-editor-hooks.test.tsx`

**Interfaces:**
- Consumes: Task 4's routes; `get`, `post`, `patch` (with `{ ifMatch }`) from `lib/api/client`; C1's `TemplateFunctionsResponse`, `TemplateFunctionSpec`, `TemplateDiagnostic`, `TemplatePrompt`, `TemplateRenderResponse`, `useCreateFromTemplate`, `TemplateAnswersVars`.
- Produces: the types, hooks and `last-answers` functions listed in Interfaces; `stubLocalStorage()` / `stubBrokenLocalStorage()` test helpers.

- [ ] **Step 1: Add the CodeMirror packages, pinned**

Run: `cd "$C3/desktop" && npm install --save-exact @codemirror/autocomplete@6.20.3 @codemirror/lint@6.9.7 @codemirror/state@6.6.0 @codemirror/view@6.43.1 && npm ls @codemirror/state @codemirror/view`
Expected: `package.json` gains the four entries with exact versions (no `^`), and `npm ls` shows one version of each, every other occurrence marked `deduped`. If `npm ls` lists a second version, stop: two copies of `@codemirror/state` break every extension.

- [ ] **Step 2: Write the failing tests**

`desktop/src/renderer/__tests__/helpers/memory-storage.ts`:

```ts
import { vi } from 'vitest';

/** Node 25 ships a bare global localStorage that shadows jsdom's; tests use
 * this in-memory stub instead. Undo with vi.unstubAllGlobals(). */
export function stubLocalStorage(): Map<string, string> {
  const mem = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => mem.get(k) ?? null,
    setItem: (k: string, v: string) => void mem.set(k, v),
    removeItem: (k: string) => void mem.delete(k),
    clear: () => mem.clear(),
  });
  return mem;
}

/** A localStorage that throws on every call (private mode, blocked site data). */
export function stubBrokenLocalStorage(): void {
  const fail = () => {
    throw new Error('storage blocked');
  };
  vi.stubGlobal('localStorage', { getItem: fail, setItem: fail, removeItem: fail, clear: fail });
}
```

`desktop/src/renderer/__tests__/template-editor-hooks.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { useCreateFromTemplate } from '../lib/api/hooks';
import {
  lintTemplate,
  saveTemplateSource,
  useCreateBlankTemplate,
  useTemplateDryRun,
  useTemplateSource,
} from '../lib/api/template-editor';
import {
  LAST_ANSWERS_KEY,
  MAX_REMEMBERED_TEMPLATES,
  initialAnswers,
  rememberAnswers,
} from '../lib/templates/last-answers';
import { stubBrokenLocalStorage, stubLocalStorage } from './helpers/memory-storage';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);
const patchMock = vi.mocked(client.patch);

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  stubLocalStorage();
});
afterEach(() => {
  vi.unstubAllGlobals();
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
});

describe('template editor calls', () => {
  it('reads source by encoded id only when an id is given', async () => {
    getMock.mockResolvedValue({ id: 'one-on-one', path: 'p', source: 's', etag: 'e' });
    renderHook(() => useTemplateSource(null), { wrapper });
    expect(getMock).not.toHaveBeenCalled();
    const { result } = renderHook(() => useTemplateSource('one-on-one'), { wrapper });
    await waitFor(() => expect(result.current.data?.etag).toBe('e'));
    expect(getMock).toHaveBeenCalledWith('/v1/templates/one-on-one/source');
  });

  it('saves with If-Match, or without it to overwrite', async () => {
    patchMock.mockResolvedValue({ id: 'x', path: 'p', etag: 'e2', status: 'applied', changeId: null });
    await saveTemplateSource('x', 'src', 'e1');
    expect(patchMock).toHaveBeenLastCalledWith('/v1/templates/x/source', { source: 'src' }, { ifMatch: 'e1' });
    await saveTemplateSource('x', 'src', null);
    expect(patchMock).toHaveBeenLastCalledWith('/v1/templates/x/source', { source: 'src' }, { ifMatch: null });
  });

  it('lints and test-runs through the sidecar', async () => {
    postMock.mockResolvedValueOnce({ diagnostics: [{ line: 1, col: 1, severity: 'error', message: 'm', code: 'c' }] });
    expect(await lintTemplate('src')).toHaveLength(1);
    expect(postMock).toHaveBeenLastCalledWith('/v1/templates/lint', { source: 'src' });

    postMock.mockResolvedValueOnce({ ok: true });
    const { result } = renderHook(() => useTemplateDryRun(), { wrapper });
    await result.current.mutateAsync({ source: 's', answers: { a: 'b' }, id: 'x' });
    expect(postMock).toHaveBeenLastCalledWith('/v1/templates/render', {
      source: 's',
      answers: { a: 'b' },
      id: 'x',
      dry_run: true,
    });
  });

  it('creates a blank template by name', async () => {
    postMock.mockResolvedValue({ id: 'weekly', path: 'p', etag: 'e', status: 'applied', changeId: null });
    const { result } = renderHook(() => useCreateBlankTemplate(), { wrapper });
    await result.current.mutateAsync('Weekly');
    expect(postMock).toHaveBeenCalledWith('/v1/templates', { name: 'Weekly' });
  });

  it('remembers the answers of a successful create', async () => {
    postMock.mockResolvedValue({ path: 'a.md', title: 'A', etag: 'e', status: 'applied' });
    const { result } = renderHook(() => useCreateFromTemplate(), { wrapper });
    await result.current.mutateAsync({ id: 'one-on-one', answers: { person: 'Alex', focus: '' } });
    expect(initialAnswers('one-on-one', ['person', 'focus'])).toEqual({ person: 'Alex' });
  });
});

describe('last answers', () => {
  it('falls back to the latest answer for the same prompt id in any template', () => {
    rememberAnswers('one-on-one', { person: 'Alex' });
    rememberAnswers('meeting-notes', { topic: 'Planning' });
    expect(initialAnswers('new-template', ['person', 'topic', 'other'])).toEqual({
      person: 'Alex',
      topic: 'Planning',
    });
    rememberAnswers('meeting-notes', { person: 'Robin' });
    expect(initialAnswers('one-on-one', ['person'])).toEqual({ person: 'Alex' });
    expect(initialAnswers('other', ['person'])).toEqual({ person: 'Robin' });
  });

  it('caps what it keeps and survives corrupt or blocked storage', () => {
    for (let i = 0; i < MAX_REMEMBERED_TEMPLATES + 5; i += 1) rememberAnswers(`t${i}`, { a: `v${i}` });
    const stored = JSON.parse(localStorage.getItem(LAST_ANSWERS_KEY)!);
    expect(Object.keys(stored.byTemplate)).toHaveLength(MAX_REMEMBERED_TEMPLATES);
    expect(stored.byTemplate.t0).toBeUndefined();
    rememberAnswers('long', { a: 'x'.repeat(501) });
    expect(initialAnswers('long', ['a'])).toEqual({ a: `v${MAX_REMEMBERED_TEMPLATES + 4}` });

    localStorage.setItem(LAST_ANSWERS_KEY, '{not json');
    expect(initialAnswers('x', ['a'])).toEqual({});
    stubBrokenLocalStorage();
    expect(() => rememberAnswers('x', { a: 'b' })).not.toThrow();
    expect(initialAnswers('x', ['a'])).toEqual({});
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/template-editor-hooks.test.tsx`
Expected: FAIL with `Failed to resolve import "../lib/api/template-editor"`.

- [ ] **Step 4: Write the implementation**

Append to `desktop/src/shared/api-types.ts`:

```ts
// ── Template editor (C3) ──────────────────────────────────────────────────

/** GET /v1/templates/functions. `queryKeys` exists once C2 is on the branch;
 * the editor treats it as optional so query completions switch off without it. */
export type TemplateRegistry = TemplateFunctionsResponse & { queryKeys?: TemplateFunctionSpec[] };

export interface TemplateLintResponse {
  diagnostics: TemplateDiagnostic[];
}

export interface TemplateSourceResponse {
  id: string;
  path: string;
  source: string;
  etag: string;
}

export interface TemplateSaveResponse {
  id: string;
  path: string;
  etag: string | null;
  status: 'applied' | 'pending';
  changeId: string | null;
}

export interface TemplateQueryValues {
  types: string[];
  statuses: string[];
  indexing: boolean;
}

export interface TemplateDryRunRequest {
  source: string;
  answers: Record<string, string>;
  id?: string;
  dry_run: true;
}

export interface TemplateDryRunResponse {
  ok: boolean;
  prompts: TemplatePrompt[];
  answers: Record<string, string>;
  rendered: (TemplateRenderResponse & { markdown: string }) | null;
  wouldBeFiledAt: string | null;
  diagnostics: TemplateDiagnostic[];
  error: string | null;
}
```

`desktop/src/renderer/lib/api/template-editor.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, patch, post } from './client';
import type {
  TemplateDiagnostic,
  TemplateDryRunRequest,
  TemplateDryRunResponse,
  TemplateLintResponse,
  TemplateQueryValues,
  TemplateRegistry,
  TemplateSaveResponse,
  TemplateSourceResponse,
} from '../../../shared/api-types';

/** Template editor (C3) calls. Every key starts with 'templates', so
 * invalidating ['templates'] after a save refreshes the list too. */

const enc = encodeURIComponent;

export function useTemplateFunctions() {
  return useQuery({
    queryKey: ['templates', 'functions'],
    queryFn: () => get<TemplateRegistry>('/v1/templates/functions'),
    staleTime: Infinity,
  });
}

export function useTemplateQueryValues() {
  return useQuery({
    queryKey: ['templates', 'query-values'],
    queryFn: () => get<TemplateQueryValues>('/v1/templates/query-values'),
    staleTime: 60_000,
    // A cold link index answers indexing: true; ask again shortly.
    refetchInterval: (q) => (q.state.data?.indexing ? 3_000 : false),
  });
}

export function useTemplateSource(id: string | null) {
  return useQuery({
    queryKey: ['templates', 'source', id],
    queryFn: () => get<TemplateSourceResponse>(`/v1/templates/${enc(id ?? '')}/source`),
    enabled: id !== null,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function lintTemplate(source: string): Promise<TemplateDiagnostic[]> {
  return post<TemplateLintResponse>('/v1/templates/lint', { source }).then((r) => r.diagnostics);
}

/** `etag` null = overwrite whatever is on disk (the conflict banner's "keep mine"). */
export function saveTemplateSource(
  id: string,
  source: string,
  etag: string | null,
): Promise<TemplateSaveResponse> {
  return patch<TemplateSaveResponse>(`/v1/templates/${enc(id)}/source`, { source }, { ifMatch: etag });
}

export function useCreateBlankTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => post<TemplateSaveResponse>('/v1/templates', { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['templates'] }),
  });
}

export function useTemplateDryRun() {
  return useMutation({
    mutationFn: (req: Omit<TemplateDryRunRequest, 'dry_run'>) =>
      post<TemplateDryRunResponse>('/v1/templates/render', { ...req, dry_run: true }),
  });
}
```

`desktop/src/renderer/lib/templates/last-answers.ts`:

```ts
/**
 * The answers last used to make a note from a template, so the template
 * editor's Test run starts from real values (spec C3: "the most recent real
 * values (last person, today)"). Per template, plus the latest value per
 * prompt id across templates, so a new template's `person` prompt starts
 * from the last person picked anywhere. localStorage only; every failure
 * is silent and just means "no remembered answers".
 */

export const LAST_ANSWERS_KEY = 'gb.templates.lastAnswers.v1';
export const MAX_REMEMBERED_TEMPLATES = 50;
export const MAX_REMEMBERED_PROMPTS = 100;
export const MAX_REMEMBERED_CHARS = 500;

interface Stored {
  byTemplate: Record<string, Record<string, string>>;
  byPrompt: Record<string, string>;
}

function load(): Stored {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(LAST_ANSWERS_KEY) ?? 'null');
    if (parsed && typeof parsed === 'object') {
      const p = parsed as Partial<Stored>;
      return {
        byTemplate: p.byTemplate && typeof p.byTemplate === 'object' ? p.byTemplate : {},
        byPrompt: p.byPrompt && typeof p.byPrompt === 'object' ? p.byPrompt : {},
      };
    }
  } catch {
    // unreadable or blocked storage: nothing remembered
  }
  return { byTemplate: {}, byPrompt: {} };
}

/** Keep the newest `max` keys; insertion order is recency (re-set keys move last). */
function trim<T>(record: Record<string, T>, max: number): Record<string, T> {
  const keys = Object.keys(record);
  return Object.fromEntries(keys.slice(Math.max(0, keys.length - max)).map((k) => [k, record[k]!]));
}

export function rememberAnswers(templateId: string, answers: Record<string, string>): void {
  const kept = Object.fromEntries(
    Object.entries(answers).filter(
      ([, v]) => typeof v === 'string' && v.trim() !== '' && v.length <= MAX_REMEMBERED_CHARS,
    ),
  );
  const stored = load();
  delete stored.byTemplate[templateId];
  stored.byTemplate[templateId] = kept;
  for (const [k, v] of Object.entries(kept)) {
    delete stored.byPrompt[k];
    stored.byPrompt[k] = v;
  }
  const next: Stored = {
    byTemplate: trim(stored.byTemplate, MAX_REMEMBERED_TEMPLATES),
    byPrompt: trim(stored.byPrompt, MAX_REMEMBERED_PROMPTS),
  };
  try {
    localStorage.setItem(LAST_ANSWERS_KEY, JSON.stringify(next));
  } catch {
    // full or blocked storage: forget silently
  }
}

/** Starting answers for a Test run: this template's last answers, else the
 * latest answer to a prompt with the same id from any template. */
export function initialAnswers(templateId: string, promptIds: string[]): Record<string, string> {
  const { byTemplate, byPrompt } = load();
  const own = byTemplate[templateId] ?? {};
  const out: Record<string, string> = {};
  for (const id of promptIds) {
    const value = own[id] ?? byPrompt[id];
    if (typeof value === 'string') out[id] = value;
  }
  return out;
}
```

In `desktop/src/renderer/lib/api/hooks.ts`, add this import directly after the `@tanstack/react-query` import:

```ts
import { rememberAnswers } from '../templates/last-answers';
```

and in `useCreateFromTemplate`, replace

```ts
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: JOTS_KEY }),
        qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] }),
      ]),
```

with

```ts
    onSuccess: (_res, { id, answers }) => {
      rememberAnswers(id, answers);
      return Promise.all([
        qc.invalidateQueries({ queryKey: JOTS_KEY }),
        qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] }),
      ]);
    },
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/template-editor-hooks.test.tsx src/renderer/__tests__/template-hooks.test.tsx && npm run typecheck`
Expected: PASS, no type errors.

- [ ] **Step 6: Commit**

```bash
cd "$C3"
git add desktop/package.json desktop/package-lock.json desktop/src/shared/api-types.ts desktop/src/renderer/lib/api/template-editor.ts desktop/src/renderer/lib/templates/last-answers.ts desktop/src/renderer/lib/api/hooks.ts desktop/src/renderer/__tests__/helpers/memory-storage.ts desktop/src/renderer/__tests__/template-editor-hooks.test.tsx
git commit -m "feat(desktop): template editor calls, pinned CodeMirror packages, remembered answers"
```

---

### Task 6: Template text analysis (`analyze.ts`)

**Files:**
- Create: `desktop/src/renderer/lib/template-editor/analyze.ts`
- Create: `desktop/src/renderer/__tests__/helpers/template-registry.ts`
- Test: `desktop/src/renderer/__tests__/template-editor-analyze.test.ts`

**Interfaces:**
- Consumes: nothing (pure string functions).
- Produces: `frontmatterRange`, `promptsSection`, `extractPrompts`, `inQueryFence`, `cursorContext`, `PromptInfo`, `CursorContext` (see Interfaces). The helper exports `REGISTRY: TemplateRegistry` (a trimmed `GET /v1/templates/functions` with `queryKeys`) and `TEMPLATE: string`, used by Tasks 7, 8 and 10.

- [ ] **Step 1: Write the failing tests**

`desktop/src/renderer/__tests__/helpers/template-registry.ts` (the query keys use `kind: 'variable'` so the fixture typechecks with or without C2's `'query_key'` kind; the editor never reads `kind`):

```ts
import type { TemplateFunctionSpec, TemplateRegistry } from '../../../shared/api-types';

function spec(
  name: string,
  kind: TemplateFunctionSpec['kind'],
  type: string,
  doc: string,
  example: string,
  extra: Partial<TemplateFunctionSpec> = {},
): TemplateFunctionSpec {
  return { name, kind, type, doc, example, owner: null, accepts: [], arg: null, argRequired: false, ...extra };
}

/** A trimmed copy of GET /v1/templates/functions (C1 + C2's queryKeys). */
export const REGISTRY: TemplateRegistry = {
  variables: [
    spec('date', 'variable', 'date', 'Today, or the date prompt.', '{{date | format: D MMM YYYY}}'),
    spec('now', 'variable', 'datetime', 'The current date and time.', '{{now.iso}}'),
    spec('context', 'variable', 'text', 'The context.', '20-contexts/{{context}}/notes'),
    spec('title', 'variable', 'text', 'The note title.', '# {{title}}'),
  ],
  fields: [
    spec('name', 'field', 'text', 'The person name.', '{{person.name}}', { owner: 'person' }),
    spec('link', 'field', 'text', 'A wikilink to the person.', '{{person.link}}', { owner: 'person' }),
    spec('iso', 'field', 'text', 'The date as YYYY-MM-DD.', '{{date.iso}}', { owner: 'date' }),
    spec('date', 'field', 'date', 'Just the date part.', '{{now.date}}', { owner: 'datetime' }),
  ],
  filters: [
    spec('format', 'filter', 'text', 'Formats a date.', '{{date | format: D MMM}}', {
      arg: '<pattern>',
      argRequired: true,
    }),
    spec('upper', 'filter', 'text', 'UPPER CASE.', '{{context | upper}}'),
  ],
  promptTypes: [
    spec('text', 'prompt_type', 'text', 'Free text.', 'type: text'),
    spec('person', 'prompt_type', 'person', 'A person.', 'type: person'),
    spec('date', 'prompt_type', 'date', 'A date.', 'type: date'),
  ],
  queryKeys: [
    spec('type', 'variable', 'text', 'Notes of this type.', 'type: action_item'),
    spec('status', 'variable', 'text', 'open = not done.', 'status: open'),
    spec('sort', 'variable', 'text', 'created or updated.', 'sort: created desc'),
    spec('context', 'variable', 'text', 'Notes in this context.', 'context: work'),
  ],
};

export const TEMPLATE = `---
template:
  name: 1-1
  prompts:
    - id: person
      ask: "Who?"
      type: person
    - ask: "Focus?"
      type: text
      id: focus
  file:
    name: "{{date | format: YYYY-MM-DD}} {{person.name}}"
  frontmatter:
    id: not-a-prompt
    type: meeting
---
# 1-1 with {{person.link}}

\`\`\`query
type: action_item
status: open
\`\`\`
`;
```

`desktop/src/renderer/__tests__/template-editor-analyze.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
  cursorContext,
  extractPrompts,
  frontmatterRange,
  inQueryFence,
} from '../lib/template-editor/analyze';
import { TEMPLATE } from './helpers/template-registry';

/** `text` with the cursor at the `|` marker removed. */
function at(marked: string): [string, number] {
  const pos = marked.indexOf('‸');
  return [marked.replace('‸', ''), pos];
}

describe('template text analysis', () => {
  it('finds the frontmatter block', () => {
    const fm = frontmatterRange(TEMPLATE)!;
    expect(TEMPLATE.slice(fm.innerEnd, fm.bodyStart)).toBe('---\n');
    expect(TEMPLATE.slice(fm.bodyStart).startsWith('# 1-1 with')).toBe(true);
    expect(frontmatterRange('# no frontmatter\n')).toBeNull();
    expect(frontmatterRange('---\nnever closed\n')).toBeNull();
  });

  it('extracts prompts in block style, type before or after id, ignoring frontmatter ids', () => {
    expect(extractPrompts(TEMPLATE)).toEqual([
      { id: 'person', type: 'person' },
      { id: 'focus', type: 'text' },
    ]);
  });

  it('extracts prompts in flow style and defaults the type to text', () => {
    const src = '---\ntemplate:\n  name: x\n  prompts: [{id: who, type: person}, {id: note}]\n---\n';
    expect(extractPrompts(src)).toEqual([
      { id: 'who', type: 'person' },
      { id: 'note', type: 'text' },
    ]);
  });

  it('knows when a position is inside a query fence', () => {
    const typePos = TEMPLATE.indexOf('type: action_item');
    expect(inQueryFence(TEMPLATE, typePos)).toBe(true);
    expect(inQueryFence(TEMPLATE, TEMPLATE.indexOf('```query'))).toBe(false);
    expect(inQueryFence(TEMPLATE, TEMPLATE.indexOf('# 1-1'))).toBe(false);
    expect(inQueryFence(TEMPLATE, TEMPLATE.lastIndexOf('```'))).toBe(false);
    expect(inQueryFence('```text\ntype: x\n```\n', 9)).toBe(false);
  });

  it('classifies placeholder positions', () => {
    expect(cursorContext(...at('# {{‸'))).toEqual({ kind: 'variable', from: 4, prefix: '' });
    expect(cursorContext(...at('# {{ per‸'))).toEqual({ kind: 'variable', from: 5, prefix: 'per' });
    expect(cursorContext(...at('{{person.li‸'))).toEqual({
      kind: 'field',
      from: 9,
      prefix: 'li',
      ownerPath: ['person'],
    });
    expect(cursorContext(...at('{{now.date.‸'))).toMatchObject({ kind: 'field', ownerPath: ['now', 'date'] });
    expect(cursorContext(...at('{{date | fo‸'))).toEqual({ kind: 'filter', from: 9, prefix: 'fo' });
    expect(cursorContext(...at('{{date | format: D‸'))).toBeNull();
    expect(cursorContext(...at('{{x}} ‸'))).toBeNull();
    expect(cursorContext(...at('{{ a + ‸'))).toBeNull();
  });

  it('offers prompt types only on a type line inside prompts', () => {
    const src = TEMPLATE.replace('      type: person', '      type: pe‸');
    expect(cursorContext(...at(src))).toMatchObject({ kind: 'prompt-type', prefix: 'pe' });
    const fmType = TEMPLATE.replace('    type: meeting', '    type: me‸');
    expect(cursorContext(...at(fmType))).toBeNull();
  });

  it('classifies query keys and values', () => {
    const key = TEMPLATE.replace('status: open', 'sta‸');
    expect(cursorContext(...at(key))).toMatchObject({ kind: 'query-key', prefix: 'sta' });
    const value = TEMPLATE.replace('status: open', 'status: op‸');
    expect(cursorContext(...at(value))).toMatchObject({ kind: 'query-value', key: 'status', prefix: 'op' });
    const quoted = TEMPLATE.replace('status: open', 'Type: "acti‸');
    expect(cursorContext(...at(quoted))).toMatchObject({ kind: 'query-value', key: 'type', prefix: 'acti' });
    const inQueryPlaceholder = TEMPLATE.replace('status: open', 'mentions: "{{person.‸');
    expect(cursorContext(...at(inQueryPlaceholder))).toMatchObject({ kind: 'field' });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/template-editor-analyze.test.ts`
Expected: FAIL with `Failed to resolve import "../lib/template-editor/analyze"`.

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/lib/template-editor/analyze.ts`:

```ts
/**
 * Read-only text analysis of a template file for the template editor:
 * where the frontmatter and the `prompts:` list are, which prompts the
 * template declares, whether a position is inside a ```query fence, and
 * what kind of completion fits at the cursor. Pure functions over the
 * document text; nothing here is evaluated.
 */

export interface PromptInfo {
  id: string;
  type: string;
}

export interface FrontmatterRange {
  /** Offset of the first character after the opening `---` line. */
  innerStart: number;
  /** Offset of the closing `---` line. */
  innerEnd: number;
  /** Offset of the first character after the closing `---` line. */
  bodyStart: number;
}

export type CursorContext =
  | { kind: 'variable'; from: number; prefix: string }
  | { kind: 'field'; from: number; prefix: string; ownerPath: string[] }
  | { kind: 'filter'; from: number; prefix: string }
  | { kind: 'prompt-type'; from: number; prefix: string }
  | { kind: 'query-key'; from: number; prefix: string }
  | { kind: 'query-value'; from: number; prefix: string; key: string };

const PROMPT_TYPES = 'person|text|date|choice|context|project';
const ID_RE = /(?:^|[\s,{])id:[ \t]*["']?([a-z][a-z0-9_]{0,31})\b/;
const TYPE_RE = new RegExp(`(?:^|[\\s,{])type:[ \\t]*["']?(${PROMPT_TYPES})\\b`);
const FENCE_OPEN_RE = /^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)/;
const FENCE_CLOSE_RE = /^ {0,3}(`{3,}|~{3,})[ \t]*$/;

function lineAt(text: string, pos: number): { start: number; end: number } {
  const start = text.lastIndexOf('\n', pos - 1) + 1;
  const nl = text.indexOf('\n', pos);
  return { start, end: nl < 0 ? text.length : nl };
}

export function frontmatterRange(text: string): FrontmatterRange | null {
  const first = text.startsWith('---\r\n') ? 5 : text.startsWith('---\n') ? 4 : -1;
  if (first < 0) return null;
  let pos = first;
  for (;;) {
    const nl = text.indexOf('\n', pos);
    const end = nl < 0 ? text.length : nl;
    if (/^-{3,}[ \t]*\r?$/.test(text.slice(pos, end))) {
      return { innerStart: first, innerEnd: pos, bodyStart: nl < 0 ? text.length : nl + 1 };
    }
    if (nl < 0) return null;
    pos = nl + 1;
  }
}

/** The `prompts:` key and its list, as offsets into `text`. */
export function promptsSection(text: string): { start: number; end: number } | null {
  const fm = frontmatterRange(text);
  if (!fm) return null;
  const inner = text.slice(fm.innerStart, fm.innerEnd);
  const m = /^([ \t]*)prompts:/m.exec(inner);
  if (!m) return null;
  const indent = m[1]!.length;
  const start = fm.innerStart + m.index;
  let pos = inner.indexOf('\n', m.index);
  while (pos >= 0 && pos + 1 < inner.length) {
    pos += 1;
    const nl = inner.indexOf('\n', pos);
    const line = inner.slice(pos, nl < 0 ? inner.length : nl).replace(/\r$/, '');
    const trimmed = line.trimStart();
    const lineIndent = line.length - trimmed.length;
    if (trimmed && !trimmed.startsWith('#') && lineIndent <= indent && !trimmed.startsWith('-')) {
      return { start, end: fm.innerStart + pos };
    }
    pos = nl;
  }
  return { start, end: fm.innerEnd };
}

/** The prompts the template declares, in order (block or flow YAML). */
export function extractPrompts(text: string): PromptInfo[] {
  const section = promptsSection(text);
  if (!section) return [];
  const items = text.slice(section.start, section.end).split(/\n[ \t]*-[ \t]+|\{/);
  const out: PromptInfo[] = [];
  const seen = new Set<string>();
  for (const item of items.slice(1)) {
    const id = ID_RE.exec(item)?.[1];
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({ id, type: TYPE_RE.exec(item)?.[1] ?? 'text' });
  }
  return out;
}

/** True when `pos` is on a content line of a ```query fence in the body. */
export function inQueryFence(text: string, pos: number): boolean {
  const fm = frontmatterRange(text);
  let lineStart = fm ? fm.bodyStart : 0;
  if (pos < lineStart) return false;
  let open: { ch: string; len: number; query: boolean } | null = null;
  for (;;) {
    const nl = text.indexOf('\n', lineStart);
    const lineEnd = nl < 0 ? text.length : nl;
    const line = text.slice(lineStart, lineEnd).replace(/\r$/, '');
    const close = open ? FENCE_CLOSE_RE.exec(line) : null;
    const closes = !!open && !!close && close[1]![0] === open.ch && close[1]!.length >= open.len;
    if (pos <= lineEnd) return !!open && open.query && !closes;
    if (closes) {
      open = null;
    } else if (!open) {
      const m = FENCE_OPEN_RE.exec(line);
      if (m) open = { ch: m[1]![0]!, len: m[1]!.length, query: m[2]!.toLowerCase() === 'query' };
    }
    if (nl < 0) return false;
    lineStart = nl + 1;
  }
}

function placeholderContext(before: string, pos: number): CursorContext | null | undefined {
  const open = before.lastIndexOf('{{');
  if (open < 0 || before.indexOf('}}', open) >= 0) return undefined;
  const expr = before.slice(open + 2);
  const pipe = expr.lastIndexOf('|');
  if (pipe >= 0) {
    const last = expr.slice(pipe + 1);
    if (last.includes(':')) return null; // a filter argument: nothing to offer
    const prefix = last.trimStart();
    if (!/^[A-Za-z0-9_]*$/.test(prefix)) return null;
    return { kind: 'filter', from: pos - prefix.length, prefix };
  }
  const path = expr.trimStart();
  if (!/^[A-Za-z0-9_.]*$/.test(path)) return null;
  const parts = path.split('.');
  const prefix = parts.pop()!;
  if (parts.length === 0) return { kind: 'variable', from: pos - prefix.length, prefix };
  if (parts.some((p) => p === '')) return null;
  return { kind: 'field', from: pos - prefix.length, prefix, ownerPath: parts };
}

/** What to complete at `pos`, or null when nothing fits. */
export function cursorContext(text: string, pos: number): CursorContext | null {
  const { start } = lineAt(text, pos);
  const before = text.slice(start, pos);
  const inPlaceholder = placeholderContext(before, pos);
  if (inPlaceholder !== undefined) return inPlaceholder;
  const section = promptsSection(text);
  if (section && pos >= section.start && pos <= section.end) {
    const m = /^[ \t]*(?:-[ \t]+)?type:[ \t]*["']?([a-z]*)$/.exec(before);
    return m ? { kind: 'prompt-type', from: pos - m[1]!.length, prefix: m[1]! } : null;
  }
  if (!inQueryFence(text, pos)) return null;
  const key = /^[ \t]*([A-Za-z]*)$/.exec(before);
  if (key) return { kind: 'query-key', from: pos - key[1]!.length, prefix: key[1]! };
  const value = /^[ \t]*([A-Za-z]+)[ \t]*:[ \t]*["']?([^"'\n]*)$/.exec(before);
  if (value) {
    const prefix = value[2]!;
    return { kind: 'query-value', from: pos - prefix.length, prefix, key: value[1]!.toLowerCase() };
  }
  return null;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/template-editor-analyze.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$C3"
git add desktop/src/renderer/lib/template-editor/analyze.ts desktop/src/renderer/__tests__/helpers/template-registry.ts desktop/src/renderer/__tests__/template-editor-analyze.test.ts
git commit -m "feat(desktop): template text analysis for the editor (prompts, fences, cursor context)"
```

---

### Task 7: Registry-driven completions (`completions.ts`)

**Files:**
- Create: `desktop/src/renderer/lib/template-editor/completions.ts`
- Test: `desktop/src/renderer/__tests__/template-editor-completions.test.ts`

**Interfaces:**
- Consumes: Task 6 (`cursorContext`, `extractPrompts`, `CursorContext`, `PromptInfo`, test helper `REGISTRY`/`TEMPLATE`); Task 5's `TemplateRegistry`; `Completion`, `CompletionContext`, `CompletionResult`, `CompletionSource` from `@codemirror/autocomplete`.
- Produces: `templateCompletions(getData)`, `optionsFor`, `valueTypeOf`, `specInfo`, `TemplateEditorData`, `QueryValueHints`, `EMPTY_HINTS`, `SORT_VALUES`. Task 8 reuses `specInfo`, `valueTypeOf` and `TemplateEditorData`.

- [ ] **Step 1: Write the failing tests**

`desktop/src/renderer/__tests__/template-editor-completions.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { CompletionContext, type CompletionResult } from '@codemirror/autocomplete';
import { EditorState } from '@codemirror/state';
import {
  EMPTY_HINTS,
  templateCompletions,
  valueTypeOf,
  type TemplateEditorData,
} from '../lib/template-editor/completions';
import { REGISTRY, TEMPLATE } from './helpers/template-registry';

const HINTS = { types: ['action_item', 'decision'], statuses: ['done', 'open'], contexts: ['work'] };

function complete(marked: string, data: Partial<TemplateEditorData> = {}): CompletionResult | null {
  const pos = marked.indexOf('‸');
  const doc = marked.replace('‸', '');
  const state = EditorState.create({ doc, selection: { anchor: pos } });
  const source = templateCompletions(() => ({ registry: REGISTRY, hints: HINTS, ...data }));
  return source(new CompletionContext(state, pos, false)) as CompletionResult | null;
}

const labels = (r: CompletionResult | null) => r?.options.map((o) => o.label) ?? [];
const BODY = TEMPLATE.replace('# 1-1 with {{person.link}}', '# {{‸');

describe('template completions', () => {
  it('offers the template prompts first, then registry variables, each with docs', () => {
    const r = complete(BODY);
    expect(labels(r)).toEqual(['person', 'focus', 'date', 'now', 'context', 'title']);
    expect(r!.from).toBe(BODY.indexOf('‸'));
    expect(r!.options[0]).toMatchObject({ detail: 'prompt · person', boost: 2 });
    expect(r!.options[0]!.info).toContain('A person.');
    expect(r!.options[2]!.info).toBe('Today, or the date prompt.\n\nExample: {{date | format: D MMM YYYY}}');
  });

  it('offers the fields of the value type after a dot', () => {
    expect(labels(complete(TEMPLATE.replace('{{person.link}}', '{{person.‸')))).toEqual(['name', 'link']);
    expect(labels(complete(TEMPLATE.replace('{{person.link}}', '{{now.date.‸')))).toEqual(['iso']);
    expect(complete(TEMPLATE.replace('{{person.link}}', '{{focus.‸'))).toBeNull();
  });

  it('offers filters after a pipe, with ": " for those that need an argument', () => {
    const r = complete(TEMPLATE.replace('{{person.link}}', '{{date | ‸'));
    expect(labels(r)).toEqual(['format', 'upper']);
    expect(r!.options[0]!.apply).toBe('format: ');
    expect(r!.options[1]!.apply).toBe('upper');
  });

  it('offers prompt types on a prompt type line', () => {
    const r = complete(TEMPLATE.replace('      type: person', '      type: ‸'));
    expect(labels(r)).toEqual(['text', 'person', 'date']);
  });

  it('offers query keys and their known values inside a query fence', () => {
    const keys = complete(TEMPLATE.replace('status: open', '‸'));
    expect(labels(keys)).toEqual(['type', 'status', 'sort', 'context']);
    expect(keys!.options[0]!.apply).toBe('type: ');
    expect(labels(complete(TEMPLATE.replace('status: open', 'status: ‸')))).toEqual(['open', 'done']);
    expect(labels(complete(TEMPLATE.replace('status: open', 'type: ‸')))).toEqual(['action_item', 'decision']);
    expect(labels(complete(TEMPLATE.replace('status: open', 'context: ‸')))).toEqual(['work']);
    expect(labels(complete(TEMPLATE.replace('status: open', 'sort: ‸')))).toEqual([
      'created desc',
      'created asc',
      'updated desc',
      'updated asc',
    ]);
    const value = complete(TEMPLATE.replace('status: open', 'status: ‸'));
    expect(value!.options[0]!.info).toBe('open = not done.\n\nExample: status: open');
  });

  it('skips query completions when the registry has no query keys (C2 absent)', () => {
    const { queryKeys: _omit, ...withoutQueries } = REGISTRY;
    expect(complete(TEMPLATE.replace('status: open', '‸'), { registry: withoutQueries })).toBeNull();
    expect(complete(TEMPLATE.replace('status: open', 'status: ‸'), { registry: withoutQueries })).toBeNull();
    expect(labels(complete(BODY, { registry: withoutQueries }))).toContain('person');
  });

  it('returns nothing before the registry loads or outside any context', () => {
    expect(complete(BODY, { registry: null })).toBeNull();
    expect(complete('plain ‸text', { hints: EMPTY_HINTS })).toBeNull();
  });

  it('resolves value types through prompts, variables and fields', () => {
    const prompts = [{ id: 'who', type: 'person' }];
    expect(valueTypeOf(['who'], prompts, REGISTRY)).toBe('person');
    expect(valueTypeOf(['now', 'date'], prompts, REGISTRY)).toBe('date');
    expect(valueTypeOf(['nope'], prompts, REGISTRY)).toBeNull();
    expect(valueTypeOf(['who', 'nope', 'iso'], prompts, REGISTRY)).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/template-editor-completions.test.ts`
Expected: FAIL with `Failed to resolve import "../lib/template-editor/completions"`.

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/lib/template-editor/completions.ts`:

```ts
import type {
  Completion,
  CompletionContext,
  CompletionResult,
  CompletionSource,
} from '@codemirror/autocomplete';
import type { TemplateFunctionSpec, TemplateRegistry } from '../../../shared/api-types';
import { cursorContext, extractPrompts, type CursorContext, type PromptInfo } from './analyze';

/** Values the query completions offer that do not live in the registry. */
export interface QueryValueHints {
  types: string[];
  statuses: string[];
  contexts: string[];
}

export interface TemplateEditorData {
  registry: TemplateRegistry | null;
  hints: QueryValueHints;
}

export const EMPTY_HINTS: QueryValueHints = { types: [], statuses: [], contexts: [] };
export const SORT_VALUES = ['created desc', 'created asc', 'updated desc', 'updated asc'];

/** The registry doc string, plus its example: what every completion and hover shows. */
export function specInfo(spec: TemplateFunctionSpec): string {
  return spec.example ? `${spec.doc}\n\nExample: ${spec.example}` : spec.doc;
}

/** The value type a dotted name resolves to, e.g. ['person'] → 'person',
 * ['now', 'date'] → 'date'; null when any step is unknown. */
export function valueTypeOf(
  path: string[],
  prompts: PromptInfo[],
  reg: TemplateRegistry,
): string | null {
  const [root, ...rest] = path;
  if (root === undefined) return null;
  const prompt = prompts.find((p) => p.id === root);
  let type: string | null = prompt
    ? (reg.promptTypes.find((t) => t.name === prompt.type)?.type ?? 'text')
    : (reg.variables.find((v) => v.name === root)?.type ?? null);
  for (const name of rest) {
    if (type === null) return null;
    const owner: string = type;
    type = reg.fields.find((f) => f.owner === owner && f.name === name)?.type ?? null;
  }
  return type;
}

function fromSpec(spec: TemplateFunctionSpec, type: string, apply?: string): Completion {
  return { label: spec.name, type, detail: spec.type, info: specInfo(spec), apply };
}

function uniq(values: string[]): string[] {
  return [...new Set(values.filter((v) => v.trim() !== ''))];
}

function queryValues(key: string, hints: QueryValueHints): string[] {
  if (key === 'status') return uniq(['open', ...hints.statuses]);
  if (key === 'sort') return SORT_VALUES;
  if (key === 'type') return uniq(hints.types);
  if (key === 'context') return uniq(hints.contexts);
  return [];
}

export function optionsFor(
  cur: CursorContext,
  text: string,
  reg: TemplateRegistry,
  hints: QueryValueHints,
): Completion[] {
  switch (cur.kind) {
    case 'variable': {
      const prompts = extractPrompts(text);
      const own = prompts.map<Completion>((p) => {
        const typeSpec = reg.promptTypes.find((t) => t.name === p.type);
        return {
          label: p.id,
          type: 'variable',
          detail: `prompt · ${p.type}`,
          info: `Your template's own prompt \`${p.id}\`.${typeSpec ? `\n\n${specInfo(typeSpec)}` : ''}`,
          boost: 2,
        };
      });
      const ids = new Set(prompts.map((p) => p.id));
      return [
        ...own,
        ...reg.variables.filter((v) => !ids.has(v.name)).map((v) => fromSpec(v, 'variable')),
      ];
    }
    case 'field': {
      const owner = valueTypeOf(cur.ownerPath, extractPrompts(text), reg);
      return owner === null
        ? []
        : reg.fields.filter((f) => f.owner === owner).map((f) => fromSpec(f, 'property'));
    }
    case 'filter':
      return reg.filters.map((f) => fromSpec(f, 'function', f.argRequired ? `${f.name}: ` : f.name));
    case 'prompt-type':
      return reg.promptTypes.map((t) => fromSpec(t, 'type'));
    case 'query-key':
      return (reg.queryKeys ?? []).map((k) => fromSpec(k, 'keyword', `${k.name}: `));
    case 'query-value': {
      const spec = (reg.queryKeys ?? []).find((k) => k.name === cur.key);
      if (!spec) return [];
      return queryValues(cur.key, hints).map<Completion>((v) => ({
        label: v,
        type: 'constant',
        detail: cur.key,
        info: specInfo(spec),
      }));
    }
  }
}

/** Completions after `{{`, after `|`, for prompt `type:`, and inside ```query
 * fences, all from the C1 registry (query keys only when C2 added them). */
export function templateCompletions(getData: () => TemplateEditorData): CompletionSource {
  return (ctx: CompletionContext): CompletionResult | null => {
    const { registry, hints } = getData();
    if (!registry) return null;
    const text = ctx.state.doc.toString();
    const cur = cursorContext(text, ctx.pos);
    if (!cur) return null;
    const options = optionsFor(cur, text, registry, hints);
    if (options.length === 0) return null;
    return {
      from: cur.from,
      options,
      validFor: cur.kind === 'query-value' ? /^[^"'\n]*$/ : /^[A-Za-z0-9_]*$/,
    };
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/template-editor-completions.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$C3"
git add desktop/src/renderer/lib/template-editor/completions.ts desktop/src/renderer/__tests__/template-editor-completions.test.ts
git commit -m "feat(desktop): template completions from the function registry"
```

---

### Task 8: Hover docs, lint markers and the extension bundle

**Files:**
- Create: `desktop/src/renderer/lib/template-editor/hover.ts`
- Create: `desktop/src/renderer/lib/template-editor/lint.ts`
- Create: `desktop/src/renderer/lib/template-editor/extensions.ts`
- Test: `desktop/src/renderer/__tests__/template-editor-hover-lint.test.ts`

**Interfaces:**
- Consumes: Task 6 (`extractPrompts`, `inQueryFence`, `promptsSection`), Task 7 (`specInfo`, `valueTypeOf`, `templateCompletions`, `TemplateEditorData`), `hoverTooltip`/`Tooltip`/`EditorView` from `@codemirror/view`, `linter`/`Diagnostic` from `@codemirror/lint`, `Text`/`Extension` from `@codemirror/state`, `autocompletion` from `@codemirror/autocomplete`, `markdown` from `@codemirror/lang-markdown`.
- Produces: `hoverAt`, `hoverDom`, `templateHover`, `TEMPLATE_LINT_DELAY_MS`, `FetchLint`, `toCmDiagnostics`, `templateLintSource`, `templateLinter`, `templateEditorExtensions(getData, fetchLint)`. Task 10 uses `templateEditorExtensions` with `lintTemplate` (Task 5).

- [ ] **Step 1: Write the failing tests**

`desktop/src/renderer/__tests__/template-editor-hover-lint.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest';
import { EditorState } from '@codemirror/state';
import { hoverAt, hoverDom } from '../lib/template-editor/hover';
import {
  TEMPLATE_LINT_DELAY_MS,
  templateLintSource,
  toCmDiagnostics,
} from '../lib/template-editor/lint';
import { REGISTRY, TEMPLATE } from './helpers/template-registry';

const posOf = (needle: string, offset = 0) => TEMPLATE.indexOf(needle) + offset;

describe('template hover docs', () => {
  it('describes a prompt, a field and a filter inside placeholders', () => {
    const prompt = hoverAt(TEMPLATE, posOf('{{person.link}}', 3), REGISTRY)!;
    expect(prompt.title).toBe('person — prompt (person)');
    expect(prompt.info).toBe('A person.\n\nExample: type: person');
    expect(TEMPLATE.slice(prompt.from, prompt.to)).toBe('person');

    const field = hoverAt(TEMPLATE, posOf('{{person.link}}', 10), REGISTRY)!;
    expect(field.title).toBe('person.link: text');
    expect(field.info).toContain('A wikilink to the person.');

    const filter = hoverAt(TEMPLATE, posOf('format: YYYY', 2), REGISTRY)!;
    expect(filter.title).toBe('| format');
    const variable = hoverAt(TEMPLATE, posOf('{{date |', 3), REGISTRY)!;
    expect(variable.title).toBe('date: date');
  });

  it('describes prompt types and query keys', () => {
    expect(hoverAt(TEMPLATE, posOf('type: person', 8), REGISTRY)!.title).toBe('type: person');
    expect(hoverAt(TEMPLATE, posOf('status: open', 2), REGISTRY)!.title).toBe('status:');
  });

  it('says nothing for unknown names, filter arguments, values and plain text', () => {
    const src = TEMPLATE.replace('{{person.link}}', '{{nobody}}');
    expect(hoverAt(src, src.indexOf('{{nobody}}') + 3, REGISTRY)).toBeNull();
    expect(hoverAt(TEMPLATE, posOf('YYYY-MM-DD', 1), REGISTRY)).toBeNull();
    expect(hoverAt(TEMPLATE, posOf('status: open', 9), REGISTRY)).toBeNull();
    expect(hoverAt(TEMPLATE, posOf('# 1-1 with', 3), REGISTRY)).toBeNull();
    expect(hoverAt(TEMPLATE, posOf('type: meeting', 1), REGISTRY)).toBeNull();
  });

  it('renders hover text without interpreting markup', () => {
    const dom = hoverDom({ from: 0, to: 1, title: '<b>x</b>', info: '<img src=x onerror=alert(1)>' });
    expect(dom.querySelector('img')).toBeNull();
    expect(dom.textContent).toContain('<img src=x onerror=alert(1)>');
  });
});

describe('template lint mapping', () => {
  const doc = EditorState.create({ doc: TEMPLATE }).doc;

  it('debounces at 500 ms', () => {
    expect(TEMPLATE_LINT_DELAY_MS).toBe(500);
  });

  it('maps a placeholder diagnostic onto the whole placeholder', () => {
    const line = TEMPLATE.split('\n').indexOf('# 1-1 with {{person.link}}') + 1;
    const [d] = toCmDiagnostics(doc, [
      { line, col: 12, severity: 'warning', message: 'unknown', code: 'unknown-name' },
    ]);
    expect(doc.sliceString(d!.from, d!.to)).toBe('{{person.link}}');
    expect(d).toMatchObject({ severity: 'warning', message: 'unknown', source: 'template' });
  });

  it('maps other diagnostics onto the word and clamps out-of-range positions', () => {
    const [word, past] = toCmDiagnostics(doc, [
      { line: 3, col: 3, severity: 'error', message: 'bad', code: 'schema' },
      { line: 999, col: 999, severity: 'info', message: 'end', code: 'x' },
    ]);
    expect(doc.sliceString(word!.from, word!.to)).toBe('name');
    expect(past!.from).toBe(doc.length);
    expect(past!.to).toBe(doc.length);
  });

  it('lints the current document and shows nothing when the request fails', async () => {
    const state = EditorState.create({ doc: TEMPLATE });
    const ok = vi.fn().mockResolvedValue([{ line: 1, col: 1, severity: 'error', message: 'x', code: 'y' }]);
    expect(await templateLintSource(ok)({ state })).toHaveLength(1);
    expect(ok).toHaveBeenCalledWith(TEMPLATE);
    const failing = vi.fn().mockRejectedValue(new Error('sidecar down'));
    expect(await templateLintSource(failing)({ state })).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/template-editor-hover-lint.test.ts`
Expected: FAIL with `Failed to resolve import "../lib/template-editor/hover"`.

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/lib/template-editor/hover.ts`:

```ts
import { hoverTooltip, type Tooltip } from '@codemirror/view';
import type { TemplateFunctionSpec, TemplateRegistry } from '../../../shared/api-types';
import { extractPrompts, inQueryFence, promptsSection } from './analyze';
import { specInfo, valueTypeOf, type TemplateEditorData } from './completions';

export interface HoverHit {
  from: number;
  to: number;
  title: string;
  info: string;
}

const WORD = /[A-Za-z0-9_]/;

function hit(from: number, to: number, title: string, spec: TemplateFunctionSpec): HoverHit {
  return { from, to, title, info: specInfo(spec) };
}

/** Split a placeholder expression on `|` outside double quotes; returns each
 * segment's start offset within `expr`. */
function segments(expr: string): { start: number; text: string }[] {
  const out: { start: number; text: string }[] = [];
  let start = 0;
  let quoted = false;
  for (let i = 0; i < expr.length; i += 1) {
    const ch = expr[i];
    if (ch === '\\' && quoted) i += 1;
    else if (ch === '"') quoted = !quoted;
    else if (ch === '|' && !quoted) {
      out.push({ start, text: expr.slice(start, i) });
      start = i + 1;
    }
  }
  out.push({ start, text: expr.slice(start) });
  return out;
}

function placeholderHit(
  text: string,
  wordFrom: number,
  wordTo: number,
  lineStart: number,
  lineEnd: number,
  reg: TemplateRegistry,
): HoverHit | null | undefined {
  const open = text.lastIndexOf('{{', wordFrom);
  if (open < lineStart || text.slice(open, wordFrom).includes('}}')) return undefined;
  const close = text.indexOf('}}', wordTo);
  if (close < 0 || close > lineEnd) return undefined;
  const expr = text.slice(open + 2, close);
  const rel = wordFrom - (open + 2);
  const word = text.slice(wordFrom, wordTo);
  const segs = segments(expr);
  const seg = [...segs].reverse().find((s) => s.start <= rel);
  if (!seg) return null;
  if (seg === segs[0]) {
    const names = seg.text.trim().split('.');
    const lead = seg.text.length - seg.text.trimStart().length;
    let offset = seg.start + lead;
    for (let i = 0; i < names.length; i += 1) {
      const name = names[i]!;
      if (rel === offset && word === name) {
        const prompts = extractPrompts(text);
        if (i === 0) {
          const prompt = prompts.find((p) => p.id === name);
          if (prompt) {
            const typeSpec = reg.promptTypes.find((t) => t.name === prompt.type);
            return {
              from: wordFrom,
              to: wordTo,
              title: `${name} — prompt (${prompt.type})`,
              info: typeSpec ? specInfo(typeSpec) : 'A prompt of this template.',
            };
          }
          const spec = reg.variables.find((v) => v.name === name);
          return spec ? hit(wordFrom, wordTo, `${name}: ${spec.type}`, spec) : null;
        }
        const owner = valueTypeOf(names.slice(0, i), prompts, reg);
        const spec = reg.fields.find((f) => f.owner === owner && f.name === name);
        return spec ? hit(wordFrom, wordTo, `${names.slice(0, i + 1).join('.')}: ${spec.type}`, spec) : null;
      }
      offset += name.length + 1;
    }
    return null;
  }
  const filterName = seg.text.split(':')[0]!;
  const lead = filterName.length - filterName.trimStart().length;
  if (rel !== seg.start + lead || word !== filterName.trim()) return null;
  const spec = reg.filters.find((f) => f.name === word);
  return spec ? hit(wordFrom, wordTo, `| ${word}`, spec) : null;
}

/** The registry entry under `pos`: a placeholder name, field or filter, a
 * prompt `type:` value, or a ```query key. */
export function hoverAt(text: string, pos: number, reg: TemplateRegistry): HoverHit | null {
  let wordFrom = pos;
  let wordTo = pos;
  while (wordFrom > 0 && WORD.test(text[wordFrom - 1]!)) wordFrom -= 1;
  while (wordTo < text.length && WORD.test(text[wordTo]!)) wordTo += 1;
  if (wordFrom === wordTo) return null;
  const word = text.slice(wordFrom, wordTo);
  const lineStart = text.lastIndexOf('\n', wordFrom - 1) + 1;
  const nl = text.indexOf('\n', wordTo);
  const lineEnd = nl < 0 ? text.length : nl;

  const inPlaceholder = placeholderHit(text, wordFrom, wordTo, lineStart, lineEnd, reg);
  if (inPlaceholder !== undefined) return inPlaceholder;

  const before = text.slice(lineStart, wordFrom);
  const section = promptsSection(text);
  if (section && wordFrom >= section.start && wordFrom <= section.end) {
    if (/^[ \t]*(?:-[ \t]+)?type:[ \t]*["']?$/.test(before)) {
      const spec = reg.promptTypes.find((t) => t.name === word);
      return spec ? hit(wordFrom, wordTo, `type: ${word}`, spec) : null;
    }
    return null;
  }
  if (inQueryFence(text, wordFrom) && /^[ \t]*$/.test(before) && text[wordTo] !== undefined) {
    if (!/^[ \t]*:/.test(text.slice(wordTo, lineEnd))) return null;
    const spec = (reg.queryKeys ?? []).find((k) => k.name === word.toLowerCase());
    return spec ? hit(wordFrom, wordTo, `${spec.name}:`, spec) : null;
  }
  return null;
}

export function hoverDom(h: HoverHit): HTMLElement {
  const dom = document.createElement('div');
  dom.className = 'gb-template-hover max-w-[360px] px-3 py-2 text-12';
  const title = document.createElement('div');
  title.className = 'font-mono text-11 text-ink-0';
  title.textContent = h.title;
  const info = document.createElement('div');
  info.className = 'mt-1 whitespace-pre-wrap text-ink-1';
  info.textContent = h.info;
  dom.append(title, info);
  return dom;
}

export function templateHover(getData: () => TemplateEditorData) {
  return hoverTooltip((view, pos): Tooltip | null => {
    const reg = getData().registry;
    if (!reg) return null;
    const h = hoverAt(view.state.doc.toString(), pos, reg);
    if (!h) return null;
    return { pos: h.from, end: h.to, above: true, create: () => ({ dom: hoverDom(h) }) };
  });
}
```

`desktop/src/renderer/lib/template-editor/lint.ts`:

```ts
import { linter, type Diagnostic } from '@codemirror/lint';
import type { Text } from '@codemirror/state';
import type { EditorView } from '@codemirror/view';
import type { TemplateDiagnostic } from '../../../shared/api-types';

/** Spec C3: lint via /v1/templates/lint, debounced 500 ms. */
export const TEMPLATE_LINT_DELAY_MS = 500;

export type FetchLint = (source: string) => Promise<TemplateDiagnostic[]>;

/** Server diagnostics (1-based line/col, whole file) → CodeMirror ranges.
 * A range covers the `{{ … }}` at that spot, else the word, else one char. */
export function toCmDiagnostics(doc: Text, diags: TemplateDiagnostic[]): Diagnostic[] {
  return diags.map((d) => {
    const line = doc.line(Math.min(Math.max(d.line, 1), doc.lines));
    const from = Math.min(line.from + Math.max(d.col - 1, 0), line.to);
    const rest = doc.sliceString(from, line.to);
    let to = from;
    if (rest.startsWith('{{')) {
      const close = rest.indexOf('}}');
      to = close >= 0 ? from + close + 2 : line.to;
    } else {
      const word = /^[^\s:]+/.exec(rest);
      to = word ? from + word[0].length : Math.min(from + 1, line.to);
    }
    return { from, to, severity: d.severity, message: d.message, source: 'template' };
  });
}

/** A CodeMirror lint source. A failed request shows no markers rather than
 * stale or invented ones. */
export function templateLintSource(fetchLint: FetchLint) {
  return async (view: Pick<EditorView, 'state'>): Promise<Diagnostic[]> => {
    const doc = view.state.doc;
    try {
      return toCmDiagnostics(doc, await fetchLint(doc.toString()));
    } catch {
      return [];
    }
  };
}

export function templateLinter(fetchLint: FetchLint) {
  return linter(templateLintSource(fetchLint), { delay: TEMPLATE_LINT_DELAY_MS });
}
```

`desktop/src/renderer/lib/template-editor/extensions.ts`:

```ts
import { autocompletion } from '@codemirror/autocomplete';
import { markdown } from '@codemirror/lang-markdown';
import type { Extension } from '@codemirror/state';
import { templateCompletions, type TemplateEditorData } from './completions';
import { templateHover } from './hover';
import { templateLinter, type FetchLint } from './lint';

/** Everything the template editor adds to CodeMirror. `getData` is read on
 * every request, so registry and hints can load after the editor mounts. */
export function templateEditorExtensions(
  getData: () => TemplateEditorData,
  fetchLint: FetchLint,
): Extension[] {
  return [
    markdown(),
    autocompletion({ override: [templateCompletions(getData)] }),
    templateHover(getData),
    templateLinter(fetchLint),
  ];
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/template-editor-hover-lint.test.ts src/renderer/__tests__/template-editor-completions.test.ts src/renderer/__tests__/template-editor-analyze.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$C3"
git add desktop/src/renderer/lib/template-editor/hover.ts desktop/src/renderer/lib/template-editor/lint.ts desktop/src/renderer/lib/template-editor/extensions.ts desktop/src/renderer/__tests__/template-editor-hover-lint.test.ts
git commit -m "feat(desktop): template hover docs and debounced sidecar lint"
```

---

### Task 9: Test run pane (`TemplateTestRun`)

**Files:**
- Create: `desktop/src/renderer/components/TemplateTestRun.tsx`
- Test: `desktop/src/renderer/__tests__/TemplateTestRun.test.tsx`

**Interfaces:**
- Consumes: Task 5 (`useTemplateDryRun`, `initialAnswers`, `TemplateDryRunResponse`, `stubLocalStorage`), Task 6 (`extractPrompts`), the existing `RichMarkdownEditor` (`markdown`, `onSave`, `readOnly`, `jotId`) and `Btn`.
- Produces: `<TemplateTestRun templateId source />`: runs once on mount, then on "run again"; one labelled input per prompt (label = the prompt's `ask`); "would be filed at" + the rendered body through `RichMarkdownEditor` read-only (C2's query blocks run there, with ticking disabled because the editor is read-only); errors in a `role="alert"`.

- [ ] **Step 1: Write the failing test**

`desktop/src/renderer/__tests__/TemplateTestRun.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { TemplateTestRun } from '../components/TemplateTestRun';
import { rememberAnswers } from '../lib/templates/last-answers';
import type { TemplateDryRunResponse } from '../../shared/api-types';
import { TEMPLATE } from './helpers/template-registry';
import { stubLocalStorage } from './helpers/memory-storage';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const postMock = vi.mocked(client.post);

const PROMPTS = [
  { id: 'person', ask: 'Who?', type: 'person' as const, optional: false, default: null, options: [] },
  { id: 'focus', ask: 'Focus?', type: 'text' as const, optional: true, default: null, options: [] },
];

function ok(person: string): TemplateDryRunResponse {
  return {
    ok: true,
    prompts: PROMPTS,
    answers: { person },
    rendered: {
      path: `20-contexts/work/one-on-ones/2026-10-09-${person.toLowerCase()}-1-1.md`,
      folder: '20-contexts/work/one-on-ones',
      filename: 'x.md',
      title: `2026-10-09 ${person} 1-1`,
      frontmatter: {},
      body: `# 1-1 with [[${person}]]\n`,
      markdown: '',
    },
    wouldBeFiledAt: `20-contexts/work/one-on-ones/2026-10-09-${person.toLowerCase()}-1-1-2.md`,
    diagnostics: [],
    error: null,
  };
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <TemplateTestRun templateId="one-on-one" source={TEMPLATE} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  stubLocalStorage();
});
afterEach(() => {
  postMock.mockReset();
  vi.unstubAllGlobals();
});

describe('TemplateTestRun', () => {
  it('runs once on open with remembered answers and shows the filed path and rendered note', async () => {
    rememberAnswers('one-on-one', { person: 'Alex' });
    postMock.mockResolvedValue(ok('Alex'));
    mount();
    expect(await screen.findByText('20-contexts/work/one-on-ones/2026-10-09-alex-1-1-2.md')).toBeInTheDocument();
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(postMock).toHaveBeenCalledWith('/v1/templates/render', {
      source: TEMPLATE,
      answers: { person: 'Alex' },
      id: 'one-on-one',
      dry_run: true,
    });
    await waitFor(() => expect(screen.getByText(/1-1 with/)).toBeInTheDocument());
    expect(screen.getByLabelText('Who?')).toHaveValue('Alex');
    expect(screen.getByLabelText('Focus?')).toHaveValue('');
  });

  it('runs again with edited answers', async () => {
    postMock.mockResolvedValueOnce(ok('Sample Person'));
    mount();
    const who = await screen.findByLabelText('Who?');
    expect(who).toHaveValue('Sample Person');
    fireEvent.change(who, { target: { value: 'Robin' } });
    postMock.mockResolvedValueOnce(ok('Robin'));
    fireEvent.click(screen.getByRole('button', { name: 'run again' }));
    await waitFor(() =>
      expect(postMock).toHaveBeenLastCalledWith('/v1/templates/render', {
        source: TEMPLATE,
        answers: { person: 'Robin' },
        id: 'one-on-one',
        dry_run: true,
      }),
    );
    expect(await screen.findByText('20-contexts/work/one-on-ones/2026-10-09-robin-1-1-2.md')).toBeInTheDocument();
  });

  it('shows a render error inline and keeps the typed answers', async () => {
    postMock.mockResolvedValueOnce({
      ok: false,
      prompts: PROMPTS,
      answers: {},
      rendered: null,
      wouldBeFiledAt: null,
      diagnostics: [],
      error: 'person: a person can not contain [ ] | #',
    });
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('person: a person can not contain');
    expect(screen.queryByText(/would be filed at/)).not.toBeInTheDocument();
  });

  it('shows a sidecar failure', async () => {
    postMock.mockRejectedValueOnce(new Error('sidecar down'));
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('test run failed — sidecar down');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/TemplateTestRun.test.tsx`
Expected: FAIL with `Failed to resolve import "../components/TemplateTestRun"`.

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/components/TemplateTestRun.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react';
import { useTemplateDryRun } from '../lib/api/template-editor';
import { extractPrompts } from '../lib/template-editor/analyze';
import { initialAnswers } from '../lib/templates/last-answers';
import type { TemplateDryRunResponse } from '../../shared/api-types';
import { Btn } from './Btn';
import { RichMarkdownEditor } from './RichMarkdownEditor';

const noop = () => {};

/** Spec C3 Test run: render the editor's current text with sample answers
 * (last real answers first) and show the result through the normal rich
 * renderer, read-only, with the target path. Nothing is written. */
export function TemplateTestRun({ templateId, source }: { templateId: string; source: string }) {
  const run = useTemplateDryRun();
  const [answers, setAnswers] = useState<Record<string, string>>(() =>
    initialAnswers(
      templateId,
      extractPrompts(source).map((p) => p.id),
    ),
  );
  const [result, setResult] = useState<TemplateDryRunResponse | null>(null);
  const [runs, setRuns] = useState(0);

  function go(next: Record<string, string>) {
    run.mutate(
      { source, answers: next, id: templateId },
      {
        onSuccess: (res) => {
          setResult(res);
          setAnswers(res.ok ? res.answers : { ...res.answers, ...next });
          setRuns((n) => n + 1);
        },
      },
    );
  }

  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    go(answers);
  });

  const prompts = result?.prompts ?? [];
  return (
    <div className="flex h-full flex-col overflow-hidden" aria-label="test run">
      <div className="flex-shrink-0 border-b border-hairline px-4 py-3">
        {prompts.map((p) => (
          <label key={p.id} className="mb-2 block text-12 text-ink-1">
            {p.ask}
            <input
              aria-label={p.ask}
              value={answers[p.id] ?? ''}
              placeholder={p.optional ? 'optional' : ''}
              onChange={(e) => setAnswers((a) => ({ ...a, [p.id]: e.target.value }))}
              className="mt-1 block w-full rounded-sm border border-hairline-2 bg-vellum px-2 py-1 text-12 text-ink-0"
            />
          </label>
        ))}
        <Btn variant="secondary" size="sm" onClick={() => go(answers)} disabled={run.isPending}>
          {run.isPending ? 'rendering…' : 'run again'}
        </Btn>
      </div>
      <div className="flex-1 overflow-auto px-4 py-3">
        {run.isError && (
          <p role="alert" className="text-12 text-oxblood">
            test run failed — {run.error instanceof Error ? run.error.message : 'error'}
          </p>
        )}
        {result?.error && (
          <p role="alert" className="text-12 text-oxblood">
            {result.error}
          </p>
        )}
        {result?.wouldBeFiledAt && (
          <p className="mb-2 font-mono text-11 text-ink-2">
            would be filed at <code>{result.wouldBeFiledAt}</code>
          </p>
        )}
        {result?.rendered && (
          <RichMarkdownEditor
            key={runs}
            markdown={result.rendered.body}
            onSave={noop}
            readOnly
            jotId={`template-preview-${templateId}`}
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/TemplateTestRun.test.tsx && npm run typecheck && npx eslint --max-warnings 0 src/renderer/components/TemplateTestRun.tsx src/renderer/__tests__/TemplateTestRun.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$C3"
git add desktop/src/renderer/components/TemplateTestRun.tsx desktop/src/renderer/__tests__/TemplateTestRun.test.tsx
git commit -m "feat(desktop): template test run pane with sample answers and the rich renderer"
```

---

### Task 10: Template source editor (`TemplateSourceEditor`)

**Files:**
- Create: `desktop/src/renderer/components/TemplateSourceEditor.tsx`
- Test: `desktop/src/renderer/__tests__/TemplateSourceEditor.test.tsx`

**Interfaces:**
- Consumes: Task 5 (`useTemplateSource`, `useTemplateFunctions`, `useTemplateQueryValues`, `lintTemplate`, `saveTemplateSource`), Task 7 (`EMPTY_HINTS`, `TemplateEditorData`), Task 8 (`templateEditorExtensions`), Task 9 (`TemplateTestRun`); `useContexts` from `lib/api/hooks`; `ApiError` (`.status`); `registerNavigationGuard` from `stores/navigation`; `toast`; `CodeMirror` from `@uiw/react-codemirror`; `keymap` from `@codemirror/view`, `Prec` from `@codemirror/state`.
- Produces: `TemplateSourceEditor({ templateId, onDirtyChange?, onCreateEditor? })` and `DISCARD_TEMPLATE_PROMPT`. Buttons: "test run" (toggle), "save" (disabled unless dirty). On 409: an alert "this template changed outside the editor…" with "reload theirs" and "keep mine". Task 11 hosts it.

- [ ] **Step 1: Write the failing test**

`desktop/src/renderer/__tests__/TemplateSourceEditor.test.tsx` (CodeMirror cannot be typed into in jsdom, so, like `JotEditor.test.tsx`, edits go through the `EditorView` from `onCreateEditor`; jsdom also logs a harmless `getClientRects` measuring error from CodeMirror):

```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { EditorView } from '@codemirror/view';
import * as client from '../lib/api/client';
import { TemplateSourceEditor } from '../components/TemplateSourceEditor';
import { navigationAllowed } from '../stores/navigation';
import { REGISTRY, TEMPLATE } from './helpers/template-registry';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
vi.mock('../components/TemplateTestRun', () => ({
  TemplateTestRun: ({ source }: { source: string }) => <div data-testid="test-run">{source.length}</div>,
}));
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);
const patchMock = vi.mocked(client.patch);

const SOURCE = { id: 'one-on-one', path: '90-meta/templates/one-on-one.md', source: TEMPLATE, etag: 'e1' };

function setup(onDirtyChange?: (d: boolean) => void) {
  let view: EditorView | undefined;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <TemplateSourceEditor
        templateId="one-on-one"
        onDirtyChange={onDirtyChange}
        onCreateEditor={(v) => {
          view = v;
        }}
      />
    </QueryClientProvider>,
  );
  return {
    edit(text: string) {
      act(() => {
        if (!view) throw new Error('no editor');
        view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
      });
    },
  };
}

beforeEach(() => {
  getMock.mockImplementation(async (path: string) => {
    if (path === '/v1/templates/one-on-one/source') return SOURCE;
    if (path === '/v1/templates/functions') return REGISTRY;
    if (path === '/v1/templates/query-values') return { types: [], statuses: [], indexing: false };
    if (path === '/v1/vault/contexts') return { contexts: ['work'] };
    throw new Error(`unexpected GET ${path}`);
  });
  postMock.mockResolvedValue({ diagnostics: [] });
});
afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
  vi.restoreAllMocks();
});

describe('TemplateSourceEditor', () => {
  it('loads the template source and its path', async () => {
    setup();
    expect(await screen.findByText('90-meta/templates/one-on-one.md')).toBeInTheDocument();
    expect(screen.getByText(/1-1 with/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'save' })).toBeDisabled();
  });

  it('saves the edited text with the etag it loaded', async () => {
    const dirty = vi.fn();
    const ed = setup(dirty);
    await screen.findByText('90-meta/templates/one-on-one.md');
    ed.edit(TEMPLATE + '\nmore\n');
    expect(dirty).toHaveBeenLastCalledWith(true);
    expect(screen.getByText('unsaved')).toBeInTheDocument();
    patchMock.mockResolvedValue({ id: 'one-on-one', path: SOURCE.path, etag: 'e2', status: 'applied', changeId: null });
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
    expect(patchMock).toHaveBeenCalledWith(
      '/v1/templates/one-on-one/source',
      { source: TEMPLATE + '\nmore\n' },
      { ifMatch: 'e1' },
    );
  });

  it('on 409 shows the conflict banner; keep mine overwrites without an etag', async () => {
    const ed = setup();
    await screen.findByText('90-meta/templates/one-on-one.md');
    ed.edit('changed\n');
    patchMock.mockRejectedValueOnce(new client.ApiError('changed', 409));
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('changed outside the editor');
    patchMock.mockResolvedValueOnce({ id: 'one-on-one', path: SOURCE.path, etag: 'e3', status: 'applied', changeId: null });
    fireEvent.click(screen.getByRole('button', { name: 'keep mine' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(patchMock).toHaveBeenLastCalledWith('/v1/templates/one-on-one/source', { source: 'changed\n' }, { ifMatch: null });
  });

  it('reload theirs replaces the text with the file on disk', async () => {
    const ed = setup();
    await screen.findByText('90-meta/templates/one-on-one.md');
    ed.edit('mine\n');
    patchMock.mockRejectedValueOnce(new client.ApiError('changed', 409));
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'reload theirs' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(screen.queryByText('unsaved')).not.toBeInTheDocument();
  });

  it('asks before leaving the screen with unsaved changes', async () => {
    const ed = setup();
    await screen.findByText('90-meta/templates/one-on-one.md');
    expect(navigationAllowed('screen')).toBe(true);
    ed.edit('mine\n');
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    expect(navigationAllowed('screen')).toBe(false);
    expect(confirm).toHaveBeenCalled();
  });

  it('toggles the test run pane with the current text', async () => {
    setup();
    await screen.findByText('90-meta/templates/one-on-one.md');
    fireEvent.click(screen.getByRole('button', { name: 'test run' }));
    expect(screen.getByTestId('test-run')).toHaveTextContent(String(TEMPLATE.length));
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/TemplateSourceEditor.test.tsx`
Expected: FAIL with `Failed to resolve import "../components/TemplateSourceEditor"`.

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/components/TemplateSourceEditor.tsx` (`basicSetup` turns its own autocompletion off, because two `autocompletion()` configs with an `override` conflict):

```tsx
import { useEffect, useMemo, useRef, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { keymap, type EditorView } from '@codemirror/view';
import { Prec } from '@codemirror/state';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '../lib/api/client';
import { useContexts } from '../lib/api/hooks';
import {
  lintTemplate,
  saveTemplateSource,
  useTemplateFunctions,
  useTemplateQueryValues,
  useTemplateSource,
} from '../lib/api/template-editor';
import { EMPTY_HINTS, type TemplateEditorData } from '../lib/template-editor/completions';
import { templateEditorExtensions } from '../lib/template-editor/extensions';
import { registerNavigationGuard } from '../stores/navigation';
import { toast } from '../stores/toast';
import { Btn } from './Btn';
import { Lucide } from './Lucide';
import { TemplateTestRun } from './TemplateTestRun';

export const DISCARD_TEMPLATE_PROMPT = 'Discard your unsaved template changes?';

interface Props {
  templateId: string;
  /** Told whenever the text starts or stops differing from the saved file. */
  onDirtyChange?: (dirty: boolean) => void;
  /** Called once with the CodeMirror view; tests drive edits through it. */
  onCreateEditor?: (view: EditorView) => void;
}

/** Spec C3: CodeMirror over a template file with registry-driven
 * completions, hover docs and lint, explicit save with an etag, and a
 * Test run pane. */
export function TemplateSourceEditor({ templateId, onDirtyChange, onCreateEditor }: Props) {
  const qc = useQueryClient();
  const src = useTemplateSource(templateId);
  const fns = useTemplateFunctions();
  const values = useTemplateQueryValues();
  const contexts = useContexts();
  const [value, setValue] = useState<string | null>(null);
  const [etag, setEtag] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [showRun, setShowRun] = useState(false);
  const dirty = value !== null && saved !== null && value !== saved;

  const data = useRef<TemplateEditorData>({ registry: null, hints: EMPTY_HINTS });
  useEffect(() => {
    data.current = {
      registry: fns.data ?? null,
      hints: {
        types: values.data?.types ?? [],
        statuses: values.data?.statuses ?? [],
        contexts: contexts.data?.contexts ?? [],
      },
    };
  }, [fns.data, values.data, contexts.data]);

  useEffect(() => {
    if (src.data && value === null) {
      setValue(src.data.source);
      setSaved(src.data.source);
      setEtag(src.data.etag);
    }
  }, [src.data, value]);

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;
  useEffect(
    () =>
      registerNavigationGuard('screen', () => !dirtyRef.current || window.confirm(DISCARD_TEMPLATE_PROMPT)),
    [],
  );

  async function save(overwrite = false) {
    if (value === null || saving) return;
    setSaving(true);
    try {
      const res = await saveTemplateSource(templateId, value, overwrite ? null : etag);
      setSaved(value);
      setEtag(res.etag);
      setConflict(false);
      void qc.invalidateQueries({ queryKey: ['templates'] });
      toast.success(res.status === 'pending' ? 'template saved for approval' : 'template saved');
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(true);
      else toast.error(`could not save template: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  }

  async function reload() {
    const res = await src.refetch();
    if (res.data) {
      setValue(res.data.source);
      setSaved(res.data.source);
      setEtag(res.data.etag);
      setConflict(false);
    }
  }

  const saveRef = useRef(save);
  saveRef.current = save;
  const extensions = useMemo(
    () => [
      ...templateEditorExtensions(() => data.current, lintTemplate),
      Prec.high(
        keymap.of([
          {
            key: 'Mod-s',
            run: () => {
              void saveRef.current();
              return true;
            },
          },
        ]),
      ),
    ],
    [],
  );

  if (src.isError) {
    return (
      <div role="alert" className="p-4 text-12 text-oxblood">
        could not open template — {src.error instanceof Error ? src.error.message : 'error'}
      </div>
    );
  }
  if (value === null) return <div className="p-4 font-mono text-11 text-ink-3">loading template…</div>;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-shrink-0 items-center gap-2 border-b border-hairline px-4 py-2">
        <span className="font-mono text-11 text-ink-2">{src.data?.path}</span>
        {dirty && <span className="font-mono text-10 text-ink-3">unsaved</span>}
        <div className="flex-1" />
        <Btn
          variant={showRun ? 'secondary' : 'ghost'}
          size="sm"
          icon={<Lucide name="play" size={13} />}
          onClick={() => setShowRun((s) => !s)}
        >
          test run
        </Btn>
        <Btn variant="primary" size="sm" onClick={() => void save()} disabled={!dirty || saving}>
          {saving ? 'saving…' : 'save'}
        </Btn>
      </div>
      {conflict && (
        <div role="alert" className="flex flex-shrink-0 items-center gap-2 bg-oxblood/10 px-4 py-2 text-12 text-ink-0">
          <span className="flex-1">this template changed outside the editor. your text is not saved.</span>
          <Btn variant="ghost" size="sm" onClick={() => void reload()}>
            reload theirs
          </Btn>
          <Btn variant="danger" size="sm" onClick={() => void save(true)}>
            keep mine
          </Btn>
        </div>
      )}
      <div className="flex flex-1 overflow-hidden">
        <div className="min-w-0 flex-1 overflow-auto">
          <CodeMirror
            value={value}
            extensions={extensions}
            basicSetup={{ lineNumbers: true, foldGutter: false, autocompletion: false }}
            onChange={setValue}
            onCreateEditor={onCreateEditor}
            theme="dark"
            className="h-full text-13"
          />
        </div>
        {showRun && (
          <div className="w-1/2 min-w-0 border-l border-hairline">
            <TemplateTestRun templateId={templateId} source={value} />
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/TemplateSourceEditor.test.tsx && npm run typecheck && npx eslint --max-warnings 0 src/renderer/components/TemplateSourceEditor.tsx src/renderer/__tests__/TemplateSourceEditor.test.tsx`
Expected: PASS (the `getClientRects` stderr lines are expected).

- [ ] **Step 5: Commit**

```bash
cd "$C3"
git add desktop/src/renderer/components/TemplateSourceEditor.tsx desktop/src/renderer/__tests__/TemplateSourceEditor.test.tsx
git commit -m "feat(desktop): template source editor with completions, hover, lint and etag save"
```

---

### Task 11: Templates tab (`TemplatesPanel`) in the Jots screen

**Files:**
- Create: `desktop/src/renderer/screens/templates.tsx`
- Modify: `desktop/src/renderer/screens/jots.tsx`
- Test: `desktop/src/renderer/__tests__/TemplatesPanel.test.tsx`
- Modify: `desktop/src/renderer/__tests__/jots.test.tsx` (append)

**Interfaces:**
- Consumes: Task 10 (`TemplateSourceEditor`, `DISCARD_TEMPLATE_PROMPT`), Task 5 (`useCreateBlankTemplate`), C1 `useTemplates` (`TemplateSummary.valid`), `TopBar`, `Btn` (`ariaLabel`), `Lucide`, `toast`; in `jots.tsx` the existing `confirmLeave(guardRef)`.
- Produces: `TemplatesPanel({ onBack })` with a "jots" back button (`aria-label="back to jots"`), "new template" (inline name form, `aria-label="template name"`, "create"), and one `edit template <name>` button per template. C4 adds a "make one with ai" button to its top bar.

- [ ] **Step 1: Write the failing tests**

`desktop/src/renderer/__tests__/TemplatesPanel.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { TemplatesPanel } from '../screens/templates';
import type { TemplateSummary } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const editorProps = vi.fn();
vi.mock('../components/TemplateSourceEditor', () => ({
  DISCARD_TEMPLATE_PROMPT: 'discard?',
  TemplateSourceEditor: (props: { templateId: string; onDirtyChange?: (d: boolean) => void }) => {
    editorProps(props);
    return (
      <div>
        editing {props.templateId}
        <button type="button" onClick={() => props.onDirtyChange?.(true)}>
          make dirty
        </button>
      </div>
    );
  },
}));
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

function summary(id: string, name: string, valid = true): TemplateSummary {
  return {
    id,
    path: `90-meta/templates/${id}.md`,
    name,
    description: '',
    prompts: [],
    variables: [],
    valid,
    diagnostics: valid ? [] : [{ line: 3, col: 1, severity: 'error', message: 'bad', code: 'yaml' }],
  };
}

function mount(onBack = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <TemplatesPanel onBack={onBack} />
    </QueryClientProvider>,
  );
  return onBack;
}

beforeEach(() => {
  getMock.mockResolvedValue({ templates: [summary('one-on-one', '1-1'), summary('broken', 'broken', false)] });
});
afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  editorProps.mockReset();
  vi.restoreAllMocks();
});

describe('TemplatesPanel', () => {
  it('lists templates, broken ones too, and opens one in the editor', async () => {
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'edit template broken' }));
    expect(screen.getByText('editing broken')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'edit template broken' })).toHaveTextContent('⚠');
  });

  it('creates a blank template and opens it', async () => {
    postMock.mockResolvedValue({ id: 'weekly-review', path: 'p', etag: 'e', status: 'applied', changeId: null });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'new template' }));
    fireEvent.change(screen.getByLabelText('template name'), { target: { value: 'Weekly review' } });
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    await waitFor(() => expect(screen.getByText('editing weekly-review')).toBeInTheDocument());
    expect(postMock).toHaveBeenCalledWith('/v1/templates', { name: 'Weekly review' });
  });

  it('asks before switching away from unsaved changes', async () => {
    const onBack = mount();
    fireEvent.click(await screen.findByRole('button', { name: 'edit template 1-1' }));
    fireEvent.click(screen.getByRole('button', { name: 'make dirty' }));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    fireEvent.click(screen.getByRole('button', { name: 'edit template broken' }));
    expect(screen.getByText('editing one-on-one')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'back to jots' }));
    expect(onBack).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'back to jots' }));
    expect(onBack).toHaveBeenCalled();
  });
});
```

Append to `desktop/src/renderer/__tests__/jots.test.tsx` (it reuses that file's `apiRequest`, `withConnectors`, `withQuery`, `page` and `detail`):

```tsx
describe('JotsScreen templates tab', () => {
  it('switches to the templates panel and back', async () => {
    apiRequest.mockImplementation(withConnectors(async (_m, path) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: page };
      if (path === '/v1/templates') return { ok: true, status: 200, data: { templates: [] } };
      return { ok: true, status: 200, data: detail };
    }));
    render(withQuery(<JotsScreen />));
    await screen.findByText('first jot');
    fireEvent.click(screen.getByRole('button', { name: 'templates' }));
    expect(await screen.findByRole('heading', { name: 'templates' })).toBeInTheDocument();
    expect(screen.getByText(/pick a template to edit/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'back to jots' }));
    expect(await screen.findByRole('heading', { name: 'jots' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$C3/desktop" && npx vitest run src/renderer/__tests__/TemplatesPanel.test.tsx src/renderer/__tests__/jots.test.tsx`
Expected: FAIL. `TemplatesPanel.test.tsx` cannot resolve `../screens/templates`, and the jots test finds no "templates" button.

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/screens/templates.tsx`:

```tsx
import { useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { DISCARD_TEMPLATE_PROMPT, TemplateSourceEditor } from '../components/TemplateSourceEditor';
import { useTemplates } from '../lib/api/hooks';
import { useCreateBlankTemplate } from '../lib/api/template-editor';
import { toast } from '../stores/toast';

/** Spec C3 "Templates screen (a tab in the jots screen)": list, create
 * blank, open the template editor. Broken templates open too — editing is
 * how they get fixed. */
export function TemplatesPanel({ onBack }: { onBack: () => void }) {
  const list = useTemplates();
  const createBlank = useCreateBlankTemplate();
  const [selected, setSelected] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [newName, setNewName] = useState<string | null>(null);

  function leaveOk(): boolean {
    return !dirty || window.confirm(DISCARD_TEMPLATE_PROMPT);
  }

  function select(id: string) {
    if (id === selected || !leaveOk()) return;
    setDirty(false);
    setSelected(id);
  }

  function submitNew() {
    const name = (newName ?? '').trim();
    if (!name || !leaveOk()) return;
    createBlank.mutate(name, {
      onSuccess: (res) => {
        setNewName(null);
        setDirty(false);
        setSelected(res.id);
      },
      onError: (err) => toast.error(`could not create template: ${err.message}`),
    });
  }

  const items = list.data?.templates ?? [];
  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="templates"
        subtitle="90-meta/templates"
        right={
          <div className="flex gap-2">
            <Btn
              variant="ghost"
              size="sm"
              ariaLabel="back to jots"
              icon={<Lucide name="arrow-left" size={13} />}
              onClick={() => {
                if (leaveOk()) onBack();
              }}
            >
              jots
            </Btn>
            <Btn variant="primary" size="sm" icon={<Lucide name="plus" size={13} />} onClick={() => setNewName('')}>
              new template
            </Btn>
          </div>
        }
      />
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[260px] flex-shrink-0 overflow-auto border-r border-hairline py-2">
          {newName !== null && (
            <form
              className="flex gap-1 px-3 pb-2"
              onSubmit={(e) => {
                e.preventDefault();
                submitNew();
              }}
            >
              <input
                autoFocus
                aria-label="template name"
                value={newName}
                maxLength={80}
                onChange={(e) => setNewName(e.target.value)}
                className="min-w-0 flex-1 rounded-sm border border-hairline-2 bg-vellum px-2 py-1 text-12 text-ink-0"
              />
              <Btn type="submit" size="sm" disabled={!newName.trim() || createBlank.isPending}>
                create
              </Btn>
            </form>
          )}
          {list.isLoading && <p className="px-3 font-mono text-11 text-ink-3">loading templates…</p>}
          {list.isError && (
            <p role="alert" className="px-3 text-12 text-oxblood">
              templates unavailable
            </p>
          )}
          <ul aria-label="templates">
            {items.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  aria-label={`edit template ${t.name}`}
                  aria-current={t.id === selected ? 'true' : undefined}
                  onClick={() => select(t.id)}
                  className="block w-full px-3 py-[6px] text-left text-12 text-ink-0 hover:bg-vellum aria-[current=true]:bg-vellum"
                >
                  {!t.valid && <span aria-hidden="true">⚠ </span>}
                  {t.name}
                  <span className="block font-mono text-10 text-ink-3">{t.id}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <section className="min-w-0 flex-1">
          {selected ? (
            <TemplateSourceEditor key={selected} templateId={selected} onDirtyChange={setDirty} />
          ) : (
            <p className="p-4 text-12 text-ink-3">pick a template to edit, or make a new one.</p>
          )}
        </section>
      </div>
    </div>
  );
}
```

In `desktop/src/renderer/screens/jots.tsx`:

1. Add `import { TemplatesPanel } from './templates';` after the `TopBar` import.
2. Make this the first line inside `export function JotsScreen() {`:

```tsx
  const [tab, setTab] = useState<'jots' | 'templates'>('jots');
```

3. Directly before the component's final `return (` (after every hook and handler), add:

```tsx
  if (tab === 'templates') return <TemplatesPanel onBack={() => setTab('jots')} />;
```

4. Inside the TopBar `right` `<div className="flex gap-2">`, insert this as the first child, before the "assist" `<Btn>`:

```tsx
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="layout-template" size={13} />}
              onClick={() => {
                if (confirmLeave(guardRef)) setTab('templates');
              }}
            >
              templates
            </Btn>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$C3/desktop" && npx vitest run && npm run typecheck && npm run lint`
Expected: PASS: the whole desktop suite, no type errors, no lint warnings.

- [ ] **Step 5: Commit**

```bash
cd "$C3"
git add desktop/src/renderer/screens/templates.tsx desktop/src/renderer/screens/jots.tsx desktop/src/renderer/__tests__/TemplatesPanel.test.tsx desktop/src/renderer/__tests__/jots.test.tsx
git commit -m "feat(desktop): templates tab in the jots screen with the template editor"
```

---

## Self-review

**Spec coverage (C3 rows):**
- Template editor in CodeMirror (already a dependency through `JotEditor`; `@codemirror/autocomplete` and `@codemirror/lint` added as direct, exactly pinned dependencies): Tasks 5, 10.
- Completions after `{{` (variables, the template's own prompt ids, fields), after `|` (filters), and inside ```query (keys; values: known types, contexts, `open`), each carrying its registry doc string: Tasks 6–7, values from Task 3/4's query hints.
- Hover tooltips with the same docs: Task 8.
- Lint via `@codemirror/lint` → `POST /v1/templates/lint`, debounced 500 ms: Tasks 1, 4, 8.
- Test run split pane: sample answers prefilled with the most recent real values, rendered through the normal rich renderer with live queries, "would be filed at …": Tasks 2, 4, 5, 9, 10.
- `POST /v1/templates/render {source, answers, dry_run: true}` (nothing written, lint diagnostics included) and `POST /v1/templates/lint {source}`: Task 4.
- Templates screen as a tab in the jots screen: list, create blank, open the template editor: Tasks 3, 4, 11. ("Make one with AI" is C4.)
- Error handling: a template that fails to parse opens in the editor with its diagnostics (Tasks 1, 11); query errors shown inline (Task 1 with C2).
- Testing rows: "template editor completions, hover docs and lint markers (mocked registry); test-run pane" (Tasks 7–10).

**Placeholder scan:** every code step carries the full file or the exact edit; the only conditional step is the C2 feature check, which is code (`query_parser()`, `registry.queryKeys ?? []`, `importorskip`), not a deferred decision.

**Type consistency:** `DryRunResult.to_json()` keys = `TemplateDryRunResponse`; `SavedTemplate.to_json()` = `TemplateSaveResponse` (`changeId`); `TemplateSource.to_json()` = `TemplateSourceResponse`; `query_values()` = `TemplateQueryValues`; `useTemplateDryRun` posts `dry_run: true` that the route's `Literal[True]` requires; `TemplateEditorData` is produced by the editor and read by completions and hover; `FetchLint` matches `lintTemplate`; `DISCARD_TEMPLATE_PROMPT` is exported by Task 10 and mocked by Task 11's test.

**Review Focus:** each of the five lines names its pinning test, and those tests are in the owning tasks above.
