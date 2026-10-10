"""Templates on disk: <vault>/<TEMPLATES_REL>/<id>.md (spec decision 1).

Ids are file stems matching TEMPLATE_ID_RE. Symlinked template files are
never read, and a templates folder that resolves outside the vault is
ignored, so a template id can only ever name a file inside the vault.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ghostbrain.paths import vault_path
from ghostbrain.templates.lang import MAX_TEMPLATE_CHARS
from ghostbrain.templates.parse import Diagnostic, Template, parse_template
from ghostbrain.templates.starters import TEMPLATES_REL, seed_starter_templates

__all__ = [
    "MAX_TEMPLATE_BYTES",
    "TEMPLATES_REL",
    "TEMPLATE_ID_RE",
    "TemplateInfo",
    "TemplateInvalid",
    "TemplateNotFound",
    "list_templates",
    "load_template",
    "read_template_source",
    "templates_dir",
]

log = logging.getLogger("ghostbrain.templates.registry")

TEMPLATE_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
# UTF-8 is at most 4 bytes per character; parse_template enforces the char limit.
MAX_TEMPLATE_BYTES = MAX_TEMPLATE_CHARS * 4


class TemplateNotFound(LookupError):
    pass


class TemplateInvalid(ValueError):
    def __init__(self, template_id: str, diagnostics: tuple[Diagnostic, ...]) -> None:
        first = next((d for d in diagnostics if d.severity == "error"), None)
        super().__init__(f"line {first.line}: {first.message}" if first else "template has errors")
        self.template_id = template_id
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class TemplateInfo:
    id: str
    path: str
    template: Template | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def valid(self) -> bool:
        return self.template is not None

    def to_json(self) -> dict[str, Any]:
        t = self.template
        return {
            "id": self.id,
            "path": self.path,
            "name": t.name if t else self.id,
            "description": t.description if t else "",
            "prompts": [p.to_json() for p in t.prompts] if t else [],
            "variables": list(t.variables) if t else [],
            "valid": t is not None,
            "diagnostics": [d.to_json() for d in self.diagnostics],
        }


def templates_dir(root: Path | None = None) -> Path:
    return Path(root or vault_path()) / TEMPLATES_REL


def _inside_vault(base: Path, vault: Path) -> bool:
    try:
        return base.resolve().is_relative_to(vault.resolve())
    except (OSError, RuntimeError):  # RuntimeError: symlink loop on Python 3.11
        return False


def _error(template_id: str, message: str, code: str) -> TemplateInvalid:
    return TemplateInvalid(template_id, (Diagnostic(1, 1, "error", message, code),))


def _read_source(template_id: str, path: Path) -> str:
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_TEMPLATE_BYTES + 1)
    except OSError as e:
        raise _error(template_id, f"template file cannot be read: {e.strerror or e}", "read") from None
    if len(data) > MAX_TEMPLATE_BYTES:
        raise _error(template_id, "template file is too large", "limit")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise _error(template_id, "template file is not UTF-8 text", "encoding") from None


def _template_path(template_id: str, root: Path | None) -> Path:
    if not isinstance(template_id, str) or not TEMPLATE_ID_RE.fullmatch(template_id):
        raise TemplateNotFound(template_id)
    vault = Path(root or vault_path())
    base = templates_dir(vault)
    name = f"{template_id}.md"
    if not _inside_vault(base, vault):
        raise TemplateNotFound(template_id)
    try:
        # Exact name only: on a case-insensitive disk `Upper.md` must not load as "upper".
        exact = name in os.listdir(base)
    except OSError:
        exact = False
    path = base / name
    if not exact or path.is_symlink() or not path.is_file():
        raise TemplateNotFound(template_id)
    return path


def read_template_source(template_id: str, root: Path | None = None) -> str:
    """Raises TemplateNotFound, or TemplateInvalid (codes read/limit/encoding)."""
    return _read_source(template_id, _template_path(template_id, root))


def load_template(template_id: str, root: Path | None = None) -> Template:
    result = parse_template(read_template_source(template_id, root), template_id)
    if result.template is None:
        raise TemplateInvalid(template_id, result.diagnostics)
    return result.template


def _info(template_id: str, path: Path) -> TemplateInfo:
    rel = f"{TEMPLATES_REL}/{path.name}"
    if not TEMPLATE_ID_RE.fullmatch(template_id):
        return TemplateInfo(template_id, rel, None, (Diagnostic(
            1, 1, "error",
            "rename the file to lowercase letters, digits and dashes (e.g. weekly-review.md)",
            "file-name"),))
    try:
        result = parse_template(_read_source(template_id, path), template_id)
    except TemplateInvalid as e:
        return TemplateInfo(template_id, rel, None, e.diagnostics)
    return TemplateInfo(template_id, rel, result.template, result.diagnostics)


def list_templates(root: Path | None = None) -> list[TemplateInfo]:
    """Every *.md in the templates folder, valid or not (broken ones carry
    diagnostics). Seeds the starters first if the folder is missing."""
    vault = Path(root or vault_path())
    base = templates_dir(vault)
    if not base.exists() and not base.is_symlink():
        try:
            seed_starter_templates(vault)
        except OSError as e:  # e.g. a read-only vault: list what is there
            log.warning("could not seed starter templates in %s: %s", base, e)
    if not base.is_dir() or not _inside_vault(base, vault):
        return []
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name)
    except OSError as e:
        log.warning("could not list templates in %s: %s", base, e)
        return []
    infos = [
        _info(entry.stem, entry)
        for entry in entries
        if entry.suffix == ".md" and not entry.name.startswith(".")
        and not entry.is_symlink() and entry.is_file()
    ]
    infos.sort(key=lambda i: ((i.template.name if i.template else i.id).lower(), i.id))
    return infos
