# C1 Smart Templates — Engine + Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users can make a note from a template. They pick a template next to "new" on the Jots screen, answer a prompt or two (a person comes from the link index), and get a note that is named, filed and filled in. `/template` in the editor inserts a template's rendered body into the current note. Three starter templates ship: 1-1, Meeting notes and Decision record.

**Architecture:** `ghostbrain/templates/` is a new backend package. `lang.py` tokenizes `{{ name.field | filter: arg }}`. `values.py` holds the typed values. `functions.py` is the single registry of variables, fields, filters and prompt types, and the renderer, the API and the later linter all read it. `parse.py` validates a template file into a `Template` and returns line-numbered `Diagnostic`s. `render.py` turns a `Template` plus answers into a `RenderedNote`: one pass, size-capped, with the folder validated. `registry.py` lists and loads templates from `90-meta/templates/`, and `starters.py` seeds them. `env.py` gathers contexts, projects, the user's name and person titles. `create.py` renders and writes through B1's `vault_write.write_new(..., actor=USER)`. `ghostbrain/api/routes/templates.py` exposes list, functions, create and render. On the desktop side, `TemplatePromptDialog` renders one field per prompt (person uses A2's `/v1/vault/suggest?kind=person`), `TemplatePicker.tsx` holds the Jots "template" menu and the `/template` insert dialog, and `slash.ts` gets one appended item.

**Tech Stack:** Python 3.11+ (CI runs 3.11), FastAPI, pydantic v2, PyYAML (`safe_load` / `compose` / `safe_dump` only), the existing `ghostbrain.vault_write` (B1) and `ghostbrain.vault_index.links` (A2). Desktop: React 18, TanStack Query 5, TipTap, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-09-smart-templates-design.md`. This plan covers slice **C1 only**. It has no live query execution (C2), no template editor, lint route or Test run (C3), and no AI generation (C4). The interfaces below are shaped so those slices extend the code rather than rewrite it. See "Extension points" at the end.

## Global Constraints

- Templates are plain markdown vault files in **`90-meta/templates/`** (user-approved decision 1). The template id is the file stem and must match `[a-z0-9][a-z0-9-]{0,63}`.
- The template language "**can't run code**: variables, a few filters and query blocks, nothing Turing-complete". It is a closed grammar. Do not use Jinja (even though it is installed), and do not use any dynamic evaluation, `getattr`-style lookups or imports driven by template text. Field and filter lookups are whitelist dict lookups keyed by name.
- "An unknown name renders as the literal text and is flagged by the linter; it never errors at creation." The same holds for unknown fields, unknown filters, a filter missing its required argument, and any malformed `{{ … }}`.
- Placeholders: variables `date`, `time`, `now`, `context`, `project`, `title`, `user.name` plus prompt ids. Typed fields: `person.name`, `person.link`, `person.path`, `project.name`, `date.iso` (plus `project.slug`, `project.context`, `project.path`, `now.iso`, `now.date`). Filters: `format: <pattern>`, `slug`, `upper`, `lower`, `default: <text>`. Prompt types: `person | text | date | choice | context | project`.
- Query blocks (` ```query ` fences) **stay in the note**. Placeholders inside them are resolved at creation like any other text. C1 does not execute them.
- Creation goes through B1: `vault_write.write_new(path, content, actor=USER, reason=…)`. It never overwrites. A rendered folder that escapes the vault returns **400**, and nothing is written.
- Starter templates seed into `90-meta/templates/` **only if the folder is missing**, and never overwrite a file.
- **Security boundary.** C4 lets the AI write templates, so a malicious template must not be able to read files outside the vault, execute code, recurse without bound, or produce a path that escapes the vault. Every one of these has an explicit test in `tests/test_templates_security.py` or the route tests.
- `ghostbrain/templates/__init__.py` stays import-free (docstring only). `bootstrap.py` imports `ghostbrain.templates.starters` in the base install, which has no pydantic.
- Backend CI installs only `[dev,api]`. No numpy or semantic imports may appear in any module the templates route imports.
- Neutral example content only: the person is "Alex", the context is "work", the project is "Alpha", the user is "Sam". A CI guard (`tests/test_no_hardcoded_contexts.py`) fails on employer or legacy context names in `ghostbrain/`, `docs/` and `desktop/src`.
- A1 edits `desktop/src/renderer/lib/editor/slash.ts` and `extensions.ts` in parallel. C1 only **appends** one item at the end of `SLASH_ITEMS` and does not touch `extensions.ts`. Its `RichMarkdownEditor.tsx` change is purely additive: one import, one state, one effect and one JSX element.
- Python test commands use `python -m pytest …` from the repo root. Every new `tests/test_templates_*.py` file goes into the fixed list in `.github/workflows/ci.yml`. Files under `ghostbrain/api/tests/` are already covered by the directory entry.
- Desktop gates are `npm run typecheck` (`tsc -b`; never `tsc --noEmit`), `npx vitest run` and `npm run lint` (`eslint . --max-warnings 0`). Windows release builds rerun the desktop tests, so they must not depend on POSIX paths or timezones. JSX text must not contain a raw `'` (the `react/no-unescaped-entities` rule), so apostrophes come only from data.

## Review Focus

1. **A person typed as a free name with no page yet** ("Alex", before `30-cross-context/people/alex.md` exists). The note must still be created, with `person.link` = `[[Alex]]`. Pinned in Task 4 (`test_freeform_person_name_links_by_name`) and Task 9 (`submits a typed name when no suggestion is picked`).
2. **The same template used twice on one day** (two "Planning" meetings). The second note must get a `-2` suffix, never overwrite the first, and both must open. Pinned in Task 6 (`test_second_create_same_day_gets_suffix_never_overwrites`) and Task 7 (`test_create_twice_same_answers_gets_suffix`).
3. **A template hand-edited into invalid YAML.** It is listed with ⚠ and can't be picked. The other templates still work. Creating from it returns a 422 with the line, never a 500. Pinned in Task 5 (`test_list_keeps_valid_templates_next_to_broken_one`), Task 7 (`test_create_with_broken_template_is_422`) and Task 10 (`shows a broken template disabled with its first error`).
4. **A title that is all punctuation or non-ASCII** (topic "???" or "Ünïcödé ✓"). Creation must not crash. The filename falls back to the slug rules (`untitled`, or the ASCII remainder), and the frontmatter `title` keeps the original text. Pinned in Task 4 (`test_punctuation_only_title_slugs_to_untitled`).
5. **An existing vault that never re-runs bootstrap.** The starters must appear the first time the template list is opened, and a starter the user deleted must not come back. Pinned in Task 5 (`test_list_seeds_starters_when_folder_missing`, `test_deleted_starter_is_not_reseeded`) and Task 7 (`test_list_seeds_three_starters`).

## Decisions taken where the spec was silent or ambiguous

1. **Collision suffix.** The spec says " (2)", but B1's `write_new` (which the instructions say to use) produces `<stem>-2.md`, and template filenames are slugs anyway. C1 uses `write_new`, so a collision gives `-2`, `-3`, …, and it never overwrites.
2. **Filename slug.** `notes_manual.make_slug`'s character rules apply: lower-case, with every run of non-`[a-z0-9]` characters becoming `-`, and `untitled` when empty. Its 32-character cap is too short for `2026-10-09 Use Postgres for search`, so filenames are capped at **80**. The `slug` *filter* keeps the exact 32-character `make_slug` behavior, and a parity test guards it. The human title is stored in frontmatter `title`.
3. **`title` variable** = the rendered `file.name`, with whitespace collapsed. Inside `file.name` itself it is unknown, so it stays literal.
4. **`context` default.** The order is: an explicit `context` answer, then the context picked in the dialog (the dialog adds a context picker whenever the template uses `{{context}}` without a `context` prompt), then the first configured context. A prompt may reuse the builtin names `date`, `context` and `project` only with the matching type. The ids `time`, `now`, `title` and `user` are reserved.
5. **`user.name`** comes from an optional `user: {name: …}` key in `90-meta/config.yaml`. If that key is missing, it is "".
6. **`/template` insert route.** The spec's `POST /v1/templates/render {source, …}` is C3's Test run. C1 adds `POST /v1/templates/{id}/render {answers}`, which renders a stored template without writing. The slash insert uses the `body` only and drops the frontmatter.
7. **Seeding.** Bootstrap only runs on first launch (`api/__main__.py`), so `GET /v1/templates` also seeds when the folder is missing. Seeding writes files directly with exclusive create, like bootstrap's other seed files. It does not go through the write path, because it is a system seed and not a user or AI change.
8. **Answers.** An answer key that is neither a prompt id nor `context`, `project` or `date` returns 422. An unanswered optional prompt is an *empty* value: it renders "", every field of it is empty, and `default:` replaces it.
9. **No filing into `90-meta/`.** Template creates are `actor=user` writes. A C4 AI-written template could otherwise use the user's own click to write system files (including new templates) past B3's approval. The rendered folder must not start with `90-meta`, a dot-segment, `..`, a drive letter or a backslash.
10. **Note frontmatter.** The engine adds `title`, `created`, `updated` and `fromTemplate: <id>`. The template's `frontmatter:` keys override the first three, but `fromTemplate` is forced. No `source` key is set, so NoteView does not show its "synced note" warning. The new note opens in `NoteView` through `useNoteView.open(path)`. It is not a jot, because jots are `manual-*.md` files.
11. **Date format tokens.** A moment-style subset with English names: `YYYY YY MMMM MMM MM M DD D dddd ddd HH H mm ss`. Literal text goes in `[brackets]`.

---

## Interfaces — `ghostbrain.templates` (C2/C3/C4 build on these)

```python
# lang.py — tokenizer (pure)
MAX_TEMPLATE_CHARS = 256_000; MAX_PLACEHOLDERS = 5_000; MAX_EXPR_CHARS = 400
MAX_FILTERS = 8; MAX_NAME_DEPTH = 4
class TemplateLimitError(ValueError)
@dataclass(frozen=True) class FilterCall: name: str; arg: str | None
@dataclass(frozen=True) class Placeholder:
    raw: str; start: int; end: int; line: int; col: int          # 1-based line/col within the string tokenized
    path: tuple[str, ...] | None                                  # None = not a valid expression → literal
    filters: tuple[FilterCall, ...]
@dataclass(frozen=True) class Text: text: str
Segment = Text | Placeholder
def tokenize(source: str) -> list[Segment]                        # raises TemplateLimitError
def parse_expression(expr: str) -> tuple[tuple[str, ...], tuple[FilterCall, ...]] | None

# values.py
@dataclass(frozen=True) class DateValue: value: date
@dataclass(frozen=True) class DateTimeValue: value: datetime
@dataclass(frozen=True) class PersonValue: name: str; path: str   # .link property → "[[path-sans-.md]]" or "[[name]]"
@dataclass(frozen=True) class ProjectValue: id: str; name: str; slug: str; context: str   # .path property
@dataclass(frozen=True) class UserValue: name: str
class EmptyValue; EMPTY: EmptyValue
Value = str | DateValue | DateTimeValue | PersonValue | ProjectValue | UserValue | EmptyValue
def value_type(value: Value) -> str        # "text"|"date"|"datetime"|"person"|"project"|"user"|"empty"
def to_text(value: Value) -> str
def format_date(value: date, pattern: str) -> str
def slugify(text: str, max_len: int = 32) -> str

# functions.py — THE registry (C3 completions / hover / lint read it)
Kind = Literal["variable", "field", "filter", "prompt_type"]     # C2 adds "query_key"
@dataclass(frozen=True) class FunctionSpec:
    name: str; kind: Kind; type: str; doc: str; example: str
    owner: str | None = None; accepts: tuple[str, ...] = (); arg: str | None = None; arg_required: bool = False
    def to_json(self) -> dict[str, Any]     # camelCase: argRequired
VARIABLES, FIELDS, FILTERS, PROMPT_TYPES: tuple[FunctionSpec, ...]
FIELD_IMPLS: Mapping[tuple[str, str], Callable[[Any], Value]]          # (value_type, field) → impl
FILTER_IMPLS: Mapping[str, Callable[[Value, str | None], Value]]
FILTERS_BY_NAME: Mapping[str, FunctionSpec]
PROMPT_VALUE_TYPES: Mapping[str, str]                                  # prompt type → value type
def find_spec(kind: Kind, name: str, owner: str | None = None) -> FunctionSpec | None
def registry_json() -> dict[str, list[dict[str, Any]]]                 # {variables, fields, filters, promptTypes}

# parse.py
PromptType = Literal["person", "text", "date", "choice", "context", "project"]
@dataclass(frozen=True) class Diagnostic: line: int; col: int; severity: Literal["error","warning","info"]; message: str; code: str
    def to_json(self) -> dict[str, Any]
@dataclass(frozen=True) class Prompt: id: str; ask: str; type: PromptType; optional: bool = False; default: str | None = None; options: tuple[str, ...] = ()
    def to_json(self) -> dict[str, Any]
@dataclass(frozen=True) class FileSpec: folder: str; name: str
@dataclass(frozen=True) class Template:
    id: str; name: str; description: str; prompts: tuple[Prompt, ...]; file: FileSpec
    frontmatter: Mapping[str, Any]; body: str; body_line: int; variables: tuple[str, ...]
@dataclass(frozen=True) class ParseResult: template: Template | None; diagnostics: tuple[Diagnostic, ...]   # .ok
def parse_template(source: str, template_id: str) -> ParseResult

# render.py
class AnswerError(ValueError): field: str          # str(e) = message; HTTP detail = f"{field}: {message}"
class RenderError(ValueError)
@dataclass(frozen=True) class RenderEnv:
    now: datetime; default_context: str; contexts: tuple[str, ...]
    projects: Mapping[str, ProjectValue] = {}; user_name: str = ""
    person_title: Callable[[str], str | None] = <returns None>
@dataclass(frozen=True) class RenderedNote:
    template_id: str; folder: str; filename: str; title: str; frontmatter: dict[str, Any]; body: str
    path: str (property) ; def markdown(self) -> str
class Budget: def __init__(self, limit: int); def take(self, n: int) -> None
def coerce_answers(template: Template, answers: Mapping[str, str], env: RenderEnv) -> dict[str, Value]
def build_scope(values: Mapping[str, Value], env: RenderEnv) -> dict[str, Value]
def evaluate(ph: Placeholder, scope: Mapping[str, Value]) -> Value | None     # None → render ph.raw
def render_string(text: str, scope: Mapping[str, Value], budget: Budget | None = None) -> str
def validate_folder(folder: str) -> str                                     # RenderError
def render(template: Template, answers: Mapping[str, str], env: RenderEnv) -> RenderedNote

# registry.py
TEMPLATES_REL = "90-meta/templates"; TEMPLATE_ID_RE: re.Pattern[str]
class TemplateNotFound(LookupError); class TemplateInvalid(ValueError): template_id; diagnostics
@dataclass(frozen=True) class TemplateInfo: id: str; path: str; template: Template | None; diagnostics: tuple[Diagnostic, ...]
    valid (property); def to_json(self) -> dict[str, Any]
def templates_dir(root: Path | None = None) -> Path
def list_templates(root: Path | None = None) -> list[TemplateInfo]          # seeds if folder missing
def read_template_source(template_id: str, root: Path | None = None) -> str
def load_template(template_id: str, root: Path | None = None) -> Template

# starters.py (no pydantic import — bootstrap uses it)
STARTER_TEMPLATES: dict[str, str]                                           # file name → source
def seed_starter_templates(root: Path) -> list[str]                         # vault-relative paths written

# env.py
def build_env() -> RenderEnv

# create.py
@dataclass(frozen=True) class CreatedNote: path: str; title: str; etag: str | None; status: str
def create_from_template(template_id: str, answers: Mapping[str, str], *, actor: Actor = USER, env: RenderEnv | None = None) -> CreatedNote
def preview_from_template(template_id: str, answers: Mapping[str, str], *, env: RenderEnv | None = None) -> RenderedNote
```

HTTP (all under bearer auth like every other route):

| Route | Body | 2xx response | Errors |
|---|---|---|---|
| `GET /v1/templates` | — | `{templates: [{id, path, name, description, prompts:[{id, ask, type, optional, default, options}], variables, valid, diagnostics:[{line, col, severity, message, code}]}]}` | — |
| `GET /v1/templates/functions` | — | `{variables, fields, filters, promptTypes}` of `FunctionSpec.to_json()` | — |
| `POST /v1/templates/{id}/create` | `{answers: {str: str}}` | 201 `{path, title, etag, status}` | 404 unknown id · 422 `template has errors: line N: …` · 422 `<field>: <message>` · 400 bad folder / escape · 409 no free name |
| `POST /v1/templates/{id}/render` | `{answers}` | 200 `{path, folder, filename, title, frontmatter, body}` (writes nothing) | same as create, minus 409 |

---

## File Structure

Backend (new):
- `ghostbrain/templates/__init__.py`: docstring only.
- `ghostbrain/templates/lang.py`: tokenizer and expression parser, plus hard size limits.
- `ghostbrain/templates/values.py`: typed values, `to_text`, `format_date`, `slugify`.
- `ghostbrain/templates/functions.py`: the registry (specs and implementations) and `registry_json`.
- `ghostbrain/templates/parse.py`: the pydantic schema, `parse_template`, line-numbered diagnostics.
- `ghostbrain/templates/render.py`: answer coercion, evaluation, folder validation, `render`.
- `ghostbrain/templates/starters.py`: the three starter sources and `seed_starter_templates`.
- `ghostbrain/templates/registry.py`: list, load and read from `90-meta/templates/`.
- `ghostbrain/templates/env.py`: `build_env()` from routing config, projects, config.yaml and the link index.
- `ghostbrain/templates/create.py`: `create_from_template` and `preview_from_template`.
- `ghostbrain/api/routes/templates.py`: the four routes.

Backend (modify):
- `ghostbrain/api/main.py`: import and include the templates router.
- `ghostbrain/bootstrap.py`: call `seed_starter_templates(root)`.
- `.github/workflows/ci.yml`: add the new `tests/test_templates_*.py` files.

Backend tests (new): `tests/test_templates_lang.py`, `tests/test_templates_functions.py`, `tests/test_templates_parse.py`, `tests/test_templates_render.py`, `tests/test_templates_security.py` (adversarial cases, grown by Tasks 1, 3, 4, 5 and 6), `tests/test_templates_registry.py`, `tests/test_templates_starters.py`, `tests/test_templates_create.py`, `ghostbrain/api/tests/test_templates_routes.py`.

Desktop (new):
- `desktop/src/renderer/components/TemplatePromptDialog.tsx`: one field per prompt, required gating, person suggest, and create or insert.
- `desktop/src/renderer/components/TemplatePicker.tsx`: `TemplateList`, `TemplateMenu` (Jots) and `TemplateInsertDialog` (slash).
- Tests: `template-hooks.test.tsx`, `TemplatePromptDialog.test.tsx`, `TemplatePicker.test.tsx`, `template-slash-insert.test.tsx`.

Desktop (modify, additive):
- `desktop/src/shared/api-types.ts`: append the template types.
- `desktop/src/renderer/lib/api/hooks.ts`: extend the type import and append three hooks.
- `desktop/src/renderer/screens/jots.tsx`: render `<TemplateMenu>` beside "new".
- `desktop/src/renderer/lib/editor/slash.ts`: append the `template` item.
- `desktop/src/renderer/components/RichMarkdownEditor.tsx`: listen for `gb:slash:template` and render `TemplateInsertDialog`.
- `desktop/src/renderer/__tests__/slash.test.ts` and `jots.test.tsx`: append tests.

---

### Task 1: Template language tokenizer (`lang.py`)

**Files:**
- Create: `ghostbrain/templates/__init__.py`, `ghostbrain/templates/lang.py`
- Test: `tests/test_templates_lang.py`, `tests/test_templates_security.py` (create)
- Modify: `.github/workflows/ci.yml` (add the two test files)

**Interfaces:**
- Consumes: nothing.
- Produces: `tokenize`, `parse_expression`, `Text`, `Placeholder`, `FilterCall`, `Segment`, `TemplateLimitError`, and the constants `MAX_TEMPLATE_CHARS`, `MAX_PLACEHOLDERS`, `MAX_EXPR_CHARS`, `MAX_FILTERS` and `MAX_NAME_DEPTH`, exactly as listed in the Interfaces block.

- [ ] **Step 1: Write the failing tests**

`tests/test_templates_lang.py`:

```python
"""Template language tokenizer (spec: render.py tiny tokenizer)."""
from __future__ import annotations

import pytest

from ghostbrain.templates.lang import (
    MAX_EXPR_CHARS,
    MAX_FILTERS,
    FilterCall,
    Placeholder,
    Text,
    parse_expression,
    tokenize,
)


def test_plain_text_is_one_text_segment():
    assert tokenize("hello world") == [Text("hello world")]


def test_placeholder_with_dotted_name_and_position():
    segs = tokenize("a {{ person.name }} b")
    assert segs[0] == Text("a ")
    ph = segs[1]
    assert isinstance(ph, Placeholder)
    assert ph.raw == "{{ person.name }}"
    assert (ph.start, ph.end, ph.line, ph.col) == (2, 19, 1, 3)
    assert ph.path == ("person", "name")
    assert ph.filters == ()
    assert segs[2] == Text(" b")


def test_filters_with_bare_and_missing_args():
    ph = tokenize("{{date | format: D MMM YYYY | upper}}")[0]
    assert ph.path == ("date",)
    assert ph.filters == (FilterCall("format", "D MMM YYYY"), FilterCall("upper", None))


def test_quoted_arg_may_contain_pipes_colons_and_escaped_quotes():
    ph = tokenize('{{x | default: "a | b: \\"c\\""}}')[0]
    assert ph.filters == (FilterCall("default", 'a | b: "c"'),)


def test_line_and_col_count_across_newlines():
    segs = tokenize("one\ntwo {{x}}\n{{y}}")
    phs = [s for s in segs if isinstance(s, Placeholder)]
    assert [(p.line, p.col) for p in phs] == [(2, 5), (3, 1)]


@pytest.mark.parametrize(
    "expr",
    [
        "{{ }}",
        "{{1abc}}",
        "{{a..b}}",
        "{{a | }}",
        '{{a | default: "unterminated}}',
        "{{a b}}",
        "{{_private}}",
        "{{a.b.c.d.e}}",
        "{{a | default:}}",
        "{{a | 9bad}}",
    ],
)
def test_invalid_expressions_are_placeholders_without_path(expr):
    ph = tokenize(expr)[0]
    assert isinstance(ph, Placeholder)
    assert ph.path is None
    assert ph.raw == expr


def test_too_many_filters_is_not_an_expression():
    chain = " | ".join(["upper"] * (MAX_FILTERS + 1))
    assert parse_expression(f"x | {chain}") is None
    assert parse_expression("x | " + " | ".join(["upper"] * MAX_FILTERS)) is not None


def test_unclosed_open_braces_stay_text():
    assert tokenize("a {{x b") == [Text("a {{x b")]


def test_overlong_expression_stays_text():
    src = "{{" + "a" * (MAX_EXPR_CHARS + 1) + "}}"
    assert tokenize(src) == [Text(src)]


def test_inner_open_braces_restart_the_scan():
    segs = tokenize("use {{ to open {{date}}")
    assert segs[0] == Text("use {{ to open ")
    assert isinstance(segs[1], Placeholder) and segs[1].path == ("date",)
```

`tests/test_templates_security.py` (this file grows in Tasks 3, 4, 5 and 6):

```python
"""Adversarial templates: the template language is a security boundary
(C4 lets the AI write templates). A template must not execute code, read
files outside the vault, recurse without bound, or produce a path that
escapes the vault."""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from ghostbrain.templates.lang import (
    MAX_PLACEHOLDERS,
    MAX_TEMPLATE_CHARS,
    Placeholder,
    Text,
    TemplateLimitError,
    tokenize,
)

PKG = Path(__file__).resolve().parents[1] / "ghostbrain" / "templates"
FORBIDDEN = [
    re.compile(r"\beval\("),
    re.compile(r"\bexec\("),
    re.compile(r"(?<![.\w])compile\("),
    re.compile(r"__import__"),
    re.compile(r"\bgetattr\("),
    re.compile(r"\bsetattr\("),
    re.compile(r"\bimportlib\b"),
    re.compile(r"\bsubprocess\b"),
    re.compile(r"\bpickle\b"),
    re.compile(r"\bjinja2\b"),
    re.compile(r"yaml\.(?:load|unsafe_load|full_load)\("),
    re.compile(r"Loader=yaml\.(?:Loader|FullLoader|UnsafeLoader)\b"),
]


def test_sec_engine_source_has_no_dynamic_execution():
    assert PKG.is_dir()
    offenders = []
    for f in sorted(PKG.glob("*.py")):
        text = f.read_text(encoding="utf-8")
        for pat in FORBIDDEN:
            if pat.search(text):
                offenders.append(f"{f.name}: {pat.pattern}")
    assert offenders == []


@pytest.mark.parametrize(
    "src",
    [
        "{{ __import__('os').system('touch pwned') }}",
        "{{ person.__class__ }}",
        "{{ person.__class__.__mro__ }}",
        "{{ ''.join }}",
        "{{ date() }}",
        "{{ items[0] }}",
        "{{ a + b }}",
        "{{ open('/etc/passwd') }}",
    ],
)
def test_sec_code_like_expressions_never_parse(src):
    segs = tokenize(src)
    assert all(isinstance(s, Text) or s.path is None for s in segs)


def test_sec_placeholder_count_is_capped():
    with pytest.raises(TemplateLimitError):
        tokenize("{{x}}" * (MAX_PLACEHOLDERS + 1))


def test_sec_source_size_is_capped():
    with pytest.raises(TemplateLimitError):
        tokenize("a" * (MAX_TEMPLATE_CHARS + 1))


def test_sec_pathological_braces_finish_fast():
    start = time.monotonic()
    segs = tokenize("{" * 200_000)
    assert time.monotonic() - start < 2.0
    assert segs == [Text("{" * 200_000)]


def test_sec_many_placeholders_on_one_line_finish_fast():
    src = "x" * 100_000 + "{{a}}" * MAX_PLACEHOLDERS
    start = time.monotonic()
    segs = tokenize(src)
    assert time.monotonic() - start < 2.0
    assert sum(isinstance(s, Placeholder) for s in segs) == MAX_PLACEHOLDERS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_templates_lang.py tests/test_templates_security.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'ghostbrain.templates'`.

- [ ] **Step 3: Write the implementation**

`ghostbrain/templates/__init__.py`:

```python
"""Smart templates (spec docs/superpowers/specs/2026-10-09-smart-templates-design.md).

Deliberately import-free: bootstrap imports ``ghostbrain.templates.starters``
in installs without pydantic. Import the submodules you need.
"""
```

`ghostbrain/templates/lang.py`:

```python
"""The template language: ``{{ name.field | filter: arg }}`` placeholders.

Closed by design: a placeholder is a dotted name plus a chain of named
filters from the fixed registry (functions.py). There are no calls,
operators, indexing, loops or includes. Anything that is not exactly that
shape is not an expression and renders as its literal text. Hard limits
bound the work any template can cause.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_TEMPLATE_CHARS = 256_000
MAX_PLACEHOLDERS = 5_000
MAX_EXPR_CHARS = 400
MAX_FILTERS = 8
MAX_NAME_DEPTH = 4

_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")
_QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"', re.DOTALL)
_UNESCAPE_RE = re.compile(r"\\(.)", re.DOTALL)


class TemplateLimitError(ValueError):
    """The source exceeds a hard size limit (a security bound, not style)."""


@dataclass(frozen=True)
class FilterCall:
    name: str
    arg: str | None


@dataclass(frozen=True)
class Placeholder:
    raw: str
    start: int
    end: int
    line: int
    col: int
    path: tuple[str, ...] | None
    filters: tuple[FilterCall, ...]


@dataclass(frozen=True)
class Text:
    text: str


Segment = Text | Placeholder


def _split_pipes(expr: str) -> list[str] | None:
    parts: list[str] = []
    buf: list[str] = []
    in_quote = escaped = False
    for ch in expr:
        if in_quote:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_quote = False
        elif ch == '"':
            in_quote = True
            buf.append(ch)
        elif ch == "|":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if in_quote:
        return None
    parts.append("".join(buf))
    return parts


def _parse_filter(part: str) -> FilterCall | None:
    name, sep, rest = part.partition(":")
    name = name.strip()
    if not _NAME_RE.fullmatch(name):
        return None
    if not sep:
        return FilterCall(name, None)
    arg = rest.strip()
    if arg.startswith('"'):
        m = _QUOTED_RE.fullmatch(arg)
        if m is None:
            return None
        return FilterCall(name, _UNESCAPE_RE.sub(r"\1", m.group(1)))
    if not arg:
        return None
    return FilterCall(name, arg)


def parse_expression(expr: str) -> tuple[tuple[str, ...], tuple[FilterCall, ...]] | None:
    """``name(.field)* (| filter(: arg)?)*`` or None."""
    parts = _split_pipes(expr)
    if parts is None or len(parts) - 1 > MAX_FILTERS:
        return None
    names = parts[0].strip().split(".")
    if len(names) > MAX_NAME_DEPTH or not all(_NAME_RE.fullmatch(n) for n in names):
        return None
    filters: list[FilterCall] = []
    for part in parts[1:]:
        call = _parse_filter(part)
        if call is None:
            return None
        filters.append(call)
    return tuple(names), tuple(filters)


def tokenize(source: str) -> list[Segment]:
    """Split ``source`` into literal text and placeholders. Linear in the
    source size (each ``{{`` looks ahead at most MAX_EXPR_CHARS)."""
    if len(source) > MAX_TEMPLATE_CHARS:
        raise TemplateLimitError(f"template is larger than {MAX_TEMPLATE_CHARS} characters")
    out: list[Segment] = []
    text_start = search = 0
    count = 0
    line, line_start, scanned = 1, 0, 0
    while True:
        open_at = source.find("{{", search)
        if open_at < 0:
            break
        close_at = source.find("}}", open_at + 2, open_at + 4 + MAX_EXPR_CHARS)
        if close_at < 0 or "{{" in source[open_at + 2 : close_at]:
            search = open_at + 2
            continue
        count += 1
        if count > MAX_PLACEHOLDERS:
            raise TemplateLimitError(f"template has more than {MAX_PLACEHOLDERS} placeholders")
        line += source.count("\n", scanned, open_at)
        nl = source.rfind("\n", scanned, open_at)
        if nl >= 0:
            line_start = nl + 1
        scanned = open_at
        if open_at > text_start:
            out.append(Text(source[text_start:open_at]))
        end = close_at + 2
        parsed = parse_expression(source[open_at + 2 : close_at])
        path, filters = parsed if parsed is not None else (None, ())
        out.append(
            Placeholder(source[open_at:end], open_at, end, line, open_at - line_start + 1, path, filters)
        )
        text_start = search = end
    if text_start < len(source):
        out.append(Text(source[text_start:]))
    return out
```

Add both files to the `ci.yml` pytest list, after `tests/test_vault_index_links.py \`:

```yaml
            tests/test_templates_lang.py \
            tests/test_templates_security.py \
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_templates_lang.py tests/test_templates_security.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/templates/__init__.py ghostbrain/templates/lang.py tests/test_templates_lang.py tests/test_templates_security.py .github/workflows/ci.yml
git commit -m "feat(templates): closed {{ name | filter }} tokenizer with hard limits"
```

---

### Task 2: Typed values and the function registry (`values.py`, `functions.py`)

**Files:**
- Create: `ghostbrain/templates/values.py`, `ghostbrain/templates/functions.py`
- Test: `tests/test_templates_functions.py`
- Modify: `.github/workflows/ci.yml` (add `tests/test_templates_functions.py \`)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: everything in the `values.py` and `functions.py` sections of the Interfaces block. Render (Task 4) dispatches fields by `(value_type(v), field)` through `FIELD_IMPLS`, and filters by name through `FILTERS_BY_NAME` and `FILTER_IMPLS`. Routes (Task 7) call `registry_json()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_templates_functions.py`:

```python
"""The registry is the single source for rendering, intellisense and docs."""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from ghostbrain.templates.functions import (
    FIELD_IMPLS,
    FIELDS,
    FILTER_IMPLS,
    FILTERS,
    PROMPT_TYPES,
    PROMPT_VALUE_TYPES,
    VARIABLES,
    find_spec,
    registry_json,
)
from ghostbrain.templates.values import (
    EMPTY,
    DateTimeValue,
    DateValue,
    PersonValue,
    ProjectValue,
    UserValue,
    format_date,
    slugify,
    to_text,
    value_type,
)

D = date(2026, 10, 9)  # a Friday
DT = datetime(2026, 10, 9, 14, 30, 5)


@pytest.mark.parametrize(
    "pattern, expected",
    [
        ("YYYY-MM-DD", "2026-10-09"),
        ("D MMM YYYY", "9 Oct 2026"),
        ("MMMM YY", "October 26"),
        ("dddd [the] D", "Friday the 9"),
        ("ddd HH:mm:ss", "Fri 14:30:05"),
        ("M/D H", "10/9 14"),
    ],
)
def test_format_date_tokens(pattern, expected):
    assert format_date(DT, pattern) == expected


def test_format_date_on_a_plain_date_has_midnight_time():
    assert format_date(D, "HH:mm") == "00:00"


def test_slugify_matches_make_slug_rules():
    from ghostbrain.api.repo.notes_manual import make_slug

    for text in ["Hello World!", "  --  ", "Ünïcödé ✓", "a" * 50, "2026-10-09 Alex 1-1", "???"]:
        assert slugify(text) == make_slug(text)
    assert slugify("x" * 100, 80) == "x" * 80


def test_value_types_and_text():
    alex = PersonValue("Alex", "30-cross-context/people/alex.md")
    alpha = ProjectValue("work/alpha", "Alpha", "alpha", "work")
    assert [value_type(v) for v in ("t", DateValue(D), DateTimeValue(DT), alex, alpha, UserValue("Sam"), EMPTY)] == [
        "text", "date", "datetime", "person", "project", "user", "empty",
    ]
    assert to_text(DateValue(D)) == "2026-10-09"
    assert to_text(DateTimeValue(DT)) == "2026-10-09T14:30"
    assert to_text(alex) == "Alex" and to_text(EMPTY) == ""
    assert alex.link == "[[30-cross-context/people/alex]]"
    assert PersonValue("Alex", "").link == "[[Alex]]"
    assert alpha.path == "20-contexts/work/projects/alpha"


def test_every_field_spec_has_an_impl_and_back():
    assert {(s.owner, s.name) for s in FIELDS} == set(FIELD_IMPLS)


def test_every_filter_spec_has_an_impl_and_back():
    assert {s.name for s in FILTERS} == set(FILTER_IMPLS)


def test_prompt_types_match_the_parser_literal():
    from typing import get_args

    from ghostbrain.templates.parse import PromptType  # created in Task 3

    assert {s.name for s in PROMPT_TYPES} == set(get_args(PromptType))
    assert PROMPT_VALUE_TYPES["person"] == "person" and PROMPT_VALUE_TYPES["choice"] == "text"


def test_variable_names():
    assert {s.name for s in VARIABLES} == {"date", "time", "now", "context", "project", "title", "user"}


def test_every_spec_is_documented_and_json_ready():
    data = registry_json()
    assert set(data) == {"variables", "fields", "filters", "promptTypes"}
    json.dumps(data)
    for group in data.values():
        for spec in group:
            assert spec["doc"] and spec["example"]
    fmt = next(s for s in data["filters"] if s["name"] == "format")
    assert fmt["argRequired"] is True and fmt["arg"] == "<pattern>"


def test_find_spec():
    assert find_spec("filter", "format").arg_required is True
    assert find_spec("field", "link", owner="person").owner == "person"
    assert find_spec("field", "link", owner="project") is None
    assert find_spec("variable", "nope") is None


def test_filter_behaviour():
    fmt, dflt = FILTER_IMPLS["format"], FILTER_IMPLS["default"]
    assert fmt(DateValue(D), "D MMM") == "9 Oct"
    assert fmt("2026-10-09", "D MMM") == "9 Oct"
    assert fmt("not a date", "D MMM") == "not a date"
    assert fmt(EMPTY, "D MMM") is EMPTY
    assert dflt(EMPTY, "n/a") == "n/a"
    assert dflt("   ", "n/a") == "n/a"
    assert dflt("kept", "n/a") == "kept"
    assert FILTER_IMPLS["slug"]("Hello World", None) == "hello-world"
    assert FILTER_IMPLS["upper"]("hi", None) == "HI"
    assert FILTER_IMPLS["lower"]("HI", None) == "hi"
    for name in ("slug", "upper", "lower"):
        assert FILTER_IMPLS[name](EMPTY, None) is EMPTY
```

The test `test_prompt_types_match_the_parser_literal` imports Task 3's module. Run it with Task 3. In this task, deselect it with `-k "not parser_literal"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_templates_functions.py -v -k "not parser_literal"`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.templates.functions'`.

- [ ] **Step 3: Write the implementation**

`ghostbrain/templates/values.py`:

```python
"""Typed values the template language works with, and their text forms."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Union

SLUG_MAX = 32  # notes_manual.make_slug parity (tests/test_templates_functions.py)
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_FORMAT_RE = re.compile(r"\[([^\]]*)\]|YYYY|YY|MMMM|MMM|MM|M|DD|D|dddd|ddd|HH|H|mm|ss")


@dataclass(frozen=True)
class DateValue:
    value: date


@dataclass(frozen=True)
class DateTimeValue:
    value: datetime


@dataclass(frozen=True)
class PersonValue:
    name: str
    path: str  # vault-relative .md path, or "" for a typed name with no page

    @property
    def link(self) -> str:
        target = self.path[:-3] if self.path.endswith(".md") else self.path
        return f"[[{target or self.name}]]"


@dataclass(frozen=True)
class ProjectValue:
    id: str
    name: str
    slug: str
    context: str

    @property
    def path(self) -> str:
        return f"20-contexts/{self.context}/projects/{self.slug}"


@dataclass(frozen=True)
class UserValue:
    name: str


class EmptyValue:
    """An unanswered optional prompt: renders "", and so does every field of it."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "EMPTY"

    def __bool__(self) -> bool:
        return False


EMPTY = EmptyValue()
Value = Union[str, DateValue, DateTimeValue, PersonValue, ProjectValue, UserValue, EmptyValue]


def value_type(value: Value) -> str:
    if isinstance(value, str):
        return "text"
    if isinstance(value, DateValue):
        return "date"
    if isinstance(value, DateTimeValue):
        return "datetime"
    if isinstance(value, PersonValue):
        return "person"
    if isinstance(value, ProjectValue):
        return "project"
    if isinstance(value, UserValue):
        return "user"
    return "empty"


def to_text(value: Value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, DateValue):
        return value.value.isoformat()
    if isinstance(value, DateTimeValue):
        return value.value.isoformat(timespec="minutes")
    if isinstance(value, (PersonValue, ProjectValue, UserValue)):
        return value.name
    return ""


def format_date(value: date, pattern: str) -> str:
    """Moment-style tokens, English names; ``[text]`` is literal."""
    if isinstance(value, datetime):
        hour, minute, second = value.hour, value.minute, value.second
    else:
        hour = minute = second = 0
    month, day = _MONTHS[value.month - 1], _DAYS[value.weekday()]
    table = {
        "YYYY": f"{value.year:04d}", "YY": f"{value.year % 100:02d}",
        "MMMM": month, "MMM": month[:3], "MM": f"{value.month:02d}", "M": str(value.month),
        "DD": f"{value.day:02d}", "D": str(value.day), "dddd": day, "ddd": day[:3],
        "HH": f"{hour:02d}", "H": str(hour), "mm": f"{minute:02d}", "ss": f"{second:02d}",
    }

    def sub(m: re.Match[str]) -> str:
        if m.group(1) is not None:
            return m.group(1)
        return table[m.group(0)]

    return _FORMAT_RE.sub(sub, pattern)


def slugify(text: str, max_len: int = SLUG_MAX) -> str:
    """make_slug's rules: lower-case, non-alnum runs → '-', 'untitled' when empty."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not s:
        return "untitled"
    return s[:max_len].rstrip("-") or "untitled"
```

`ghostbrain/templates/functions.py`:

```python
"""The single registry of everything a template can name.

Rendering (render.py), GET /v1/templates/functions (completions and hover
docs) and the C3 linter all read from here. Tests assert that every spec has
an implementation and every implementation a spec, so the docs can't drift
from the behavior.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Literal, Mapping

from ghostbrain.templates.values import (
    EMPTY,
    DateTimeValue,
    DateValue,
    Value,
    format_date,
    slugify,
    to_text,
)

Kind = Literal["variable", "field", "filter", "prompt_type"]
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    kind: Kind
    type: str
    doc: str
    example: str
    owner: str | None = None
    accepts: tuple[str, ...] = ()
    arg: str | None = None
    arg_required: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name, "kind": self.kind, "type": self.type, "doc": self.doc,
            "example": self.example, "owner": self.owner, "accepts": list(self.accepts),
            "arg": self.arg, "argRequired": self.arg_required,
        }


VARIABLES: tuple[FunctionSpec, ...] = (
    FunctionSpec("date", "variable", "date",
                 "Today's date, or the answer to a `date` prompt with id `date`.",
                 "{{date | format: D MMM YYYY}}"),
    FunctionSpec("time", "variable", "text", "The current local time as HH:mm.", "{{time}}"),
    FunctionSpec("now", "variable", "datetime", "The current local date and time.",
                 "{{now | format: YYYY-MM-DD HH:mm}}"),
    FunctionSpec("context", "variable", "text",
                 "The context: a `context` prompt, else the one picked when creating, "
                 "else your first context.", "20-contexts/{{context}}/notes"),
    FunctionSpec("project", "variable", "project",
                 "The project picked when creating; empty when none.",
                 "{{project.name | default: none}}"),
    FunctionSpec("title", "variable", "text",
                 "The note's title (the rendered file name). Not available inside `file.name`.",
                 "# {{title}}"),
    FunctionSpec("user", "variable", "user",
                 "You. Set `user: {name: …}` in 90-meta/config.yaml.", "{{user.name}}"),
)

FIELDS: tuple[FunctionSpec, ...] = (
    FunctionSpec("name", "field", "text", "The person's name: their page title, or the typed name.",
                 "{{person.name}}", owner="person"),
    FunctionSpec("link", "field", "text", "A wikilink to the person's page.",
                 "{{person.link}}", owner="person"),
    FunctionSpec("path", "field", "text", "The person's page path (empty for a typed name).",
                 "{{person.path}}", owner="person"),
    FunctionSpec("name", "field", "text", "The project's name.", "{{project.name}}", owner="project"),
    FunctionSpec("slug", "field", "text", "The project's folder slug.", "{{project.slug}}",
                 owner="project"),
    FunctionSpec("context", "field", "text", "The context the project belongs to.",
                 "{{project.context}}", owner="project"),
    FunctionSpec("path", "field", "text", "The project's folder, e.g. 20-contexts/work/projects/alpha.",
                 "{{project.path}}", owner="project"),
    FunctionSpec("iso", "field", "text", "The date as YYYY-MM-DD.", "{{date.iso}}", owner="date"),
    FunctionSpec("iso", "field", "text", "The date and time in ISO 8601.", "{{now.iso}}",
                 owner="datetime"),
    FunctionSpec("date", "field", "date", "Just the date part.", "{{now.date | format: D MMM}}",
                 owner="datetime"),
    FunctionSpec("name", "field", "text", "Your name.", "{{user.name}}", owner="user"),
)

FIELD_IMPLS: Mapping[tuple[str, str], Callable[[Any], Value]] = {
    ("person", "name"): lambda v: v.name,
    ("person", "link"): lambda v: v.link,
    ("person", "path"): lambda v: v.path,
    ("project", "name"): lambda v: v.name,
    ("project", "slug"): lambda v: v.slug,
    ("project", "context"): lambda v: v.context,
    ("project", "path"): lambda v: v.path,
    ("date", "iso"): lambda v: v.value.isoformat(),
    ("datetime", "iso"): lambda v: v.value.isoformat(timespec="seconds"),
    ("datetime", "date"): lambda v: DateValue(v.value.date()),
    ("user", "name"): lambda v: v.name,
}


def _format(value: Value, arg: str | None) -> Value:
    pattern = arg or ""
    if isinstance(value, (DateValue, DateTimeValue)):
        return format_date(value.value, pattern)
    if isinstance(value, str) and _ISO_DATE_RE.fullmatch(value.strip()):
        try:
            return format_date(date.fromisoformat(value.strip()), pattern)
        except ValueError:
            return value
    return value


def _text_filter(fn: Callable[[str], str]) -> Callable[[Value, str | None], Value]:
    def apply(value: Value, _arg: str | None) -> Value:
        return EMPTY if value is EMPTY else fn(to_text(value))

    return apply


def _default(value: Value, arg: str | None) -> Value:
    if value is EMPTY or to_text(value).strip() == "":
        return arg or ""
    return value


FILTERS: tuple[FunctionSpec, ...] = (
    FunctionSpec("format", "filter", "text",
                 "Formats a date. Tokens: YYYY YY MMMM MMM MM M DD D dddd ddd HH H mm ss; "
                 "wrap literal text in [brackets].",
                 "{{date | format: D MMM YYYY}}", accepts=("date", "datetime", "text"),
                 arg="<pattern>", arg_required=True),
    FunctionSpec("slug", "filter", "text",
                 "Lower-case with dashes for anything that isn't a letter or digit (max 32).",
                 "{{person.name | slug}}", accepts=("*",)),
    FunctionSpec("upper", "filter", "text", "UPPER CASE.", "{{context | upper}}", accepts=("*",)),
    FunctionSpec("lower", "filter", "text", "lower case.", "{{person.name | lower}}", accepts=("*",)),
    FunctionSpec("default", "filter", "text",
                 "Text to use when the value is empty (an unanswered optional prompt).",
                 "{{focus | default: nothing planned}}", accepts=("*",),
                 arg="<text>", arg_required=True),
)

FILTER_IMPLS: Mapping[str, Callable[[Value, str | None], Value]] = {
    "format": _format,
    "slug": _text_filter(slugify),
    "upper": _text_filter(str.upper),
    "lower": _text_filter(str.lower),
    "default": _default,
}
FILTERS_BY_NAME: Mapping[str, FunctionSpec] = {s.name: s for s in FILTERS}

PROMPT_TYPES: tuple[FunctionSpec, ...] = (
    FunctionSpec("text", "prompt_type", "text", "Free text.", "type: text"),
    FunctionSpec("person", "prompt_type", "person",
                 "A person: pick their page (name, link, path) or type a name.", "type: person"),
    FunctionSpec("date", "prompt_type", "date", "A date (YYYY-MM-DD).", "type: date"),
    FunctionSpec("choice", "prompt_type", "text", "One of `options`.", "type: choice"),
    FunctionSpec("context", "prompt_type", "text", "One of your contexts.", "type: context"),
    FunctionSpec("project", "prompt_type", "project",
                 "One of your projects (name, slug, context, path).", "type: project"),
)
PROMPT_VALUE_TYPES: Mapping[str, str] = {s.name: s.type for s in PROMPT_TYPES}


def find_spec(kind: Kind, name: str, owner: str | None = None) -> FunctionSpec | None:
    for spec in (*VARIABLES, *FIELDS, *FILTERS, *PROMPT_TYPES):
        if spec.kind == kind and spec.name == name and (owner is None or spec.owner == owner):
            return spec
    return None


def registry_json() -> dict[str, list[dict[str, Any]]]:
    return {
        "variables": [s.to_json() for s in VARIABLES],
        "fields": [s.to_json() for s in FIELDS],
        "filters": [s.to_json() for s in FILTERS],
        "promptTypes": [s.to_json() for s in PROMPT_TYPES],
    }
```

Add `tests/test_templates_functions.py \` to `ci.yml`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_templates_functions.py tests/test_templates_security.py -v -k "not parser_literal"`
Expected: PASS. The security static guard now also scans `values.py` and `functions.py`.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/templates/values.py ghostbrain/templates/functions.py tests/test_templates_functions.py .github/workflows/ci.yml
git commit -m "feat(templates): typed values and the function registry"
```

---

### Task 3: Template parser with line-numbered diagnostics (`parse.py`)

**Files:**
- Create: `ghostbrain/templates/parse.py`
- Test: `tests/test_templates_parse.py`; append to `tests/test_templates_security.py`
- Modify: `.github/workflows/ci.yml` (add `tests/test_templates_parse.py \`)

**Interfaces:**
- Consumes: `tokenize`, `Placeholder`, `TemplateLimitError`, `MAX_TEMPLATE_CHARS` (Task 1). It also uses B1's `ghostbrain.vault_write.text.parse_note(text) -> ParsedNote`, which has the fields `bom`, `has_frontmatter`, `fm_head`, `fm_inner`, `fm_close`, `gap` and `body`.
- Produces: `PromptType`, `Diagnostic`, `Prompt`, `FileSpec`, `Template`, `ParseResult`, `parse_template(source, template_id)`, plus the constants `DEFAULT_FOLDER = "20-contexts/{{context}}/notes"`, `RESERVED_IDS`, `SHADOWABLE`, `MAX_TREE_NODES = 5_000` and `MAX_TREE_DEPTH = 12`.

- [ ] **Step 1: Write the failing tests**

`tests/test_templates_parse.py`:

```python
"""parse_template: valid, defaults, missing fields, bad prompt types, line numbers."""
from __future__ import annotations

from ghostbrain.templates.parse import parse_template

VALID = """---
template:
  name: 1-1
  description: Weekly 1-1
  prompts:
    - id: person
      ask: "Who's this 1-1 with?"
      type: person
    - id: focus
      ask: Anything specific?
      type: text
      optional: true
  file:
    folder: "20-contexts/{{context}}/one-on-ones"
    name: "{{date | format: YYYY-MM-DD}} {{person.name}} 1-1"
  frontmatter:
    type: meeting
    attendees: ["{{person.link}}"]
---
# 1-1 with {{person.link}}

{{focus}}
"""


def _codes(result):
    return [d.code for d in result.diagnostics]


def test_valid_template_parses():
    r = parse_template(VALID, "one-on-one")
    assert r.ok and r.diagnostics == ()
    t = r.template
    assert (t.id, t.name, t.description) == ("one-on-one", "1-1", "Weekly 1-1")
    assert [p.id for p in t.prompts] == ["person", "focus"]
    assert t.prompts[0].type == "person" and t.prompts[1].optional is True
    assert t.file.folder == "20-contexts/{{context}}/one-on-ones"
    assert t.file.name == "{{date | format: YYYY-MM-DD}} {{person.name}} 1-1"
    assert t.frontmatter == {"type": "meeting", "attendees": ["{{person.link}}"]}
    assert t.body == "# 1-1 with {{person.link}}\n\n{{focus}}\n"
    assert t.body_line == 20
    assert t.variables == ("context", "date", "focus", "person")


def test_defaults_for_minimal_template():
    t = parse_template("---\ntemplate:\n  name: Scratch\n---\nhello\n", "scratch").template
    assert t.prompts == () and t.frontmatter == {} and t.description == ""
    assert t.file.folder == "20-contexts/{{context}}/notes"
    assert t.file.name == "{{date | format: YYYY-MM-DD}} Scratch"
    assert t.variables == ("context", "date")


def test_choice_prompt_keeps_options_and_default():
    src = (
        "---\ntemplate:\n  name: D\n  prompts:\n    - id: status\n      ask: Status\n"
        "      type: choice\n      options: [proposed, accepted]\n      default: accepted\n---\n"
    )
    p = parse_template(src, "d").template.prompts[0]
    assert p.options == ("proposed", "accepted") and p.default == "accepted"
    assert p.to_json() == {
        "id": "status", "ask": "Status", "type": "choice", "optional": False,
        "default": "accepted", "options": ["proposed", "accepted"],
    }


def test_missing_name_points_at_template_key():
    r = parse_template("---\ntemplate:\n  description: x\n---\n", "t")
    assert not r.ok and _codes(r) == ["schema"]
    d = r.diagnostics[0]
    assert (d.line, d.col, d.severity) == (2, 1, "error")
    assert "template.name" in d.message and "Field required" in d.message


def test_bad_prompt_type_has_line_and_col():
    src = (
        "---\ntemplate:\n  name: Bad\n  prompts:\n    - id: who\n      ask: Who?\n"
        "      type: email\n---\nbody\n"
    )
    r = parse_template(src, "bad")
    assert not r.ok
    d = r.diagnostics[0]
    assert (d.line, d.col) == (7, 7)
    assert "template.prompts.0.type" in d.message


def test_choice_without_options_and_options_on_text():
    no_opts = "---\ntemplate:\n  name: X\n  prompts:\n    - id: s\n      ask: S\n      type: choice\n---\n"
    assert "needs `options`" in parse_template(no_opts, "x").diagnostics[0].message
    stray = (
        "---\ntemplate:\n  name: X\n  prompts:\n    - id: s\n      ask: S\n      type: text\n"
        "      options: [a]\n---\n"
    )
    assert "only allowed on choice" in parse_template(stray, "x").diagnostics[0].message


def test_duplicate_prompt_id_points_at_second():
    src = (
        "---\ntemplate:\n  name: Dup\n  prompts:\n    - id: who\n      ask: A\n      type: text\n"
        "    - id: who\n      ask: B\n      type: text\n---\n"
    )
    r = parse_template(src, "dup")
    assert _codes(r) == ["prompt-id"]
    assert (r.diagnostics[0].line, r.diagnostics[0].col) == (8, 7)


def test_reserved_and_shadowed_prompt_ids():
    reserved = "---\ntemplate:\n  name: X\n  prompts:\n    - id: title\n      ask: T\n      type: text\n---\n"
    assert "built-in" in parse_template(reserved, "x").diagnostics[0].message
    wrong = "---\ntemplate:\n  name: X\n  prompts:\n    - id: date\n      ask: When\n      type: text\n---\n"
    assert "must have type date" in parse_template(wrong, "x").diagnostics[0].message
    ok = "---\ntemplate:\n  name: X\n  prompts:\n    - id: date\n      ask: When\n      type: date\n---\n"
    assert parse_template(ok, "x").ok


def test_unknown_key_is_an_error():
    r = parse_template("---\ntemplate:\n  name: X\n  colour: red\n---\n", "x")
    assert "Extra inputs are not permitted" in r.diagnostics[0].message
    assert r.diagnostics[0].line == 4


def test_not_a_template():
    assert _codes(parse_template("# just markdown\n", "x")) == ["no-frontmatter"]
    assert _codes(parse_template("---\ntitle: x\n---\nbody\n", "x")) == ["no-template"]


def test_yaml_error_is_line_numbered():
    r = parse_template("---\ntemplate:\n  name: [unclosed\n---\n", "x")
    assert _codes(r) == ["yaml"] and r.diagnostics[0].line >= 2


def test_top_level_extra_key_is_only_a_warning():
    r = parse_template("---\ntags: [a]\ntemplate:\n  name: X\n---\n", "x")
    assert r.ok
    assert [(d.code, d.severity, d.line) for d in r.diagnostics] == [("ignored-key", "warning", 2)]
```

Append to `tests/test_templates_security.py`:

```python
from ghostbrain.templates.parse import parse_template  # noqa: E402

BOMB = """---
a: &a ["x","x","x","x","x","x","x","x","x"]
b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]
c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]
d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]
e: &e [*d,*d,*d,*d,*d,*d,*d,*d,*d]
f: &f [*e,*e,*e,*e,*e,*e,*e,*e,*e]
g: &g [*f,*f,*f,*f,*f,*f,*f,*f,*f]
template:
  name: Bomb
  frontmatter:
    boom: *g
---
"""


def test_sec_yaml_python_tags_do_not_execute(monkeypatch):
    import os

    monkeypatch.setattr(os, "system", lambda *_a, **_k: pytest.fail("os.system ran"))
    r = parse_template("---\ntemplate: !!python/object/apply:os.system ['echo pwned']\n---\n", "x")
    assert not r.ok and r.diagnostics[0].code == "yaml"


def test_sec_yaml_alias_bomb_is_rejected_fast():
    start = time.monotonic()
    r = parse_template(BOMB, "bomb")
    assert time.monotonic() - start < 2.0
    assert not r.ok and r.diagnostics[0].code == "limit"


def test_sec_recursive_yaml_is_rejected():
    src = "---\ntemplate:\n  name: Loop\n  frontmatter:\n    me: &me [*me]\n---\n"
    r = parse_template(src, "loop")
    assert not r.ok and r.diagnostics[0].code == "limit"


def test_sec_deeply_nested_yaml_does_not_crash():
    src = "---\ntemplate:\n  name: Deep\n  frontmatter:\n    x: " + "[" * 3000 + "]" * 3000 + "\n---\n"
    r = parse_template(src, "deep")
    assert not r.ok and r.diagnostics[0].code in ("yaml", "limit")


def test_sec_oversized_source_is_a_diagnostic_not_a_crash():
    r = parse_template("---\ntemplate:\n  name: Big\n---\n" + "a" * MAX_TEMPLATE_CHARS, "big")
    assert not r.ok and r.diagnostics[0].code == "limit"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_templates_parse.py tests/test_templates_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.templates.parse'`.

- [ ] **Step 3: Write the implementation**

`ghostbrain/templates/parse.py`:

```python
"""Load and validate a template file (spec: Template format, parse.py).

The frontmatter's ``template:`` mapping is validated with pydantic, and every
problem becomes a line/col ``Diagnostic`` so the C3 editor can mark it.
Only ``yaml.safe_load`` / ``yaml.compose`` with SafeLoader are used, so YAML
tags cannot construct Python objects. Alias bombs and recursive aliases are
caught by a node/depth budget before anything walks them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ghostbrain.templates.lang import MAX_TEMPLATE_CHARS, Placeholder, TemplateLimitError, tokenize
from ghostbrain.vault_write.text import parse_note

PromptType = Literal["person", "text", "date", "choice", "context", "project"]
Severity = Literal["error", "warning", "info"]

PROMPT_ID_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
DEFAULT_FOLDER = "20-contexts/{{context}}/notes"
SHADOWABLE: Mapping[str, str] = {"date": "date", "context": "context", "project": "project"}
RESERVED_IDS = frozenset({"time", "now", "title", "user"})
MAX_PROMPTS = 20
MAX_TREE_NODES = 5_000
MAX_TREE_DEPTH = 12


@dataclass(frozen=True)
class Diagnostic:
    line: int
    col: int
    severity: Severity
    message: str
    code: str

    def to_json(self) -> dict[str, Any]:
        return {"line": self.line, "col": self.col, "severity": self.severity,
                "message": self.message, "code": self.code}


@dataclass(frozen=True)
class Prompt:
    id: str
    ask: str
    type: PromptType
    optional: bool = False
    default: str | None = None
    options: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "ask": self.ask, "type": self.type, "optional": self.optional,
                "default": self.default, "options": list(self.options)}


@dataclass(frozen=True)
class FileSpec:
    folder: str
    name: str


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    description: str
    prompts: tuple[Prompt, ...]
    file: FileSpec
    frontmatter: Mapping[str, Any]
    body: str
    body_line: int
    variables: tuple[str, ...]


@dataclass(frozen=True)
class ParseResult:
    template: Template | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return self.template is not None


class _PromptModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=PROMPT_ID_PATTERN)
    ask: str = Field(min_length=1, max_length=200)
    type: PromptType
    optional: bool = False
    default: str | None = Field(default=None, max_length=2_000)
    options: list[str] | None = Field(default=None, min_length=1, max_length=50)

    @model_validator(mode="after")
    def _options_match_type(self) -> "_PromptModel":
        if self.type == "choice":
            if not self.options:
                raise ValueError("a choice prompt needs `options`")
            if self.default is not None and self.default not in self.options:
                raise ValueError("`default` must be one of `options`")
        elif self.options is not None:
            raise ValueError("`options` is only allowed on choice prompts")
        return self


class _FileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder: str = Field(default=DEFAULT_FOLDER, min_length=1, max_length=300)
    name: str | None = Field(default=None, min_length=1, max_length=300)


class _TemplateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)
    prompts: list[_PromptModel] = Field(default_factory=list, max_length=MAX_PROMPTS)
    file: _FileModel = Field(default_factory=_FileModel)
    frontmatter: dict[str, Any] = Field(default_factory=dict)


def _tree_problem(value: Any) -> str | None:
    """Iterative walk with a node and depth budget: alias bombs blow the
    node budget, recursive aliases blow the depth budget."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_TREE_NODES:
            return "frontmatter is too large (YAML aliases may be expanding it)"
        if depth > MAX_TREE_DEPTH:
            return "frontmatter is nested too deeply (or refers to itself)"
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    return "frontmatter keys must be text"
                stack.append((child, depth + 1))
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return None


def _strings(value: Any) -> Iterator[str]:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _locate(fm_inner: str, loc: tuple[Any, ...], fm_line: int) -> tuple[int, int]:
    """Line/col (1-based, whole file) of the deepest YAML node on ``loc``."""
    try:
        node = yaml.compose(fm_inner, Loader=yaml.SafeLoader)
    except (yaml.YAMLError, RecursionError):
        return fm_line, 1
    if node is None:
        return fm_line, 1
    mark = node.start_mark
    for part in loc:
        child = None
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode) and key_node.value == str(part):
                    child, mark = value_node, key_node.start_mark
                    break
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int) and 0 <= part < len(node.value):
            child = node.value[part]
            mark = child.start_mark
        if child is None:
            break
        node = child
    return fm_line + mark.line, mark.column + 1


def parse_template(source: str, template_id: str) -> ParseResult:
    diags: list[Diagnostic] = []

    def fail(line: int, col: int, message: str, code: str) -> ParseResult:
        return ParseResult(None, (*diags, Diagnostic(line, col, "error", message, code)))

    if len(source) > MAX_TEMPLATE_CHARS:
        return fail(1, 1, f"template is larger than {MAX_TEMPLATE_CHARS} characters", "limit")
    parsed = parse_note(source)
    if not parsed.has_frontmatter:
        return fail(1, 1, "a template starts with a --- frontmatter block that has a `template:` key",
                    "no-frontmatter")
    fm_line = parsed.fm_head.count("\n") + 1
    body_line = (parsed.fm_head + parsed.fm_inner + parsed.fm_close + parsed.gap).count("\n") + 1
    try:
        meta = yaml.safe_load(parsed.fm_inner)
    except yaml.MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        line = fm_line + (mark.line if mark else 0)
        return fail(line, (mark.column + 1) if mark else 1,
                    f"frontmatter is not valid YAML: {e.problem or e}", "yaml")
    except yaml.YAMLError as e:
        return fail(fm_line, 1, f"frontmatter is not valid YAML: {e}", "yaml")
    except RecursionError:
        return fail(fm_line, 1, "frontmatter is nested too deeply", "limit")
    if not isinstance(meta, dict) or not isinstance(meta.get("template"), dict):
        return fail(fm_line, 1, "frontmatter needs a `template:` mapping", "no-template")
    problem = _tree_problem(meta)
    if problem is not None:
        return fail(fm_line, 1, problem, "limit")
    for key in meta:
        if key != "template":
            line, col = _locate(parsed.fm_inner, (key,), fm_line)
            diags.append(Diagnostic(line, col, "warning",
                                    f"top-level key `{key}` is ignored; note frontmatter goes "
                                    "under template.frontmatter", "ignored-key"))
    try:
        model = _TemplateModel.model_validate(meta["template"])
    except ValidationError as e:
        errors = []
        for err in e.errors():
            loc = ("template", *err["loc"])
            line, col = _locate(parsed.fm_inner, loc, fm_line)
            where = ".".join(str(p) for p in loc)
            errors.append(Diagnostic(line, col, "error", f"{where}: {err['msg']}", "schema"))
        return ParseResult(None, (*diags, *errors))

    errors = []
    seen: set[str] = set()
    for i, p in enumerate(model.prompts):
        loc = ("template", "prompts", i, "id")
        message = None
        if p.id in seen:
            message = f"duplicate prompt id `{p.id}`"
        elif p.id in RESERVED_IDS:
            message = f"`{p.id}` is a built-in variable; pick another id"
        elif p.id in SHADOWABLE and SHADOWABLE[p.id] != p.type:
            message = f"a prompt with id `{p.id}` must have type {SHADOWABLE[p.id]}"
        seen.add(p.id)
        if message:
            line, col = _locate(parsed.fm_inner, loc, fm_line)
            errors.append(Diagnostic(line, col, "error", message, "prompt-id"))

    file_name = model.file.name or "{{date | format: YYYY-MM-DD}} " + model.name
    variables: set[str] = set()
    try:
        for text in (model.file.folder, file_name, parsed.body, *_strings(model.frontmatter)):
            for seg in tokenize(text):
                if isinstance(seg, Placeholder) and seg.path:
                    variables.add(seg.path[0])
    except TemplateLimitError as e:
        errors.append(Diagnostic(body_line, 1, "error", str(e), "limit"))
    if errors:
        return ParseResult(None, (*diags, *errors))

    prompts = tuple(
        Prompt(p.id, p.ask, p.type, p.optional, p.default, tuple(p.options or ()))
        for p in model.prompts
    )
    template = Template(
        id=template_id,
        name=model.name,
        description=model.description,
        prompts=prompts,
        file=FileSpec(model.file.folder, file_name),
        frontmatter=model.frontmatter,
        body=parsed.body,
        body_line=body_line,
        variables=tuple(sorted(variables)),
    )
    return ParseResult(template, tuple(diags))
```

Add `tests/test_templates_parse.py \` to `ci.yml`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_templates_parse.py tests/test_templates_security.py tests/test_templates_functions.py -v`
Expected: PASS, including the `parser_literal` test that Task 2 deselected.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/templates/parse.py tests/test_templates_parse.py tests/test_templates_security.py .github/workflows/ci.yml
git commit -m "feat(templates): template parser with line-numbered diagnostics"
```

---

### Task 4: Renderer — answers, evaluation, folder validation (`render.py`)

**Files:**
- Create: `ghostbrain/templates/render.py`
- Test: `tests/test_templates_render.py`; append to `tests/test_templates_security.py`
- Modify: `.github/workflows/ci.yml` (add `tests/test_templates_render.py \`)

**Interfaces:**
- Consumes: `tokenize`, `Text`, `Placeholder` (Task 1); `FIELD_IMPLS`, `FILTER_IMPLS`, `FILTERS_BY_NAME`, the value classes, `EMPTY`, `slugify`, `to_text` and `value_type` (Task 2); `Template` and `Prompt` (Task 3).
- Produces: `AnswerError(field, message)`, `RenderError`, `RenderEnv`, `RenderedNote` (`.path`, `.markdown()`), `Budget`, `coerce_answers`, `build_scope`, `evaluate`, `render_string`, `validate_folder` and `render(template, answers, env) -> RenderedNote`, plus the constants `MAX_ANSWER_CHARS = 10_000`, `MAX_OUTPUT_CHARS = 1_000_000` and `FILENAME_SLUG_MAX = 80`.

- [ ] **Step 1: Write the failing tests**

`tests/test_templates_render.py`:

````python
"""render(): variables, typed fields, filters, literals, filing, frontmatter."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import yaml

from ghostbrain.templates.functions import VARIABLES
from ghostbrain.templates.parse import parse_template
from ghostbrain.templates.render import (
    AnswerError,
    RenderEnv,
    build_scope,
    render,
)
from ghostbrain.templates.values import ProjectValue

NOW = datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2)))
ENV = RenderEnv(
    now=NOW,
    default_context="work",
    contexts=("work", "personal"),
    projects={"work/alpha": ProjectValue("work/alpha", "Alpha", "alpha", "work")},
    user_name="Sam",
    person_title=lambda p: {"30-cross-context/people/alex.md": "Alex"}.get(p),
)
PROMPTS = """  prompts:
    - id: person
      ask: Who?
      type: person
    - id: focus
      ask: Focus?
      type: text
      optional: true
"""


def tpl(body: str, *, prompts: str = PROMPTS, file: str = "", fm: str = ""):
    src = f"---\ntemplate:\n  name: T\n{prompts}{file}{fm}---\n{body}"
    r = parse_template(src, "t")
    assert r.ok, r.diagnostics
    return r.template


ALEX = {"person": "30-cross-context/people/alex"}


def test_scope_covers_exactly_the_registry_variables():
    assert set(build_scope({}, ENV)) | {"title"} == {s.name for s in VARIABLES}


def test_variables_and_typed_fields():
    t = tpl("{{person.name}}|{{person.link}}|{{person.path}}|{{date.iso}}|{{time}}|{{user.name}}|{{context}}|{{now.iso}}")
    assert render(t, ALEX, ENV).body == (
        "Alex|[[30-cross-context/people/alex]]|30-cross-context/people/alex.md|2026-10-09|14:30|Sam|work"
        "|2026-10-09T14:30:00+02:00"
    )


def test_person_name_falls_back_to_humanized_stem():
    t = tpl("{{person.name}}")
    assert render(t, {"person": "30-cross-context/people/jo-ann-lee.md"}, ENV).body == "Jo Ann Lee"


def test_freeform_person_name_links_by_name():
    t = tpl("{{person.name}} {{person.link}} [{{person.path}}]")
    assert render(t, {"person": "Alex"}, ENV).body == "Alex [[Alex]] []"


def test_filters():
    t = tpl(
        "{{date | format: D MMM YYYY}}|{{date | format: dddd [the] D}}|{{now | format: HH:mm}}"
        "|{{focus | upper}}|{{focus | lower}}|{{focus | slug}}"
    )
    assert render(t, {**ALEX, "focus": "Hello World"}, ENV).body == (
        "9 Oct 2026|Friday the 9|14:30|HELLO WORLD|hello world|hello-world"
    )


def test_default_filter_and_quoted_arg():
    t = tpl('{{focus | default: n/a}}|{{focus | default: "a | b"}}')
    assert render(t, ALEX, ENV).body == "n/a|a | b"


def test_unknown_names_fields_and_filters_stay_literal():
    body = "{{nope}} {{person.age}} {{date | shout}} {{date | format}} {{ bad expr }}"
    assert render(tpl(body), ALEX, ENV).body == body


def test_prompt_default_and_required():
    prompts = (
        "  prompts:\n    - id: status\n      ask: Status\n      type: choice\n"
        "      options: [proposed, accepted]\n      default: accepted\n"
        "    - id: who\n      ask: Who?\n      type: text\n"
    )
    t = tpl("{{status}} {{who}}", prompts=prompts)
    assert render(t, {"who": "x"}, ENV).body == "accepted x"
    with pytest.raises(AnswerError) as e:
        render(t, {}, ENV)
    assert e.value.field == "who" and "required" in str(e.value)
    with pytest.raises(AnswerError) as e:
        render(t, {"who": "x", "status": "maybe"}, ENV)
    assert e.value.field == "status"


@pytest.mark.parametrize(
    "answers, field",
    [
        ({**ALEX, "colour": "red"}, "colour"),
        ({**ALEX, "date": "9 Oct"}, "date"),
        ({**ALEX, "context": "nowhere"}, "context"),
        ({**ALEX, "project": "work/ghost"}, "project"),
        ({"person": "Al [[x]]"}, "person"),
        ({**ALEX, "focus": "x" * 10_001}, "focus"),
    ],
)
def test_bad_answers_name_their_field(answers, field):
    with pytest.raises(AnswerError) as e:
        render(tpl("{{focus}}"), answers, ENV)
    assert e.value.field == field


def test_implicit_context_project_and_date_answers():
    t = tpl("{{context}} {{project.name}} {{project.path}} {{date | format: D MMM}}",
            file='  file:\n    folder: "20-contexts/{{context}}/x"\n')
    note = render(t, {**ALEX, "context": "personal", "project": "work/alpha", "date": "2026-12-01"}, ENV)
    assert note.body == "personal Alpha 20-contexts/work/projects/alpha 1 Dec"
    assert note.folder == "20-contexts/personal/x"


def test_unanswered_optional_typed_prompt_is_empty_everywhere():
    prompts = "  prompts:\n    - id: project\n      ask: P\n      type: project\n      optional: true\n"
    t = tpl("[{{project.name}}] [{{project.name | default: none}}]", prompts=prompts)
    assert render(t, {}, ENV).body == "[] [none]"


def test_title_is_the_rendered_name_and_literal_inside_it():
    t = tpl("# {{title}}", file='  file:\n    name: "{{date | format: YYYY-MM-DD}} {{person.name}} {{title}}"\n')
    note = render(t, ALEX, ENV)
    assert note.title == "2026-10-09 Alex {{title}}"
    assert note.body == "# 2026-10-09 Alex {{title}}"


def test_filing_folder_filename_and_path():
    t = tpl("x", file='  file:\n    folder: "20-contexts/{{context}}/one-on-ones"\n'
                      '    name: "{{date | format: YYYY-MM-DD}} {{person.name}} 1-1"\n')
    note = render(t, ALEX, ENV)
    assert (note.folder, note.filename, note.title) == (
        "20-contexts/work/one-on-ones", "2026-10-09-alex-1-1.md", "2026-10-09 Alex 1-1")
    assert note.path == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md"


def test_long_titles_cap_the_filename_at_80():
    t = tpl("x", file='  file:\n    name: "{{focus}}"\n')
    note = render(t, {**ALEX, "focus": "word " * 40}, ENV)
    # 80-char cut lands on a dash, which is then stripped (make_slug rule).
    assert note.filename == ("word-" * 16).rstrip("-") + ".md"
    assert note.title == ("word " * 40).strip()


def test_punctuation_only_title_slugs_to_untitled():
    t = tpl("x", file='  file:\n    name: "{{focus}}"\n')
    assert render(t, {**ALEX, "focus": "???"}, ENV).filename == "untitled.md"
    note = render(t, {**ALEX, "focus": "Ünïcödé ✓"}, ENV)
    assert note.filename == "n-c-d.md" and note.title == "Ünïcödé ✓"


def test_frontmatter_defaults_rendering_and_markdown():
    fm = ('  frontmatter:\n    type: meeting\n    attendees: ["{{person.link}}"]\n'
          '    meta: {who: "{{person.name}}", n: 3, ok: true}\n    title: Custom\n'
          '    fromTemplate: hijack\n')
    note = render(tpl("Body {{person.name}}\n", fm=fm), ALEX, ENV)
    assert note.frontmatter == {
        "title": "Custom",
        "created": "2026-10-09T14:30:00+02:00",
        "updated": "2026-10-09T14:30:00+02:00",
        "type": "meeting",
        "attendees": ["[[30-cross-context/people/alex]]"],
        "meta": {"who": "Alex", "n": 3, "ok": True},
        "fromTemplate": "t",
    }
    text = note.markdown()
    assert text.startswith("---\n")
    head, body = text[4:].split("---\n\n", 1)
    assert yaml.safe_load(head) == note.frontmatter
    assert body == "Body Alex\n"


def test_placeholders_inside_query_fences_are_resolved():
    body = '```query\ntype: action_item\nmentions: "{{person.link}}"\nstatus: open\n```\n'
    assert render(tpl(body), ALEX, ENV).body == (
        '```query\ntype: action_item\nmentions: "[[30-cross-context/people/alex]]"\nstatus: open\n```\n'
    )
````

Append to `tests/test_templates_security.py`:

```python
import yaml as _yaml  # noqa: E402
from datetime import datetime as _dt, timedelta as _td, timezone as _tz  # noqa: E402

from ghostbrain.templates.render import (  # noqa: E402
    MAX_OUTPUT_CHARS,
    RenderEnv,
    RenderError,
    render,
)

_ENV = RenderEnv(now=_dt(2026, 10, 9, 14, 30, tzinfo=_tz(_td(hours=2))),
                 default_context="work", contexts=("work",))


def _t(folder: str, body: str = "x", name: str = "n"):
    src = (
        "---\ntemplate:\n  name: Evil\n  prompts:\n    - id: focus\n      ask: F\n      type: text\n"
        f"      optional: true\n  file:\n    folder: {_yaml.safe_dump(folder).splitlines()[0]}\n"
        f"    name: {_yaml.safe_dump(name).splitlines()[0]}\n---\n{body}"
    )
    r = parse_template(src, "evil")
    assert r.ok, r.diagnostics
    return r.template


@pytest.mark.parametrize(
    "folder, answer",
    [
        ("../../etc", ""),
        ("/etc", ""),
        ("20-contexts/../../..", ""),
        ("20-contexts/{{focus}}", "../../outside"),
        ("20-contexts/{{focus}}", "a\\..\\..\\b"),
        ("C:/Windows", ""),
        ("20-contexts/x:stream", ""),
        ("90-meta/templates", ""),
        ("90-META/prompts", ""),
        ("20-contexts/.git", ""),
        ("20-contexts/CON", ""),
        ("20-contexts/{{nope}}", ""),
        ("20-contexts/{{focus}}", "line\nbreak"),
        ("{{focus}}", "   "),
        ("a/b/c/d/e/f/g/h/i/j/k", ""),
    ],
)
def test_sec_rendered_folder_cannot_escape_or_hit_system_areas(folder, answer):
    with pytest.raises(RenderError):
        render(_t(folder), {"focus": answer} if answer else {}, _ENV)


def test_sec_file_name_cannot_carry_a_path():
    note = render(_t("20-contexts/work", name="../../evil/{{focus}}"), {"focus": "../x"}, _ENV)
    assert note.path == "20-contexts/work/evil-x.md"


def test_sec_answers_are_never_re_expanded():
    note = render(_t("20-contexts/work", body="{{focus}}"), {"focus": "{{user.name}} {{date}}"}, _ENV)
    assert note.body == "{{user.name}} {{date}}"


def test_sec_answers_cannot_inject_frontmatter_keys():
    src = (
        "---\ntemplate:\n  name: Inj\n  prompts:\n    - id: focus\n      ask: F\n      type: text\n"
        "  frontmatter:\n    summary: \"{{focus}}\"\n---\nbody\n"
    )
    t = parse_template(src, "inj").template
    from ghostbrain.vault_write.text import parse_note

    note = render(t, {"focus": "x\nevil: true\n---\ninjected"}, _ENV)
    parsed = parse_note(note.markdown())  # the same fence finder the write path uses
    data = _yaml.safe_load(parsed.fm_inner)
    assert "evil" not in data and data["summary"] == "x\nevil: true\n---\ninjected"
    assert parsed.body == "body\n"


def test_sec_output_size_is_capped():
    body = "{{focus}}" * 200
    with pytest.raises(RenderError):
        render(_t("20-contexts/work", body=body), {"focus": "x" * 10_000}, _ENV)
    assert 200 * 10_000 > MAX_OUTPUT_CHARS


def test_sec_person_path_answers_cannot_traverse():
    from ghostbrain.templates.render import AnswerError

    src = "---\ntemplate:\n  name: P\n  prompts:\n    - id: person\n      ask: W\n      type: person\n---\n{{person.link}}"
    t = parse_template(src, "p").template
    for bad in ("../../etc/passwd", "/etc/passwd", "30-cross-context/../../x", "C:/x", ".hidden/x", "a\\b"):
        with pytest.raises(AnswerError):
            render(t, {"person": bad}, _ENV)


def test_sec_person_lookup_never_reads_files():
    """Person names come from the in-memory link index only."""
    seen: list[str] = []
    env = RenderEnv(now=_ENV.now, default_context="work", contexts=("work",),
                    person_title=lambda p: seen.append(p) or None)
    src = "---\ntemplate:\n  name: P\n  prompts:\n    - id: person\n      ask: W\n      type: person\n---\n{{person.name}}"
    t = parse_template(src, "p").template
    assert render(t, {"person": "30-cross-context/people/alex"}, env).body == "Alex"
    assert seen == ["30-cross-context/people/alex.md"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_templates_render.py tests/test_templates_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.templates.render'`.

- [ ] **Step 3: Write the implementation**

`ghostbrain/templates/render.py`:

```python
"""Render a parsed template with answers into a note (spec: render.py).

Single pass with no recursion: a placeholder's value is inserted as text and
never re-scanned, so an answer containing ``{{…}}`` stays literal. Total
output is budgeted, frontmatter values are serialised with
``yaml.safe_dump`` (answers can't inject keys), and the target folder is
validated before anything can be written.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping

import yaml

from ghostbrain.templates.functions import FIELD_IMPLS, FILTER_IMPLS, FILTERS_BY_NAME
from ghostbrain.templates.lang import Placeholder, Text, tokenize
from ghostbrain.templates.parse import Template
from ghostbrain.templates.values import (
    EMPTY,
    DateTimeValue,
    DateValue,
    PersonValue,
    ProjectValue,
    UserValue,
    Value,
    slugify,
    to_text,
    value_type,
)

MAX_ANSWER_CHARS = 10_000
MAX_OUTPUT_CHARS = 1_000_000
MAX_TITLE_CHARS = 200
MAX_PERSON_NAME_CHARS = 200
MAX_FOLDER_DEPTH = 10
MAX_SEGMENT_CHARS = 120
MAX_TREE_DEPTH = 12
MAX_TREE_NODES = 5_000
FILENAME_SLUG_MAX = 80
SYSTEM_TOP_LEVEL = "90-meta"
IMPLICIT_ANSWERS: Mapping[str, str] = {"context": "context", "project": "project", "date": "date"}
_BAD_SEGMENT_CHARS = frozenset('<>:"|?*\\')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PERSON_NAME_BAD_RE = re.compile(r"[\[\]|#\r\n]")


class AnswerError(ValueError):
    """An answer is missing or invalid; ``field`` is the prompt id."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class RenderError(ValueError):
    """The rendered note can't be filed: bad folder, or too large."""


def _no_title(_path: str) -> str | None:
    return None


@dataclass(frozen=True)
class RenderEnv:
    now: datetime
    default_context: str
    contexts: tuple[str, ...]
    projects: Mapping[str, ProjectValue] = field(default_factory=dict)
    user_name: str = ""
    person_title: Callable[[str], str | None] = _no_title


@dataclass(frozen=True)
class RenderedNote:
    template_id: str
    folder: str
    filename: str
    title: str
    frontmatter: dict[str, Any]
    body: str

    @property
    def path(self) -> str:
        return f"{self.folder}/{self.filename}"

    def markdown(self) -> str:
        fm = yaml.safe_dump(self.frontmatter, sort_keys=False, allow_unicode=True,
                            default_flow_style=False)
        return f"---\n{fm}---\n\n{self.body}"


class Budget:
    def __init__(self, limit: int) -> None:
        self.left = limit

    def take(self, n: int) -> None:
        self.left -= n
        if self.left < 0:
            raise RenderError(f"the rendered note is larger than {MAX_OUTPUT_CHARS} characters")


def _humanize(stem: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_\s]+", stem) if w) or stem


def _coerce_person(field_id: str, raw: str, env: RenderEnv) -> PersonValue:
    if "/" in raw or "\\" in raw or raw.lower().endswith(".md"):
        parts = raw.split("/")
        if (
            "\\" in raw
            or raw.startswith("/")
            or "\x00" in raw
            or any(p in ("", ".", "..") or p.startswith(".") or ":" in p for p in parts)
        ):
            raise AnswerError(field_id, "a person must be a vault note path or a name")
        path = raw if raw.lower().endswith(".md") else f"{raw}.md"
        stem = PurePosixPath(path).stem
        title = env.person_title(path)
        return PersonValue(name=title if title and title != stem else _humanize(stem), path=path)
    if len(raw) > MAX_PERSON_NAME_CHARS or _PERSON_NAME_BAD_RE.search(raw):
        raise AnswerError(field_id, "a person's name can't contain [ ] | # or line breaks")
    return PersonValue(name=raw, path="")


def _coerce_one(kind: str, field_id: str, raw: str, env: RenderEnv, options: tuple[str, ...]) -> Value:
    if kind == "text":
        return raw
    if kind == "choice":
        if raw not in options:
            raise AnswerError(field_id, f"pick one of: {', '.join(options)}")
        return raw
    if kind == "date":
        try:
            if not _DATE_RE.fullmatch(raw):
                raise ValueError(raw)
            return DateValue(date.fromisoformat(raw))
        except ValueError:
            raise AnswerError(field_id, "use a date like 2026-10-09") from None
    if kind == "context":
        if raw not in env.contexts:
            raise AnswerError(field_id, f"unknown context `{raw}`")
        return raw
    if kind == "project":
        project = env.projects.get(raw)
        if project is None:
            raise AnswerError(field_id, f"unknown project `{raw}`")
        return project
    return _coerce_person(field_id, raw, env)


def coerce_answers(template: Template, answers: Mapping[str, str], env: RenderEnv) -> dict[str, Value]:
    prompt_ids = {p.id for p in template.prompts}
    for key, raw in answers.items():
        if key not in prompt_ids and key not in IMPLICIT_ANSWERS:
            raise AnswerError(key, f"unknown answer `{key}`")
        if not isinstance(raw, str):
            raise AnswerError(key, "answers must be text")
        if len(raw) > MAX_ANSWER_CHARS:
            raise AnswerError(key, f"answer is longer than {MAX_ANSWER_CHARS} characters")
    values: dict[str, Value] = {}
    for p in template.prompts:
        raw = (answers.get(p.id) or "").strip()
        if not raw:
            if p.default is not None:
                raw = p.default
            elif p.optional:
                values[p.id] = EMPTY
                continue
            else:
                raise AnswerError(p.id, "an answer is required")
        values[p.id] = _coerce_one(p.type, p.id, raw, env, p.options)
    for key, kind in IMPLICIT_ANSWERS.items():
        raw = (answers.get(key) or "").strip()
        if key not in prompt_ids and raw:
            values[key] = _coerce_one(kind, key, raw, env, ())
    return values


def build_scope(values: Mapping[str, Value], env: RenderEnv) -> dict[str, Value]:
    """Builtins (see functions.VARIABLES, minus `title`) overlaid with answers."""
    scope: dict[str, Value] = {
        "date": DateValue(env.now.date()),
        "time": f"{env.now.hour:02d}:{env.now.minute:02d}",
        "now": DateTimeValue(env.now),
        "context": env.default_context,
        "project": EMPTY,
        "user": UserValue(env.user_name),
    }
    for key, value in values.items():
        if value is EMPTY and key in ("date", "context"):
            continue  # an unanswered optional date/context prompt keeps the builtin
        scope[key] = value
    return scope


def evaluate(ph: Placeholder, scope: Mapping[str, Value]) -> Value | None:
    """The placeholder's value, or None to render it literally."""
    if ph.path is None or ph.path[0] not in scope:
        return None
    value = scope[ph.path[0]]
    for name in ph.path[1:]:
        if value is EMPTY:
            continue
        impl = FIELD_IMPLS.get((value_type(value), name))
        if impl is None:
            return None
        value = impl(value)
    for call in ph.filters:
        spec = FILTERS_BY_NAME.get(call.name)
        if spec is None or (spec.arg_required and call.arg is None) or (spec.arg is None and call.arg is not None):
            return None
        value = FILTER_IMPLS[call.name](value, call.arg)
    return value


def render_string(text: str, scope: Mapping[str, Value], budget: Budget | None = None) -> str:
    budget = budget or Budget(MAX_OUTPUT_CHARS)
    out: list[str] = []
    for seg in tokenize(text):
        if isinstance(seg, Text):
            piece = seg.text
        else:
            value = evaluate(seg, scope)
            piece = seg.raw if value is None else to_text(value)
        budget.take(len(piece))
        out.append(piece)
    return "".join(out)


def validate_folder(folder: str) -> str:
    f = folder.strip().rstrip("/")
    if not f:
        raise RenderError("the template's folder rendered empty")
    if "{{" in f or "}}" in f:
        raise RenderError(f"folder has an unresolved placeholder: {f}")
    if f.startswith("/") or "\\" in f:
        raise RenderError("folder must be a vault-relative path using /")
    parts = f.split("/")
    if len(parts) > MAX_FOLDER_DEPTH:
        raise RenderError(f"folder is deeper than {MAX_FOLDER_DEPTH} levels")
    for part in parts:
        if (
            part in ("", ".", "..")
            or part.startswith(".")
            or part.endswith(".")
            or part != part.strip()
            or len(part) > MAX_SEGMENT_CHARS
            or any(c in _BAD_SEGMENT_CHARS or ord(c) < 32 for c in part)
            or part.split(".")[0].upper() in _WINDOWS_RESERVED
        ):
            raise RenderError(f"folder segment {part!r} is not allowed")
    if parts[0].lower() == SYSTEM_TOP_LEVEL:
        raise RenderError("templates can't file notes under 90-meta (system area)")
    return "/".join(parts)


def _render_tree(value: Any, scope: Mapping[str, Value], budget: Budget, depth: int, nodes: list[int]) -> Any:
    nodes[0] += 1
    if nodes[0] > MAX_TREE_NODES or depth > MAX_TREE_DEPTH:
        raise RenderError("template frontmatter is too large or too deeply nested")
    if isinstance(value, str):
        return render_string(value, scope, budget)
    if isinstance(value, dict):
        return {str(k): _render_tree(v, scope, budget, depth + 1, nodes) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_tree(v, scope, budget, depth + 1, nodes) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def render(template: Template, answers: Mapping[str, str], env: RenderEnv) -> RenderedNote:
    budget = Budget(MAX_OUTPUT_CHARS)
    scope = build_scope(coerce_answers(template, answers, env), env)
    raw_title = render_string(template.file.name, scope, budget)
    title = " ".join(raw_title.split())[:MAX_TITLE_CHARS] or template.name
    folder = validate_folder(render_string(template.file.folder, scope, budget))
    scope = {**scope, "title": title}
    rendered_fm = _render_tree(dict(template.frontmatter), scope, budget, 0, [0])
    body = render_string(template.body, scope, budget)
    stamp = env.now.isoformat(timespec="seconds")
    frontmatter = {"title": title, "created": stamp, "updated": stamp, **rendered_fm,
                   "fromTemplate": template.id}
    filename = slugify(title, FILENAME_SLUG_MAX) + ".md"
    return RenderedNote(template.id, folder, filename, title, frontmatter, body)
```

Add `tests/test_templates_render.py \` to `ci.yml`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_templates_render.py tests/test_templates_security.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/templates/render.py tests/test_templates_render.py tests/test_templates_security.py .github/workflows/ci.yml
git commit -m "feat(templates): single-pass renderer with answer coercion and folder guard"
```

---

### Task 5: Starter templates, registry and bootstrap seeding

**Files:**
- Create: `ghostbrain/templates/starters.py`, `ghostbrain/templates/registry.py`
- Modify: `ghostbrain/bootstrap.py` (import, plus one call in `bootstrap()` after the `SEED_FILES` loop)
- Test: `tests/test_templates_starters.py`, `tests/test_templates_registry.py`; append to `tests/test_templates_security.py`
- Modify: `.github/workflows/ci.yml` (add both test files)

**Interfaces:**
- Consumes: `parse_template`, `Template`, `Diagnostic` (Task 3); `render`, `RenderEnv` (Task 4, in tests); `MAX_TEMPLATE_CHARS` (Task 1); `ghostbrain.paths.vault_path()`.
- Produces: `STARTER_TEMPLATES`, `seed_starter_templates(root) -> list[str]`, `TEMPLATES_REL`, `TEMPLATE_ID_RE`, `TemplateNotFound`, `TemplateInvalid(template_id, diagnostics)`, `TemplateInfo` (with `.valid` and `.to_json()`), `templates_dir`, `list_templates`, `read_template_source` and `load_template`, all as in the Interfaces block.

- [ ] **Step 1: Write the failing tests**

`tests/test_templates_starters.py`:

```python
"""Starter templates: valid, render as advertised, seeded once, never overwritten."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ghostbrain.templates.parse import parse_template
from ghostbrain.templates.render import RenderEnv, render
from ghostbrain.templates.starters import STARTER_TEMPLATES, seed_starter_templates

ENV = RenderEnv(now=datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2))),
                default_context="work", contexts=("work", "personal"))


def _tpl(name: str):
    r = parse_template(STARTER_TEMPLATES[name], name[:-3])
    assert r.ok and r.diagnostics == (), r.diagnostics
    return r.template


def test_the_three_starters():
    assert sorted(STARTER_TEMPLATES) == ["decision-record.md", "meeting-notes.md", "one-on-one.md"]
    assert [_tpl(n).name for n in sorted(STARTER_TEMPLATES)] == ["Decision record", "Meeting notes", "1-1"]


def test_one_on_one_renders_as_in_the_spec():
    note = render(_tpl("one-on-one.md"), {"person": "Alex"}, ENV)
    assert note.path == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md"
    assert note.frontmatter["type"] == "meeting"
    assert note.frontmatter["attendees"] == ["[[Alex]]"]
    assert note.body.startswith("# 1-1 with [[Alex]] — 9 Oct 2026\n")
    assert '```query\ntype: action_item\nmentions: "[[Alex]]"\nstatus: open\nsort: created desc\n```' in note.body


def test_meeting_notes_renders():
    note = render(_tpl("meeting-notes.md"), {"topic": "Planning"}, ENV)
    assert note.path == "20-contexts/work/meetings/2026-10-09-planning.md"
    assert note.body.startswith("# Planning — 9 Oct 2026\n")
    assert "## Action items" in note.body


def test_decision_record_defaults():
    note = render(_tpl("decision-record.md"), {"decision": "Use Postgres for search"}, ENV)
    assert note.path == "20-contexts/work/decisions/2026-10-09-use-postgres-for-search.md"
    assert note.frontmatter["status"] == "accepted" and note.frontmatter["type"] == "decision"
    assert "**Project:** none" in note.body


def test_seed_writes_all_when_folder_missing(tmp_path: Path):
    written = seed_starter_templates(tmp_path)
    assert sorted(written) == [f"90-meta/templates/{n}" for n in sorted(STARTER_TEMPLATES)]
    for name, body in STARTER_TEMPLATES.items():
        assert (tmp_path / "90-meta/templates" / name).read_text(encoding="utf-8") == body
    assert seed_starter_templates(tmp_path) == []


def test_deleted_starter_is_not_reseeded(tmp_path: Path):
    seed_starter_templates(tmp_path)
    (tmp_path / "90-meta/templates/meeting-notes.md").unlink()
    assert seed_starter_templates(tmp_path) == []
    assert not (tmp_path / "90-meta/templates/meeting-notes.md").exists()


def test_seed_never_overwrites(tmp_path: Path):
    folder = tmp_path / "90-meta/templates"
    folder.mkdir(parents=True)
    (folder / "one-on-one.md").write_text("mine", encoding="utf-8")
    assert seed_starter_templates(tmp_path) == []
    assert (folder / "one-on-one.md").read_text(encoding="utf-8") == "mine"


def test_bootstrap_seeds_starters_and_keeps_edits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    from ghostbrain.bootstrap import bootstrap

    root = bootstrap(tmp_path)
    f = root / "90-meta/templates/one-on-one.md"
    assert f.read_text(encoding="utf-8") == STARTER_TEMPLATES["one-on-one.md"]
    f.write_text("edited", encoding="utf-8")
    bootstrap(tmp_path)
    assert f.read_text(encoding="utf-8") == "edited"
```

`tests/test_templates_registry.py`:

```python
"""Listing and loading templates from 90-meta/templates/."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.templates.registry import (
    TemplateInvalid,
    TemplateNotFound,
    list_templates,
    load_template,
    read_template_source,
)

OK = "---\ntemplate:\n  name: Weekly review\n---\n# Week {{date | format: D MMM}}\n"
BROKEN = "---\ntemplate:\n  name: [unclosed\n---\n"


def _put(root: Path, name: str, text: str | bytes) -> Path:
    p = root / "90-meta/templates" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        p.write_bytes(text)
    else:
        p.write_text(text, encoding="utf-8")
    return p


def test_list_seeds_starters_when_folder_missing(tmp_path: Path):
    infos = list_templates(tmp_path)
    assert [i.template.name for i in infos] == ["1-1", "Decision record", "Meeting notes"]
    assert all(i.valid for i in infos)
    j = infos[0].to_json()
    assert j["id"] == "one-on-one" and j["path"] == "90-meta/templates/one-on-one.md"
    assert j["valid"] is True and j["diagnostics"] == []
    assert j["variables"] == ["context", "date", "focus", "person"]
    assert [p["id"] for p in j["prompts"]] == ["person", "focus"]


def test_empty_folder_is_not_seeded(tmp_path: Path):
    (tmp_path / "90-meta/templates").mkdir(parents=True)
    assert list_templates(tmp_path) == []


def test_list_keeps_valid_templates_next_to_broken_one(tmp_path: Path):
    _put(tmp_path, "weekly-review.md", OK)
    _put(tmp_path, "broken.md", BROKEN)
    infos = {i.id: i for i in list_templates(tmp_path)}
    assert infos["weekly-review"].valid
    bad = infos["broken"].to_json()
    assert bad["valid"] is False and bad["name"] == "broken" and bad["prompts"] == []
    assert bad["diagnostics"][0]["code"] == "yaml"


def test_bad_file_name_encoding_and_size_are_listed_invalid(tmp_path: Path):
    _put(tmp_path, "My Notes.md", OK)
    _put(tmp_path, "latin.md", "---\ntemplate:\n  name: caf\xe9\n---\n".encode("latin-1"))
    _put(tmp_path, "huge.md", OK + "a" * 1_100_000)
    _put(tmp_path, ".hidden.md", OK)
    _put(tmp_path, "notes.txt", OK)
    codes = {i.id: i.diagnostics[0].code for i in list_templates(tmp_path)}
    assert codes == {"My Notes": "file-name", "latin": "encoding", "huge": "limit"}


def test_load_and_read(tmp_path: Path):
    _put(tmp_path, "weekly-review.md", OK)
    assert read_template_source("weekly-review", tmp_path) == OK
    t = load_template("weekly-review", tmp_path)
    assert t.id == "weekly-review" and t.name == "Weekly review"


def test_load_unknown_and_invalid(tmp_path: Path):
    _put(tmp_path, "broken.md", BROKEN)
    with pytest.raises(TemplateNotFound):
        load_template("missing", tmp_path)
    with pytest.raises(TemplateInvalid) as e:
        load_template("broken", tmp_path)
    assert e.value.diagnostics[0].code == "yaml"
    assert str(e.value).startswith("line ")


def test_default_root_is_the_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _put(tmp_path, "weekly-review.md", OK)
    assert load_template("weekly-review").name == "Weekly review"
```

Append to `tests/test_templates_security.py`:

```python
import os  # noqa: E402

from ghostbrain.templates.registry import (  # noqa: E402
    TemplateNotFound,
    list_templates,
    load_template,
    read_template_source,
)

_OK_TPL = "---\ntemplate:\n  name: Outside\n---\nsecret body\n"


def _symlink(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")


@pytest.mark.parametrize("bad_id", ["../secret", "..", "a/b", "A", ".hidden", "x" * 65, "", "secret.md"])
def test_sec_template_ids_cannot_traverse(tmp_path, bad_id):
    vault = tmp_path / "vault"
    (vault / "90-meta/templates").mkdir(parents=True)
    (vault / "90-meta/secret.md").write_text(_OK_TPL, encoding="utf-8")
    with pytest.raises(TemplateNotFound):
        load_template(bad_id, vault)
    with pytest.raises(TemplateNotFound):
        read_template_source(bad_id, vault)


def test_sec_symlinked_template_file_is_never_read(tmp_path):
    vault = tmp_path / "vault"
    (vault / "90-meta/templates").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text(_OK_TPL, encoding="utf-8")
    _symlink(outside, vault / "90-meta/templates/outside.md")
    assert [i.id for i in list_templates(vault)] == []
    with pytest.raises(TemplateNotFound):
        read_template_source("outside", vault)


def test_sec_symlinked_templates_folder_outside_vault_is_ignored(tmp_path):
    vault = tmp_path / "vault"
    (vault / "90-meta").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "outside.md").write_text(_OK_TPL, encoding="utf-8")
    _symlink(elsewhere, vault / "90-meta/templates")
    assert list_templates(vault) == []
    with pytest.raises(TemplateNotFound):
        load_template("outside", vault)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_templates_starters.py tests/test_templates_registry.py tests/test_templates_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.templates.starters'`.

- [ ] **Step 3: Write the implementation**

`ghostbrain/templates/starters.py`:

````python
"""The three starter templates (spec: 1-1, Meeting notes, Decision record).

Seeded into <vault>/90-meta/templates/ only when that folder is missing, with
exclusive create: a user's edit or deletion is never undone. No pydantic
import here, because bootstrap imports this module in base installs.
"""
from __future__ import annotations

from pathlib import Path

TEMPLATES_FOLDER = ("90-meta", "templates")

ONE_ON_ONE = """---
template:
  name: 1-1
  description: Weekly 1-1 with open follow-ups for the person
  prompts:
    - id: person
      ask: "Who's this 1-1 with?"
      type: person
    - id: focus
      ask: "Anything specific to cover?"
      type: text
      optional: true
  file:
    folder: "20-contexts/{{context}}/one-on-ones"
    name: "{{date | format: YYYY-MM-DD}} {{person.name}} 1-1"
  frontmatter:
    type: meeting
    attendees: ["{{person.link}}"]
---
# 1-1 with {{person.link}} — {{date | format: D MMM YYYY}}

{{focus}}

## Open follow-ups

```query
type: action_item
mentions: "{{person.link}}"
status: open
sort: created desc
```

## Notes

- 
"""

MEETING_NOTES = """---
template:
  name: Meeting notes
  description: Agenda, notes, decisions and action items for any meeting
  prompts:
    - id: topic
      ask: "What's the meeting about?"
      type: text
  file:
    folder: "20-contexts/{{context}}/meetings"
    name: "{{date | format: YYYY-MM-DD}} {{topic}}"
  frontmatter:
    type: meeting
---
# {{topic}} — {{date | format: D MMM YYYY}}

## Attendees

- 

## Agenda

- 

## Notes

- 

## Decisions

- 

## Action items

- [ ] 
"""

DECISION_RECORD = """---
template:
  name: Decision record
  description: One decision, the options weighed, and why
  prompts:
    - id: decision
      ask: "What did you decide?"
      type: text
    - id: status
      ask: "Status"
      type: choice
      options: [proposed, accepted, superseded]
      default: accepted
    - id: project
      ask: "Which project?"
      type: project
      optional: true
  file:
    folder: "20-contexts/{{context}}/decisions"
    name: "{{date | format: YYYY-MM-DD}} {{decision}}"
  frontmatter:
    type: decision
    status: "{{status}}"
---
# {{decision}}

**Date:** {{date | format: D MMM YYYY}} · **Status:** {{status}} · **Project:** {{project.name | default: none}}

## Context

What made this decision necessary?

## Options considered

1. 

## Decision

## Consequences
"""

STARTER_TEMPLATES: dict[str, str] = {
    "one-on-one.md": ONE_ON_ONE,
    "meeting-notes.md": MEETING_NOTES,
    "decision-record.md": DECISION_RECORD,
}


def seed_starter_templates(root: Path) -> list[str]:
    """Write the starters if <root>/90-meta/templates is missing. Returns the
    vault-relative paths written; [] when the folder already existed."""
    folder = Path(root).joinpath(*TEMPLATES_FOLDER)
    if folder.exists() or folder.is_symlink():
        return []
    folder.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, body in STARTER_TEMPLATES.items():
        try:
            with open(folder / name, "x", encoding="utf-8", newline="\n") as fh:
                fh.write(body)
        except FileExistsError:
            continue
        written.append("/".join((*TEMPLATES_FOLDER, name)))
    return written
````

`ghostbrain/templates/registry.py`:

```python
"""Templates on disk: <vault>/90-meta/templates/<id>.md (spec decision 1).

Ids are file stems matching TEMPLATE_ID_RE. Symlinked template files are
never read, and a templates folder that resolves outside the vault is
ignored, so a template id can only ever name a file inside the vault.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ghostbrain.paths import vault_path
from ghostbrain.templates.lang import MAX_TEMPLATE_CHARS
from ghostbrain.templates.parse import Diagnostic, Template, parse_template
from ghostbrain.templates.starters import seed_starter_templates

TEMPLATES_REL = "90-meta/templates"
TEMPLATE_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
MAX_TEMPLATE_BYTES = MAX_TEMPLATE_CHARS * 4


class TemplateNotFound(LookupError):
    pass


class TemplateInvalid(ValueError):
    def __init__(self, template_id: str, diagnostics: tuple[Diagnostic, ...]) -> None:
        first = next((d for d in diagnostics if d.severity == "error"), None)
        super().__init__(f"line {first.line}: {first.message}" if first else "template has errors")
        self.template_id = template_id
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class TemplateInfo:
    id: str
    path: str
    template: Template | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def valid(self) -> bool:
        return self.template is not None

    def to_json(self) -> dict[str, Any]:
        t = self.template
        return {
            "id": self.id,
            "path": self.path,
            "name": t.name if t else self.id,
            "description": t.description if t else "",
            "prompts": [p.to_json() for p in t.prompts] if t else [],
            "variables": list(t.variables) if t else [],
            "valid": t is not None,
            "diagnostics": [d.to_json() for d in self.diagnostics],
        }


def templates_dir(root: Path | None = None) -> Path:
    return Path(root or vault_path()) / TEMPLATES_REL


def _inside_vault(base: Path, vault: Path) -> bool:
    try:
        return base.resolve().is_relative_to(vault.resolve())
    except OSError:
        return False


def _read_source(template_id: str, path: Path) -> str:
    if path.stat().st_size > MAX_TEMPLATE_BYTES:
        raise TemplateInvalid(template_id, (Diagnostic(1, 1, "error", "template file is too large", "limit"),))
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise TemplateInvalid(
            template_id, (Diagnostic(1, 1, "error", "template file is not UTF-8 text", "encoding"),)
        ) from None


def _template_path(template_id: str, root: Path | None) -> Path:
    if not isinstance(template_id, str) or not TEMPLATE_ID_RE.fullmatch(template_id):
        raise TemplateNotFound(template_id)
    vault = Path(root or vault_path())
    base = templates_dir(vault)
    path = base / f"{template_id}.md"
    if path.is_symlink() or not path.is_file() or not _inside_vault(base, vault):
        raise TemplateNotFound(template_id)
    return path


def read_template_source(template_id: str, root: Path | None = None) -> str:
    return _read_source(template_id, _template_path(template_id, root))


def load_template(template_id: str, root: Path | None = None) -> Template:
    result = parse_template(read_template_source(template_id, root), template_id)
    if result.template is None:
        raise TemplateInvalid(template_id, result.diagnostics)
    return result.template


def _info(template_id: str, path: Path) -> TemplateInfo:
    rel = f"{TEMPLATES_REL}/{path.name}"
    if not TEMPLATE_ID_RE.fullmatch(template_id):
        return TemplateInfo(template_id, rel, None, (Diagnostic(
            1, 1, "error",
            "rename the file to lowercase letters, digits and dashes (e.g. weekly-review.md)",
            "file-name"),))
    try:
        result = parse_template(_read_source(template_id, path), template_id)
    except TemplateInvalid as e:
        return TemplateInfo(template_id, rel, None, e.diagnostics)
    return TemplateInfo(template_id, rel, result.template, result.diagnostics)


def list_templates(root: Path | None = None) -> list[TemplateInfo]:
    """Every *.md in the templates folder, valid or not (broken ones carry
    diagnostics). Seeds the starters first if the folder is missing."""
    vault = Path(root or vault_path())
    base = templates_dir(vault)
    if not base.exists() and not base.is_symlink():
        seed_starter_templates(vault)
    if not base.is_dir() or not _inside_vault(base, vault):
        return []
    infos = [
        _info(entry.stem, entry)
        for entry in sorted(base.iterdir(), key=lambda p: p.name)
        if entry.suffix == ".md" and not entry.name.startswith(".")
        and not entry.is_symlink() and entry.is_file()
    ]
    infos.sort(key=lambda i: ((i.template.name if i.template else i.id).lower(), i.id))
    return infos
```

In `ghostbrain/bootstrap.py`, add the import after `from ghostbrain.paths import vault_path`:

```python
from ghostbrain.templates.starters import seed_starter_templates
```

In `bootstrap()`, directly after the `for rel, body in SEED_FILES.items(): _write_if_absent(...)` loop, add:

```python
    # Smart-template starters (90-meta/templates/), only if that folder is missing.
    seed_starter_templates(root)
```

Add `tests/test_templates_starters.py \` and `tests/test_templates_registry.py \` to `ci.yml`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_templates_starters.py tests/test_templates_registry.py tests/test_templates_security.py tests/test_bootstrap_contexts.py tests/test_bootstrap_routing_mode.py tests/test_no_hardcoded_contexts.py -v`
Expected: PASS. The bootstrap tests show that seeding stays idempotent and adds no banned names.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/templates/starters.py ghostbrain/templates/registry.py ghostbrain/bootstrap.py tests/test_templates_starters.py tests/test_templates_registry.py tests/test_templates_security.py .github/workflows/ci.yml
git commit -m "feat(templates): starter templates, registry and bootstrap seeding"
```

---

### Task 6: Render environment and create-through-the-write-path (`env.py`, `create.py`)

**Files:**
- Create: `ghostbrain/templates/env.py`, `ghostbrain/templates/create.py`
- Test: `tests/test_templates_create.py`; append to `tests/test_templates_security.py`
- Modify: `.github/workflows/ci.yml` (add `tests/test_templates_create.py \`)

**Interfaces:**
- Consumes: `load_template` (Task 5); `render`, `RenderEnv`, `RenderedNote` (Task 4); `ProjectValue` (Task 2); `ghostbrain.routing_config.contexts()`; `ghostbrain.api.repo.projects.list_projects() -> list[dict]` (keys `id`, `name`, `slug`, `context`); `ghostbrain.vault_index.links.get_link_index() -> LinkIndex` (`.ready`, `.ensure_fresh(wait)`, `.get(path) -> NoteEntry | None` with `.title`); and B1's `vault_write.write_new(rel_path, content, *, actor, reason) -> WriteResult(status, change_id, etag, path, updated)`, `vault_write.resolve_safe(rel) -> Path` (raises `InvalidPath`) and `vault_write.USER`.
- Produces: `build_env() -> RenderEnv`; `CreatedNote(path, title, etag, status)`; `create_from_template(template_id, answers, *, actor=USER, env=None)`; `preview_from_template(template_id, answers, *, env=None)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_templates_create.py`:

```python
"""create_from_template writes through vault_write as the user; preview writes nothing."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ghostbrain import vault_write
from ghostbrain.templates import env as env_mod
from ghostbrain.templates.create import create_from_template, preview_from_template
from ghostbrain.templates.render import RenderEnv
from ghostbrain.templates.starters import seed_starter_templates

NOW = datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2)))
ENV = RenderEnv(now=NOW, default_context="work", contexts=("work", "personal"))


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(root))
    seed_starter_templates(root)
    return root


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_create_writes_through_the_write_path_as_user(vault: Path, monkeypatch):
    calls = []
    real = vault_write.write_new

    def spy(rel_path, content, *, actor, reason="", max_attempts=100):
        calls.append((rel_path, actor, reason))
        return real(rel_path, content, actor=actor, reason=reason, max_attempts=max_attempts)

    monkeypatch.setattr("ghostbrain.templates.create.vault_write.write_new", spy)
    created = create_from_template("meeting-notes", {"topic": "Planning"}, env=ENV)
    assert created.path == "20-contexts/work/meetings/2026-10-09-planning.md"
    assert (created.title, created.status) == ("2026-10-09 Planning", "applied")
    assert created.etag
    assert calls == [(created.path, "user", "new note from template meeting-notes")]
    text = (vault / created.path).read_text(encoding="utf-8")
    head, body = text[4:].split("---\n\n", 1)
    assert yaml.safe_load(head)["fromTemplate"] == "meeting-notes"
    assert body.startswith("# Planning — 9 Oct 2026\n")


def test_second_create_same_day_gets_suffix_never_overwrites(vault: Path):
    first = create_from_template("meeting-notes", {"topic": "Planning"}, env=ENV)
    original = (vault / first.path).read_bytes()
    second = create_from_template("meeting-notes", {"topic": "Planning"}, env=ENV)
    assert second.path == "20-contexts/work/meetings/2026-10-09-planning-2.md"
    assert (vault / first.path).read_bytes() == original


def test_preview_writes_nothing(vault: Path):
    before = _files(vault)
    note = preview_from_template("one-on-one", {"person": "Alex"}, env=ENV)
    assert note.path == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md"
    assert _files(vault) == before


def test_build_env_reads_contexts_projects_and_user(vault: Path, monkeypatch):
    (vault / "90-meta/routing.yaml").write_text("contexts:\n  - work\n  - personal\n", encoding="utf-8")
    (vault / "90-meta/projects.json").write_text(json.dumps([
        {"id": "work/alpha", "context": "work", "slug": "alpha", "name": "Alpha",
         "description": "", "archived": False, "created_at": 0},
    ]), encoding="utf-8")
    (vault / "90-meta/config.yaml").write_text("user:\n  name: Sam\n", encoding="utf-8")
    monkeypatch.setattr(env_mod, "_now", lambda: NOW)
    env = env_mod.build_env()
    assert (env.now, env.default_context, env.contexts, env.user_name) == (NOW, "work", ("work", "personal"), "Sam")
    assert env.projects["work/alpha"].name == "Alpha"


def test_build_env_without_config_has_empty_user(vault: Path):
    assert env_mod.build_env().user_name == ""


def test_person_title_uses_a_ready_index_only(vault: Path, monkeypatch):
    class Ready:
        ready = True

        def ensure_fresh(self, wait=0.25):
            return True

        def get(self, path):
            return SimpleNamespace(title="Alex Smith") if path == "30-cross-context/people/alex.md" else None

    class Cold(Ready):
        ready = False

    monkeypatch.setattr(env_mod, "get_link_index", lambda: Ready())
    assert env_mod.build_env().person_title("30-cross-context/people/alex.md") == "Alex Smith"
    monkeypatch.setattr(env_mod, "get_link_index", lambda: Cold())
    assert env_mod.build_env().person_title("30-cross-context/people/alex.md") is None
```

Append to `tests/test_templates_security.py`:

```python
def test_sec_symlinked_folder_inside_vault_cannot_write_outside(tmp_path, monkeypatch):
    from ghostbrain.templates.create import create_from_template, preview_from_template
    from ghostbrain.vault_write import InvalidPath

    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "90-meta/templates").mkdir(parents=True)
    (vault / "20-contexts/work").mkdir(parents=True)
    _symlink(outside, vault / "20-contexts/work/escape")
    (vault / "90-meta/templates/escape.md").write_text(
        "---\ntemplate:\n  name: Escape\n  file:\n    folder: 20-contexts/work/escape\n---\nx\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))
    with pytest.raises(InvalidPath):
        preview_from_template("escape", {}, env=_ENV)
    with pytest.raises(InvalidPath):
        create_from_template("escape", {}, env=_ENV)
    assert list(outside.iterdir()) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_templates_create.py tests/test_templates_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.templates.create'`.

- [ ] **Step 3: Write the implementation**

`ghostbrain/templates/env.py`:

```python
"""Everything a render needs from the vault: contexts, projects, the user's
name, person titles from the in-memory link index (A2), and the clock."""
from __future__ import annotations

import logging
from datetime import datetime

import yaml

from ghostbrain import routing_config
from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.paths import vault_path
from ghostbrain.templates.render import RenderEnv
from ghostbrain.templates.values import ProjectValue
from ghostbrain.vault_index.links import get_link_index

log = logging.getLogger("ghostbrain.templates")


def _now() -> datetime:
    return datetime.now().astimezone()


def _user_name() -> str:
    try:
        data = yaml.safe_load((vault_path() / "90-meta" / "config.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return ""
    user = data.get("user") if isinstance(data, dict) else None
    name = user.get("name") if isinstance(user, dict) else None
    return name.strip()[:200] if isinstance(name, str) else ""


def _person_title(path: str) -> str | None:
    """Indexed title, never a file read. A cold index answers None (the
    renderer then humanizes the file stem) and starts building."""
    try:
        index = get_link_index()
        if not index.ready:
            index.ensure_fresh(wait=0)
            return None
        entry = index.get(path)
        return entry.title if entry is not None else None
    except Exception:  # noqa: BLE001 — a lookup must never fail a create
        log.exception("link index lookup failed for %s", path)
        return None


def build_env() -> RenderEnv:
    contexts = tuple(routing_config.contexts())
    projects = {
        p["id"]: ProjectValue(id=p["id"], name=p["name"], slug=p["slug"], context=p["context"])
        for p in projects_repo.list_projects()
        if isinstance(p, dict) and all(isinstance(p.get(k), str) for k in ("id", "name", "slug", "context"))
    }
    return RenderEnv(
        now=_now(),
        default_context=contexts[0] if contexts else "personal",
        contexts=contexts,
        projects=projects,
        user_name=_user_name(),
        person_title=_person_title,
    )
```

`ghostbrain/templates/create.py`:

```python
"""New note from a template: render, then create through B1's write path."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ghostbrain import vault_write
from ghostbrain.templates.env import build_env
from ghostbrain.templates.registry import load_template
from ghostbrain.templates.render import RenderedNote, RenderEnv, render
from ghostbrain.vault_write import USER, Actor


@dataclass(frozen=True)
class CreatedNote:
    path: str
    title: str
    etag: str | None
    status: str


def preview_from_template(
    template_id: str, answers: Mapping[str, str], *, env: RenderEnv | None = None
) -> RenderedNote:
    """Render without writing. Raises InvalidPath if the target would leave
    the vault (e.g. a symlinked folder)."""
    note = render(load_template(template_id), answers, env or build_env())
    vault_write.resolve_safe(note.path)
    return note


def create_from_template(
    template_id: str,
    answers: Mapping[str, str],
    *,
    actor: Actor = USER,
    env: RenderEnv | None = None,
) -> CreatedNote:
    note = render(load_template(template_id), answers, env or build_env())
    result = vault_write.write_new(
        note.path, note.markdown(), actor=actor, reason=f"new note from template {template_id}"
    )
    return CreatedNote(result.path, note.title, result.etag, result.status)
```

`write_new` → `write` → `resolve_safe` resolves symlinks and raises `InvalidPath` before any byte is written, so `create` needs no separate pre-check.

Add `tests/test_templates_create.py \` to `ci.yml`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_templates_create.py tests/test_templates_security.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/templates/env.py ghostbrain/templates/create.py tests/test_templates_create.py tests/test_templates_security.py .github/workflows/ci.yml
git commit -m "feat(templates): render env and create via vault_write as user"
```

---

### Task 7: Template routes

**Files:**
- Create: `ghostbrain/api/routes/templates.py`
- Modify: `ghostbrain/api/main.py` (import, plus `app.include_router(templates_routes.router)` after `projects_routes`)
- Test: `ghostbrain/api/tests/test_templates_routes.py`

**Interfaces:**
- Consumes: `list_templates`, `TemplateNotFound`, `TemplateInvalid` (Task 5); `create_from_template`, `preview_from_template` (Task 6); `AnswerError`, `RenderError` (Task 4); `registry_json` (Task 2). B1's `InvalidPath` is already mapped to 400 and `WriteConflict` to 409 by `install_vault_write_errors`.
- Produces: the four HTTP routes in the table above. Task 8 consumes the JSON shapes.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_templates_routes.py`:

```python
"""/v1/templates: list, functions, create (write path, user), render (no write)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

NOW = datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2)))


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr("ghostbrain.templates.env._now", lambda: NOW)


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def _put(vault: Path, name: str, text: str) -> None:
    (vault / "90-meta/templates").mkdir(parents=True, exist_ok=True)
    (vault / "90-meta/templates" / name).write_text(text, encoding="utf-8")


def test_list_seeds_three_starters(client, auth_headers, tmp_vault):
    r = client.get("/v1/templates", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()["templates"]
    assert [t["name"] for t in items] == ["1-1", "Decision record", "Meeting notes"]
    assert all(t["valid"] for t in items)
    assert (tmp_vault / "90-meta/templates/one-on-one.md").is_file()


def test_functions_registry(client, auth_headers):
    data = client.get("/v1/templates/functions", headers=auth_headers).json()
    assert {f["name"] for f in data["filters"]} == {"format", "slug", "upper", "lower", "default"}
    assert any(f["owner"] == "person" and f["name"] == "link" for f in data["fields"])


def test_create_one_on_one(client, auth_headers, tmp_vault):
    client.get("/v1/templates", headers=auth_headers)  # seed
    r = client.post("/v1/templates/one-on-one/create", headers=auth_headers,
                    json={"answers": {"person": "30-cross-context/people/alex"}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["path"] == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md"
    assert body["title"] == "2026-10-09 Alex 1-1" and body["status"] == "applied" and body["etag"]
    text = (tmp_vault / body["path"]).read_text(encoding="utf-8")
    head, note_body = text[4:].split("---\n\n", 1)
    fm = yaml.safe_load(head)
    assert fm["attendees"] == ["[[30-cross-context/people/alex]]"]
    assert fm["fromTemplate"] == "one-on-one" and fm["created"] == "2026-10-09T14:30:00+02:00"
    assert note_body.startswith("# 1-1 with [[30-cross-context/people/alex]] — 9 Oct 2026\n")


def test_create_goes_through_write_path_as_user(client, auth_headers, tmp_vault, monkeypatch):
    from ghostbrain import vault_write

    seen = []
    real = vault_write.write_new

    def spy(rel_path, content, *, actor, reason="", max_attempts=100):
        seen.append(actor)
        return real(rel_path, content, actor=actor, reason=reason, max_attempts=max_attempts)

    monkeypatch.setattr("ghostbrain.templates.create.vault_write.write_new", spy)
    client.get("/v1/templates", headers=auth_headers)
    r = client.post("/v1/templates/meeting-notes/create", headers=auth_headers,
                    json={"answers": {"topic": "Planning"}})
    assert r.status_code == 201 and seen == ["user"]


def test_create_twice_same_answers_gets_suffix(client, auth_headers, tmp_vault):
    client.get("/v1/templates", headers=auth_headers)
    paths = [
        client.post("/v1/templates/meeting-notes/create", headers=auth_headers,
                    json={"answers": {"topic": "Planning"}}).json()["path"]
        for _ in range(2)
    ]
    assert paths == ["20-contexts/work/meetings/2026-10-09-planning.md",
                     "20-contexts/work/meetings/2026-10-09-planning-2.md"]


def test_missing_required_answer_names_the_field(client, auth_headers, tmp_vault):
    client.get("/v1/templates", headers=auth_headers)
    r = client.post("/v1/templates/one-on-one/create", headers=auth_headers, json={"answers": {}})
    assert r.status_code == 422 and r.json()["detail"] == "person: an answer is required"


def test_non_string_answers_are_rejected(client, auth_headers, tmp_vault):
    r = client.post("/v1/templates/one-on-one/create", headers=auth_headers,
                    json={"answers": {"person": ["x"]}})
    assert r.status_code == 422


@pytest.mark.parametrize("tid", ["nope", ".secret", "..secret", "UPPER"])
def test_unknown_or_unsafe_ids_are_404(client, auth_headers, tmp_vault, tid):
    r = client.post(f"/v1/templates/{tid}/create", headers=auth_headers, json={"answers": {}})
    assert r.status_code == 404


def test_encoded_traversal_id_is_404(client, auth_headers, tmp_vault):
    r = client.post("/v1/templates/..%2F..%2Froutingyaml/create", headers=auth_headers,
                    json={"answers": {}})
    assert r.status_code == 404


def test_create_with_broken_template_is_422(client, auth_headers, tmp_vault):
    _put(tmp_vault, "broken.md", "---\ntemplate:\n  name: [unclosed\n---\n")
    r = client.post("/v1/templates/broken/create", headers=auth_headers, json={"answers": {}})
    assert r.status_code == 422 and r.json()["detail"].startswith("template has errors: line ")


def test_escaping_folder_is_400_and_writes_nothing(client, auth_headers, tmp_vault):
    _put(tmp_vault, "evil.md", '---\ntemplate:\n  name: Evil\n  file:\n    folder: "../../outside"\n---\nx\n')
    before = _files(tmp_vault.parent)
    r = client.post("/v1/templates/evil/create", headers=auth_headers, json={"answers": {}})
    assert r.status_code == 400
    assert _files(tmp_vault.parent) == before


def test_render_returns_note_and_writes_nothing(client, auth_headers, tmp_vault):
    client.get("/v1/templates", headers=auth_headers)
    before = _files(tmp_vault)
    r = client.post("/v1/templates/meeting-notes/render", headers=auth_headers,
                    json={"answers": {"topic": "Planning", "context": "personal"}})
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == "20-contexts/personal/meetings/2026-10-09-planning.md"
    assert data["folder"] == "20-contexts/personal/meetings"
    assert data["filename"] == "2026-10-09-planning.md"
    assert data["body"].startswith("# Planning — 9 Oct 2026\n")
    assert data["frontmatter"]["type"] == "meeting"
    assert _files(tmp_vault) == before
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest ghostbrain/api/tests/test_templates_routes.py -v`
Expected: FAIL. Every request returns 404 because the routes don't exist yet.

- [ ] **Step 3: Write the implementation**

`ghostbrain/api/routes/templates.py`:

```python
"""Smart templates, slice C1 (spec 2026-10-09-smart-templates-design.md).

GET  /v1/templates                  list (seeds starters if the folder is missing)
GET  /v1/templates/functions        the registry, for intellisense
POST /v1/templates/{id}/create      render + vault_write.write_new(actor=user)
POST /v1/templates/{id}/render      render only (the /template slash insert)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ghostbrain.templates.create import create_from_template, preview_from_template
from ghostbrain.templates.functions import registry_json
from ghostbrain.templates.registry import TemplateInvalid, TemplateNotFound, list_templates
from ghostbrain.templates.render import AnswerError, RenderError

router = APIRouter(prefix="/v1/templates", tags=["templates"])
_ERRORS = (TemplateNotFound, TemplateInvalid, AnswerError, RenderError)


class AnswersBody(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict, max_length=50)


def _http_error(template_id: str, exc: Exception) -> HTTPException:
    if isinstance(exc, TemplateNotFound):
        return HTTPException(status_code=404, detail=f"template not found: {template_id}")
    if isinstance(exc, TemplateInvalid):
        return HTTPException(status_code=422, detail=f"template has errors: {exc}")
    if isinstance(exc, AnswerError):
        return HTTPException(status_code=422, detail=f"{exc.field}: {exc}")
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
def get_templates() -> dict[str, Any]:
    return {"templates": [info.to_json() for info in list_templates()]}


@router.get("/functions")
def get_functions() -> dict[str, Any]:
    return registry_json()


@router.post("/{template_id}/create", status_code=201)
def create_note(template_id: str, body: AnswersBody) -> dict[str, Any]:
    try:
        created = create_from_template(template_id, body.answers)
    except _ERRORS as e:
        raise _http_error(template_id, e) from e
    return {"path": created.path, "title": created.title, "etag": created.etag, "status": created.status}


@router.post("/{template_id}/render")
def render_note(template_id: str, body: AnswersBody) -> dict[str, Any]:
    try:
        note = preview_from_template(template_id, body.answers)
    except _ERRORS as e:
        raise _http_error(template_id, e) from e
    return {"path": note.path, "folder": note.folder, "filename": note.filename,
            "title": note.title, "frontmatter": note.frontmatter, "body": note.body}
```

In `ghostbrain/api/main.py`, add the import after `from ghostbrain.api.routes import suggestions as suggestions_routes`:

```python
from ghostbrain.api.routes import templates as templates_routes
```

Then add the router after `app.include_router(projects_routes.router)`:

```python
    app.include_router(templates_routes.router)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest ghostbrain/api/tests/test_templates_routes.py -v`
Expected: PASS. Then run the full backend CI list once: `python -m pytest ghostbrain/api/tests/ tests/test_templates_*.py tests/test_no_hardcoded_contexts.py -q` and expect it to PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/routes/templates.py ghostbrain/api/main.py ghostbrain/api/tests/test_templates_routes.py
git commit -m "feat(api): /v1/templates list, functions, create and render routes"
```

---

### Task 8: Desktop API types and hooks

**Files:**
- Modify: `desktop/src/shared/api-types.ts` (append), `desktop/src/renderer/lib/api/hooks.ts` (extend the type import and append the hooks)
- Test: `desktop/src/renderer/__tests__/template-hooks.test.tsx`

**Interfaces:**
- Consumes: the HTTP shapes from Task 7, plus `get` and `post` from `lib/api/client`.
- Produces: the types `TemplatePromptType`, `TemplatePrompt`, `TemplateDiagnostic`, `TemplateSummary`, `TemplatesResponse`, `TemplateCreateResponse`, `TemplateRenderResponse`, `TemplateFunctionSpec` and `TemplateFunctionsResponse`. The hooks are `useTemplates(opts?: { enabled?: boolean })`, `useCreateFromTemplate()` (mutation variables `{ id: string; answers: Record<string, string> }`) and `useRenderTemplate()` (the same variables).

- [ ] **Step 1: Write the failing test**

`desktop/src/renderer/__tests__/template-hooks.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { useCreateFromTemplate, useRenderTemplate, useTemplates } from '../lib/api/hooks';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});

describe('template hooks', () => {
  it('useTemplates fetches only when enabled', async () => {
    getMock.mockResolvedValue({ templates: [] });
    renderHook(() => useTemplates({ enabled: false }), { wrapper });
    expect(getMock).not.toHaveBeenCalled();
    const { result } = renderHook(() => useTemplates(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual({ templates: [] }));
    expect(getMock).toHaveBeenCalledWith('/v1/templates');
  });

  it('useCreateFromTemplate posts answers to the encoded id', async () => {
    postMock.mockResolvedValue({ path: 'a.md', title: 'A', etag: 'e', status: 'applied' });
    const { result } = renderHook(() => useCreateFromTemplate(), { wrapper });
    await result.current.mutateAsync({ id: 'one-on-one', answers: { person: 'Alex' } });
    expect(postMock).toHaveBeenCalledWith('/v1/templates/one-on-one/create', { answers: { person: 'Alex' } });
  });

  it('useRenderTemplate posts to /render', async () => {
    postMock.mockResolvedValue({ path: 'a.md', folder: 'f', filename: 'a.md', title: 'A', frontmatter: {}, body: 'B' });
    const { result } = renderHook(() => useRenderTemplate(), { wrapper });
    const res = await result.current.mutateAsync({ id: 'meeting-notes', answers: {} });
    expect(postMock).toHaveBeenCalledWith('/v1/templates/meeting-notes/render', { answers: {} });
    expect(res.body).toBe('B');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/template-hooks.test.tsx`
Expected: FAIL with `useTemplates is not a function` (or the equivalent export error).

- [ ] **Step 3: Write the implementation**

Append to `desktop/src/shared/api-types.ts`:

```ts
// ── Smart templates (C1) ──────────────────────────────────────────────────

export type TemplatePromptType = 'person' | 'text' | 'date' | 'choice' | 'context' | 'project';

export interface TemplatePrompt {
  id: string;
  ask: string;
  type: TemplatePromptType;
  optional: boolean;
  default: string | null;
  options: string[];
}

export interface TemplateDiagnostic {
  line: number;
  col: number;
  severity: 'error' | 'warning' | 'info';
  message: string;
  code: string;
}

export interface TemplateSummary {
  id: string;
  path: string;
  name: string;
  description: string;
  prompts: TemplatePrompt[];
  /** Root names the template references, e.g. ['context', 'date', 'person']. */
  variables: string[];
  valid: boolean;
  diagnostics: TemplateDiagnostic[];
}

export interface TemplatesResponse {
  templates: TemplateSummary[];
}

export interface TemplateCreateResponse {
  path: string;
  title: string;
  etag: string | null;
  status: 'applied' | 'pending';
}

export interface TemplateRenderResponse {
  path: string;
  folder: string;
  filename: string;
  title: string;
  frontmatter: Record<string, unknown>;
  body: string;
}

export interface TemplateFunctionSpec {
  name: string;
  kind: 'variable' | 'field' | 'filter' | 'prompt_type';
  type: string;
  doc: string;
  example: string;
  owner: string | null;
  accepts: string[];
  arg: string | null;
  argRequired: boolean;
}

export interface TemplateFunctionsResponse {
  variables: TemplateFunctionSpec[];
  fields: TemplateFunctionSpec[];
  filters: TemplateFunctionSpec[];
  promptTypes: TemplateFunctionSpec[];
}
```

In `hooks.ts`, add `TemplateCreateResponse,`, `TemplateRenderResponse,` and `TemplatesResponse,` to the existing `import { … } from '../../../shared/api-types';` list. Then append at the end of the file:

```ts
// ── Smart templates (C1) ──────────────────────────────────────────────────

export function useTemplates(opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['templates'],
    queryFn: () => get<TemplatesResponse>('/v1/templates'),
    enabled: opts.enabled ?? true,
    staleTime: 10_000,
  });
}

export interface TemplateAnswersVars {
  id: string;
  answers: Record<string, string>;
}

export function useCreateFromTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, answers }: TemplateAnswersVars) =>
      post<TemplateCreateResponse>(`/v1/templates/${encodeURIComponent(id)}/create`, { answers }),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: JOTS_KEY }),
        qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] }),
      ]),
  });
}

export function useRenderTemplate() {
  return useMutation({
    mutationFn: ({ id, answers }: TemplateAnswersVars) =>
      post<TemplateRenderResponse>(`/v1/templates/${encodeURIComponent(id)}/render`, { answers }),
  });
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/template-hooks.test.tsx && npm run typecheck`
Expected: PASS, with no type errors.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/shared/api-types.ts desktop/src/renderer/lib/api/hooks.ts desktop/src/renderer/__tests__/template-hooks.test.tsx
git commit -m "feat(desktop): template API types and hooks"
```

---

### Task 9: Template prompt dialog

**Files:**
- Create: `desktop/src/renderer/components/TemplatePromptDialog.tsx`
- Test: `desktop/src/renderer/__tests__/TemplatePromptDialog.test.tsx`

**Interfaces:**
- Consumes: `useContexts`, `useProjects`, `useCreateFromTemplate` and `useRenderTemplate` (Task 8 and existing hooks); `fetchSuggestions(kind, query, timeoutMs)`, `createLatestFetcher(fetcher)` and `SuggestResult` from `lib/editor/link-suggest` (A2); and the types `TemplateSummary`, `TemplatePrompt`, `TemplateCreateResponse`, `SuggestItem` and `Project`.
- Produces: `TemplatePromptDialog(props: { template: TemplateSummary; mode: 'create' | 'insert'; onClose: () => void; onCreated?: (res: TemplateCreateResponse) => void; onInsert?: (markdown: string) => void })`, `dialogFields(template): TemplatePrompt[]` and `todayIso(now?: Date): string`. Task 10 uses all three.

- [ ] **Step 1: Write the failing test**

`desktop/src/renderer/__tests__/TemplatePromptDialog.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { ApiError } from '../lib/api/client';
import { TemplatePromptDialog, dialogFields, todayIso } from '../components/TemplatePromptDialog';
import type { TemplateSummary } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const ONE_ON_ONE: TemplateSummary = {
  id: 'one-on-one',
  path: '90-meta/templates/one-on-one.md',
  name: '1-1',
  description: '',
  prompts: [
    { id: 'person', ask: "Who's this 1-1 with?", type: 'person', optional: false, default: null, options: [] },
    { id: 'focus', ask: 'Anything specific to cover?', type: 'text', optional: true, default: null, options: [] },
  ],
  variables: ['context', 'date', 'focus', 'person'],
  valid: true,
  diagnostics: [],
};

const DECISION: TemplateSummary = {
  id: 'decision-record',
  path: '90-meta/templates/decision-record.md',
  name: 'Decision record',
  description: '',
  prompts: [
    { id: 'decision', ask: 'What did you decide?', type: 'text', optional: false, default: null, options: [] },
    { id: 'status', ask: 'Status', type: 'choice', optional: false, default: 'accepted', options: ['proposed', 'accepted'] },
    { id: 'when', ask: 'When?', type: 'date', optional: false, default: null, options: [] },
    { id: 'project', ask: 'Which project?', type: 'project', optional: true, default: null, options: [] },
  ],
  variables: ['context', 'decision', 'project', 'status', 'when'],
  valid: true,
  diagnostics: [],
};

beforeEach(() => {
  getMock.mockImplementation(async (path: string) => {
    if (path === '/v1/vault/contexts') return { contexts: ['work', 'personal'] };
    if (path === '/v1/projects')
      return [{ id: 'work/alpha', context: 'work', slug: 'alpha', name: 'Alpha', description: '', archived: false, created_at: 0 }];
    if (path.startsWith('/v1/vault/suggest?kind=person'))
      return {
        items: [{ kind: 'person', label: 'Alex', path: '30-cross-context/people/alex.md', context: '', detail: '30-cross-context/people/alex', count: null }],
        indexing: false,
      };
    throw new Error(`unexpected GET ${path}`);
  });
});

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});

describe('dialogFields', () => {
  it('adds an implicit context picker only when the template uses {{context}} without a prompt', () => {
    expect(dialogFields(ONE_ON_ONE).map((f) => f.id)).toEqual(['person', 'focus', 'context']);
    expect(dialogFields({ ...ONE_ON_ONE, variables: ['person'] }).map((f) => f.id)).toEqual(['person', 'focus']);
    expect(dialogFields(DECISION).map((f) => f.id)).toEqual(['decision', 'status', 'when', 'project', 'context']);
  });
});

describe('TemplatePromptDialog', () => {
  it('renders one field per prompt and gates submit on required answers', async () => {
    render(withQuery(<TemplatePromptDialog template={ONE_ON_ONE} mode="create" onClose={() => {}} />));
    expect(screen.getByLabelText("Who's this 1-1 with?")).toBeInTheDocument();
    expect(screen.getByLabelText(/Anything specific to cover\? \(optional\)/)).toBeInTheDocument();
    await screen.findByRole('option', { name: 'personal' });
    expect(screen.getByLabelText('Context')).toHaveValue('work');
    expect(screen.getByRole('button', { name: 'create' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'Alex' } });
    expect(screen.getByRole('button', { name: 'create' })).toBeEnabled();
  });

  it('picks a person from suggest and creates the note', async () => {
    postMock.mockResolvedValue({ path: '20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md', title: '2026-10-09 Alex 1-1', etag: 'e', status: 'applied' });
    const onCreated = vi.fn();
    const onClose = vi.fn();
    render(withQuery(<TemplatePromptDialog template={ONE_ON_ONE} mode="create" onClose={onClose} onCreated={onCreated} />));
    await screen.findByRole('option', { name: 'personal' });
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'al' } });
    fireEvent.click(await screen.findByRole('button', { name: /^Alex/ }));
    expect(getMock).toHaveBeenCalledWith('/v1/vault/suggest?kind=person&q=al&limit=20');
    expect(screen.getByLabelText("Who's this 1-1 with?")).toHaveValue('Alex');
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(postMock).toHaveBeenCalledWith('/v1/templates/one-on-one/create', {
      answers: { person: '30-cross-context/people/alex.md', context: 'work' },
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('submits a typed name when no suggestion is picked', async () => {
    postMock.mockResolvedValue({ path: 'x.md', title: 'x', etag: null, status: 'applied' });
    render(withQuery(<TemplatePromptDialog template={ONE_ON_ONE} mode="create" onClose={() => {}} />));
    await screen.findByRole('option', { name: 'personal' });
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/v1/templates/one-on-one/create', { answers: { person: 'Alex', context: 'work' } }),
    );
  });

  it('prefills choice defaults and today for dates, and sends picked projects', async () => {
    postMock.mockResolvedValue({ path: 'x.md', title: 'x', etag: null, status: 'applied' });
    render(withQuery(<TemplatePromptDialog template={DECISION} mode="create" onClose={() => {}} />));
    await screen.findByRole('option', { name: 'work / Alpha' });
    expect(screen.getByLabelText('Status')).toHaveValue('accepted');
    expect(screen.getByLabelText('When?')).toHaveValue(todayIso());
    fireEvent.change(screen.getByLabelText('What did you decide?'), { target: { value: 'Use Postgres' } });
    fireEvent.change(screen.getByLabelText(/Which project\?/), { target: { value: 'work/alpha' } });
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/v1/templates/decision-record/create', {
        answers: { decision: 'Use Postgres', status: 'accepted', when: todayIso(), project: 'work/alpha', context: 'work' },
      }),
    );
  });

  it('shows a server error and marks the field it names', async () => {
    postMock.mockRejectedValue(new ApiError("person: a person's name can't contain [ ] | # or line breaks", 422));
    render(withQuery(<TemplatePromptDialog template={ONE_ON_ONE} mode="create" onClose={() => {}} />));
    await screen.findByRole('option', { name: 'personal' });
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'A]]' } });
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("can't contain");
    expect(screen.getByLabelText("Who's this 1-1 with?")).toHaveAttribute('aria-invalid', 'true');
  });

  it('insert mode renders and hands back the body', async () => {
    postMock.mockResolvedValue({ path: 'x.md', folder: 'f', filename: 'x.md', title: 'x', frontmatter: {}, body: '# 1-1 with [[Alex]]\n' });
    const onInsert = vi.fn();
    render(withQuery(<TemplatePromptDialog template={ONE_ON_ONE} mode="insert" onClose={() => {}} onInsert={onInsert} />));
    await screen.findByRole('option', { name: 'personal' });
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: 'insert' }));
    await waitFor(() => expect(onInsert).toHaveBeenCalledWith('# 1-1 with [[Alex]]\n'));
    expect(postMock.mock.calls[0]![0]).toBe('/v1/templates/one-on-one/render');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/TemplatePromptDialog.test.tsx`
Expected: FAIL with `Failed to resolve import "../components/TemplatePromptDialog"`.

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/components/TemplatePromptDialog.tsx`:

```tsx
import { useEffect, useMemo, useRef, useState } from 'react';
import { useContexts, useCreateFromTemplate, useProjects, useRenderTemplate } from '../lib/api/hooks';
import { createLatestFetcher, fetchSuggestions, type SuggestResult } from '../lib/editor/link-suggest';
import type {
  Project,
  SuggestItem,
  TemplateCreateResponse,
  TemplatePrompt,
  TemplateSummary,
} from '../../shared/api-types';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

/** A dialog may wait longer than the inline 300 ms editor suggest. */
const PERSON_SUGGEST_TIMEOUT_MS = 1500;
const INPUT =
  'mb-3 w-full rounded-r6 border bg-vellum px-3 py-[7px] text-13 text-ink-0 placeholder:text-ink-3 focus:border-ink-3 focus:outline-none';
const FIELD_ERROR_RE = /^([a-z][a-z0-9_]*): ([\s\S]*)$/;

export function todayIso(now: Date = new Date()): string {
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${m}-${d}`;
}

/** The template's prompts plus the implicit context/project pickers it needs. */
export function dialogFields(template: TemplateSummary): TemplatePrompt[] {
  const ids = new Set(template.prompts.map((p) => p.id));
  const extra: TemplatePrompt[] = [];
  if (template.variables.includes('context') && !ids.has('context')) {
    extra.push({ id: 'context', ask: 'Context', type: 'context', optional: false, default: null, options: [] });
  }
  if (template.variables.includes('project') && !ids.has('project')) {
    extra.push({ id: 'project', ask: 'Project', type: 'project', optional: true, default: null, options: [] });
  }
  return [...template.prompts, ...extra];
}

function initialValue(f: TemplatePrompt): string {
  if (f.default !== null) return f.default;
  if (f.type === 'date') return todayIso();
  if (f.type === 'choice') return f.options[0] ?? '';
  return '';
}

interface PersonFieldProps {
  inputId: string;
  invalid: boolean;
  onChange: (value: string) => void;
  suggest: (query: string) => Promise<SuggestResult>;
}

function PersonField({ inputId, invalid, onChange, suggest }: PersonFieldProps) {
  const [text, setText] = useState('');
  const [items, setItems] = useState<SuggestItem[]>([]);
  const latest = useRef('');

  async function onType(q: string) {
    setText(q);
    onChange(q);
    latest.current = q;
    if (!q.trim()) {
      setItems([]);
      return;
    }
    const res = await suggest(q);
    if (latest.current === q) setItems(res.items.filter((i) => i.path !== null));
  }

  function pick(item: SuggestItem) {
    latest.current = '';
    setText(item.label);
    onChange(item.path!);
    setItems([]);
  }

  return (
    <div className="relative">
      <input
        id={inputId}
        type="text"
        role="combobox"
        aria-expanded={items.length > 0}
        aria-autocomplete="list"
        aria-invalid={invalid}
        value={text}
        onChange={(e) => void onType(e.target.value)}
        placeholder="a name, or pick their page"
        className={`${INPUT} ${invalid ? 'border-oxblood' : 'border-hairline-2'}`}
      />
      {items.length > 0 && (
        <ul className="absolute left-0 right-0 top-[38px] z-10 max-h-[180px] overflow-y-auto rounded-r6 border border-hairline-2 bg-paper py-1 shadow-card">
          {items.map((item) => (
            <li key={item.path!}>
              <button
                type="button"
                onClick={() => pick(item)}
                className="block w-full px-3 py-1 text-left text-12 text-ink-0 hover:bg-vellum"
              >
                {item.label}
                <span className="ml-2 font-mono text-10 text-ink-3">{item.detail}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface Props {
  template: TemplateSummary;
  mode: 'create' | 'insert';
  onClose: () => void;
  onCreated?: (res: TemplateCreateResponse) => void;
  onInsert?: (markdown: string) => void;
}

export function TemplatePromptDialog({ template, mode, onClose, onCreated, onInsert }: Props) {
  const fields = useMemo(() => dialogFields(template), [template]);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.id, initialValue(f)])),
  );
  const [error, setError] = useState<{ field: string | null; message: string } | null>(null);
  const contexts = useContexts().data?.contexts ?? [];
  const projectsQuery = useProjects();
  const projects: Project[] = Array.isArray(projectsQuery.data) ? projectsQuery.data : [];
  const create = useCreateFromTemplate();
  const renderTpl = useRenderTemplate();
  const pending = create.isPending || renderTpl.isPending;
  const peopleFetcher = useMemo(
    () => createLatestFetcher((kind, q) => fetchSuggestions(kind, q, PERSON_SUGGEST_TIMEOUT_MS)),
    [],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !pending) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [pending, onClose]);

  const effective = (f: TemplatePrompt): string => {
    const v = values[f.id] ?? '';
    if (f.type === 'context' && !v && !f.optional) return contexts[0] ?? '';
    return v;
  };
  const missing = fields.filter((f) => !f.optional && !effective(f).trim());
  const set = (id: string, v: string) => setValues((prev) => ({ ...prev, [id]: v }));

  function submit() {
    if (missing.length > 0 || pending) return;
    const answers: Record<string, string> = {};
    for (const f of fields) {
      const v = effective(f).trim();
      if (v) answers[f.id] = v;
    }
    setError(null);
    const onError = (err: Error) => {
      const m = FIELD_ERROR_RE.exec(err.message);
      const field = m && fields.some((f) => f.id === m[1]) ? m[1]! : null;
      setError({ field, message: err.message });
    };
    if (mode === 'create') {
      create.mutate(
        { id: template.id, answers },
        {
          onSuccess: (res) => {
            onCreated?.(res);
            onClose();
          },
          onError,
        },
      );
    } else {
      renderTpl.mutate(
        { id: template.id, answers },
        {
          onSuccess: (res) => {
            onInsert?.(res.body);
            onClose();
          },
          onError,
        },
      );
    }
  }

  function control(f: TemplatePrompt) {
    const inputId = `tpl-${template.id}-${f.id}`;
    const invalid = error?.field === f.id;
    const cls = `${INPUT} ${invalid ? 'border-oxblood' : 'border-hairline-2'}`;
    switch (f.type) {
      case 'person':
        return (
          <PersonField
            inputId={inputId}
            invalid={invalid}
            onChange={(v) => set(f.id, v)}
            suggest={(q) => peopleFetcher('person', q)}
          />
        );
      case 'date':
        return (
          <input id={inputId} type="date" aria-invalid={invalid} value={effective(f)}
            onChange={(e) => set(f.id, e.target.value)} className={cls} />
        );
      case 'choice':
        return (
          <select id={inputId} aria-invalid={invalid} value={effective(f)}
            onChange={(e) => set(f.id, e.target.value)} className={cls}>
            {f.options.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        );
      case 'context':
        return (
          <select id={inputId} aria-invalid={invalid} value={effective(f)}
            onChange={(e) => set(f.id, e.target.value)} className={cls}>
            {f.optional && <option value="">—</option>}
            {contexts.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        );
      case 'project':
        return (
          <select id={inputId} aria-invalid={invalid} value={effective(f)}
            onChange={(e) => set(f.id, e.target.value)} className={cls}>
            <option value="">none</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{`${p.context} / ${p.name}`}</option>
            ))}
          </select>
        );
      default:
        return (
          <input id={inputId} type="text" aria-invalid={invalid} value={effective(f)}
            onChange={(e) => set(f.id, e.target.value)} className={cls} />
        );
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`new from template ${template.name}`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget && !pending) onClose();
      }}
    >
      <form
        className="w-[420px] rounded-r6 border border-hairline-2 bg-paper p-5 shadow-card"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="mb-4 flex items-center justify-between">
          <span className="font-body text-13 font-medium text-ink-0">{template.name}</span>
          <button type="button" aria-label="close" onClick={onClose}
            className="rounded-sm p-[2px] text-ink-2 hover:text-ink-0">
            <Lucide name="x" size={14} />
          </button>
        </div>
        {fields.map((f) => (
          <div key={f.id}>
            <label htmlFor={`tpl-${template.id}-${f.id}`} className="mb-1 block font-mono text-10 text-ink-2">
              {f.ask}
              {f.optional ? ' (optional)' : ''}
            </label>
            {control(f)}
          </div>
        ))}
        {error && (
          <div role="alert" className="mb-3 text-12 text-oxblood">
            {error.message}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Btn variant="ghost" size="sm" onClick={onClose}>
            cancel
          </Btn>
          <Btn variant="primary" size="sm" type="submit" disabled={missing.length > 0 || pending}>
            {mode === 'create' ? 'create' : 'insert'}
          </Btn>
        </div>
      </form>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/TemplatePromptDialog.test.tsx && npm run typecheck && npx eslint --max-warnings 0 src/renderer/components/TemplatePromptDialog.tsx src/renderer/__tests__/TemplatePromptDialog.test.tsx`
Expected: PASS, with no type or lint errors.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/components/TemplatePromptDialog.tsx desktop/src/renderer/__tests__/TemplatePromptDialog.test.tsx
git commit -m "feat(desktop): template prompt dialog with person suggest"
```

---

### Task 10: Template picker and the Jots "template" menu

**Files:**
- Create: `desktop/src/renderer/components/TemplatePicker.tsx`
- Modify: `desktop/src/renderer/screens/jots.tsx` (import, plus `<TemplateMenu>` placed before the "new" `Btn` in the TopBar `right` div)
- Test: `desktop/src/renderer/__tests__/TemplatePicker.test.tsx`; append one test to `desktop/src/renderer/__tests__/jots.test.tsx`

**Interfaces:**
- Consumes: `useTemplates` (Task 8); `TemplatePromptDialog` (Task 9); `useNoteView((s) => s.open)` and `toast`, both already in `jots.tsx`.
- Produces: `TemplateList({ enabled?, onPick })`, `TemplateMenu({ onCreated: (res: TemplateCreateResponse) => void })` and `TemplateInsertDialog({ onClose, onInsert: (markdown: string) => void })`. Task 11 uses `TemplateInsertDialog`.

- [ ] **Step 1: Write the failing tests**

`desktop/src/renderer/__tests__/TemplatePicker.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { TemplateInsertDialog, TemplateMenu } from '../components/TemplatePicker';
import type { TemplateSummary } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const MEETING: TemplateSummary = {
  id: 'meeting-notes',
  path: '90-meta/templates/meeting-notes.md',
  name: 'Meeting notes',
  description: 'Agenda, notes, decisions',
  prompts: [{ id: 'topic', ask: 'Topic', type: 'text', optional: false, default: null, options: [] }],
  variables: ['context', 'date', 'topic'],
  valid: true,
  diagnostics: [],
};
const BROKEN: TemplateSummary = {
  id: 'broken',
  path: '90-meta/templates/broken.md',
  name: 'broken',
  description: '',
  prompts: [],
  variables: [],
  valid: false,
  diagnostics: [{ line: 3, col: 1, severity: 'error', message: 'template.name: Field required', code: 'schema' }],
};

beforeEach(() => {
  getMock.mockImplementation(async (path: string) => {
    if (path === '/v1/templates') return { templates: [MEETING, BROKEN] };
    if (path === '/v1/vault/contexts') return { contexts: ['work'] };
    if (path === '/v1/projects') return [];
    throw new Error(`unexpected GET ${path}`);
  });
});

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});

async function fillTopicAndSubmit(label: 'create' | 'insert') {
  fireEvent.change(await screen.findByLabelText('Topic'), { target: { value: 'Planning' } });
  await waitFor(() => expect(screen.getByRole('button', { name: label })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: label }));
}

describe('TemplateMenu', () => {
  it('fetches templates only once the menu opens', async () => {
    render(withQuery(<TemplateMenu onCreated={() => {}} />));
    expect(getMock).not.toHaveBeenCalledWith('/v1/templates');
    fireEvent.click(screen.getByRole('button', { name: 'template' }));
    expect(await screen.findByRole('menuitem', { name: /Meeting notes/ })).toBeEnabled();
  });

  it('shows a broken template disabled with its first error', async () => {
    render(withQuery(<TemplateMenu onCreated={() => {}} />));
    fireEvent.click(screen.getByRole('button', { name: 'template' }));
    const item = await screen.findByRole('menuitem', { name: /broken/ });
    expect(item).toBeDisabled();
    expect(item).toHaveAttribute('title', 'line 3: template.name: Field required');
  });

  it('picking a template opens its prompts and reports the created note', async () => {
    const res = { path: '20-contexts/work/meetings/2026-10-09-planning.md', title: '2026-10-09 Planning', etag: 'e', status: 'applied' as const };
    postMock.mockResolvedValue(res);
    const onCreated = vi.fn();
    render(withQuery(<TemplateMenu onCreated={onCreated} />));
    fireEvent.click(screen.getByRole('button', { name: 'template' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: /Meeting notes/ }));
    expect(screen.queryByRole('menu')).toBeNull();
    await fillTopicAndSubmit('create');
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(res));
  });

  it('shows an error when templates cannot load', async () => {
    getMock.mockRejectedValue(new Error('sidecar down'));
    render(withQuery(<TemplateMenu onCreated={() => {}} />));
    fireEvent.click(screen.getByRole('button', { name: 'template' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('templates unavailable — sidecar down');
  });
});

describe('TemplateInsertDialog', () => {
  it('lists templates, prompts, and inserts the rendered body', async () => {
    postMock.mockResolvedValue({ path: 'x.md', folder: 'f', filename: 'x.md', title: 'x', frontmatter: {}, body: '# Planning\n' });
    const onInsert = vi.fn();
    render(withQuery(<TemplateInsertDialog onClose={() => {}} onInsert={onInsert} />));
    expect(screen.getByRole('dialog', { name: 'insert template' })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('menuitem', { name: /Meeting notes/ }));
    await fillTopicAndSubmit('insert');
    await waitFor(() => expect(onInsert).toHaveBeenCalledWith('# Planning\n'));
    expect(postMock).toHaveBeenCalledWith('/v1/templates/meeting-notes/render', {
      answers: { topic: 'Planning', context: 'work' },
    });
  });
});
```

Append inside the `describe('JotsScreen', …)` block of `desktop/src/renderer/__tests__/jots.test.tsx`. Add `import { useNoteView } from '../stores/note-view';` and `import type { TemplateSummary } from '../../shared/api-types';` (merging the latter into the existing type import) at the top:

```tsx
  it('"template" menu creates a note from a template and opens it', async () => {
    const MEETING: TemplateSummary = {
      id: 'meeting-notes',
      path: '90-meta/templates/meeting-notes.md',
      name: 'Meeting notes',
      description: '',
      prompts: [{ id: 'topic', ask: 'Topic', type: 'text', optional: false, default: null, options: [] }],
      variables: ['context', 'date', 'topic'],
      valid: true,
      diagnostics: [],
    };
    useNoteView.getState().close();
    apiRequest.mockImplementation(withConnectors(async (method, path) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: { items: [], total: 0 } satisfies JotsPage };
      if (path === '/v1/templates') return { ok: true, status: 200, data: { templates: [MEETING] } };
      if (path === '/v1/projects') return { ok: true, status: 200, data: [] };
      if (method === 'POST' && path === '/v1/templates/meeting-notes/create')
        return {
          ok: true,
          status: 201,
          data: { path: '20-contexts/work/meetings/2026-10-09-planning.md', title: '2026-10-09 Planning', etag: 'e', status: 'applied' },
        };
      return { ok: true, status: 200, data: { items: [], total: 0 } };
    }));

    render(withQuery(<JotsScreen />));
    fireEvent.click(await screen.findByRole('button', { name: 'template' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: /Meeting notes/ }));
    fireEvent.change(await screen.findByLabelText('Topic'), { target: { value: 'Planning' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'create' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    await waitFor(() =>
      expect(useNoteView.getState().path).toBe('20-contexts/work/meetings/2026-10-09-planning.md'),
    );
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/TemplatePicker.test.tsx src/renderer/__tests__/jots.test.tsx`
Expected: FAIL. The picker test fails with `Failed to resolve import "../components/TemplatePicker"`, and the new jots test fails with "Unable to find role button template".

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/components/TemplatePicker.tsx`:

```tsx
import { useState } from 'react';
import { useTemplates } from '../lib/api/hooks';
import type { TemplateCreateResponse, TemplateSummary } from '../../shared/api-types';
import { Btn } from './Btn';
import { Lucide } from './Lucide';
import { TemplatePromptDialog } from './TemplatePromptDialog';

function firstError(t: TemplateSummary): string {
  const d = t.diagnostics.find((x) => x.severity === 'error');
  return d ? `line ${d.line}: ${d.message}` : 'template has errors';
}

/** Templates from 90-meta/templates; broken ones are shown disabled with ⚠. */
export function TemplateList({
  enabled = true,
  onPick,
}: {
  enabled?: boolean;
  onPick: (t: TemplateSummary) => void;
}) {
  const q = useTemplates({ enabled });
  if (q.isLoading) return <div className="px-3 py-2 font-mono text-11 text-ink-3">loading templates…</div>;
  if (q.isError) {
    return (
      <div role="alert" className="px-3 py-2 text-12 text-oxblood">
        templates unavailable — {q.error instanceof Error ? q.error.message : 'error'}
      </div>
    );
  }
  const items = q.data?.templates ?? [];
  if (items.length === 0) {
    return <div className="px-3 py-2 font-mono text-11 text-ink-3">no templates in 90-meta/templates</div>;
  }
  return (
    <ul role="menu" aria-label="templates">
      {items.map((t) => (
        <li key={t.id} role="none">
          <button
            type="button"
            role="menuitem"
            disabled={!t.valid}
            title={t.valid ? t.description : firstError(t)}
            onClick={() => onPick(t)}
            className="block w-full px-3 py-[6px] text-left text-12 text-ink-0 hover:bg-vellum disabled:cursor-not-allowed disabled:text-ink-3"
          >
            {!t.valid && <span aria-hidden="true">⚠ </span>}
            {t.name}
            {t.valid && t.description && (
              <span className="block text-11 text-ink-3">{t.description}</span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Jots screen: "template" button → list → prompt dialog → created note. */
export function TemplateMenu({ onCreated }: { onCreated: (res: TemplateCreateResponse) => void }) {
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<TemplateSummary | null>(null);
  return (
    <div className="relative">
      <Btn variant="ghost" size="sm" icon={<Lucide name="file-plus" size={13} />} onClick={() => setOpen((o) => !o)}>
        template
      </Btn>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-[260px] rounded-r6 border border-hairline-2 bg-paper py-1 shadow-card">
          <TemplateList
            enabled={open}
            onPick={(t) => {
              setOpen(false);
              setChosen(t);
            }}
          />
        </div>
      )}
      {chosen && (
        <TemplatePromptDialog
          template={chosen}
          mode="create"
          onClose={() => setChosen(null)}
          onCreated={onCreated}
        />
      )}
    </div>
  );
}

/** `/template` in the editor: pick a template, answer, insert its body. */
export function TemplateInsertDialog({
  onClose,
  onInsert,
}: {
  onClose: () => void;
  onInsert: (markdown: string) => void;
}) {
  const [chosen, setChosen] = useState<TemplateSummary | null>(null);
  if (chosen) {
    return <TemplatePromptDialog template={chosen} mode="insert" onClose={onClose} onInsert={onInsert} />;
  }
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="insert template"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-[320px] rounded-r6 border border-hairline-2 bg-paper py-2 shadow-card">
        <div className="mb-1 flex items-center justify-between px-3">
          <span className="font-body text-13 font-medium text-ink-0">insert template</span>
          <button type="button" aria-label="close" onClick={onClose}
            className="rounded-sm p-[2px] text-ink-2 hover:text-ink-0">
            <Lucide name="x" size={14} />
          </button>
        </div>
        <TemplateList onPick={setChosen} />
      </div>
    </div>
  );
}
```

In `desktop/src/renderer/screens/jots.tsx`, add `import { TemplateMenu } from '../components/TemplatePicker';` next to the other component imports. Then, inside the TopBar `right` `<div className="flex gap-2">`, insert this immediately before the `variant="primary"` "new" `<Btn>`:

```tsx
            <TemplateMenu
              onCreated={(res) => {
                if (res.status === 'pending') {
                  toast.info('note saved for approval');
                  return;
                }
                toast.success(`created — ${res.title}`);
                openNote(res.path);
              }}
            />
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd desktop && npx vitest run src/renderer/__tests__/TemplatePicker.test.tsx src/renderer/__tests__/jots.test.tsx && npm run typecheck && npx eslint --max-warnings 0 src/renderer/components/TemplatePicker.tsx src/renderer/screens/jots.tsx`
Expected: PASS. The existing jots tests still find the "new" button: the template button's accessible name is "template", which does not match `/new/`.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/components/TemplatePicker.tsx desktop/src/renderer/screens/jots.tsx desktop/src/renderer/__tests__/TemplatePicker.test.tsx desktop/src/renderer/__tests__/jots.test.tsx
git commit -m "feat(desktop): new note from template on the Jots screen"
```

---

### Task 11: `/template` slash insert

**Files:**
- Modify: `desktop/src/renderer/lib/editor/slash.ts` (append one item at the **end** of `SLASH_ITEMS`, without reordering)
- Modify: `desktop/src/renderer/components/RichMarkdownEditor.tsx` (additive: import, state, effect and JSX)
- Test: append to `desktop/src/renderer/__tests__/slash.test.ts`; create `desktop/src/renderer/__tests__/template-slash-insert.test.tsx`

**Interfaces:**
- Consumes: `TemplateInsertDialog({ onClose, onInsert })` (Task 10), `buildEditorExtensions()` (existing), and the `editorRef` in `RichMarkdownEditor` (existing).
- Produces: `SLASH_ITEMS` gains `{ key: 'template', title: 'Template', run }`, which deletes the slash range and emits `gb:slash:template`. `RichMarkdownEditor` opens `TemplateInsertDialog` on that event and inserts the returned markdown at the cursor.

- [ ] **Step 1: Write the failing tests**

Append to `desktop/src/renderer/__tests__/slash.test.ts`. Add `vi` to the vitest import, and add `import { Editor } from '@tiptap/core';` and `import { buildEditorExtensions } from '../lib/editor/extensions';`:

```ts
describe('template slash command', () => {
  it('matches on "templ"', () => {
    expect(filterSlashItems('templ').map((i) => i.key)).toEqual(['template']);
  });

  it('clears the slash range and emits gb:slash:template', () => {
    const editor = new Editor({ extensions: buildEditorExtensions(), content: '<p>/templ</p>' });
    const spy = vi.fn();
    editor.on('gb:slash:template' as Parameters<typeof editor.on>[0], spy);
    SLASH_ITEMS.find((i) => i.key === 'template')!.run(editor, { from: 1, to: 7 });
    expect(spy).toHaveBeenCalledTimes(1);
    expect(editor.getText()).toBe('');
    editor.destroy();
  });
});
```

`desktop/src/renderer/__tests__/template-slash-insert.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';

vi.mock('../components/TemplatePicker', () => ({
  TemplateInsertDialog: ({ onInsert, onClose }: { onInsert: (md: string) => void; onClose: () => void }) => (
    <button
      type="button"
      onClick={() => {
        onInsert('## Inserted heading\n');
        onClose();
      }}
    >
      fake insert
    </button>
  ),
}));

describe('RichMarkdownEditor /template', () => {
  it('opens the template dialog on the slash event and inserts the rendered body', async () => {
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor markdown="start" onSave={() => {}} jotId="t" onEditorReady={(e) => {
        editor = e;
      }} />,
    );
    expect(screen.queryByRole('button', { name: 'fake insert' })).toBeNull();
    act(() => {
      (editor as unknown as { emit: (event: string) => void }).emit('gb:slash:template');
    });
    fireEvent.click(await screen.findByRole('button', { name: 'fake insert' }));
    await waitFor(() => expect(editor!.getHTML()).toContain('<h2>Inserted heading</h2>'));
    expect(screen.queryByRole('button', { name: 'fake insert' })).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/slash.test.ts src/renderer/__tests__/template-slash-insert.test.tsx`
Expected: FAIL. `filterSlashItems('templ')` returns `[]`, and "Unable to find role button fake insert".

- [ ] **Step 3: Write the implementation**

In `desktop/src/renderer/lib/editor/slash.ts`, append this as the **last** element of `SLASH_ITEMS`, after the `photo` item:

```ts
  {
    key: 'template',
    title: 'Template',
    run: (e, r) => {
      e.chain().focus().deleteRange(r).run();
      // EditorEvents is a closed interface; gb:slash:template is a custom event
      // handled by RichMarkdownEditor (opens TemplateInsertDialog).
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (e as any).emit('gb:slash:template');
    },
  },
```

In `desktop/src/renderer/components/RichMarkdownEditor.tsx`, make these additive edits:

1. Add this import below `import { WebcamCaptureModal } from './WebcamCaptureModal';`:
```tsx
import { TemplateInsertDialog } from './TemplatePicker';
```
2. Add this state below `const [camOpen, setCamOpen] = useState(false);`:
```tsx
  const [templateOpen, setTemplateOpen] = useState(false);
```
3. Add this effect directly after the existing `gb:slash:photo` subscription effect:
```tsx
  // Subscribe to the /template slash command (smart templates, C1).
  useEffect(() => {
    if (!editor) return;
    const handler = () => setTemplateOpen(true);
    editor.on('gb:slash:template' as Parameters<typeof editor.on>[0], handler);
    return () => {
      editor.off('gb:slash:template' as Parameters<typeof editor.off>[0], handler);
    };
  }, [editor]);
```
4. Add this directly after the closing `/>` of `<WebcamCaptureModal … />`:
```tsx
      {templateOpen && (
        <TemplateInsertDialog
          onClose={() => setTemplateOpen(false)}
          onInsert={(md) => {
            const ed = editorRef.current;
            if (!ed || ed.isDestroyed) return;
            // tiptap-markdown parses the string as markdown at the cursor;
            // onUpdate then schedules the normal autosave.
            ed.chain().focus().insertContent(md).run();
          }}
        />
      )}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd desktop && npx vitest run && npm run typecheck && npm run lint`
Expected: the whole desktop suite passes, including the existing `RichMarkdownEditor`, `NoteView`, `jots` and `markdown-roundtrip` tests. Typecheck and lint are clean.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/lib/editor/slash.ts desktop/src/renderer/components/RichMarkdownEditor.tsx desktop/src/renderer/__tests__/slash.test.ts desktop/src/renderer/__tests__/template-slash-insert.test.tsx
git commit -m "feat(desktop): /template slash command inserts a rendered template"
```

---

## Extension points (not built in C1, documented so later slices extend rather than rewrite)

- **C2 Live queries.** The renderer treats a ` ```query ` fence as plain text, so its placeholders are already resolved (pinned in Task 4 and in the 1-1 starter). C2 adds `ghostbrain/templates/query.py` with `parse_query_block(text: str) -> tuple[Query | None, list[Diagnostic]]` and `run_query(query, index) -> list[dict]`. It reuses `Diagnostic` from `parse.py`. It also extends `functions.Kind` with `"query_key"` and appends a `QUERY_KEYS: tuple[FunctionSpec, ...]` to `functions.py`, plus the matching branch in `registry_json()` (`"queryKeys"`). The renderer itself does not change.
- **C3 Template editor.** Completions and hover read `GET /v1/templates/functions` (`TemplateFunctionsResponse`, already typed in Task 8). C3 adds `ghostbrain/templates/lint.py` with `lint(source: str, template_id: str) -> list[Diagnostic]`. That function is `parse_template(...).diagnostics` plus, for every `Placeholder` from `lang.tokenize` (which already carries `line`/`col`, offset by `Template.body_line` for the body), an `unknown-name` warning when `path[0]` is neither a prompt id nor a `find_spec("variable", …)`, when a field fails `find_spec("field", name, owner)`, or when a filter fails `find_spec("filter", …)`. Test run is `parse_template(source, "draft")` followed by `render(template, answers, build_env())`, with no write.
- **C4 AI templates.** Generate a draft, validate it with `parse_template(draft, id)`, and on failure repair once using `[d.to_json() for d in diagnostics]`. Save with `vault_write.write(f"{TEMPLATES_REL}/{id}.md", content=draft, op="create", actor=ASSISTANT, reason="AI template")`, with `id` slugged to `TEMPLATE_ID_RE`. B3's risk policy holds that write as `pending`. `registry.list_templates` picks the template up once it is applied. Templates can never file into `90-meta/` (Decision 9), so an approved AI template still cannot write system files through the user's create action.

---

## Self-review

**Spec coverage (C1 rows):**
- The template format (prompts, file naming and folder, frontmatter, placeholders) is Tasks 1, 3 and 4.
- The registry `functions.py` is Task 2, and `GET /v1/templates/functions` is Task 7.
- `parse.py` with pydantic and line-numbered errors is Task 3.
- `render.py` (tokenizer and evaluator, no dynamic evaluation, slugged filenames, collision suffix, folder guard) is Tasks 1, 4 and 6.
- Starter seeding that never overwrites is Task 5.
- `GET /v1/templates` and `POST /{id}/create` through the write path as user are Task 7.
- The prompt dialog (person suggest, context and project pickers, date input, choice select, required gating) is Task 9.
- The Jots entry point is Task 10. The `/template` slash insert is Task 11.
- Error handling:
  - A template that fails to parse is listed with ⚠ and can't be used (Tasks 5, 7 and 10).
  - A required prompt blocks submit (Task 9).
  - An optional prompt renders empty or its default (Task 4).
  - A folder escape returns 400 and writes nothing (Tasks 4 and 7).
  - A collision gets a suffix and never overwrites (Tasks 6 and 7).
- These spec rows are deliberately left out as C2–C4: `query.py` and `/v1/vault/query`, the query NodeView, the template editor and `/lint`, the `/render {source}` Test run, `/generate`, and the Templates tab.

**Security coverage:**
- No code execution: Task 1 (code-like expressions, static source guard) and Task 3 (YAML python tags).
- No reads outside the vault: Task 5 (id traversal, symlinked file or folder) and Task 4 (person answers resolved through the index only, with traversal rejected).
- No unbounded recursion or size: Task 1 (placeholder and size caps, pathological braces), Task 3 (alias bomb, recursive alias, deep nesting), and Task 4 (no re-expansion, output cap, frontmatter injection).
- No escaping paths: Task 4 (15 folder cases, file name carrying a path), Task 6 (a symlinked folder inside the vault) and Task 7 (route returns 400 and writes nothing).

**Type consistency checked:**
- `RenderEnv`, `RenderedNote.path` and `markdown()`, `AnswerError.field`, `TemplateInvalid.diagnostics`, `TemplateInfo.to_json()` keys versus `TemplateSummary`, `CreatedNote.status` versus `TemplateCreateResponse.status`, and the render-route JSON versus `TemplateRenderResponse` all match.
- `useCreateFromTemplate` and `useRenderTemplate` take `{ id, answers }`. `TemplateInsertDialog` and `TemplateMenu` props match their use in Tasks 10 and 11.
- Shared test helpers in `tests/test_templates_security.py` are defined before use: `_symlink` (Task 5) and `_ENV` (Task 4) are reused by Task 6's appended test.
