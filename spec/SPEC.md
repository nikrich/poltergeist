# Second Brain System — Build Spec

**Version:** 1.0
**Owner:** Jannik (jannik@codeship.tech)
**Target:** macOS, Python 3.11+, Obsidian
**License:** MIT (intended open source)
**Status:** Ready to build

---

## Read This First (Claude Code)

This document specifies a complete personal knowledge automation system. It is designed to be built **incrementally** over multiple Claude Code sessions, following the phased build sequence in **Section 9**.

**Your starting point:**

1. Read this entire spec end-to-end before writing any code.
2. Confirm the environment is correct: macOS, Python 3.11+, Node.js 20+, Obsidian installed, Anthropic API key in env.
3. Begin with **Phase 1 (Foundation)** in Section 9. Do not skip ahead.
4. Each phase has explicit **Acceptance Criteria**. Do not move to the next phase until current phase passes its criteria.
5. After every phase, commit to git with the phase name in the commit message.

**Conventions used in this doc:**

- File paths starting with `vault/` refer to the Obsidian vault root.
- File paths starting with `secondbrain/` refer to the source code repo root.
- Code blocks marked `# stub` are scaffolding; replace with real implementation.
- `TODO(jannik)` markers indicate places where Jannik must provide values (org IDs, paths, etc.).

**Important constraints:**

- Sanlam compliance is **out of scope** — Jannik confirmed everything runs locally on his machine. Do not add extra encryption layers or compliance gates beyond what is specified.
- The system runs only on Jannik's local machine. No cloud deployment.
- Open source readiness is a **goal, not a phase 1 requirement**. Build it cleanly, package it last.
- Aim for portability (macOS first, Linux later) but don't over-engineer for Linux until macOS works end-to-end.

---

## Section 1 — Goals and Non-Goals

### 1.1 Goals

A second brain that:

- **Captures everything** Jannik does in Claude Code, Claude desktop, GitHub, Jira, Confluence, Slack, Gmail, Teams, Calendar — automatically.
- **Routes content to context** (Sanlam, Codeship, ReducedRecipes, Personal) with high accuracy.
- **Learns Jannik's working style** by maintaining an evolving profile that future Claude sessions automatically load.
- **Surfaces what matters** through a daily digest and Obsidian dashboards.
- **Operates invisibly** — no manual triggers required after setup. Trust through observability (audit logs), not approval flows.
- **Extensible** via a connector pattern so new sources (Linear, Notion, etc.) can be added without core changes.

### 1.2 Non-Goals

- Real-time Claude desktop conversation capture (impossible without browser extensions or ToS violations — accept hourly polling lag).
- Multi-user / team-shared vault (single user only for v1).
- Cloud deployment (local-only).
- Mobile app (Obsidian mobile reads the synced vault, that's enough).
- Performance evaluation metrics for individuals (descriptive flow metrics only — never use for performance reviews).

---

## Section 2 — System Overview

```
┌──────────────────────────────────────────────────────────────┐
│                          Sources                              │
│  Claude Code  Claude Desktop  GitHub  Jira  Confluence       │
│  Slack  Gmail  Teams  Calendar  Obsidian                     │
└────────────┬─────────────────────────────────────────────────┘
             │ (connectors normalize to standard event shape)
             ▼
┌──────────────────────────────────────────────────────────────┐
│                    Filesystem Queue                           │
│   90-meta/queue/{pending,processing,failed,done}             │
└────────────┬─────────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────┐
│                     Worker Pipeline                           │
│  1. Context routing  →  2. Note generation                   │
│  3. Artifact extraction (Claude sessions only)               │
│  4. Profile diff (Claude sessions only)                      │
│  5. Backlinking  →  6. Audit log                            │
└────────────┬─────────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────┐
│                       Obsidian Vault                          │
│  20-contexts/{ctx}/{source}/  — raw notes per source         │
│  10-daily/  — daily digests                                  │
│  60-dashboards/  — Dataview queries                          │
│  80-profile/  — evolving Jannik profile                      │
└──────────────────────────────────────────────────────────────┘
```

**Key flow:** Connectors run on schedule (or on file events for Claude Code). They drop normalized events into `pending/`. The worker picks them up, processes through the pipeline, writes to the vault. The daily digest job reads vault state at 06:30, generates digest, writes to `10-daily/`.

---

## Section 3 — Vault Structure

### 3.1 Directory Layout

Create this structure in the Obsidian vault on first run:

```
vault/
├── 00-inbox/raw/
│   ├── claude-code/
│   ├── claude-desktop/
│   ├── github/
│   ├── jira/
│   ├── slack/
│   ├── gmail/
│   ├── teams/
│   ├── confluence/
│   └── calendar/
├── 10-daily/
│   ├── YYYY-MM-DD.md
│   └── by-context/
│       ├── sanlam-YYYY-MM-DD.md
│       ├── codeship-YYYY-MM-DD.md
│       ├── reducedrecipes-YYYY-MM-DD.md
│       └── personal-YYYY-MM-DD.md
├── 20-contexts/
│   ├── sanlam/
│   ├── codeship/
│   ├── reducedrecipes/
│   └── personal/
├── 30-cross-context/
│   ├── people/
│   ├── topics/
│   └── decisions/
├── 50-team/
│   ├── members/
│   ├── velocity/
│   └── _pulse.md
├── 60-dashboards/
│   ├── all.md
│   ├── sanlam.md
│   ├── codeship.md
│   ├── reducedrecipes.md
│   ├── personal.md
│   └── team-pulse.md
├── 80-profile/
│   ├── _index.md
│   ├── working-style.md
│   ├── preferences.md
│   ├── current-projects.md
│   ├── people.md
│   ├── decisions.md
│   ├── _recent.md
│   └── _proposed/
│       └── YYYY-MM-DD.jsonl
└── 90-meta/
    ├── routing.yaml
    ├── config.yaml
    ├── queue/
    │   ├── pending/
    │   ├── processing/
    │   ├── failed/
    │   └── done/
    ├── audit/
    │   └── YYYY-MM-DD.jsonl
    └── prompts/
        ├── router.md
        ├── extractor.md
        ├── profile-updater.md
        ├── digest.md
        └── classifier.md
```

Each context folder (`20-contexts/{ctx}/`) has the same substructure:

```
{context}/
├── _index.md
├── _profile.md
├── claude/
│   ├── sessions/
│   └── artifacts/
│       ├── specs/
│       ├── decisions/
│       ├── prompts/
│       └── code/
├── github/
│   ├── prs/
│   └── repos/
├── jira/
│   └── tickets/
├── confluence/
├── slack/
├── gmail/
├── projects/
└── people/
```

### 3.2 Frontmatter Schema

Every note has YAML frontmatter following this schema:

```yaml
---
# Required
id: <uuid>
context: sanlam | codeship | reducedrecipes | personal | cross
type: session | pr | issue | ticket | page | decision | artifact | person | project | message | email

# Source
source: claude-code | claude-desktop | github | jira | slack | gmail | teams | confluence | calendar | manual
sourceId: <original-id>
sourceUrl: <url-if-applicable>

# Time
created: 2026-05-06T14:23:11Z
updated: 2026-05-06T14:23:11Z
ingestedAt: 2026-05-06T14:25:00Z

# Classification
status: open | closed | resolved | in-progress | archived | none
priority: none | low | medium | high
people: ["[[30-cross-context/people/name]]"]

# Routing metadata
routingConfidence: 0.0-1.0
classifierFlags: []

# Optional
tags: []
project: "[[link-to-project]]"
parent: "[[link-to-parent]]"
---
```

The `context` field drives every Dataview query. Always populate it.

---

## Section 4 — Connector Architecture

### 4.1 Base Interface

```python
# secondbrain/connectors/_base.py

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any
import json
import uuid

class Connector(ABC):
    """Base class for all data source connectors."""

    name: str  # e.g., "github" — set in subclass
    version: str = "1.0"

    def __init__(self, config: dict, queue_dir: Path, state_dir: Path):
        self.config = config
        self.queue_dir = queue_dir
        self.state_dir = state_dir

    @abstractmethod
    def fetch(self, since: datetime) -> list[dict]:
        """Fetch raw events from source since timestamp."""

    @abstractmethod
    def normalize(self, raw: dict) -> dict:
        """Convert source-specific data to standard event shape."""

    @abstractmethod
    def health_check(self) -> bool:
        """Verify connector can reach source. Used by digest's system health."""

    def run(self) -> int:
        """Standard run loop. Returns count of events queued."""
        since = self._get_last_run()
        raw_events = self.fetch(since)
        for raw in raw_events:
            event = self.normalize(raw)
            self._enqueue(event)
        self._save_last_run()
        return len(raw_events)

    def _enqueue(self, event: dict) -> None:
        event_id = event.get("id") or str(uuid.uuid4())
        path = self.queue_dir / "pending" / f"{event['timestamp']}-{self.name}-{event_id}.json"
        path.write_text(json.dumps(event, indent=2))

    def _get_last_run(self) -> datetime:
        state_file = self.state_dir / f"{self.name}.last_run"
        if state_file.exists():
            return datetime.fromisoformat(state_file.read_text().strip())
        return datetime.fromtimestamp(0)

    def _save_last_run(self) -> None:
        state_file = self.state_dir / f"{self.name}.last_run"
        state_file.write_text(datetime.utcnow().isoformat())
```

### 4.2 Standard Event Shape

All connectors emit events in this shape:

```json
{
  "id": "uuid",
  "source": "github",
  "type": "pr",
  "subtype": "opened|merged|reviewed|commented",
  "timestamp": "2026-05-06T14:23:11Z",
  "actorId": "github:jannik",
  "actorEmail": "jannik@codeship.tech",
  "title": "Short title",
  "body": "Full content / description",
  "url": "https://...",
  "rawData": { },
  "metadata": {
    "repo": "...",
    "org": "...",
    "branch": "..."
  },
  "routingHint": "codeship"
}
```

### 4.3 Connector Inventory

| Connector | Source | Fetch Method | Cadence | Notes |
|-----------|--------|--------------|---------|-------|
| `claude_code` | `~/.claude/projects/*.jsonl` | File watcher (`watchdog`) | Real-time | Use project path for routing hint |
| `claude_desktop` | Anthropic export API | HTTP poll | Hourly | Diff against last sync |
| `github` | GitHub REST API | HTTP poll | 2 hours | Filter to configured orgs |
| `jira` | Jira REST API | HTTP poll | 4 hours | JQL: `updated >= -4h` |
| `confluence` | Confluence REST API | HTTP poll | Daily 06:00 | CQL: `lastModified >= -24h` |
| `slack` | Slack Web API | HTTP poll | 1 hour | Configured channels + DMs |
| `gmail` | Gmail API | HTTP poll | 2 hours | Unread + labeled, last 24h |
| `teams` | MS Graph API | HTTP poll | 4 hours | Optional; check tenant first |
| `calendar` | Google Calendar API | HTTP poll | 1 hour | Today + tomorrow |
| `obsidian` | Local REST API plugin | File watcher | Real-time | For manually-created notes |

### 4.4 Adding a New Connector

To add e.g. Linear:

1. Create `secondbrain/connectors/linear/`
2. Implement `LinearConnector(Connector)` with `fetch`, `normalize`, `health_check`.
3. Register in `secondbrain/connectors/registry.py`.
4. Add routing rules to `vault/90-meta/routing.yaml`.
5. Add launchd schedule entry in `orchestration/launchd/`.

No core code changes required.

---

## Section 5 — Queue and Worker

### 5.1 Queue Implementation

Filesystem-based queue using atomic POSIX `rename()` for transitions:

```
vault/90-meta/queue/
├── pending/      # connectors write here
├── processing/   # worker claims (rename pending → processing)
├── failed/       # rename + write .error sidecar
└── done/         # rename after success; nightly cleanup >7 days
```

Filename convention: `<ISO-timestamp>-<source>-<id>.json`

### 5.2 Worker Daemon

```python
# secondbrain/worker/main.py

import time
import json
import logging
from pathlib import Path

from secondbrain.worker.pipeline import process_event
from secondbrain.worker.audit import audit_log

QUEUE = Path("vault/90-meta/queue")
SLEEP_INTERVAL = 5  # seconds

def run_loop() -> None:
    logging.info("Worker started")
    while True:
        event_path = _claim_next()
        if event_path is None:
            time.sleep(SLEEP_INTERVAL)
            continue

        event = json.loads(event_path.read_text())
        try:
            process_event(event)
            _move(event_path, QUEUE / "done")
            audit_log("event_processed", event["id"], status="success")
        except Exception as e:
            logging.exception("Processing failed for %s", event["id"])
            _move(event_path, QUEUE / "failed")
            (QUEUE / "failed" / f"{event_path.name}.error").write_text(str(e))
            audit_log("event_failed", event["id"], error=str(e))

def _claim_next() -> Path | None:
    pending = sorted((QUEUE / "pending").glob("*.json"))
    if not pending:
        return None
    target = QUEUE / "processing" / pending[0].name
    pending[0].rename(target)  # atomic claim
    return target

def _move(src: Path, dst_dir: Path) -> None:
    src.rename(dst_dir / src.name)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_loop()
```

### 5.3 Processing Pipeline

```python
# secondbrain/worker/pipeline.py

def process_event(event: dict) -> None:
    """Run an event through the full processing pipeline."""

    # 1. Context routing
    context, confidence = route_to_context(event)
    event["context"] = context
    event["routingConfidence"] = confidence

    # If confidence too low, write to review queue and stop
    if confidence < THRESHOLD_AUTO_ROUTE:
        write_to_review_queue(event)
        return

    # 2. Note generation
    note_path = generate_note(event)

    # 3. Artifact extraction (only for Claude sessions)
    if event["source"] in ("claude-code", "claude-desktop"):
        extract_artifacts(event, note_path)

        # 4. Profile diff proposal
        propose_profile_update(event)

    # 5. Backlinking
    add_backlinks(note_path)

    # 6. Audit log written by run_loop
```

### 5.4 Confidence Thresholds

Defined in `vault/90-meta/config.yaml`:

```yaml
thresholds:
  auto_route: 0.85          # below this, goes to review queue
  auto_apply_profile: 0.90  # below this, profile diff stays proposed
  flag_for_review: 0.70
  reject_below: 0.50        # below this, drop the event
```

---

## Section 6 — LLM Prompts

All prompts live in `vault/90-meta/prompts/` as markdown files. They use Jinja2-style `{{variable}}` substitution.

### 6.1 Router Prompt

```markdown
# vault/90-meta/prompts/router.md

You are a routing classifier for Jannik's personal knowledge system.

Available contexts:
- **sanlam**: work at Sanlam (financial services, internal projects, team)
- **codeship**: Jannik's company, clients, products like Hive
- **reducedrecipes**: ReducedRecipes product (recipe aggregation)
- **personal**: life, family, hobbies, health, music, cooking

Given the following content, output JSON:
```json
{
  "context": "sanlam|codeship|reducedrecipes|personal|needs_review",
  "confidence": 0.0,
  "reasoning": "one sentence explanation",
  "secondary_contexts": []
}
```

If confidence < 0.7, return context = "needs_review".

Content:
{{content}}
```

### 6.2 Extractor Prompt

```markdown
# vault/90-meta/prompts/extractor.md

Read this Claude conversation and extract any of:

1. **SPECIFICATIONS** — formal specs, requirements, design docs
2. **DECISIONS** — explicit decisions with reasoning
3. **CODE** — non-trivial code (>20 lines) worth saving as a file
4. **PROMPTS** — prompts that worked well
5. **UNRESOLVED** — open questions, blockers, "to figure out later"

Output JSON array (empty if nothing meaningful):
```json
[
  {
    "type": "spec|decision|code|prompt|unresolved",
    "title": "short title",
    "content": "full content",
    "tags": []
  }
]
```

Conversation:
{{content}}
```

### 6.3 Profile Updater Prompt

```markdown
# vault/90-meta/prompts/profile-updater.md

You are maintaining a profile of Jannik. Read this conversation and propose
profile changes only for facts you're confident about.

Current profile:
{{profile}}

Conversation:
{{conversation}}

Output JSON array of proposed changes:
```json
[
  {
    "field": "current-projects|preferences|working-style|people|decisions",
    "operation": "add|update|contradict",
    "before": "current value if updating",
    "after": "new value",
    "evidence": "exact quote from conversation",
    "confidence": 0.0
  }
]
```

Be conservative. Single offhand mentions are NOT confident updates.
```

### 6.4 Digest Prompt

```markdown
# vault/90-meta/prompts/digest.md

Generate Jannik's daily digest for {{date}}.

Inputs:
- Yesterday's events: {{events}}
- Today's calendar: {{calendar}}
- Open items needing attention: {{open_items}}
- Profile (recent layer): {{profile_recent}}
- Review queue items: {{review_queue}}

Output structure (markdown):

1. **⚠ Decisions needed** (only if review_queue not empty)
2. **📅 Today** (calendar events, top 3 priorities)
3. **Per-context overnight** (Sanlam, Codeship, ReducedRecipes, Personal)
   - Highlights (2-3 bullets max)
   - Needs you (PRs to review, mentions, blockers)
   - Skip section if no activity
4. **👥 Check-ins suggested** (with reasoning per person)
5. **📊 System health** (one line — count processed, count failed, last sync)

Tone: direct, professional, scannable in 2 minutes.
```

---

## Section 7 — Profile System

### 7.1 Profile Layers

| Layer | File(s) | Update Frequency | Approval |
|-------|---------|------------------|----------|
| Stable | `working-style.md`, `preferences.md` | Monthly | Manual review only |
| Current | `current-projects.md`, `people.md` | Weekly batch | Auto if 3+ corroborating sessions |
| Recent | `_recent.md` | Daily | Auto |

### 7.2 Diff and Decay Logic

**Daily** (worker pipeline, per session):
```
- Run profile-updater prompt on session
- Append diff entries to vault/80-profile/_proposed/YYYY-MM-DD.jsonl
- Do NOT apply yet
```

**Weekly** (Sunday 22:00):
```
- Read all proposed diffs from past 7 days
- Group by field
- For each group:
  - 3+ corroborating proposals  → auto-apply to Current layer
  - 1-2 proposals               → discard
  - Contradiction with Stable   → flag for monthly review
- Log applied changes to audit
- Add review items to next morning's digest
```

**Monthly** (1st of month, 22:00):
```
- Decay: items in Current not reinforced in 60 days → archive
- Promote: stable patterns in Current (>30 days, consistent) → propose Stable update
- Stable updates ALWAYS require manual approval (digest review item)
```

### 7.3 CLAUDE.md Generation

Nightly job builds per-project `CLAUDE.md` files for projects under `~/code/`:

```python
# secondbrain/profile/claude_md.py

def generate_claude_md(project_path: Path) -> None:
    context = detect_context(project_path)  # via routing.yaml

    sections = [
        read("vault/80-profile/working-style.md"),
        read("vault/80-profile/preferences.md"),
        read(f"vault/20-contexts/{context}/_profile.md"),
        filter_by_context(read("vault/80-profile/current-projects.md"), context),
        read("vault/80-profile/_recent.md"),
    ]

    (project_path / "CLAUDE.md").write_text("\n\n".join(sections))
```

---

## Section 8 — Daily Digest

### 8.1 Schedule

- 06:30 daily via launchd
- Output: `vault/10-daily/YYYY-MM-DD.md`
- Optional: macOS notification "Digest ready"

### 8.2 Output Template

```markdown
# Digest — {{day_name}}, {{date}}

## ⚠ Needs your decision ({{count}})
{{review_queue_items}}

## 📅 Today
{{calendar_events}}

## 🏢 Sanlam
{{sanlam_section}}

## 🚀 Codeship
{{codeship_section}}

## 🍳 ReducedRecipes
{{reducedrecipes_section}}

## 🏠 Personal
{{personal_section}}

## 👥 Check-ins suggested
{{check_in_suggestions}}

## 📊 System health
{{health_line}}
```

### 8.3 Per-Context Digests

Generated only if context has meaningful activity (>5 events or >1 needs-attention item). Path: `vault/10-daily/by-context/{context}-YYYY-MM-DD.md`.

### 8.4 Check-in Suggestion Heuristics

A person warrants check-in suggestion if any of:

- They have a PR open >3 days waiting for Jannik's review
- They have a Jira ticket in same status >7 days
- They haven't shipped anything in 5+ working days (could be stuck)
- They were mentioned in Slack with negative sentiment / escalation language
- Last 1:1 was >14 days ago (per calendar)

Phrasing: **"worth a check-in with X because Y"** — not metric-based judgments.

---

## Section 9 — Build Sequence (Phased)

Each phase has a goal, deliverables, and acceptance criteria. **Do not move to the next phase until acceptance is met.** Commit after each phase.

### Phase 1 — Foundation (Week 1)

**Goal:** Vault structure and queue infrastructure exist. Worker can pick up an event and log it.

**Deliverables:**
- [ ] Vault directory structure created (Section 3.1)
- [ ] Obsidian plugins installed: Dataview, Templater, Periodic Notes, Local REST API
- [ ] `vault/90-meta/routing.yaml` with placeholder values (use `TODO(jannik)` for org IDs)
- [ ] `vault/90-meta/config.yaml` with thresholds (Section 5.4)
- [ ] Python project scaffolded: `secondbrain/` with `pyproject.toml`, basic deps (anthropic, watchdog, pyyaml, frontmatter, python-dotenv)
- [ ] `connectors/_base.py` implementing the base class (Section 4.1)
- [ ] `worker/main.py` implementing the run loop (Section 5.2) — process_event is a stub that just logs
- [ ] `worker/audit.py` for audit log writes
- [ ] launchd plist for worker (Section 10.1)
- [ ] README.md in repo with setup instructions

**Acceptance:**
- Manually drop a JSON event in `vault/90-meta/queue/pending/`. Worker picks it up within 10 seconds, moves to `done/`, writes audit entry. Verify via `tail -f vault/90-meta/audit/*.jsonl`.

### Phase 2 — Profile Foundation (Week 1-2)

**Goal:** Hand-written initial profile, CLAUDE.md generation working.

**Deliverables:**
- [ ] Hand-write `vault/80-profile/_index.md`, `working-style.md`, `preferences.md`, `current-projects.md` based on Jannik's user memories
- [ ] `secondbrain/profile/claude_md.py` (Section 7.3)
- [ ] launchd timer for nightly CLAUDE.md regeneration
- [ ] Test directory: create `~/code/test-project/` with a stub `package.json`, run generator

**Acceptance:**
- Open Claude Code in `~/code/test-project/`. Without any prompt from Jannik, Claude greets him with awareness of his role, working style, and current projects (e.g., "I see you're working on ReducedRecipes…").

### Phase 3 — Claude Code Capture (Week 2)

**Goal:** Claude Code sessions automatically captured and processed.

**Deliverables:**
- [ ] `connectors/claude_code/__init__.py` with file watcher
- [ ] SessionEnd hook script at `~/.claude/hooks/session-end.sh`
- [ ] `worker/pipeline.py` implementing routing + note generation steps
- [ ] `worker/router.py` invoking the router prompt
- [ ] `worker/extractor.py` invoking the extractor prompt
- [ ] **Initial run mode: review-only.** All routing decisions go to review queue for first 2 weeks. Audit log captures proposed actions.
- [ ] Migration: After 2 weeks of >90% accuracy on review, switch to auto-route mode (lower threshold to 0.85).

**Acceptance:**
- End a Claude Code session. Within 2 minutes:
  - Session log appears in `vault/00-inbox/raw/claude-code/`
  - Within ~30 seconds more, processed note appears in `vault/20-contexts/{context}/claude/sessions/`
  - Any extracted artifacts (specs, decisions) appear in `artifacts/` subfolders
  - Audit log entry confirms processing

### Phase 4 — GitHub Connector (Week 3)

**Goal:** First external source flowing end to end.

**Deliverables:**
- [ ] `connectors/github/__init__.py` (PR + issue + commit fetching)
- [ ] Note templates for PR, issue, repo
- [ ] Routing config updated with org→context mapping (`TODO(jannik)`: provide actual orgs)
- [ ] launchd timer (every 2 hours)
- [ ] One Dataview query in `vault/60-dashboards/all.md` showing open PRs

**Acceptance:**
- Open a PR in a Codeship repo. Within 2 hours, it appears in `vault/20-contexts/codeship/github/prs/` with correct frontmatter. Dataview dashboard shows it.

### Phase 5 — Daily Digest v1 (Week 3-4)

**Goal:** Morning digest with current data sources (Claude Code + GitHub).

**Deliverables:**
- [ ] `worker/digest.py` implementing digest generation
- [ ] launchd timer (06:30 daily)
- [ ] Digest prompt (Section 6.4) refined for Jannik's voice preference
- [ ] Per-context digest generator (only when activity exists)
- [ ] System health line generator (counts from audit log)

**Acceptance:**
- Wake up to a digest in `vault/10-daily/<today>.md`. Read it in under 2 minutes. It includes: yesterday's GitHub activity, captured Claude Code sessions, system health line. No false items, no missing items from data we have.

### Phase 6 — Profile Auto-Update (Week 4-5)

**Goal:** Profile evolves automatically from Claude sessions, with safety rails.

**Deliverables:**
- [ ] `worker/profile.py` implementing diff proposal
- [ ] Weekly batch job (Sunday 22:00) for diff review and apply
- [ ] Monthly batch job (1st of month) for decay and Stable promotion proposals
- [ ] Digest integration: review items appear in Monday morning digest

**Acceptance:**
- After 2 weeks of running, profile `current-projects.md` reflects what Jannik has actually been working on, without him editing it. Audit log shows each change with evidence.

### Phase 7 — Jira + Confluence (Week 5-6)

**Deliverables:**
- [ ] `connectors/jira/__init__.py`
- [ ] `connectors/confluence/__init__.py`
- [ ] Per-site auth (different credentials for Sanlam vs Codeship Atlassian instances)
- [ ] launchd timers (Jira every 4h, Confluence daily 06:00)
- [ ] Digest sections for Jira tickets and Confluence updates

**Acceptance:**
- A Jira ticket transition is reflected in vault within 4 hours. A Confluence page edit appears in next day's digest.

### Phase 8 — Claude Desktop Capture (Week 6)

**Goal:** Claude.ai conversations flow into vault.

**Pre-work spike (Phase 8.0):**
- Investigate Claude desktop conversation storage on macOS. Check `~/Library/Application Support/Claude/` and similar paths. Determine if conversations are stored locally readable.
- If not local: investigate Anthropic export API (current format, rate limits).
- Write a 1-page findings doc before implementing.

**Deliverables:**
- [ ] `connectors/claude_desktop/__init__.py` (hourly poll or local file watch, whichever the spike yields)
- [ ] Routing relies on classifier (no project path hint available)
- [ ] Integration with same processing pipeline as Claude Code

**Acceptance:**
- A Claude.ai conversation from earlier today appears in `vault/20-contexts/{context}/claude/sessions/` within 1 hour.

### Phase 9 — Slack + Gmail (Week 7-8)

**Goal:** Communication sources, with aggressive filtering.

**Deliverables:**
- [ ] `connectors/slack/__init__.py` — only configured channels and DMs, only mentions
- [ ] `connectors/gmail/__init__.py` — labeled threads + unread last 24h
- [ ] Routing rules tuned (sender domain → context, label prefix → context)
- [ ] Digest filter: mentions only, not raw message volume

**Acceptance:**
- A Slack mention of Jannik triggers a vault note. An email from a known sanlam.co.za address routes to Sanlam context.

### Phase 10 — Metrics & Velocity (Week 9-10)

**Goal:** Engineering visibility for Sanlam team plus check-in heuristics.

**Deliverables:**
- [ ] `worker/metrics.py` calculating cycle time, review latency, stale items
- [ ] Weekly metric snapshot job (Sunday 22:30)
- [ ] `vault/60-dashboards/team-pulse.md` with Dataview queries
- [ ] Check-in suggestion logic (Section 8.4)

**Acceptance:**
- Sunday digest includes weekly trend lines (cycle time, throughput vs previous week). Team-pulse dashboard renders correctly. Check-in suggestions name 1-3 people with reasoning.

### Phase 11 — Calendar (Week 11)

**Deliverables:**
- [ ] `connectors/calendar/__init__.py` (Google Calendar API)
- [ ] Per-calendar routing (work vs personal)
- [ ] Digest "Today" section pulls live calendar

**Acceptance:**
- Today's meetings appear in morning digest with correct context tagging.

### Phase 12 — Teams (Week 12, optional)

**Deliverables (only if Sanlam tenant allows app registration):**
- [ ] `connectors/teams/__init__.py` (MS Graph API)
- [ ] Auth via Entra ID app registration
- [ ] Mentions and important channel posts

**Acceptance:**
- Teams mentions appear in vault. If Entra blocks app registration, document blocker and skip.

### Phase 13 — Strength Features (Week 13+)

These make the system genuinely offload thinking. Implement in any order based on perceived value.

- [ ] **Semantic linking** — embedding-based weekly cross-link pass (sentence-transformers, all-MiniLM-L6-v2)
- [ ] **Decision tracking** — auto-detect decisions, flag reversals against past decisions
- [ ] **Inverse search** — weekly "where am I unexpectedly referenced" pass
- [ ] **Check-in briefs** — full one-page brief per suggested check-in
- [ ] **Pyramid synthesis** — daily → weekly → monthly compression layers
- [ ] **Anticipation prompts** — "you usually work on X on Mondays, calendar's empty, want to block?"

### Phase 14 — Open Source Packaging (Final)

**Deliverables:**
- [ ] `setup.sh` for fresh-machine install
- [ ] `vault-template/` directory in repo
- [ ] Comprehensive README with screenshots
- [ ] Connector authoring guide (`docs/connectors.md`)
- [ ] Prompt customization guide (`docs/prompts.md`)
- [ ] MIT LICENSE file
- [ ] GitHub Actions for linting
- [ ] Example `routing.yaml.example`

**Acceptance:**
- Clean macOS clone of repo, run `./setup.sh`, follow README, system runs end-to-end.

---

## Section 10 — Orchestration

### 10.1 launchd Plists

All plists live in `secondbrain/orchestration/launchd/`. Loaded via `launchctl load <plist>`.

**Worker (always running):**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jannik.secondbrain.worker</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>-m</string>
        <string>secondbrain.worker.main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/jannik/secondbrain</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/jannik/secondbrain/logs/worker.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/jannik/secondbrain/logs/worker.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>TODO(jannik): set via setup.sh</string>
    </dict>
</dict>
</plist>
```

**Scheduled jobs use `StartCalendarInterval`:**

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key>
    <integer>6</integer>
    <key>Minute</key>
    <integer>30</integer>
</dict>
```

### 10.2 Scheduled Jobs Summary

| Plist | Job | Schedule |
|-------|-----|----------|
| `worker.plist` | Queue worker | Always running |
| `claude-code-watcher.plist` | Claude Code file watcher | Always running |
| `github-fetch.plist` | GitHub poll | Every 2h |
| `jira-fetch.plist` | Jira poll | Every 4h |
| `confluence-fetch.plist` | Confluence poll | Daily 06:00 |
| `slack-fetch.plist` | Slack poll | Every 1h |
| `gmail-fetch.plist` | Gmail poll | Every 2h |
| `teams-fetch.plist` | Teams poll | Every 4h |
| `calendar-fetch.plist` | Calendar poll | Every 1h |
| `claude-desktop-sync.plist` | Claude.ai sync | Every 1h |
| `daily-digest.plist` | Digest generation | Daily 06:30 |
| `weekly-profile.plist` | Profile review | Sunday 22:00 |
| `weekly-summary.plist` | Week-in-review | Sunday 22:30 |
| `monthly-review.plist` | Profile decay | 1st of month 22:00 |
| `nightly-claude-md.plist` | CLAUDE.md regen | Daily 02:00 |
| `nightly-cleanup.plist` | Queue cleanup | Daily 03:00 |

### 10.3 Hooks

**Claude Code SessionEnd hook** at `~/.claude/hooks/session-end.sh`:

```bash
#!/bin/bash
set -euo pipefail

SESSION_FILE="${1:-}"
if [[ -z "$SESSION_FILE" ]]; then
    echo "Usage: $0 <session-file>" >&2
    exit 1
fi

QUEUE_DIR="$HOME/secondbrain/vault/90-meta/queue/pending"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
EVENT_ID="claudecode-${TIMESTAMP}-$(uuidgen)"

cat > "${QUEUE_DIR}/${EVENT_ID}.json" <<EOF
{
  "id": "${EVENT_ID}",
  "source": "claude-code",
  "type": "session",
  "timestamp": "${TIMESTAMP}",
  "rawData": {"sessionFile": "${SESSION_FILE}"},
  "metadata": {"projectPath": "$(pwd)"}
}
EOF
```

---

## Section 11 — Repository Structure

```
secondbrain/
├── README.md
├── LICENSE                       # MIT
├── pyproject.toml
├── setup.sh
├── docs/
│   ├── setup.md
│   ├── connectors.md             # how to author a connector
│   ├── prompts.md                # how to customize prompts
│   └── architecture.md
├── secondbrain/
│   ├── __init__.py
│   ├── connectors/
│   │   ├── _base.py
│   │   ├── registry.py
│   │   ├── claude_code/
│   │   ├── claude_desktop/
│   │   ├── github/
│   │   ├── jira/
│   │   ├── confluence/
│   │   ├── slack/
│   │   ├── gmail/
│   │   ├── teams/
│   │   └── calendar/
│   ├── worker/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── pipeline.py
│   │   ├── router.py
│   │   ├── extractor.py
│   │   ├── profile.py
│   │   ├── digest.py
│   │   ├── metrics.py
│   │   └── audit.py
│   ├── profile/
│   │   ├── claude_md.py
│   │   └── decay.py
│   └── llm/
│       ├── client.py             # Anthropic API wrapper
│       └── prompts.py            # prompt loader (Jinja2)
├── orchestration/
│   ├── launchd/
│   │   ├── worker.plist
│   │   ├── github-fetch.plist
│   │   └── ...
│   └── scripts/
│       ├── install.sh
│       └── uninstall.sh
├── vault-template/               # starter vault distributed with repo
│   ├── 90-meta/
│   │   ├── routing.yaml.example
│   │   ├── config.yaml
│   │   └── prompts/
│   └── 80-profile/
│       └── _index.md.template
├── examples/
│   └── (sample data for testing)
└── tests/
    ├── test_router.py
    ├── test_pipeline.py
    └── test_connectors/
```

---

## Section 12 — Operational Notes

### 12.1 Cost Estimates (Anthropic API)

Daily LLM costs (approximate, Sonnet 4):
- Router: ~50 calls × small prompt = $0.05
- Extractor: ~10 sessions × medium prompt = $0.30
- Profile updater: ~10 sessions × medium prompt = $0.50
- Digest: 1 call × large prompt = $0.20

**Total: ~$1-2/day, ~$30-60/month.** Use Haiku for routing to cut further.

### 12.2 Failure Modes and Recovery

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Connector API down | health_check fails | Retries with backoff; surfaces in digest health line |
| Worker crashed | launchd KeepAlive | Auto-restart |
| LLM API timeout | Per-call retry, then fail | Manual replay of `failed/` events |
| Routing mistake | Audit log review | Manually move note + add routing rule |
| Bad profile update | Weekly review catches | Git revert of vault |
| Disk full | Nightly cleanup; alert if >80% | Manual |

### 12.3 Backup

- Vault is a git repo, push to private GitHub remote daily (cron).
- `.gitignore`: `90-meta/queue/`, `90-meta/audit/` older than 30 days, `80-profile/_proposed/` older than 30 days.
- `secondbrain/` source repo separate from vault repo.

### 12.4 Maintenance Time Budget

- **Daily** (5 min): glance at digest, accept/reject any review queue items
- **Weekly** (15 min): scan audit log, review approved profile diffs
- **Monthly** (30 min): manual profile review, archive stale items
- **Quarterly** (1 hour): full vault review, reorganize if needed

---

## Section 13 — Open Questions / Decisions Pending

These need answers from Jannik before relevant phases:

1. **Atlassian site URLs** — needed for Phase 7 routing config. Defer until Phase 7.
2. **GitHub org names** — needed for Phase 4 routing config. Defer until Phase 4.
3. **Slack workspace IDs** — needed for Phase 9. Defer until Phase 9.
4. **Sanlam Teams tenant policy** — does Entra allow app registration? Resolved or skipped at Phase 12.
5. **Anthropic API key** — required from Phase 1. Add to env via `setup.sh`.
6. **Vault location on disk** — default `~/secondbrain/vault/`. Configurable.

---

## Section 14 — Definition of Done (System-Level)

The full system is "done" when:

1. Jannik wakes up to a daily digest with no manual intervention required.
2. All 4 contexts have meaningful activity flowing in from at least 3 sources each.
3. Profile updates automatically without breaking Stable layer.
4. Audit log shows zero failed events for 7 consecutive days.
5. New Claude Code sessions in any project automatically have correct CLAUDE.md context.
6. Repo is clean, tested, and could be cloned by someone else and run.

---

**End of Spec — Version 1.0**