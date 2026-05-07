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

# Claude Code project paths → context. Phase 3.
claude_code:
  project_paths:
    # "/Users/jannik/development/sanlam-": sanlam
    # "/Users/jannik/development/codeship-": codeship
    # "/Users/jannik/development/reducedrecipes": reducedrecipes
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
""",
    "90-meta/prompts/router.md": "# Router prompt\n\nDefined in Phase 3 (SPEC §6.1).\n",
    "90-meta/prompts/extractor.md": "# Extractor prompt\n\nDefined in Phase 3 (SPEC §6.2).\n",
    "90-meta/prompts/profile-updater.md": "# Profile updater prompt\n\nDefined in Phase 6 (SPEC §6.3).\n",
    "90-meta/prompts/digest.md": "# Digest prompt\n\nDefined in Phase 5 (SPEC §6.4).\n",
    "90-meta/prompts/classifier.md": "# Classifier prompt\n\nUsed for fine-grained classification. Defined later.\n",
    "80-profile/_index.md": "# Profile index\n\nHand-written in Phase 2.\n",
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
