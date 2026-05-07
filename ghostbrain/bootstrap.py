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
    "github/prs",
    "github/repos",
    "jira/tickets",
    "confluence",
    "slack",
    "gmail",
    "projects",
    "people",
)

# Files written verbatim if missing. Keyed by relative path under vault/.
SEED_FILES: dict[str, str] = {
    "90-meta/routing.yaml": """\
# Routing rules — maps source signals to one of: sanlam, codeship, reducedrecipes, personal.
# Filled in over later phases. TODO(jannik) markers indicate values to provide
# when the relevant connector lands.

version: 1

# GitHub orgs → context. Phase 4.
github:
  orgs:
    # TODO(jannik): "sanlam-org": sanlam
    # TODO(jannik): "codeship-tech": codeship
    # TODO(jannik): "reducedrecipes": reducedrecipes
    {}

# Jira sites → context. Phase 7.
jira:
  sites:
    # TODO(jannik): "sanlam.atlassian.net": sanlam
    # TODO(jannik): "codeship.atlassian.net": codeship
    {}

# Confluence spaces → context. Phase 7.
confluence:
  spaces:
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
    # TODO(jannik): adjust these to your actual development tree.
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
  model: claude-sonnet-4-6
  router_model: claude-haiku-4-5-20251001  # cheap model for routing

worker:
  poll_interval_seconds: 5

profile:
  # Roots scanned by `ghostbrain-claude-md --all`. Each direct child that looks
  # like a project (package.json / pyproject.toml / .git / etc.) gets a
  # CLAUDE.md regenerated.
  project_roots:
    - ~/code
    - ~/development
""",
    "90-meta/prompts/router.md": "# Router prompt\n\nDefined in Phase 3 (SPEC §6.1).\n",
    "90-meta/prompts/extractor.md": "# Extractor prompt\n\nDefined in Phase 3 (SPEC §6.2).\n",
    "90-meta/prompts/profile-updater.md": "# Profile updater prompt\n\nDefined in Phase 6 (SPEC §6.3).\n",
    "90-meta/prompts/digest.md": "# Digest prompt\n\nDefined in Phase 5 (SPEC §6.4).\n",
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
- TODO(jannik): how you want to be presented with options vs decided answers.

## Communication preferences
- TODO(jannik): tone, terseness, what to never do (e.g. "no emoji").

## Workflow
- TODO(jannik): TDD / commit cadence / how PRs should be sized.
""",
    "80-profile/preferences.md": """\
# Preferences

<!-- Hand-write this. -->

## Tools
- TODO(jannik): preferred editor, shell, package managers.

## Languages
- TODO(jannik): which languages and idioms you actually use day-to-day.

## What I don't want
- TODO(jannik): patterns to avoid, words/phrases that grate.
""",
    "80-profile/current-projects.md": """\
# Current projects

<!-- Use H2 headings to separate per-context sections. The generator filters
this file to the H2 matching the project's context. Keep section names
exactly: sanlam / codeship / reducedrecipes / personal. -->

## sanlam
- TODO(jannik): active Sanlam initiatives.

## codeship
- TODO(jannik): active Codeship clients/products.

## reducedrecipes
- TODO(jannik): ReducedRecipes priorities.

## personal
- TODO(jannik): hobby projects, life threads worth context.
""",
    "80-profile/_recent.md": "<!-- Auto-managed by ghostbrain (Phase 6). Do not hand-edit. -->\n",
    "60-dashboards/all.md": "# All contexts dashboard\n\nDataview queries land in Phase 4.\n",
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
