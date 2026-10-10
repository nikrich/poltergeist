# Ontology & Ratification — Design

**Status:** Approved in conversation 2026-10-10, section by section. Awaiting review of this written spec.
**Origin:** The user wants the vault built as **ontologies**:
- a personal ontology (the user → their contexts → their projects);
- a per-project ontology that ties everything inside a project together.

Facts must be **ratified** through a ratification backlog. As data flows in, contradictions are raised, and ratified facts are promoted to **gold**. Agents use a graph DB, with vectors holding the ontology together. Metrics and evals must show that agents improve as knowledge is ratified.
**Source of the model:** the user's knowledge-system brief (17 Sep 2026, in the user's vault) and the related meeting transcript *Ontology-Driven Development Replacing Agile Ceremonies*.

**Poltergeist is tenant zero** for that system, so this spec applies the brief faithfully, at personal scale.
**Spike:** `arcadedb-embedded` 26.10.1 was validated on 2026-10-10. Results are in §9. The code was throwaway, and the spike branch was deleted.

## Decisions (from the conversation)

- **Tenant zero.** Same grades, layers, contradiction classes and provenance tagging as the brief. What we learn here feeds the broader knowledge-system work.
- **Two grades:**
  - **Observed (silver):** machine-written, confidence-scored, *informs only*.
  - **Ratified (gold):** human-promoted, audited, *may gate*.
  - Raw vault notes stay the bronze layer and the source of evidence.
- **Pilot project: Orbit.** The dedicated Orbit context is empty today. ~350 Orbit notes sit under the user's main `work` context (meetings, Claude sessions, Slack, Jira, Confluence, GitHub), plus some under `personal` and `cross`. The backfill must establish the project binding itself.
- **Pilot success** has four parts:
  1. a long-running backfill processes all Orbit data;
  2. a ratification backlog is built;
  3. the ontology forms, and gold links back to artefacts (doc-library docs, jots, captures);
  4. metrics and evals show agents improving as knowledge is ratified.
- **Evals have two tracks:**
  - a **sealed** hand-written Orbit Q&A set, which measures generalisation;
  - **probes** auto-generated from each ratified fact, which measure whether gold is used.
- **Storage:**
  - **SQLite** holds the Observed candidate queue and an **append-only ratification log**. The log is the source of truth for gold.
  - **ArcadeDB embedded** holds the gold graph (Cypher + JVector vectors). The graph is a **rebuildable projection of the log**.
  - Rejected alternatives:
    - SQLite only (agents can't compose Cypher; weak tenant-zero fit);
    - markdown-native (graph queries and the "observed never gates" guarantee would be fragile);
    - a graph server in Docker (breaks one-click install);
    - LadybugDB (a young fork of the archived Kùzu; it stays the fallback engine).
- **"Observed informs, Ratified gates" is enforced physically.** Chat may use silver, labelled by grade. Building agents read only from ArcadeDB, which contains only gold.
- **Existing numpy semantic index stays** for the pilot. Moving search into ArcadeDB is a later, separate change: behind `api/repo/search.py`, with numpy as the fallback.
- **People are not graph nodes.** This is the brief's "systems, never people" rule.
  - People live in a thin directory beside the graph and are referenced as `stated_by` / `ratified_by`.
  - The graph models `Role`s.
  - Nothing is scored per person.
  - `Self` is the one exception.
- **Nothing in the ontology is keyed by a human-readable name or path.** A separate feature will allow contexts and projects to be renamed.
- **Viewing happens in Poltergeist.** The Ontology screen reuses the A6 graph renderer (#153). Gold is also written out as markdown, so the vault remains an open, Obsidian-readable format.
- **Long-running backfill = a resumable scheduler job,** modelled on gmail-backfill, rather than a single persistent process.

## Non-goals

- A team or multi-user ratification session, quorum or async pre-votes. This is single-user. The session record is still kept, for the multi-user carry-over.
- Contradiction *discovery* across codebases or schemas (call graphs, schema lineage). Pilot equivalences come from text evidence only.
- Ontologies for projects other than Orbit during the pilot. The machinery is project-generic, but enablement is per project.
- Migrating semantic search into ArcadeDB (see Decisions).
- Remediation of decisions made under a reverted rule. Revert exists, but the "what was concluded under this rule" query comes later.
- Implementing project/context renames. That is a separate feature; this spec only guarantees the ontology survives them.
- Per-person metrics of any kind.

## Design

### 1. The ontology model

There are three layers, following the brief.

**Core layer.** These types are built in and versioned with the code.

| Node | Meaning | Key |
|---|---|---|
| `Self` | the user; the root | fixed ID |
| `Context` | work, personal, … | stable context ID |
| `Project` | e.g. Orbit | stable project ID (not `ctx/slug`) |
| `Artefact` | any vault item: doc-library doc, jot, capture (connector note in `00-inbox/raw/<source>/`), transcript, ticket, email … | note `id` frontmatter, falling back to the stable basename |

- `Artefact` carries `kind` (reusing `vault_index/kinds.py` `NOTE_KINDS`), `path` (a cached value the indexer refreshes) and `source_url`.
- Double-clicking an artefact in Poltergeist opens the note.

**Binding layer.** About a dozen predicates. They are always ratified, never inferred into gold.

- `Self -WORKS_IN-> Context`
- `Project -IN-> Context`
- `Artefact -ABOUT-> Project`
- `Concept -RECORDED_IN-> System`. No `Concept` becomes gold without naming the system that is its source of truth (the brief's rule).

**Domain layer.** One per project. Content is open-ended but drawn from a fixed set of meta-kinds.

- **Nodes:** `Concept`, `Rule` (carries a value, e.g. `lapse_day = 31`), `Decision` (choice, rejected options, rationale), `Requirement`, `System`, `Role`, `OpenQuestion`.
- **Edges:**
  - `PART_OF → Project`, which places every domain node in its project;
  - `DEFINES`, `CONSTRAINS`, `DEPENDS_ON`;
  - `SUPERSEDES`, which absorbs today's `worker/reversal.py` semantics;
  - `SAME_AS`, a ratified equivalence that drives automatic contradiction detection later;
  - `SCOPED_EXCEPTION`, a "by design" ratification with its scope and reason;
  - `EVIDENCED_BY → Artefact`, with properties `quote`, `locator` (heading or offset) and `confidence`.

**Every gold node and edge carries:**
- `ratification_id`;
- `valid_from` and `valid_to`, which answer "what was true on date X" and make revert possible;
- `provenance` ∈ {`observed`, `extracted`, `answered`, `seeded`}, the brief's POC metric;
- `extractor_version`.

**Single-valued predicates** (for example a `Rule`'s value) are declared in the schema. Two different values for the same subject and predicate is a contradiction.

**Stable identity.**
- Contexts and projects get immutable UUIDs. A migration assigns them.
  - `projects.json` entries gain a `uuid` field.
  - Contexts, which `routing.yaml` knows only by name, get theirs from the `identities` table in `ontology.db`, a uuid ↔ current-name mapping.
  - Names are mutable properties.
- A rename is written to the log as a `relabel` event, which needs no ratification. A rebuild therefore yields current names, and renames never enter the backlog.

### 2. Storage

**SQLite: `~/ghostbrain/ontology/ontology.db`.** The tables:

- `candidates`: subject reference, predicate, object reference or value, confidence, extractor version, status (`pending | merged | rejected | ratified | investigating`), embedding (384-d MiniLM, the same model as the semantic index), created/updated.
- `evidence`: candidate ID, artefact ID, quote, locator.
- `log`: **append-only.** Columns: sequence, timestamp, event type, payload JSON, actor. Event types: `ratify | reject | by_design | investigate | revert | relabel | bind | seed`.
- `backfill_runs` and `backfill_cursor`: per project.
- `eval_runs`, `eval_results` and `probes`.
- `audit`: one row per gold-tool call. Columns: tool, caller, question, returned ratification IDs.
- `directory`: people. Columns: id, display name, aliases. Never written to the graph.
- `identities`: maps uuid ↔ current name for each context and project. A `relabel` event updates it.
- `projects_enabled` (project uuid, seed terms), `bindings` (project, artefact, path, title, `bound | excluded`), `extractions` (artefact, content hash, extractor version, status, error) and `items` (backlog items: type, status, candidate, payload, resolution). These are working state. Gold is always reconstructible from `log` alone.

**ArcadeDB: `~/ghostbrain/ontology/gold/`.**
- **Single owner:** the sidecar. ArcadeDB embedded holds an **exclusive per-process lock**, verified in the spike. CLI subcommands and MCP always go through the sidecar's HTTP API.
- **The JVM starts lazily,** on first ontology use, with a 512 MB heap. Users who never touch ontology features pay neither the ~3 s cold start nor the ~400 MB of RAM.
- **`projector.apply(event)`** applies one log event to the graph.
- **`projector.rebuild()`** drops and replays the whole log. A graph property `last_applied_seq` lets startup detect lag and catch up, or rebuild if the graph is corrupt.
- **Vector index:** a JVector index on `Concept`, `Rule`, `Decision`, `Requirement` and `System` embeddings. It is used for equivalence candidates and for `truth` lookups.

**Markdown projection.**
- Each gold domain node is written to `20-contexts/<ctx>/projects/<project>/ontology/<kind>/<uuid8>-<slug>.md`, with frontmatter `type: ontology`, `ontologyKind`, `uuid` and `ratifiedAt`.
- The body holds the value or definition, wikilinks to related nodes, and a list of evidence wikilinks.
- The files are regenerated from the graph. A header marks them as generated, and hand edits are overwritten.
- They are indexed like any note.

### 3. Observed pipeline

**Step 0: scoping.**
- Per project, a seed pass combines semantic search (`api/repo/search.py`) with keyword and identifier matching. The user supplies seed terms such as the project's name, ticket keys and repo names.
- The pass produces a set of proposed `Artefact -ABOUT-> Project` bindings, which reach the backlog as **one bulk binding item** (ratify all, or remove exceptions).
- Only ratified bindings feed extraction.
- New notes routed into a context are re-scored. Matches append to an open bulk-binding item.

**Extraction** (`ontology/extract/extractor.py`) runs per artefact. Notes over ~8k tokens are chunked on headings, or on transcript time windows.
- **Prompt inputs:** the note text; the meta-kinds schema; a compact digest of the project's current gold (names, kinds, IDs, key values, capped at ~2k tokens) so the model maps to existing nodes instead of creating duplicates; and the stable IDs of known roles.
- **Output:** strict JSON, a list of candidates. Each candidate has: subject (existing gold ID or a new-node proposal), predicate, object or value, evidence quote, locator and self-rated confidence.
- **Validation:** candidates are discarded if the evidence quote is not a whitespace-normalised substring of the note, if they break the schema, or if their predicate is unknown. The discard count is logged per run, and it feeds extraction precision metrics.
- **LLM calls** go through `get_provider()`, i.e. the subscription CLIs. Every call passes an explicit budget well above the claude client's $0.50 default cap. Prompts live in `90-meta/prompts/ontology-extract.md`.

**Triage** (`ontology/extract/triage.py`) takes each validated candidate in turn:
1. Embed the candidate's canonical text (`subject predicate object`).
2. A cosine match ≥ τ_dup against a `pending` candidate with the same predicate and an equal value: **merge**. The new evidence is attached and confidence rises with independent corroboration.
3. A cosine match ≥ τ_rej against a `rejected` candidate: **drop**. This is logged but no item is created. Rejections persist.
4. Same subject and a single-valued predicate, but a different value from a pending candidate or a gold fact: create or extend a **contradiction** item. Against gold, it is a **re-opened** item.
5. Similar subject names across artefacts with different IDs (cosine ≥ τ_eq, no shared ID): an **equivalence** item, proposing `SAME_AS`.
6. Otherwise: a new `pending` candidate.

τ values are config with defaults: `0.92`, `0.90` and `0.85`. They are tuned during milestone 2 using the precision metrics.

**Backfill job.** The scheduler job `ontology-backfill` runs every 2 minutes, like gmail-backfill.
- Each tick processes the next K artefacts (default 5) from `backfill_cursor`, ordered **oldest to newest**, so later decisions naturally `SUPERSEDE` earlier ones.
- It is idempotent on (artefact content hash, extractor version). A version bump allows an opt-in re-run.
- It pauses itself, recording a reason, when:
  - **pending backlog > cap** (default 150). Queue growth means extraction is too noisy;
  - **the daily LLM-call budget is spent** (default 300 calls);
  - **there is an error streak** (5 consecutive failures).
- Paused runs resume automatically when the condition clears, or when the user presses "resume."
- **State:** `GET /v1/ontology/projects/{id}/backfill`, which returns processed/total, status, pause reason and last error.

**Live extraction.** After the backfill completes, `worker/pipeline.py` enqueues an extraction for any newly written note bound to an ontology-enabled project. Other projects are untouched.

### 4. Ratification backlog

**Item types:**
- `binding` (bulk)
- `contradiction`
- `candidate`, phrased as a confirmation of the de facto answer: "Today X, per N sources: right?"
- `equivalence`
- `blocked`, raised by `poltergeist_truth` on a miss
- `reopened`

**Actions:**

| Action | Applies to | Log event | Effect |
|---|---|---|---|
| Ratify (value editable first: the correction channel) | all | `ratify` | node/edge enters gold; provenance `extracted`, or `answered` for blocked items |
| Reject | all | `reject` | candidate `rejected`; triage drops look-alikes from then on |
| Investigate | all | `investigate` | creates a linked jot/task; item parked |
| Pick A / Pick B | contradiction | `ratify` + `reject` | the winner enters gold |
| By design | contradiction | `by_design` | both kept, with a `SCOPED_EXCEPTION` (scope + reason); never re-raised |
| Revert | any gold node/edge | `revert` | sets `valid_to`; the projection removes it |

**Ranking score** (milestone 2):
`3·blocked + 2·is_contradiction + 1·fragility + 1·project_activity − 1·cost_to_close`, with confidence as the tiebreak.
- **fragility:** the fact rests on a single source, and that source is more than 90 days old.
- **project_activity:** notes for the project in the last 14 days.
- **cost_to_close:** 0 for a yes/no, 1 when multi-source reading is needed.

**Cap.** The visible queue shows the top 15; the rest appear only as a count. A **consent bundle** groups items that meet all three conditions: confidence ≥ 0.85, at least 2 independent artefacts, and no conflicts. The bundle can be expanded, items removed, and the rest ratified in one action.

**Session mode** (milestone 2): an optional 10-minute timer, with keys `j`/`k`/`r`/`x`/`i`. It ends with a summary: ratified, rejected, agent blocks cleared, coverage delta. The session record goes in the log as a `session` payload. The daily digest gains the line "N items blocking agents".

### 5. Agent access

All tools are forwarded to the sidecar via `mcp/client.py`.

| Tool | Audience | Reads | Behaviour |
|---|---|---|---|
| `poltergeist_ask` (extended) | chat, questions | raw + silver + gold | Retrieval adds gold facts and pending candidates. Answers label each fact's grade inline (`gold, ratified <date>` / `unratified, N sources[, conflicting]`) |
| `poltergeist_truth(question, project?)` | building agents | **ArcadeDB only** | Vector search over gold plus 1-hop expansion. Returns facts with `ratification_id`, `valid_from` and evidence links. **On a miss:** returns `unknown_in_gold: true` plus the best silver suggestion, explicitly marked, and raises a `blocked` item carrying the question and caller |
| `poltergeist_ontology_cypher(query)` | building agents | **ArcadeDB only** | Runs via `db.query()`, which rejects non-idempotent statements. Row limit 500, timeout 5 s. The schema (node/edge types, single-valued predicates) is in the tool description |

- Every `truth` and `cypher` call writes an `audit` row.
- Chat-mode tools never return a fact without its grade label.

### 6. Evals and metrics

- **Sealed set:** `~/ghostbrain/evals/<project>-sealed.yaml`, about 30 entries of `{q, expected, notes}`, written by the user. It lives **outside the vault**, so it is never indexed, extracted or shown in the backlog.
- **Probes:** on each `ratify`, one `{q, expected}` probe is generated from the fact and stored in `probes`.
- **Runner:** `ghostbrain-api eval ontology --project <id> [--track sealed|probes|both]`, plus a nightly scheduled job (`ontology-eval`, 03:30).
  - Each question runs in three modes: **raw** (search + answer, today's `poltergeist_ask` path without the ontology), **+silver** (chat mode), and **gold-only** (`truth` mode).
  - **Judging:** an LLM judge with a fixed rubric grades each answer `correct | partial | wrong | abstained`, and checks that each cited artefact supports the claim.
  - Each run is stamped with `log_seq`, the ontology version.
- **Agent metrics:** accuracy per mode and track; **confidently-wrong rate** (wrong with no hedge); correct-abstention rate; citation validity; truth-tool `unknown` rate.
- **Process metrics:** backlog inflow vs drain per day; extraction precision (ratified ÷ (ratified + rejected)) per extractor version; quote-validation discard rate; coverage (share of bound artefacts backing at least one gold fact); minutes in session mode.
- **Surface:** the Metrics tab (milestone 3) shows accuracy vs gold-fact count per mode, plus the process numbers. Milestones 1–2 only record data.

### 7. Desktop

A new **Ontology** screen with a project picker and three tabs:

- **Backlog:** item list. Each item shows the claim, evidence quotes (click to open the artefact), action buttons and "show in graph". Milestone 1 is a plain list with Ratify / Reject / Investigate / Pick; milestone 2 adds ranking, cap, bundles and session mode.
- **Graph:** the A6 canvas renderer, fed by `GET /v1/ontology/graph?project=&focus=&depth=&include_observed=`, which returns A6's ego-graph response shape.
  - Node kinds are extended with `project | concept | rule | decision | requirement | system | role | question | artefact`.
  - Gold nodes are solid; Observed nodes are dashed ghost rings (toggle); contradictions are red edges.
  - Clicking a node opens a side panel with its facts, provenance, validity, evidence and pending items. Double-clicking an artefact opens the note.
- **Metrics:** milestone 3.
- **Backfill status** sits in the screen header: progress, pause reason, resume button.

### 8. API: `ghostbrain/api/routes/ontology.py` (prefix `/v1/ontology`)

- `GET /projects`: ontology-enabled projects. `POST /projects/{id}/enable` takes the seed terms.
- `GET|POST /projects/{id}/backfill`: status, pause, resume.
- `GET /backlog?project=&limit=`, `POST /backlog/{item}/action` with `{action, value?, scope?, reason?}`.
- `GET /graph`, `GET /nodes/{uuid}`, `POST /nodes/{uuid}/revert`.
- `POST /truth`, `POST /cypher`: the MCP backends.
- `GET /metrics?project=`, `POST /evals/run`.
- `POST /rebuild`: replays the log into the graph.

### 9. Packaging (from the spike)

- **Measured:** `arcadedb-embedded` adds ~130–143 MB on disk (bundled JRE 55 MB plus jars 35 MB) and ~330–430 MB RSS at a 512 MB heap. JVM start is ~3 s cold and ~0.2 s warm. Frozen builds worked on macOS arm64 and Windows (CI windows-2022); dev mode worked on Ubuntu 22.04.
- **`packaging/sidecar.spec`:**
  - add `arcadedb_embedded/jre` and `arcadedb_embedded/jars` as **verbatim datas**, so PyInstaller does not relocate the JRE's dylibs;
  - add `collect_submodules('arcadedb_embedded')`, `collect_submodules('jpype')` and `_jpype`;
  - add `copy_metadata` for both packages;
  - `backports.tarfile` is already present.
- **Notarization blocker:** `lz4-java-*.jar` contains unsigned darwin `.dylib`s. A pre-sign build step strips `net/jpountz/util/darwin/*` from the jar; lz4-java falls back to its pure-Java codec. The same step prunes unused jars (studio, console, graphql, postgresw, redisw, mcp, server where it isn't needed). Verification: `notarytool` passes in the release build.
- **Entitlements:** the existing `entitlements.mac.plist` already grants `allow-jit`, `allow-unsigned-executable-memory` and `disable-library-validation`. No change.
- **Smoke test:** `scripts/smoke-sidecar.py` gains an ontology step: start, create a temp graph, run one Cypher query and one vector query. It runs in every release job (mac, linux, win).
- **pyproject:** a new `ontology` extra (`arcadedb-embedded>=26.10.1,<27`), installed by the release build.

## Delivery milestones

Each milestone gets its own implementation plan. **The first plan covers milestone 1 only.**

1. **Walking skeleton, visible in a dev build.**
   - SQLite store and log; ArcadeDB adapter with projector and rebuild; stable UUIDs for contexts and projects.
   - Scoping and a bulk binding item for Orbit.
   - Extraction and triage for duplicates and rejections only, on ~25 Orbit notes, triggered manually.
   - Plain backlog list; Ontology screen Graph tab using the A6 renderer; markdown projection.
   - Sidecar packaging changes, including the lz4 strip.
   - **Done when** ratified Orbit facts appear in Poltergeist's graph view in `npm run dev`, linked to their artefacts.
2. **Full backfill and backlog.**
   - `ontology-backfill` job with pauses and status; live extraction.
   - Contradiction, equivalence and re-opened items.
   - Ranking, cap, consent bundles, session mode, digest line; τ tuning.
3. **Agents and evals.**
   - `truth`, `cypher` and the grade-labelled `ask`; blocked items; audit.
   - Sealed set, probes, runner and judge; nightly job; Metrics tab.
4. **Contradiction reasoning.**
   - A ratified `SAME_AS` makes conflicting single-valued facts fire automatically on every new candidate or gold change.
   - Revert's "concluded under this rule" query.

## Error handling

- **ArcadeDB fails to start** (missing JRE, lock held, corrupt store): ontology routes return `503 {reason}` and the Ontology screen shows a disabled banner with the reason. Everything else is unaffected. Search never depends on ArcadeDB.
- **Graph lags or is corrupt:** at startup, compare `last_applied_seq` with the log. Catch up if behind, and run a full rebuild on any apply error. A manual "Rebuild" button is in screen settings. The log is never modified by recovery.
- **Lock held by another process** (e.g. a stray dev sidecar): reported as such, with no retries that could fight over the lock.
- **LLM failure or malformed JSON:** one retry with a repair prompt, then the artefact is marked `failed` and the run continues. Five consecutive failures pause the run.
- **Quote validation discards** are logged, never surfaced as items.
- **Artefact deleted or moved:** evidence keeps the artefact ID. A missing artefact shows as a ghost node "source missing". Gold is not auto-reverted.
- **Context/project renamed:** a `relabel` event updates the names. Paths are refreshed by the indexer, and nothing is keyed on them.

## Testing

- **Projector determinism (the key invariant):** for random event sequences, `rebuild()` equals incremental `apply()`, compared node-for-node and edge-for-edge, including `revert` and `relabel`.
- **Store:** the log is append-only (no update or delete paths); candidate state transitions are valid.
- **Triage:** the duplicate, rejection, contradiction, re-opened, equivalence and new cases, with fixed embeddings.
- **Extraction:** quote-must-exist validation, schema rejection, chunking; golden tests on a few synthetic Orbit-like notes with a stubbed provider.
- **Backfill:** each pause condition, idempotency on hash and version, cursor resume after restart.
- **Stable identity:** renaming a context or project leaves every gold node, edge and evidence link intact.
- **API and MCP contract tests:** **gold-only tools cannot return silver** (a seeded pending candidate never appears in `truth` or `cypher` output); `cypher` write statements are rejected.
- **Evals:** the runner with a stub judge, and the metric computations.
- **Desktop:** Vitest for the backlog actions, the graph-mode adapter onto A6 kinds, and the backfill status header.
- **Release:** the smoke-sidecar ontology step on all three OSes, and notarization in the mac release.
- **Sandboxing:** all backend tests set `GHOSTBRAIN_STATE_DIR` / the ontology dir to tmp. Local pytest otherwise clobbers live recorder state.
