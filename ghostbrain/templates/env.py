"""Everything a render needs from the vault: contexts, projects, the user's
name, person titles from the in-memory link index (A2), and the clock."""
from __future__ import annotations

import logging
from datetime import datetime

import yaml

from ghostbrain import routing_config
from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.paths import vault_path
from ghostbrain.templates.render import RenderEnv
from ghostbrain.templates.values import ProjectValue
from ghostbrain.vault_index.links import get_link_index

log = logging.getLogger("ghostbrain.templates")


def _now() -> datetime:
    return datetime.now().astimezone()


def _user_name() -> str:
    try:
        data = yaml.safe_load((vault_path() / "90-meta" / "config.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return ""
    user = data.get("user") if isinstance(data, dict) else None
    name = user.get("name") if isinstance(user, dict) else None
    return name.strip()[:200] if isinstance(name, str) else ""


def _person_title(path: str) -> str | None:
    """Indexed title, never a file read. A cold index answers None (the
    renderer then humanizes the file stem) and starts building."""
    try:
        index = get_link_index()
        if not index.ready:
            index.ensure_fresh(wait=0)
            return None
        entry = index.get(path)
        return entry.title if entry is not None else None
    except Exception:  # a lookup must never fail a create
        log.exception("link index lookup failed for %s", path)
        return None


def build_env() -> RenderEnv:
    contexts = tuple(routing_config.contexts())
    projects = {
        p["id"]: ProjectValue(id=p["id"], name=p["name"], slug=p["slug"], context=p["context"])
        for p in projects_repo.list_projects()
        if isinstance(p, dict) and all(isinstance(p.get(k), str) for k in ("id", "name", "slug", "context"))
    }
    return RenderEnv(
        now=_now(),
        default_context=contexts[0] if contexts else "personal",
        contexts=contexts,
        projects=projects,
        user_name=_user_name(),
        person_title=_person_title,
    )
