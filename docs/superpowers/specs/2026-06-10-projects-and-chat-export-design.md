# Dynamic Projects + Chat-Summary Export — Design

**Date:** 2026-06-10
**Status:** Approved
**Repo:** ghost-brain (Poltergeist sidecar + desktop)
**Execution:** on a git worktree, branch `feat/projects-and-chat-export` off latest `main`

## Summary

Two features sharing one concept:

1. **Dynamic projects** — user-defined routing destinations nested under the four
   fixed contexts (`sanlam`, `codeship`, `reducedrecipes`, `personal`). Managed
   in-app, stored in a synced vault registry, picked up dynamically by the LLM
   auto-router, the manual re-route UI, and the jots tree.
2. **Chat-summary export** — one action on a chat conversation produces an LLM
   summary saved as a jot, which auto-routes to a context/project like any
   other jot and is reviewable/editable in the jots screen.

## Decisions (alternatives considered)

| Decision | Chosen | Rejected |
|---|---|---|
| Project model | Nested under fixed contexts | Replace contexts; parallel tag-like dimension |
| Management | In-app UI + `/v1/projects` API | Vault-folders-as-registry; hand-edited config file |
| Routing | Auto-router picks context AND project; manual re-route too | Manual-only; jots-only |
| Chat export | LLM summary, auto-routed like a jot | Raw transcript dump; manual destination pick |
| Vault shape | Registry file + project folders + frontmatter stamp | Frontmatter only; folders-as-registry |

## 1. Project registry (sidecar)

New `ghostbrain/api/repo/projects.py` managing `<vault>/90-meta/projects.json`
(atomic tmp+rename writes, UTF-8, corrupt-file tolerant — same pattern as chat
storage). The registry syncs with the vault across machines.

Project shape:

```json
{
  "id": "codeship/poltergeist",
  "context": "codeship",
  "slug": "poltergeist",
  "name": "Poltergeist",
  "description": "the second-brain product: vault, connectors, desktop app",
  "archived": false,
  "created_at": 1781100000.0
}
```

- `slug` is derived from the name (kebab-case, filesystem-safe), unique per
  context; `id` is `<context>/<slug>`.
- Creating a project also creates `20-contexts/<context>/projects/<slug>/`.
- Contexts remain the fixed four — projects do not create contexts.

`/v1/projects` routes:

| Route | Behavior |
|---|---|
| `GET /v1/projects?includeArchived=` | List (active only by default), grouped client-side |
| `POST /v1/projects` | Create `{context, name, description?}` → 409 on duplicate slug in context, 422 on unknown context |
| `PATCH /v1/projects/{context}/{slug}` | Edit name/description, set/unset `archived` |

No DELETE in v1 — archive only (routed notes reference the project).
Renaming changes `name` only; `slug` (and folder) are immutable in v1.

## 2. Routing with projects

**Auto-router** (`ghostbrain/worker/router.py`): the hardcoded context enum in
`ROUTER_JSON_SCHEMA` becomes a dynamic **destination** enum built per call from
the registry: `["sanlam", "sanlam/capstone", "codeship/poltergeist", ...]` — a
bare context means "no project". Active projects' names + descriptions are
injected into the router prompt. Heuristic pre-routing (email domains, Slack
workspaces, label prefixes) keeps picking bare contexts; only the LLM stage
picks projects. `needs_review` behavior is unchanged.

**Validation:** a router result naming an unknown or archived project degrades
to context-only routing — never `needs_review` because of a bad project.

**Manual routing** (`/v1/notes/{id}/route`): request gains optional `project`
(slug), validated against the registry for the given context (422 on
unknown/archived).

**Note placement** (`notes_manual.move_jot`): with a project, the target dir is
`20-contexts/<context>/projects/<slug>/`; without, today's
`20-contexts/<context>/notes/` stays. Frontmatter gains `project: <slug>` when
set. Moving a note between projects (or to none) is a re-route.

**Listing** (`list_jots` + `GET /v1/notes?source=manual`): results include
`project`; new `project` query filter. The jot-file scan extends to
`20-contexts/*/projects/*/`.

## 3. Chat-summary export

`POST /v1/chat/{conv_id}/export-jot`:

1. Load the conversation (404 if missing; 400 if it has no assistant message).
2. One `llm/client.py` call (sonnet) with a structured prompt over the
   transcript: outcome summary, decisions, findings, open questions, and the
   vault wikilinks cited in the thread (preserved verbatim so the jot links
   back to sources).
3. Write the summary as an inbox jot with frontmatter
   `source: chat-summary`, `chat_id: <conv_id>`, `chat_title`, plus the normal
   jot fields. The LLM call completes before any file is written — a failed
   export writes nothing (502 with detail).
4. Auto-route it immediately through the same path as `/v1/notes/{id}/route-auto`.
5. Return `{jot_id, path, routingStatus, context, project}`.

Re-exporting the same conversation creates a new jot (no dedup in v1).

## 4. Desktop UI

- **Projects manager** — new section in the Settings screen (no new sidebar
  entry): projects grouped by context; create form (context picker, name,
  description); inline edit; archive toggle with archived items collapsed.
- **Jots screen** — tree grouping becomes context → project → month, with
  project-less jots directly under the context as today; the re-route control
  becomes a two-level context/project picker fed by `useProjects`; a project
  filter joins the existing context/tag filters.
- **Chat screen** — "export to jots" action in the thread TopBar with a pending
  state (the LLM call takes ~5-15s; disable during export); on success, a toast
  shows the routed destination with an affordance to open the jot; on failure,
  an error toast with the detail.
- **Hooks** — `useProjects`, `useCreateProject`, `useUpdateProject`,
  `useExportChatToJot`; project mutations invalidate `['projects']`, export
  invalidates `['jots']`.

## 5. Error handling

- Corrupt/missing `projects.json` → empty registry; routing degrades to
  context-only; the projects UI surfaces the parse error instead of an empty
  state lying about there being no projects.
- Archived projects disappear from the router enum and pickers; existing notes
  stay where they are and keep their frontmatter.
- Registry writes are atomic; concurrent project edits are last-writer-wins
  (single-user app, acceptable).
- Export endpoint: 404 unknown conversation, 400 empty conversation, 502 LLM
  failure (nothing written), routing failure after write → jot exists in inbox
  with `needs_review`, surfaced in the response.

## 6. Testing

- **pytest:** registry CRUD (create/slug collision/unknown context/archive/
  corrupt file), destination-enum builder, router fallback on unknown project,
  `move_jot` + frontmatter with project, `list_jots` project filter, manual
  route with project validation, export endpoint with faked LLM + faked router
  (success, empty-conversation 400, LLM-failure 502 writes nothing).
- **Vitest:** projects settings section (list/create/edit/archive), jots tree
  project grouping + re-route picker, export button states (idle/pending/
  success/error).

## Out of scope (v1)

- Deleting projects / renaming slugs (and the folder migrations both imply)
- Per-project digests or dashboards
- Moving existing routed notes into projects in bulk
- Project-scoped chat or search
- Dedup/update semantics for repeated chat exports
