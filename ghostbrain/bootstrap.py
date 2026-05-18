"""Idempotent vault bootstrap. Creates the directory tree and seed files
described in SPEC §3.1 and §5.4.

Run via ``python -m ghostbrain.bootstrap`` or ``ghostbrain-bootstrap``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.bootstrap")

CONTEXTS: tuple[str, ...] = ("sanlam", "codeship", "reducedrecipes", "personal")

# Top-level directories under vault/.
TOP_LEVEL_DIRS: tuple[str, ...] = (
    "00-inbox/raw/claude-code",
    "00-inbox/raw/claude-desktop",
    "00-inbox/raw/github",
    "00-inbox/raw/jira",
    "00-inbox/raw/slack",
    "00-inbox/raw/gmail",
    "00-inbox/raw/teams",
    "00-inbox/raw/confluence",
    "00-inbox/raw/calendar",
    "10-daily/by-context",
    "10-daily/weekly",
    "30-cross-context/people",
    "30-cross-context/topics",
    "30-cross-context/decisions",
    "50-team/members",
    "50-team/velocity",
    "60-dashboards",
    "80-profile/_proposed",
    "90-meta/queue/pending",
    "90-meta/queue/processing",
    "90-meta/queue/failed",
    "90-meta/queue/done",
    "90-meta/audit",
    "90-meta/prompts",
)

# Substructure replicated under each 20-contexts/{ctx}/.
CONTEXT_SUBDIRS: tuple[str, ...] = (
    "claude/sessions",
    "claude/artifacts/specs",
    "claude/artifacts/decisions",
    "claude/artifacts/prompts",
    "claude/artifacts/code",
    "claude/artifacts/unresolved",
    "claude/artifacts/action_items",
    "github/prs",
    "github/issues",
    "github/repos",
    "jira/tickets",
    "confluence",
    "calendar",
    "calendar/transcripts",
    "calendar/artifacts/decisions",
    "calendar/artifacts/action_items",
    "calendar/artifacts/unresolved",
    "calendar/artifacts/specs",
    "slack",
    "gmail",
    "projects",
    "people",
)

# Prompt content. Edit `vault/90-meta/prompts/*.md` after bootstrap to tune
# behavior — these are seeds, not the live source of truth at runtime.
_ROUTER_PROMPT = """\
<!-- Router prompt. Used by ghostbrain.worker.router for events that don't
match a fast path-based rule. -->

RESPOND WITH JSON ONLY. NO PROSE. NO MARKDOWN FENCES. NO PREAMBLE.

You are a routing classifier for a personal knowledge system.

Available contexts: sanlam, codeship, reducedrecipes, personal — see
`routing.yaml` and `20-contexts/<ctx>/_profile.md` for what each covers.

Decide which context the content below belongs to. Be conservative — if
signals point in multiple directions, return `needs_review`.

Your entire response must be a single JSON object exactly matching:

`{"context": "...", "confidence": 0.0, "reasoning": "...", "secondary_contexts": []}`

`context` ∈ `{sanlam, codeship, reducedrecipes, personal, needs_review}`.
`confidence` ∈ [0, 1]. Return `needs_review` when confidence < 0.7.

Content to classify:
{{content}}
"""

_EXTRACTOR_PROMPT = """\
<!-- Extractor prompt. Used by ghostbrain.worker.extractor on every Claude
session note. -->

RESPOND WITH JSON ONLY. NO PROSE. NO MARKDOWN FENCES. NO PREAMBLE.
Your entire response must be a single JSON object of the form:
`{"items": [...]}` where `items` is an array (possibly empty: `{"items": []}`).

Extract any of the following that are clearly present and durable.
**Be conservative** — it is correct to return `[]` for short, exploratory,
or chatty sessions.

Categories:
1. `spec` — formal specifications, requirements, design docs.
2. `decision` — explicit decisions with stated reasoning.
3. `code` — non-trivial code blocks (>20 lines) worth saving.
4. `prompt` — prompts/templates that worked and could be reused.
5. `unresolved` — open questions, blockers, "to figure out later".

Do NOT extract: generic facts, questions answered inline, tool-call output,
or text that was rewritten/discarded later in the session.

Output shape:
`{"items": [{"type": "...", "title": "...", "content": "...", "tags": []}, ...]}`

`type` is one of the five above. `title` ≤ 12 words.
`content` is the full markdown content. `tags` is an array of strings.

Return `{"items": []}` if nothing meaningful is present.

Conversation excerpt:
{{content}}
"""

_REVERSAL_CHECK_PROMPT = """\
<!-- Reversal-check prompt. Used by ghostbrain.worker.reversal after a new
decision artifact is written. -->

RESPOND WITH JSON ONLY. NO PROSE. NO MARKDOWN FENCES. NO PREAMBLE.
Your entire response must be a single JSON object exactly matching:
`{"reversals": [{"contradicts_id": "...", "reasoning": "..."}, ...]}`
Use `{"reversals": []}` when nothing contradicts — empty is the right
answer most of the time.

You're given a NEW decision and a list of EARLIER decisions from the
same context. Identify only earlier decisions that the new one
**directly reverses or contradicts**. Be conservative.

A reversal looks like:
- "do X" while earlier said "do not X" or "do Y instead of X" on the
  same subject.
- The new decision rescinds/abandons something previously committed.
- A different option chosen from the same set as an earlier decision.

A reversal does NOT look like:
- Refinement or follow-on work that builds on the earlier decision.
- Adjacent decisions on different subject matter.
- Course-corrections that don't actually change the prior decision.
- Any case where you'd need to invent justification.

`reasoning` is one sentence quoting/paraphrasing the conflict.
`contradicts_id` must match an ID from the candidates — never invent.

NEW decision:
title: {{new_title}}

{{new_body}}

EARLIER decisions in this context:

{{candidates}}
"""


_GMAIL_RELEVANCE_PROMPT = """\
<!-- Gmail relevance gate. Used by ghostbrain.connectors.gmail to decide
whether a thread should be ingested into the vault. Anything the gate
rejects is dropped silently — it never lands in the inbox. -->

RESPOND WITH JSON ONLY. NO PROSE. NO MARKDOWN FENCES. NO PREAMBLE.
Your entire response must be a single JSON object exactly matching:
`{"relevant": true|false, "reason": "<one short sentence>"}`

You are gating which emails enter a personal knowledge system for a
software engineer working across these contexts:

- **sanlam** — Sanlam Digital (financial services, ASCP, claims, RBAC,
  policy admin, funeral product, Confluence specs, Jira tickets,
  capstone team, regulatory work).
- **codeship** — codeship.tech client services and Codeship's own
  product work (multiple clients, AI infra, contract delivery).
- **reducedrecipes** — ReducedRecipes app/site (recipes, social
  publishing, Cloudflare).
- **personal** — personal projects (HungryGhost, Slenderware,
  IndieGlue, Greenlight, hobby code, real-life logistics that need
  follow-up).

Mark `relevant: true` ONLY when the thread is plausibly worth surfacing
in a daily digest of work + life follow-ups.

NOT relevant (set `relevant: false`):
- Marketing emails, newsletters, mass promotions, sales pitches.
- Generic digests (Quora, Medium stats, ProductHunt, daily.dev,
  LinkedIn job alerts, Splice, Humble Bundle).
- Service emails already covered by another connector (GitHub PR
  notifications, Calendar event reminders, npm token housekeeping).
- Routine billing statements ("your invoice is ready", usage recaps).
- Anything you'd normally archive without reading.

Be conservative on dropping but decisive on noise: when in real doubt,
prefer `relevant: true` so signal is never silently swallowed. The
user can always tighten the denylist after reviewing.

`reason` is one short sentence (≤ 120 chars) the user can read in the
audit log to understand the decision.

Email to evaluate:

{{content}}
"""


_WEEKLY_DIGEST_PROMPT = """\
<!-- Weekly digest prompt. Used by ghostbrain.worker.weekly_digest. The
output is a markdown document written to vault/10-daily/weekly/<week>.md
verbatim. -->

You are writing a weekly review for the user of a personal knowledge
system. The user reads this once a week (Sunday morning) and wants a
strategic view: what's drifting, what's recurring, who needs unblocking
— patterns that don't show up in any single daily digest.

Tone:
- Direct. No preamble. No "I hope this helps". No "Here's your weekly".
- Plain markdown. No emoji. No marketing voice.
- Bullets, not paragraphs. Each bullet is one observation.
- Skip sections silently when empty.
- Aim for ~25 lines of content. The user re-reads this; brevity matters.

## Wikilinks — IMPORTANT

The input below renders many items as `<title> -> [[vault/path|alias]]`.
Copy each wikilink VERBATIM. Keep the `[[path|alias]]` form exactly.
Each bullet that references a specific decision, artifact, or stale
item must end with its wikilink so the user can click through to the
source note. Never invent a link.

Structure (omit any section that has no content):

```markdown
# Week {{week_label}} — {{week_start}} -> {{week_end}}

## At a glance

[2-3 sentences. Lead with the single most important pattern of the
week. If nothing meaningful happened, say "Quiet week." in one line.]

## Decisions made

[Every decision artifact captured this week, grouped by context. Each
bullet ends with its `[[wikilink]]`.]

## Action items still open

[Action-item artifacts. Lead with owner if named. Each ends with the
`[[wikilink]]`.]

## Risks not moving

[`unresolved` artifacts that aged >=3 days or appeared in multiple
daily digests.]

## Recurring themes

[Cross-context threads — a topic in 2+ contexts, or a person in 2+
days. Skip if nothing recurs.]

## People to follow up with

[From "Check-in suggestions" only. "<name> -- last activity <date> --
<reason>".]

## Where you appear unexpectedly

[From "Unexpected references this week" only. Group by name; lead
with [CROSS] items. One bullet per reference, ending with the
`[[wikilink]]`.]

## Quiet this week

[From "Quiet contexts" only. One nudge line.]

## System health

[One line: "N events processed across <day_count> days. By source:
<src: count, ...>."]
```

Be conservative — if the week was quiet, say so in one line and stop.

This week's data:

{{events}}
"""


_TRANSCRIPT_EXTRACTOR_PROMPT = """\
<!-- Transcript extractor prompt. Used by ghostbrain.recorder.linker after a
meeting transcript is written to <ctx>/calendar/transcripts/. Tuned for
spoken meeting content, not written sessions. -->

RESPOND WITH JSON ONLY. NO PROSE. NO MARKDOWN FENCES. NO PREAMBLE.
Your entire response must be a single JSON object of the form:
`{"items": [...]}` where `items` is an array (possibly empty: `{"items": []}`).

You are reading a raw automatic transcript of a real meeting. Speakers are
not labelled. Audio is imperfect — expect homophones, broken sentences,
filler words, and tangents. Be **conservative**: only surface things that
are clearly stated, not inferred.

Categories to extract (in priority order):

1. `decision` — an explicit decision the group reached, with the stated
   reason if present. Phrases like "we'll go with X", "let's use Y",
   "agreed, we're not doing Z". Skip vague leanings.

2. `action_item` — a concrete commitment to do something. Capture the
   owner if named, the action, and a deadline if stated. Phrases like
   "I'll send the spec by Friday", "Alex will follow up with legal",
   "we need to update the dashboard before launch". Skip generic
   intent ("we should think about X") unless an owner accepted it.

3. `unresolved` — open questions or blockers raised but not resolved
   in the meeting. "We still don't know how X handles Y", "depends on
   when finance signs off". Capture enough context that a future reader
   understands what's blocking what.

4. `spec` — only when the meeting walked through a real specification
   (architecture review, API contract, requirements doc). Most meetings
   have none. Default to skipping.

Do NOT extract: small talk, status updates already in tickets, repeated
restatements, tangents abandoned mid-sentence, or anything the audio is
too garbled to quote with confidence.

Output shape:
`{"items": [{"type": "...", "title": "...", "content": "...", "tags": []}, ...]}`

`title` ≤ 12 words, written in the user's voice (e.g.
"Decision: ditch SIMI integration for MVP"). For action_item, include
the owner in the title when known: "Alex: send updated RBAC spec to legal".
`content` is full markdown — quote the relevant phrasing from the
transcript when it sharpens the artifact, then add one line of context
naming the meeting topic and any constraint mentioned.
`tags` is an array of short strings — use them for cross-meeting threads
(e.g. ["rbac", "compliance"]).

Return `{"items": []}` for short, low-signal, or chatty meetings. Empty is
the right answer most of the time.

Transcript:
{{content}}
"""

_PROFILE_UPDATER_PROMPT = """\
<!-- Profile updater prompt. Used by ghostbrain.profile.diff per Claude
session. Output is a JSON object envelope wrapping an array of proposed
diffs. -->

RESPOND WITH JSON ONLY. NO PROSE. NO MARKDOWN FENCES. NO PREAMBLE.
Your entire response must be a single JSON object of the form:
`{"diffs": [...]}` — possibly empty: `{"diffs": []}`.

You are maintaining a profile of the user. Read the conversation excerpt
below and propose profile changes ONLY for facts you are confident about.
**Be conservative.** Single offhand mentions are NOT confident updates.

Fields: `current-projects` (auto-applied), `preferences`/`working-style`
(stable, manual review), `people`, `decisions`.

Operations: `add`, `update`, `contradict`.

## Current profile

{{profile}}

## Conversation excerpt

{{conversation}}

Output:

```
{"diffs": [
  {
    "field": "...", "operation": "...",
    "before": "...", "after": "...",
    "evidence": "exact short quote", "confidence": 0.0
  }
]}
```

Return `{"diffs": []}` whenever the conversation is exploratory or
doesn't surface durable profile facts. Empty is the right answer most
of the time.
"""

_DIGEST_PROMPT = """\
<!-- Digest prompt. Used by ghostbrain.worker.digest. The output is a
markdown document written to vault/10-daily/YYYY-MM-DD.md verbatim. -->

You are writing a daily digest for the user of a personal knowledge system.
The user reads this once per morning. They want to know what happened
yesterday across their work contexts in under 2 minutes.

Tone:
- Direct. No preamble. No "I hope this helps". No "Here's your digest".
- Plain markdown. No emoji. No marketing voice.
- Per-context sections only when that context had activity. Skip silently
  when empty.
- Short bullets, not paragraphs. The user reads diffs, not prose.

## Wikilinks — IMPORTANT

The input below renders many items as `<title> -> [[vault/path|alias]]`.
The `|alias` portion is what Obsidian renders to the user — it keeps the
bullet visually compact while the long path resolves the link reliably.

**Copy each wikilink VERBATIM into your output.** Keep the `[[path|alias]]`
form exactly — do not drop the `|alias` segment, do not rewrite the path,
do not invent new links. If you're not sure which link applies, omit the
link rather than guessing.

Two specific rules:
- For "Needs your decision", emit one bullet per review item formatted
  as `- [[path|alias]] (source, confidence)` — no event_id in the bullet.
- For per-context bullets, when summarising N items into one line, pick
  the most representative wikilink and append it after the bullet text.
  Don't list every link inline; the goal is one click-through per
  thought.

Structure (omit any section that has no content):

```markdown
# Digest — {{day_name}}, {{date}}

## Yesterday at a glance

[1-2 sentences. Lead with the most important thing.]

## Needs your decision

[Only if review queue items appear in input. One bullet per item, each
with its `[[wikilink]]`. Skip section if empty.]

## Today

[Render only when "Today's calendar" appears in input. List meetings
chronologically: "HH:MM-HH:MM Title (context)" per bullet. Skip if no
calendar data.]

## Anticipated

[Render only when "Anticipated absences" appears in input. One soft
nudge bullet per absent context that's usually active on this
weekday. Skip if empty.]

## <Context name>

[One section per context with activity. 2-4 bullets max. Each bullet
ends with the most relevant `[[wikilink]]`.

If "Meeting transcripts captured" appears in input for this context,
surface them as "<title> transcribed (N min) -> [[wikilink]]". One
bullet per transcript max.

If "Transcript-derived artifacts" appears for this context, group them
by type and link the highest-signal one. Action items deserve their
own bullet — call out owners by name where stated.]

## Needs you

[Render only when "Stale items" appears in input. Surface stale PRs
and tickets that need attention, each with its `[[wikilink]]`. Group
by kind. Skip if empty.]

## Check-ins suggested

[Render only when "Check-in suggestions" appears in input. Format:
"worth a check-in with <person> because <reason>". Skip if empty.]

## System health

[One line.]
```

Be conservative — a 6-line digest is better than a 20-line digest padded
with filler.

Yesterday's data:

{{events}}
"""

_ALL_DASHBOARD = """\
# All contexts — dashboard

Cross-context view of recent activity. Requires the Dataview plugin.

## Open PRs

```dataview
TABLE WITHOUT ID
  link(file.path, default(title, file.name)) AS PR,
  context,
  metadata.repo AS Repo,
  metadata.origin AS Origin,
  ingestedAt AS "Captured"
FROM "20-contexts"
WHERE type = "pr"
  AND (metadata.state = "OPEN" OR metadata.state = null)
SORT ingestedAt DESC
LIMIT 25
```

## Recent Claude Code sessions

```dataview
TABLE WITHOUT ID
  link(file.path, default(title, file.name)) AS Session,
  context,
  routingMethod AS Routed,
  ingestedAt AS "Captured"
FROM "20-contexts"
WHERE source = "claude-code" AND type = "session"
SORT ingestedAt DESC
LIMIT 15
```

## Anything routed to needs_review

```dataview
TABLE WITHOUT ID
  link(file.path, default(title, file.name)) AS Note,
  source,
  routingReasoning AS Why
FROM "00-inbox"
WHERE context = "needs_review"
SORT ingestedAt DESC
```
"""

# Files written verbatim if missing. Keyed by relative path under vault/.
SEED_FILES: dict[str, str] = {
    "90-meta/routing.yaml": """\
# Routing rules — maps source signals to one of: sanlam, codeship, reducedrecipes, personal.
# Filled in over later phases. TODO markers indicate values to provide
# when the relevant connector lands.

version: 1

# GitHub orgs → context. Phase 4.
github:
  orgs:
    # TODO: "sanlam-org": sanlam
    # TODO: "codeship-tech": codeship
    # TODO: "reducedrecipes": reducedrecipes
    {}

# Jira sites → context. Used by the router for path-first routing of
# Jira events, and by the Jira connector to know which sites to fetch.
jira:
  sites:
    # TODO: "your-site.atlassian.net": your-context
    {}

# Confluence sites + spaces → context. Confluence shares Atlassian site
# auth with Jira; you typically only need to add the same site once per
# product. Space keys are short codes from page URLs.
confluence:
  sites:
    # TODO: "your-site.atlassian.net": your-context
    {}
  spaces:
    # TODO: e.g. "ASCP": sanlam
    {}

# Slack workspaces → context. The connector polls each workspace for
# @-mentions over the configured lookback window and routes them
# straight to the listed context (workspace slug = strongest signal).
# Required user-token scopes: search:read, users:read, team:read,
# channels:history, groups:history, im:history, mpim:history.
# Save tokens via `ghostbrain-slack-token-add <slug> <xoxp-token>`.
slack:
  workspaces:
    # Example:
    #   sft:
    #     context: sanlam
    #     lookback_hours: 24
    #     mentions_only: true
    #   codeship:
    #     context: codeship
    {}

# Gmail accounts + routing. The connector polls each account in
# `gmail.accounts`; threads are filtered by:
#   1. `denylist_domains` — drop matching senders before any cost.
#   2. `relevance_gate` — LLM (Haiku) drops everything that isn't
#      worth surfacing for the user's contexts.
# Surviving threads are then routed using `sender_domains` (strongest
# signal) or `label_prefixes` (fallback).
gmail:
  accounts:
    # TODO: add Gmail accounts you want to ingest. Run
    # `ghostbrain-gmail-auth <email>` once per account to authorize.
    # Example:
    #   jannik@example.com:
    #     monitored_labels: ["sanlam/policies", "codeship"]
    #     unread_lookback_hours: 24
    {}
  # Drop these senders entirely before they reach the LLM gate.
  # Supports exact (`humblebundle.com`) and subdomain (`*.humblebundle.com`).
  denylist_domains: []
  # Toggle the LLM relevance gate (Haiku). Set false to disable; the
  # denylist still applies.
  relevance_gate: true
  label_prefixes:
    # "sanlam/": sanlam
    {}
  sender_domains:
    # "sanlam.co.za": sanlam
    {}

# Joplin notebooks → context. The connector polls the Joplin Data API
# exposed by the desktop app's Web Clipper service. Enable in Joplin:
# Tools → Options → Web Clipper → "Enable Web Clipper Service", then
# paste the auth token below.
#   - `notebooks` empty = ingest every notebook (router falls back to LLM).
#   - non-empty = allowlist + fast-route table (notes outside listed
#     notebooks are skipped at fetch time, no LLM cost).
joplin:
  # TODO: paste the token from Joplin's Web Clipper settings.
  token: ""
  # host: "http://localhost:41184"  # uncomment if you moved the port
  notebooks:
    # Example:
    #   Sanlam: sanlam
    #   Codeship: codeship
    #   Personal: personal
    {}

# Calendar accounts → context. One block per provider.
calendar:
  google:
    accounts:
      # TODO: "you@gmail.com": personal
      # TODO: "you@workspace.com": work
      {}

# Claude Code project paths → context. Longest-prefix match wins.
# Used by ghostbrain.profile.claude_md to pick the right context profile.
claude_code:
  project_paths:
    # TODO: adjust these to your actual development tree.
    # Examples:
    # "~/development/sft-capstone-hive": sanlam
    # "~/development/sanlam-digisure": sanlam
    # "~/development/nikrich": codeship
    # "~/development/reducedrecipes": reducedrecipes
    {}

# Fallback when no rule matches. Worker sends low-confidence events to review queue.
default: needs_review
""",
    "90-meta/config.yaml": """\
# Pipeline thresholds. See SPEC §5.4.

thresholds:
  auto_route: 0.85          # below this, goes to review queue
  auto_apply_profile: 0.90  # below this, profile diff stays proposed
  flag_for_review: 0.70
  reject_below: 0.50        # below this, drop the event

llm:
  # Aliases (`haiku`, `sonnet`, `opus`) are passed to `claude -p --model`.
  router_model: haiku       # frequent + classification
  extractor_model: opus     # once/session — quality matters
  digest_model: opus        # once/day — voice + synthesis matter
  profile_model: opus       # confidence judgement on profile diffs

worker:
  poll_interval_seconds: 5
  # routing_mode: review_only | live
  # review_only writes events to 00-inbox/raw only and audit-logs the
  # routing decision; nothing lands under 20-contexts/<ctx>/. Flip to
  # `live` after ~2 weeks of audit-log review.
  routing_mode: review_only

profile:
  # Roots scanned by `ghostbrain-claude-md --all`. Each direct child that looks
  # like a project (package.json / pyproject.toml / .git / etc.) gets a
  # CLAUDE.md regenerated.
  project_roots:
    - ~/code
    - ~/development

# Inverse search (Phase 13 strength feature). Surfaces unexpected
# mentions of watched names in the weekly digest. Each entry is a
# name key and the phrases the matcher should look for; optional
# expected_contexts narrows where a mention is "expected" so cross-
# context surfacings get flagged separately.
inverse_search:
  watched_names: {}
  # Example:
  #   jannik811:
  #     - jannik
  #     - jannik richter
  #     - jr
  expected_contexts: {}
  # Example:
  #   jannik811: [sanlam, codeship, personal]
  lookback_days: 7

# Autonomous meeting recorder (Phase 12). Watches Apple Calendar, records
# eligible meetings via BlackHole + mic, transcribes with whisper.cpp,
# links transcripts to calendar event notes.
recorder:
  enabled: true
  poll_interval_seconds: 30
  end_grace_seconds: 60
  audio_device: "Ghost Brain"
  excluded_titles:
    - Focus
    - focus
  excluded_contexts: []
  included_contexts: []
""",
    "90-meta/prompts/router.md": _ROUTER_PROMPT,
    "90-meta/prompts/extractor.md": _EXTRACTOR_PROMPT,
    "90-meta/prompts/transcript-extractor.md": _TRANSCRIPT_EXTRACTOR_PROMPT,
    "90-meta/prompts/gmail-relevance.md": _GMAIL_RELEVANCE_PROMPT,
    "90-meta/prompts/reversal-check.md": _REVERSAL_CHECK_PROMPT,
    "90-meta/prompts/profile-updater.md": _PROFILE_UPDATER_PROMPT,
    "90-meta/prompts/digest.md": _DIGEST_PROMPT,
    "90-meta/prompts/weekly-digest.md": _WEEKLY_DIGEST_PROMPT,
    "90-meta/prompts/classifier.md": "# Classifier prompt\n\nUsed for fine-grained classification. Defined later.\n",
    "80-profile/_index.md": """\
# Profile index

The profile layer is the source of truth for who the user is, how they work,
and what they're working on. The CLAUDE.md generator stitches these files
together per project so every Claude Code session starts with this context.

Files:
- `working-style.md` — how decisions get made, communication style.
- `preferences.md` — tools, languages, formatting, what NOT to do.
- `current-projects.md` — active work, organized by H2 sections per context
  (`## sanlam`, `## codeship`, `## reducedrecipes`, `## personal`). The
  generator filters this to the matching context for each project.
- `_recent.md` — short-lived layer maintained by the daily worker (Phase 6).
- `_proposed/YYYY-MM-DD.jsonl` — auto-detected diffs awaiting review.

Edit working-style / preferences / current-projects by hand. The other two
files are managed by ghostbrain.
""",
    "80-profile/working-style.md": """\
# Working style

<!-- Hand-write this. Replace placeholders below. -->

## Decision style
- TODO: how you want to be presented with options vs decided answers.

## Communication preferences
- TODO: tone, terseness, what to never do (e.g. "no emoji").

## Workflow
- TODO: TDD / commit cadence / how PRs should be sized.
""",
    "80-profile/preferences.md": """\
# Preferences

<!-- Hand-write this. -->

## Tools
- TODO: preferred editor, shell, package managers.

## Languages
- TODO: which languages and idioms you actually use day-to-day.

## What I don't want
- TODO: patterns to avoid, words/phrases that grate.
""",
    "80-profile/current-projects.md": """\
# Current projects

<!-- Use H2 headings to separate per-context sections. The generator filters
this file to the H2 matching the project's context. Keep section names
exactly: sanlam / codeship / reducedrecipes / personal. -->

## sanlam
- TODO: active Sanlam initiatives.

## codeship
- TODO: active Codeship clients/products.

## reducedrecipes
- TODO: ReducedRecipes priorities.

## personal
- TODO: hobby projects, life threads worth context.
""",
    "80-profile/_recent.md": "<!-- Auto-managed by ghostbrain (Phase 6). Do not hand-edit. -->\n",
    "60-dashboards/all.md": _ALL_DASHBOARD,
}


def bootstrap(root: Path | None = None) -> Path:
    """Create the vault tree and seed files. Idempotent.

    Returns the resolved vault root.
    """
    root = (root or vault_path()).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    for rel in TOP_LEVEL_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)

    for ctx in CONTEXTS:
        ctx_root = root / "20-contexts" / ctx
        ctx_root.mkdir(parents=True, exist_ok=True)
        for sub in CONTEXT_SUBDIRS:
            (ctx_root / sub).mkdir(parents=True, exist_ok=True)
        # Per-context index + profile stubs.
        _write_if_absent(ctx_root / "_index.md", f"# {ctx.title()} context\n")
        _write_if_absent(
            ctx_root / "_profile.md",
            f"# {ctx.title()} profile\n\nContext-specific profile, populated in Phase 6.\n",
        )

    # Per-context daily digest folder gets a placeholder so Obsidian shows it.
    (root / "10-daily" / "by-context").mkdir(parents=True, exist_ok=True)

    for rel, body in SEED_FILES.items():
        _write_if_absent(root / rel, body)

    log.info("Vault ready at %s", root)
    return root


def _write_if_absent(path: Path, body: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = bootstrap()
    print(f"Vault bootstrapped at: {root}")


if __name__ == "__main__":
    main()
