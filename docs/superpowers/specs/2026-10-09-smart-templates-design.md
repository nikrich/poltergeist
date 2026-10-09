# Smart Templates — Design

- **Date:** 2026-10-09
- **Status:** Draft — awaiting review
- **Repo:** ghost-brain (poltergeist)
- **Depends on:**
  - the link index and suggest routes from the editor spec (`2026-10-09-confluence-editor-design.md`, slice A2), for live queries and person prompts;
  - **AI Changes + Revert** (`2026-10-09-ai-changes-revert-design.md`): the write path (B1) and approvals (B3) for AI-made templates.
- **Author:** brainstormed with Jannik

## Goal & intent

**What the user asked for** (the Brainstead item they wanted pulled in): a template is more than a blank form. It can:
- ask a question or two when you make a note ("who's this 1-1 with?");
- name and file the note for you;
- fill it with **live lists**, such as every open follow-up for that person, that keep themselves up to date.

The editor should also suggest what can go next and explain each piece, and there should be a **Test run** before real use. You can ask the AI to make a template, but it waits for your acceptance before it's saved.

**Assumptions (correct me):**

- **Templates are vault files** (plain markdown), so they're portable and editable anywhere. They live in `90-meta/templates/`, which spec B's risk policy already treats as needing approval for non-user writes.
- **"Live lists" render inside Poltergeist.** In other editors they show as readable query source, not results.
- The template language **can't run code**: variables, a few filters and query blocks, nothing Turing-complete. That keeps "a template ran something" off the table and makes intellisense complete.

## Scope

In scope:

- **Template format:** prompts, file naming and folder, frontmatter, `{{ … }}` placeholders.
- **"New from template"** with a prompt dialog, filing, and opening the new note.
- **Live `query` blocks** rendered by the editor, with a "mark done" action.
- **A template editor** with completions, hover docs, linting, and Test run.
- **AI-generated templates,** held as pending changes.
- **Three starter templates:** 1-1, Meeting notes, Decision record.

Non-goals:

- Loops, conditionals, or arbitrary expressions in templates. Queries cover the "list of things" need.
- Dataview / Templater compatibility. Their languages are large and executable; we borrow only the ` ```query ` fence idea.
- Auto-applying templates to notes created by connectors.
- Template inheritance or partials.

## Template format (on disk)

`90-meta/templates/one-on-one.md`:

````markdown
---
template:
  name: 1-1
  description: Weekly 1-1 with open follow-ups for the person
  prompts:
    - id: person
      ask: "Who's this 1-1 with?"
      type: person          # person | text | date | choice | context | project
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
````

**Placeholders** (`{{ … }}`) use a fixed registry, `ghostbrain/templates/functions.py`, which is the single source for rendering, intellisense, docs and linting:

- **Variables:** prompt ids; `date`, `time`, `now`; `context` (the user's current or default context); `project`; `title`; `user.name`. Typed prompts expose fields: `person.name`, `person.link`, `person.path`, `project.name`, `date.iso`.
- **Filters:** `format: <pattern>` (dates), `slug`, `upper`, `lower`, `default: <text>`.
- An unknown name renders as the literal text and is flagged by the linter; it never errors at creation.

**Query blocks** (` ```query ` fences) **stay in the note.** They are not expanded into static text, so the list stays current. Keys:

- `type`: matches frontmatter `artifactType` or `type`.
- `context`, `tag`, `mentions`: a wikilink or name, matched against outgoing links, else the body text.
- `status`: `open` means frontmatter `status` is not `done` or `closed`, which covers today's `action_item` notes that have no status.
- `since` (`7d`, `2026-10-01`), `sort` (`created|updated` + `asc|desc`), `limit` (default 20, max 100).

Placeholders inside a query block are resolved at creation, so the block is concrete in the note. Outside Poltergeist it degrades to a readable code block.

## Architecture

### Backend (`ghostbrain/templates/`, new)

- `parse.py`: load a template file and validate the `template:` frontmatter (pydantic model). It returns structured errors with line numbers for the linter.
- `render.py`: a tiny tokenizer and evaluator for `{{ name.field | filter: arg }}`, with no `eval` and no Jinja. `render(template, answers) -> RenderedNote{folder, filename, frontmatter, body}`.
  - Filenames are slugged with the existing `notes_manual.make_slug` rules.
  - Collisions get ` (2)`, ` (3)`, ….
  - The folder is validated with `_resolve_safe`, so a rendered folder can't escape the vault.
- `functions.py`: the registry `{name: {kind, type, doc, example}}`.
- `query.py`: runs a query against spec A2's link index, which is extended to carry `artifactType, type, status, context, tags, created, updated`. It returns `[{path, title, context, status, created, snippet}]`.
- **Seeding:** `bootstrap.py` writes the three starter templates into `90-meta/templates/` if the folder is missing. It never overwrites.

Routes (`ghostbrain/api/routes/templates.py`):

| Route | Purpose |
|---|---|
| `GET /v1/templates` | list `{id, name, description, prompts}` |
| `GET /v1/templates/functions` | the registry, for intellisense |
| `POST /v1/templates/{id}/create` `{answers}` | render, then create via `vault_write.write(op="create", actor=user)`, then return `{path}` |
| `POST /v1/templates/render` `{source, answers, dry_run: true}` | Test run: rendered note plus target path, nothing written; lint diagnostics included |
| `POST /v1/templates/lint` `{source}` | diagnostics `[{line, col, severity, message}]` |
| `POST /v1/vault/query` `{query}` | live query results (also used outside templates) |
| `POST /v1/templates/generate` `{description}` | AI-drafted template saved via the write path as `actor=assistant` under `90-meta/templates/` (→ pending, spec B3) |

### Renderer

- **New from template:** a split button next to "new jot" in `screens/jots.tsx`, plus a `/template` slash item that inserts a rendered body into the *current* note (no filing).
  - Choosing a template opens `TemplatePromptDialog`, with one field per prompt. `person` uses spec A2's `GET /v1/vault/suggest?kind=person`; `context` and `project` use the existing `useContexts` / `useProjects`; `date` uses a native date input; `choice` uses a select.
  - Submit → `/create` → the new note opens in the editor.
- **Query block NodeView** (`lib/editor/query-block.ts`): renders results as a list of links with status checkboxes. Ticking one calls the write path to set `status: done` (a `fields` write, actor user), and the list refreshes. Results are fetched on mount and on focus, and every 60 s while visible. A "⋯" menu has: Edit query (toggles to source) and **Freeze**, which replaces the block with a static markdown list for sharing or export.
- **Templates screen** (a tab in the jots screen): list, create blank, "Make one with AI", and open the template editor.
- **Template editor:** CodeMirror (already a dependency via `JotEditor`; `@codemirror/autocomplete` and `@codemirror/lint` are added as direct dependencies if the lockfile only has them transitively) with:
  - `@codemirror/autocomplete`: after `{{`, it offers variables, the template's own prompt ids and fields; after `|`, filters; inside ` ```query `, query keys and values (known `type`s, contexts, `open`). Every completion carries its registry doc string.
  - **hover tooltips** with the same docs;
  - **lint** via `@codemirror/lint` → `/v1/templates/lint` (debounced 500 ms);
  - **Test run** split pane: sample answers are prefilled with the most recent real values (last person, today), the result renders through the normal rich renderer with live queries executed, and the target path shows as "would be filed at …".
- **Make one with AI:** a dialog with a description box → `/generate` → shows "Pending your approval on the Changes screen", with a link. Approving there saves it; spec B3 handles the approval UI.

### AI generation

`templates/generate.py` runs a single agent turn (`ghostbrain/llm/agent.py`), the same pattern as `docs_assist`:
- a template-writer system prompt that embeds the **registry docs** and the format reference above;
- tools limited to `poltergeist_search` / `poltergeist_get_note`, so it can look at the user's existing notes for structure.

The output is validated with `parse.py`. Invalid output gets one automatic repair turn with the parse errors, and otherwise returns an error. It's never saved invalid.

## Data flow (create from template)

```
Split button → pick "1-1" → TemplatePromptDialog (person = Alex via suggest)
→ POST /v1/templates/one-on-one/create {answers:{person:"30-cross-context/people/thando", focus:""}}
  → render: folder 20-contexts/work/one-on-ones, name "2026-10-09 Alex 1-1"
  → vault_write.write(op=create, actor=user) → {path}
→ editor opens note → query NodeView → POST /v1/vault/query → open action items mentioning [[…/thando]]
```

## Error handling

- **Template fails to parse:** it's listed with a ⚠ and can't be used until fixed; the template editor shows the diagnostics.
- **Required prompt unanswered:** the dialog blocks submit; optional prompts render empty, or their `default:`.
- **Rendered folder invalid or escaping the vault:** 400 with the message; nothing is written.
- **Filename collision:** a ` (n)` suffix, never an overwrite.
- **Query error** (bad key or value): the block shows the error inline with the source; the note still opens.
- **Query index unavailable:** a "results unavailable — retry" chip.
- **AI generation fails or produces invalid output twice:** an error in the dialog with the raw draft offered as copyable text; nothing saved.

## Testing

- **Pytest:**
  - parser (valid, missing fields, bad prompt types, line-numbered errors);
  - renderer (variables, typed fields, filters, unknown names stay literal, slug, collision suffix, vault-escape rejection, placeholders resolved inside query fences);
  - query engine (each key, `open` semantics with missing `status`, mentions via link vs text, sort and limit, the 100 cap);
  - routes (create goes through the write path as user; render dry-run writes nothing; generate saves as assistant to `90-meta/templates` and comes back **pending**; invalid AI output gets one repair, then an error);
  - starter-template seeding never overwrites.
- **Vitest:** prompt dialog (types, required gating, person suggest); query NodeView (render, tick sets status done and refreshes, freeze produces a static list, error state); template editor completions, hover docs and lint markers (mocked registry); test-run pane.
- **Round-trip fixture:** a ` ```query ` block survives the rich editor byte-stable (it's a code fence).

## Slices (build order)

1. **C1 Engine + creation:** template format, parse and render, registry, create route, prompt dialog, starter templates, `/template` slash insert. *(Needs B1's write path for `op=create`. Before B1 ships, it uses `note.save_note_at_path` behind the same function.)*
2. **C2 Live queries:** link-index fields, `/v1/vault/query`, the query NodeView with tick-to-done and freeze. *(Needs A2.)*
3. **C3 Template editor:** completions, hover docs, lint, Test run.
4. **C4 AI-generated templates:** the generate route, pending approval. *(Needs B3.)*

## Decisions (approved by the user 2026-10-09)

1. **Template folder.** `90-meta/templates/` (recommended: system area, covered by the risk policy) or a visible top-level `70-templates/`? → **`90-meta/templates/`.**
2. **Live query results inside other tools.** Keep queries live only (recommended), or also write a static snapshot under each block on save so Obsidian and exports show results? → **Live only, plus the manual Freeze action.**
3. **Status for follow-ups.** Ticking an item writes `status: done` into the action item's frontmatter, which today has no status field. → **Yes:** it's the minimal way to make "open follow-ups" meaningful.
