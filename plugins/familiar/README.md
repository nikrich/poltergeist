# Familiar

A chief of staff for your second brain. Familiar sweeps what changed in your
vault on a schedule, keeps a rolling memory, and writes you a briefing:
recurring themes, open loops ("you told Pieter you'd send the doc — 9 days
ago"), decisions made, contradictions, and blind-spot questions.

Everything it produces is real markdown in your vault under `Familiar/` —
searchable, chat-visible, and yours even if you uninstall the plugin.

## What it does

- **Weekly sweep** (default Monday 07:00, configurable): reads only the notes
  that changed since the last run plus its rolling memory — bounded tokens,
  no full-archive re-reads.
- **Briefing** → `Familiar/briefings/YYYY-MM-DD.md`, rendered in the plugin
  screen with history.
- **Open-loops tracker** → `Familiar/open-loops.md`: commitments with stable
  ids, owed-to, source note, and state. Check off or dismiss loops in the UI;
  your edits always win over the model, and dismissed loops are never
  resurrected.
- **Decisions log** → `Familiar/decisions.md`: append-only, deduplicated.
- **Rolling memory** → `Familiar/memory.md`: how context persists between
  runs without re-reading the archive.
- **Run now** button for on-demand sweeps; failed runs surface their error and
  keep raw output in the plugin's data dir for debugging.

## Settings

Day, hour, model (`haiku`/`sonnet`/`opus`), and the per-run character budget
are configurable in the plugin screen.

## How it works

`main.cjs` polls a due-run check every 15 minutes (missed slots catch up on
next launch). A run assembles the delta via the Poltergeist activity feed,
reads changed notes, and makes one structured-output LLM call through the
app's backend (`POST /v1/llm/run`). Output is validated against a JSON
schema, merged against a fresh read of the trackers (user edits win), and
written back through the notes API. The plugin never touches your vault
files directly — everything goes through the app.

## Install

Poltergeist → Plugins → Install from folder (this directory), or install
from git. Requires the plugin `api.fetch` bridge (Poltergeist ≥ the
`feat/plugin-system` builds of July 2026).
