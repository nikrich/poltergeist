"""The three starter templates (spec: 1-1, Meeting notes, Decision record).

Seeded into <vault>/90-meta/templates/ only when that folder is missing, with
exclusive create: a user's edit or deletion is never undone. No pydantic
import here (nor anything that pulls it in), because bootstrap imports this
module in base installs. ``TEMPLATES_REL`` lives here for the same reason;
the registry imports it.
"""
from __future__ import annotations

from pathlib import Path

TEMPLATES_REL = "90-meta/templates"

ONE_ON_ONE = """---
template:
  name: 1-1
  description: Weekly 1-1 with open follow-ups for the person
  prompts:
    - id: person
      ask: "Who's this 1-1 with?"
      type: person
    - id: focus
      ask: "Anything specific to cover?"
      type: text
      optional: true
  file:
    folder: "20-contexts/{{context}}/one-on-ones"
    name: "{{date | format: YYYY-MM-DD}} {{person.name}} 1-1"
  frontmatter:
    type: meeting
    attendees: ["{{person.link}}"]
---
# 1-1 with {{person.link}} — {{date | format: D MMM YYYY}}

{{focus}}

## Open follow-ups

```query
type: action_item
mentions: "{{person.link}}"
status: open
sort: created desc
```

## Notes

- 
"""

MEETING_NOTES = """---
template:
  name: Meeting notes
  description: Agenda, notes, decisions and action items for any meeting
  prompts:
    - id: topic
      ask: "What's the meeting about?"
      type: text
  file:
    folder: "20-contexts/{{context}}/meetings"
    name: "{{date | format: YYYY-MM-DD}} {{topic}}"
  frontmatter:
    type: meeting
---
# {{topic}} — {{date | format: D MMM YYYY}}

## Attendees

- 

## Agenda

- 

## Notes

- 

## Decisions

- 

## Action items

- [ ] 
"""

DECISION_RECORD = """---
template:
  name: Decision record
  description: One decision, the options weighed, and why
  prompts:
    - id: decision
      ask: "What did you decide?"
      type: text
    - id: status
      ask: "Status"
      type: choice
      options: [proposed, accepted, superseded]
      default: accepted
    - id: project
      ask: "Which project?"
      type: project
      optional: true
  file:
    folder: "20-contexts/{{context}}/decisions"
    name: "{{date | format: YYYY-MM-DD}} {{decision}}"
  frontmatter:
    type: decision
    status: "{{status}}"
---
# {{decision}}

**Date:** {{date | format: D MMM YYYY}} · **Status:** {{status}} · **Project:** {{project.name | default: none}}

## Context

What made this decision necessary?

## Options considered

1. 

## Decision

## Consequences
"""

STARTER_TEMPLATES: dict[str, str] = {
    "one-on-one.md": ONE_ON_ONE,
    "meeting-notes.md": MEETING_NOTES,
    "decision-record.md": DECISION_RECORD,
}


def seed_starter_templates(root: Path) -> list[str]:
    """Write the starters if <root>/90-meta/templates is missing. Returns the
    vault-relative paths written; [] when the folder already existed, or when
    it would resolve outside the vault (a symlinked 90-meta)."""
    vault = Path(root)
    folder = vault / TEMPLATES_REL
    if folder.exists() or folder.is_symlink():
        return []
    if not folder.resolve().is_relative_to(vault.resolve()):
        return []
    folder.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, body in STARTER_TEMPLATES.items():
        try:
            with open(folder / name, "x", encoding="utf-8", newline="\n") as fh:
                fh.write(body)
        except FileExistsError:
            continue
        written.append(f"{TEMPLATES_REL}/{name}")
    return written
