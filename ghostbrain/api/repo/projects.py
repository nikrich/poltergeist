"""Project registry: user-defined routing destinations nested under contexts.

Stored at <vault>/90-meta/projects.json so it syncs with the vault. Atomic
writes (tmp+rename); a corrupt registry reads as empty — routing then degrades
to context-only rather than failing.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ghostbrain import routing_config
from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.projects")

REGISTRY_REL = "90-meta/projects.json"
PROJECT_DIR_TEMPLATE = "20-contexts/{context}/projects/{slug}"


class UnknownContext(ValueError):
    pass


class ProjectExists(ValueError):
    pass


def _registry_path() -> Path:
    return vault_path() / REGISTRY_REL


def _read() -> list[dict]:
    path = _registry_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("unreadable projects registry %s: %s", path, exc)
        return []
    return data if isinstance(data, list) else []


def _write(items: list[dict]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_projects(*, include_archived: bool = False) -> list[dict]:
    items = _read()
    if not include_archived:
        items = [p for p in items if not p.get("archived")]
    return items


def get_project(context: str, slug: str, *, active_only: bool = False) -> dict | None:
    for p in _read():
        if p["context"] == context and p["slug"] == slug:
            if active_only and p.get("archived"):
                return None
            return p
    return None


def create_project(context: str, name: str, description: str = "") -> dict:
    # Function-level import to avoid the import cycle:
    # projects → notes_manual → router → projects (Task 3 wires router to projects)
    from ghostbrain.api.repo.notes_manual import make_slug  # noqa: PLC0415

    if context not in routing_config.contexts():
        raise UnknownContext(context)
    slug = make_slug(name)
    if not slug:
        raise ValueError("project name produces an empty slug")
    if get_project(context, slug) is not None:
        raise ProjectExists(f"{context}/{slug}")
    project = {
        "id": f"{context}/{slug}",
        "context": context,
        "slug": slug,
        "name": name.strip(),
        "description": description.strip(),
        "archived": False,
        "created_at": time.time(),
    }
    items = _read()
    items.append(project)
    _write(items)
    folder = vault_path() / PROJECT_DIR_TEMPLATE.format(context=context, slug=slug)
    folder.mkdir(parents=True, exist_ok=True)
    return project


def update_project(
    context: str,
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    archived: bool | None = None,
) -> dict | None:
    items = _read()
    for p in items:
        if p["context"] == context and p["slug"] == slug:
            if name is not None:
                p["name"] = name.strip()
            if description is not None:
                p["description"] = description.strip()
            if archived is not None:
                p["archived"] = bool(archived)
            _write(items)
            return p
    return None


def active_destinations() -> list[str]:
    """Routing destinations: bare contexts + 'context/slug' for active projects."""
    dests = list(routing_config.contexts())
    dests.extend(p["id"] for p in list_projects())
    return dests


def project_prompt_lines() -> list[str]:
    """'context/slug — Name: description' lines for the router prompt."""
    out = []
    for p in list_projects():
        desc = f": {p['description']}" if p["description"] else ""
        out.append(f"{p['id']} — {p['name']}{desc}")
    return out
