# Ontology Scope Ratification — Design (Milestone 1.5)

**Status:** Approved in conversation 2026-10-10. Awaiting review of this written addendum.
**Extends:** `2026-10-10-ontology-ratification-design.md` (the base spec). Where the two disagree, this addendum wins for scoping and extraction.
**Origin:** The first onboarding run on real data pulled in unrelated notes. The seed term appeared only in a note's auto-generated `related:` links, and extraction turned every fact in those notes into backlog items. The user wants this rule:

> Onboarding a project must produce a proper ontology with nothing unrelated in it. Where the system is unsure whether something belongs, it asks, at the level of the topic. For example: "Is claims triage part of Orbit?" The user ratifies yes or no, and the answer sticks.

(Examples here use neutral names. "Orbit" is a project and "claims triage" a topic.)

## Decisions (from the conversation)

- **The project boundary is itself ratified knowledge.** Each project has a set of **topics**, each one either *in scope* or *out of scope*. Both kinds of decision go through the backlog and the log, the same as facts.
- **Questions are asked once per topic, not once per note.** Uncertain notes are grouped by topic, and the user answers one question per topic: *"Is claims triage part of Orbit?"*
- **A "no" is permanent and enforced.** An out-of-scope topic excludes its notes now and in every future scope and extraction pass. Its facts are dropped and it is never asked again. A "yes" binds its notes.
- **The boundary is settled before the facts.** In the backlog, scope questions rank above bindings and facts. A fact whose topic is still undecided waits behind that topic's question.
- **The boundary is visible and queryable.** `Topic` nodes appear in the gold graph with `IN_SCOPE` / `OUT_OF_SCOPE` edges to the project. Agents can later answer "is X part of Orbit?" from gold.
- **Already shipped (prerequisite fix):** keyword scoping matches note content only (title and body, excluding frontmatter and wikilink targets), and extraction is told the project name and seeds and keeps only facts about the project.

## Non-goals

- Topic hierarchies, such as sub-topics of sub-topics. Topics are flat per project.
- Automatic merging of synonym topics. The classifier is shown existing topic labels and asked to reuse them, and the user can reject a duplicate question.
- Cross-project topic sharing. A topic belongs to exactly one project.
- Re-classifying notes that are already bound when no scope decision touches them.

## Design

### 1. Model additions

- **New vertex type:** `Topic`, with props `name` and `project`. Its UI kind is `topic`, with its own colour token.
- **New edge types:**
  - `IN_SCOPE` (Topic → Project) and `OUT_OF_SCOPE` (Topic → Project), which carry the ratification props as usual.
  - `HAS_TOPIC` (Artefact → Topic), written for notes bound through a topic decision.
- **New event type:** `scope`, with payload
  `{project, topic_uid, name, decision: "in"|"out", artefacts: [{aid, path, title}], excluded: [aid]}`.
  - **`in`:** upsert the Topic, add `IN_SCOPE`, add `ABOUT` + `HAS_TOPIC` for `artefacts`.
  - **`out`:** upsert the Topic, add `OUT_OF_SCOPE`, and **remove** `ABOUT` edges from the project for every aid in `artefacts` + `excluded`. Removal needs `GoldGraph.delete_edge(etype, src, dst)`.
  - Both are deterministic on replay, so the rebuild-equals-incremental invariant still holds.
- **New SQLite working table:** `topics(project_uuid, uid, name, status: pending|in|out, created)`, plus a `topic` column on `candidates`. Gold stays reconstructible from the log alone.

### 2. Scoping with three bands

For each note found by keyword or semantic discovery, using content only:

| Band | Signals | Outcome |
|---|---|---|
| **In** | Any of: the seed is in the title or a heading; ≥3 body mentions; the note sits in the project folder; the note's topic is already ratified *in* | Into the bulk binding item, as today |
| **Unsure** | 1–2 body mentions, or a semantic-only hit with no content mention | Topic classification (below) |
| **Out** | No content mention and no semantic hit, or the note's topic is already ratified *out* | Skipped silently, and logged in the run summary |

**Topic classification** (`ontology/topics.py`) runs on unsure notes in batches of 10, using the `fast` tier.
- **Input:** the project name and description, the seeds, and the project's existing topic labels with their status. Per note: the title and the first ~1,500 characters of the body.
- **Output, strict JSON per note:**
  - `topic`: a short noun phrase. The classifier must reuse an existing label when it means the same thing.
  - `lean`: `about` | `not_about` | `unclear`.
  - `reason`: one sentence.
- Notes whose topic is already decided are auto-routed: *in* to the binding, *out* to skip.
- The remaining notes are grouped by topic into one **scope item** per pending topic.

### 3. The scope backlog item

- **Type:** `scope`.
- **Payload:** `{topic_uid, name, lean, notes: [{aid, path, title, reason}]}`.
- **Card text:** *"Is **claims triage** part of **Orbit**?"* followed by the classifier's lean ("probably not"), the note count, and up to 5 sample notes. Each sample note opens on click, and the full list expands.

| Action | Effect |
|---|---|
| **Yes** (optionally unticking notes as exceptions) | `scope` event `in`. The ticked notes are bound, the unticked ones excluded. Waiting candidates for this topic are released into the backlog. |
| **No** | `scope` event `out`. All the topic's notes are excluded, including any already bound. Waiting candidates for this topic are rejected with reason `out_of_scope`. |
| **Investigate** | Parks the item, as other items do. |

**Ranking:** scope items come first, then bindings, then candidates. They are never hidden by the cap.

### 4. Extraction respects the boundary

- **Prompt inputs** (in addition to what's already there): the in-scope and out-of-scope topic lists, and the instruction to tag each candidate with a `topic` (reusing labels).
- **Triage by the candidate's topic:**
  - **Out:** the candidate is dropped and counted as `out_of_scope`, with no item.
  - **In:** normal triage.
  - **Unknown or pending:** the candidate is stored with status `waiting_scope` and no item. If no scope item exists yet for that topic, one is created, with this candidate's source note as its sample.
- **When a topic is decided:** waiting candidates are released (`in`, creating their items) or rejected (`out`).

### 5. API

- `POST /v1/ontology/backlog/{id}/action` accepts `yes` / `no` for scope items. `ratify` / `reject` are accepted as synonyms. `exclude` applies to *yes*.
- `GET /v1/ontology/projects/{uuid}/topics` returns topics with their status and note counts, for the boundary view.
- `GET /v1/ontology/graph` includes Topic nodes and their edges.

### 6. Desktop

- **Scope card** at the top of the backlog: the question, the lean pill, sample notes (clickable), an exceptions checklist on expand, and **Yes / No / Not sure** buttons. They use the same per-row pending guard and error handling as the other cards.
- **Graph:** Topic nodes in a distinct colour. The node panel shows the topic's decision, its date, and its notes.
- **Boundary list** under the project picker: in-scope topics, then out-of-scope topics, each with a note count. This is read-only in M1.5; reversing a decision is a revert, which is M2.

## Error handling

- **Classifier failure:** one retry with a repair prompt. If it still fails, the batch's notes stay *unsure* with topic `unclassified`, and are presented together as one scope item, "Unclassified notes (N)". Nothing is bound silently.
- **Stale topic:** a scope action on a topic that was decided meanwhile returns 409, the same as a double ratify.
- **Over-eager labels:** the classifier inventing near-duplicate labels shows up as two questions. Answering both is safe, and duplicates are tracked as a quality metric for the M3 evals.

## Testing

- **Scoping bands:** a title mention or 3 mentions gives *in*; a single mention or a semantic-only hit gives *unsure*; no mention gives *out*; a note whose topic was decided *in* or *out* is auto-routed.
- **Classifier:** batching, label reuse given in the prompt, strict-JSON validation, retry, and the `unclassified` fallback (with a stubbed LLM).
- **Scope actions:**
  - *yes* binds the ticked notes, excludes the unticked ones, and releases waiting candidates;
  - *no* excludes all the topic's notes, removes previously added `ABOUT` edges and rejects waiting candidates;
  - a second action returns 409.
- **Projector:** `scope in` and `scope out` events, including `ABOUT` removal; the rebuild-equals-incremental determinism test extended with scope events.
- **Extraction:** a candidate whose topic is *out* is dropped, *pending* is held, and *in* is passed through. Deciding the topic releases or rejects the held candidates.
- **Desktop:** the scope card renders the question and lean; *Yes* with one note unticked posts `exclude`; *No* posts `no`; Topic nodes render.
- **End to end on the sandbox:** onboarding produces scope questions for borderline topics, a *no* removes their notes and facts, and the backlog then holds only project facts.
