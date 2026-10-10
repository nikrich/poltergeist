"""New note from a template: render, then create through B1's write path."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ghostbrain import vault_write
from ghostbrain.templates.env import build_env
from ghostbrain.templates.registry import load_template
from ghostbrain.templates.render import RenderedNote, RenderEnv, render
from ghostbrain.vault_write import USER, Actor


@dataclass(frozen=True)
class CreatedNote:
    path: str
    title: str
    etag: str | None
    status: str


def preview_from_template(
    template_id: str, answers: Mapping[str, str], *, env: RenderEnv | None = None
) -> RenderedNote:
    """Render without writing. Raises InvalidPath if the target would leave
    the vault (e.g. a symlinked folder)."""
    note = render(load_template(template_id), answers, env or build_env())
    vault_write.resolve_safe(note.path)
    return note


def create_from_template(
    template_id: str,
    answers: Mapping[str, str],
    *,
    actor: Actor = USER,
    env: RenderEnv | None = None,
) -> CreatedNote:
    note = render(load_template(template_id), answers, env or build_env())
    result = vault_write.write_new(
        note.path, note.markdown(), actor=actor, reason=f"new note from template {template_id}"
    )
    return CreatedNote(result.path, note.title, result.etag, result.status)
