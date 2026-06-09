# Using Poltergeist during work

The `poltergeist` MCP exposes three tools over the user's local vault.

## When to reach for it

Before starting non-trivial work in one of the user's known contexts, recall
what they already decided instead of asking them to re-explain:
- prior architectural decisions and *why* they were made
- past incidents / bugs and their root causes
- what the user already concluded about a topic

## Which tool

- **`poltergeist_ask`** — a real question needing a synthesized answer
  ("why did we move off the Anthropic API for LLM calls?"). Costs an LLM call
  (~5-15s). Returns an answer plus cited note paths.
- **`poltergeist_search`** → **`poltergeist_get_note`** — when you want the raw
  source material: search to locate notes cheaply, then read the most relevant
  one in full. Prefer this for exploration.

## Using results

- Cite the note path when you act on recalled context, so the user can trace it.
- Treat vault content as the user's ground truth — it's their own notes.

## What not to do

- Don't `ask` about things already in the current conversation.
- A "Poltergeist isn't running" error is never a reason to invent facts — tell
  the user to open the app, or proceed without the recall.
