"""Save an AI-drafted template as a pending change (spec C4 + B3).

The draft goes through the write path as ``assistant`` into
``90-meta/templates/``. B3's risk rules hold that write: nothing reaches the
vault until the user approves it on the Changes screen. The exact text is
re-checked first (``verify_exact``) and written verbatim, so the bytes the
user approves are the bytes that were validated. This module refuses when
the rules would not hold the write, and the write itself runs with
``require_hold``, which refuses before anything is stored: an AI template
can never take effect on its own.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ghostbrain.changes import log as change_log
from ghostbrain.paths import vault_path
from ghostbrain.templates.generate import verify_exact
from ghostbrain.templates.parse import Template
from ghostbrain.templates.starters import TEMPLATES_REL, seed_starter_templates
from ghostbrain.templates.values import slugify
from ghostbrain.vault_write import (
    ASSISTANT,
    NotHeldError,
    ProposedChange,
    WriteConflict,
    resolve_safe,
    risk,
    write,
)

log = logging.getLogger("ghostbrain.templates.ai_save")

NEW_ID_MAX = 60
MAX_ID_ATTEMPTS = 50
MAX_PENDING_SCAN = 500

# One proposal at a time: two saves must not pick the same free id, since a
# pending change does not create its file.
_save_lock = threading.Lock()


class NotHeld(RuntimeError):
    """The approval policy would not hold an AI template; nothing was saved."""


@dataclass(frozen=True)
class SavedAiTemplate:
    id: str
    path: str
    name: str
    change_id: str | None

    def to_json(self) -> dict[str, Any]:
        return {"status": "pending", "id": self.id, "path": self.path, "name": self.name,
                "changeId": self.change_id}


def _pending_paths() -> set[str]:
    rows = change_log.list_changes(status="pending", path_query=TEMPLATES_REL, limit=MAX_PENDING_SCAN)
    return {p for row in rows for p in (row.rel_path, row.dest_path) if p}


def _candidates(stem: str) -> Iterator[tuple[str, str]]:
    pending = _pending_paths()
    for n in range(1, MAX_ID_ATTEMPTS + 1):
        template_id = stem if n == 1 else f"{stem}-{n}"
        rel = f"{TEMPLATES_REL}/{template_id}.md"
        if rel in pending or resolve_safe(rel).exists():
            continue
        yield template_id, rel


def save_ai_template(source: str, template: Template, *, reason: str) -> SavedAiTemplate:
    """Propose ``source`` (validated as ``template``) as a new template.
    Returns the pending change; raises DraftInvalid (``source`` is not the
    validated template), NotHeld or WriteConflict (no free id). Nothing
    reaches the vault in any of those cases."""
    verify_exact(source, template)
    data = source.encode("utf-8")
    stem = slugify(template.name, NEW_ID_MAX)
    with _save_lock:
        # Seed first: the approved write creates the folder, after which the
        # starters would never be seeded.
        seed_starter_templates(vault_path())
        for template_id, rel in _candidates(stem):
            proposal = ProposedChange(actor=ASSISTANT, op="create", rel_path=rel, dest_path=None,
                                      before=None, after=data, reason=reason, requested=(rel,))
            if not risk.evaluate(proposal):
                raise NotHeld("the approval rules would not hold this template; nothing was saved")
            try:
                res = write(rel, content=source, op="create", actor=ASSISTANT, reason=reason,
                            verbatim=True, require_hold=True)
            except WriteConflict:
                continue  # created meanwhile: try the next id
            except NotHeldError as e:
                raise NotHeld("the AI template would not be held for approval; "
                              "nothing was saved") from e
            if res.status != "pending":  # unreachable: require_hold refuses first
                log.error("AI template %s was not held for approval (status %s)", rel, res.status)
                raise NotHeld("the AI template was not held for approval")
            return SavedAiTemplate(template_id, rel, template.name, res.change_id)
    raise WriteConflict(None, f"no free template id near {stem!r}")
