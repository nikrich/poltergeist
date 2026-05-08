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
    "github/prs",
    "github/issues",
    "github/repos",
    "jira/tickets",
    "confluence",
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
<!-- Digest prompt. Used by ghostbrain.worker.digest. -->

You are writing a daily digest for a personal knowledge system. The user
reads this once per morning and wants to know what happened yesterday across
their work contexts in under 2 minutes.

Tone:
- Direct. No preamble. No "I hope this helps".
- Plain markdown. No emoji. No marketing voice.
- Per-context sections only when that context had activity. Skip silently
  when empty.
- Short bullets, not paragraphs.

Structure (omit any section that has no content):

```markdown
# Digest — {{day_name}}, {{date}}

## Yesterday at a glance

[1-2 sentences. Lead with the most important thing.]

## Needs your decision

[Only if events landed in needs_review. Skip otherwise.]

## <Context name>

[One section per context with activity. 2-4 bullets max.]

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

# Slack workspaces → context. Phase 9.
slack:
  workspaces:
    {}

# Gmail label/sender prefix → context. Phase 9.
gmail:
  label_prefixes:
    # "sanlam/": sanlam
    {}
  sender_domains:
    # "sanlam.co.za": sanlam
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
""",
    "90-meta/prompts/router.md": _ROUTER_PROMPT,
    "90-meta/prompts/extractor.md": _EXTRACTOR_PROMPT,
    "90-meta/prompts/profile-updater.md": _PROFILE_UPDATER_PROMPT,
    "90-meta/prompts/digest.md": _DIGEST_PROMPT,
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
