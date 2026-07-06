# Brain constellation — semantic graph view of the vault

**Status:** design · awaiting review
**Date:** 2026-07-06
**Mockup:** `docs/superpowers/mockups/brain-constellation.html` (published Artifact — pan/zoom/hover/click)

## Summary

Replace the placeholder `vault` screen with a living, beautiful map of the vault:
every note is a star, positioned **by meaning** (2-D projection of its embedding), so
notes about the same thing cluster into visible "lobes". Wikilinks and semantic
`related:` neighbours are drawn as synapses. Hovering a star blooms it and its
neighbours; clicking opens the note and its related-by-meaning list. The whole field
drifts, twinkles, and occasionally fires signals along synapses.

The point of difference: layout is **semantic, not arbitrary physics**. It looks like a
brain because it *is* a map of the user's thinking. That leans directly on data
Poltergeist already computes and stores — the embedding index — which no other second-
brain graph view has for free.

## Goals / non-goals

**Goals**
- Delight-first: an ambient, genuinely beautiful portrait of the brain (approved direction "A").
- Navigate for free: click a star → open the note (reuse the existing note-open flow).
- Discover for free: semantic bridges surface non-obvious cross-context connections.
- Scale to a real vault (low thousands of notes) at 60fps.

**Non-goals (YAGNI, this iteration)**
- No editing/creating notes from the graph.
- No 3-D. 2-D projection only.
- No live physics simulation in v1 (see "Approach": physics is an additive follow-on, not v1).
- No timeline/animation-over-time of vault growth.
- No server-side rendering; the graph renders client-side from a JSON payload.

## Approach

Chosen: **A — embedding constellation** (from the three options discussed), structured so
the **C — hybrid** physics-on-hover layer is a small additive follow-on if we want it later.

Why not B (force-directed): physics positions are arbitrary and hairball-prone on a big
vault; they throw away the meaning we already have. We keep light physics as an *optional*
interaction layer on top of the semantic base layout, never as the layout itself.

### Layout is precomputed in Python, not in the browser

The 2-D positions come from projecting the existing `vectors.npz` embedding matrix
(`n_notes × 384`, MiniLM) down to 2-D with **UMAP** (falls back to PCA if `umap-learn`
is unavailable — PCA needs no extra dependency and still clusters acceptably). This runs
as part of the existing `semantic/refresh` pass and is cached to disk. The browser never
does dimensionality reduction; it just renders points. This keeps the renderer simple and
the layout **stable** between sessions (a note doesn't jump around every load).

## Architecture

Three layers, each independently testable:

### 1. Python — projection (extends `ghostbrain/semantic/`)

- New module `ghostbrain/semantic/projection.py`:
  - `project(index: Index) -> dict[str, [x, y]]` — reduce `index.vectors` to 2-D,
    normalise to a stable coordinate box, return path → `[x, y]`.
  - UMAP when importable; PCA (numpy SVD, already a dependency) otherwise. Log which was used.
- Cache: `layout.json` next to `vectors.npz` in `index_dir()`:
  `{ "model_name", "method": "umap"|"pca", "positions": { "<rel_path>": [x, y] } }`.
  Written atomically (same pattern as `index.save`), `chmod 600`.
- Hook into `ghostbrain/semantic/refresh.py`: after embeddings are (re)scored, recompute
  the projection when the vector set changed. Projection is O(n) and cheap relative to
  embedding, so recompute-on-change is fine.

### 2. API — graph endpoint (`ghostbrain/api/`)

- `GET /v1/vault/graph` → `GraphResponse`:
  ```
  {
    nodes: [{ path, title, context, tags, x, y, degree, updated }],
    edges: [{ source, target, weight, kind }],   // kind: "related" | "wikilink"
    regions: [{ id, label, color, count }]
  }
  ```
- Builder (`ghostbrain/api/repo/graph.py`):
  - Nodes: walk the vault (reuse existing note-listing/frontmatter reads), attach `[x, y]`
    from `layout.json`. Notes missing a projection (not yet embedded) are placed with a
    deterministic fallback position and flagged, not dropped.
  - `context` (→ region) derived from the note's vault path / frontmatter, mapped to a
    stable colour. Region colours live in one shared place (see "Shared region palette").
  - Edges:
    - `related`: parse each note's `related:` frontmatter list → weighted edges. Weight
      from the stored similarity if available, else a default.
    - `wikilink`: `parent:` and inline `[[...]]` links → edges with `kind: "wikilink"`.
  - `degree` computed from edge count (drives node size).
- Payload is cache-friendly (ETag/last-built) — a big vault should not rebuild per request.
- Empty/again-empty vault → `{ nodes: [], edges: [], regions: [] }` (renderer shows an
  empty state, never an error).

### 3. Renderer — the constellation (`desktop/src/renderer/`)

- One graphics dependency. **Decision pending** (see Open questions): the mockup proves a
  hand-rolled **Canvas 2D** renderer is enough for the target scale and gives full control
  of the glow/synapse aesthetic with zero deps. Preference is Canvas 2D unless we expect
  >~3–4k nodes, in which case a WebGL lib (sigma.js / regl) is warranted.
- New `useVaultGraph()` hook in `lib/api/hooks.ts` → `GET /v1/vault/graph` via React Query.
- New `components/BrainConstellation.tsx` — the canvas + camera (pan/zoom), render loop,
  hit-testing, hover/selection state. Ports the mockup's proven techniques:
  - additive-blended glow sprites per region colour,
  - **wall-clock-driven** animation (not per-frame accumulation) so it's robust to
    background-tab rAF throttling,
  - `prefers-reduced-motion` freezes drift/twinkle/signals.
- Rewrite `screens/vault.tsx` to host the constellation. Keep the existing "open vault
  folder" action as a secondary control (it's still useful), not the whole screen.
- Interactions:
  - Hover → bloom node + neighbours, floating label, dim the rest.
  - Click → open the note. Reuse the existing note-open path (the same flow other screens
    use to open a `Note` by path) rather than inventing a new one. Show a side panel with
    title, path, excerpt, and the related-by-meaning list (each related item is itself
    clickable → re-focus + open).
  - Region legend → isolate a context.
- Uses existing design tokens (`bg-paper`, `ink-*`, the neon accent) for chrome. The canvas
  itself commits to a dark "mind at night" ground regardless of app theme — a deliberate
  choice, since additive glow requires a dark ground (documented, not an omission).

## Shared region palette

Region → colour must agree between the API (`regions[].color`) and the renderer. Define it
once (Python side, surfaced in the payload) so there's a single source of truth. Mockup
palette: poltergeist `#6EE7A8`, sanlam `#38BDF8`, personal `#A78BFA`, reducedrecipes
`#FBBF24`, codeship `#F472B6`. Contexts beyond these get colours from a deterministic
extended ramp (even lightness, varied hue — same principle as the dataviz palette).

## Data flow

```
semantic/refresh  ──►  vectors.npz + index.json           (existing)
                  ──►  layout.json  (UMAP/PCA 2-D)         (new)
                          │
GET /v1/vault/graph  ◄────┘  + vault frontmatter (related:/parent:/[[..]])
   → GraphResponse (nodes+edges+regions)
          │
useVaultGraph() ──► BrainConstellation.tsx ──► Canvas render + interactions
                                        └─► click ──► existing open-note flow
```

## Error handling / edge cases

- `umap-learn` missing → PCA fallback, logged, `method` recorded in `layout.json` and payload.
- Note embedded but not yet projected (stale layout) → deterministic fallback position + flag.
- Note with no edges → isolated star (still drawn; not culled).
- Vault empty → empty state in the UI, 200 with empty arrays from the API.
- Very large vault → payload cached (ETag); renderer culls off-screen nodes (mockup already does).
- Background-tab throttling → wall-clock animation clock (learned while building the mockup).

## Testing

- **Python:** `projection.py` unit tests (deterministic PCA path: known vectors → stable,
  normalised 2-D box; UMAP path guarded/optional). `graph.py` builder tests: frontmatter
  with `related:`/`parent:`/`[[..]]` → expected nodes/edges/degree; missing-projection
  fallback; empty vault.
- **API:** endpoint test for `GET /v1/vault/graph` shape + empty case + caching header.
- **Renderer:** `useVaultGraph` hook test (mocked fetch); `BrainConstellation` smoke test
  (renders, hit-testing maps a screen point to the right node, click invokes open-note).
  Canvas pixel output isn't asserted; logic is extracted from draw code to be testable.

## Suggested slices (each independently shippable/reviewable)

1. **Projection + cache** — `projection.py`, `layout.json`, wired into `semantic/refresh`,
   with tests. No UI. Verifiable via the CLI + inspecting `layout.json`.
2. **Graph API** — `GET /v1/vault/graph` + builder + shared region palette + tests.
3. **Constellation renderer** — `BrainConstellation.tsx`, `useVaultGraph`, rewrite
   `vault.tsx`, ported from the mockup; hover + click-to-open + region isolate.
4. *(optional follow-on)* **Hybrid physics** — light force layer on hover/drag over the
   semantic base positions (the "C" option). Only if we want more interactivity.

## Open questions for review

1. **Renderer tech:** Canvas 2D (zero-dep, proven in mockup, my recommendation) vs a WebGL
   lib (only if we expect very large vaults). Decision affects slice 3.
2. **Context → region mapping:** derive region purely from vault path, or also honour an
   explicit frontmatter field if present?
3. **Scope of edges in v1:** ship with `related:` (semantic) edges only for a cleaner first
   cut, and add `wikilink` edges in a follow-up? Or both from the start?
4. **Single-theme canvas:** confirm the deliberate always-dark canvas is acceptable given
   the rest of the app defaults to the light "paper" theme.
