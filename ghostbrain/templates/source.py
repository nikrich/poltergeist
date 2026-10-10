"""Template files as editable source (spec C3, template editor): read with
an etag, save through the B1 write path, start a blank template, and the
value hints the editor's query completions offer."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from ghostbrain import vault_write
from ghostbrain.paths import vault_path
from ghostbrain.templates.lang import MAX_TEMPLATE_CHARS
from ghostbrain.templates.registry import TEMPLATE_ID_RE, read_template_source
from ghostbrain.templates.starters import TEMPLATES_REL, seed_starter_templates
from ghostbrain.templates.values import slugify
from ghostbrain.vault_write import Actor

MAX_NAME_CHARS = 80
NEW_ID_MAX = 60  # leaves room for write_new's "-NN" suffix inside TEMPLATE_ID_RE's 64
MAX_HINTS = 30
_BAD_NAME_RE = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]")

BLANK_TEMPLATE = """---
template:
  name: {name}
  description: ""
  prompts:
    - id: topic
      ask: "What is this note about?"
      type: text
  file:
    folder: "20-contexts/{{{{context}}}}/notes"
    name: "{{{{date | format: YYYY-MM-DD}}}} {{{{topic}}}}"
---
# {{{{topic}}}}

"""


class SourceTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class TemplateSource:
    id: str
    path: str
    source: str
    etag: str

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "path": self.path, "source": self.source, "etag": self.etag}


@dataclass(frozen=True)
class SavedTemplate:
    id: str
    path: str
    etag: str | None
    status: str
    change_id: str | None

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "path": self.path, "etag": self.etag, "status": self.status,
                "changeId": self.change_id}


def _rel(template_id: str) -> str:
    return f"{TEMPLATES_REL}/{template_id}.md"


def read_source(template_id: str) -> TemplateSource:
    """Raises TemplateNotFound, or TemplateInvalid (read/limit/encoding)."""
    source = read_template_source(template_id)
    etag = vault_write.compute_etag(source.encode("utf-8"))
    return TemplateSource(template_id, _rel(template_id), source, etag)


def save_source(template_id: str, source: str, *, actor: Actor, base_etag: str | None) -> SavedTemplate:
    """Replace an existing template file. A template with errors may be
    saved (that is how it gets fixed); the list shows it with ⚠."""
    read_template_source(template_id)  # exists, is a plain file, not a symlink
    if len(source) > MAX_TEMPLATE_CHARS:
        raise SourceTooLarge(f"template is larger than {MAX_TEMPLATE_CHARS} characters")
    res = vault_write.write(_rel(template_id), content=source, actor=actor, base_etag=base_etag,
                            reason=f"edit template {template_id}")
    return SavedTemplate(template_id, res.path, res.etag, res.status, res.change_id)


def blank_template(name: str) -> str:
    # json.dumps is a valid YAML double-quoted scalar (ASCII-escaped).
    return BLANK_TEMPLATE.format(name=json.dumps(name))


def create_blank(name: str, *, actor: Actor) -> SavedTemplate:
    bad = bool(_BAD_NAME_RE.search(name))
    name = " ".join(name.split())
    if bad or not name or len(name) > MAX_NAME_CHARS:
        raise ValueError(f"a template name is 1-{MAX_NAME_CHARS} characters on one line")
    # Creating the folder ourselves would stop the starters from ever seeding.
    seed_starter_templates(vault_path())
    stem = slugify(name, NEW_ID_MAX)  # "untitled" when nothing is slug-able
    if not TEMPLATE_ID_RE.fullmatch(stem):
        stem = "template"
    res = vault_write.write_new(_rel(stem), blank_template(name), actor=actor,
                                reason=f"new template {name}")
    return SavedTemplate(PurePosixPath(res.path).stem, res.path, res.etag, res.status, res.change_id)


def query_values() -> dict[str, Any]:
    """Known values for query completions, from A2's link index: the most
    common note types and statuses. Empty while the index is cold."""
    from ghostbrain.vault_index.links import get_link_index

    index = get_link_index()
    if not index.ready:
        index.ensure_fresh(wait=0)
        return {"types": [], "statuses": [], "indexing": True}
    types: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    for entry in index.entries():
        kind = entry.artifact_type or entry.type
        if kind:
            types[kind] += 1
        if entry.status:
            statuses[entry.status.strip().lower()] += 1
    return {
        "types": [k for k, _ in types.most_common(MAX_HINTS)],
        "statuses": [k for k, _ in statuses.most_common(MAX_HINTS)],
        "indexing": False,
    }
