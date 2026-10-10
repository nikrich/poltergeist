"""Test run (spec C3): render a template's *source* with sample answers and
report where the note would be filed. Nothing is written, ever."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from ghostbrain import vault_write
from ghostbrain.templates.lint import lint
from ghostbrain.templates.parse import SHADOWABLE, Diagnostic, Prompt, Template, parse_template
from ghostbrain.templates.render import AnswerError, RenderedNote, RenderEnv, RenderError, render

SAMPLE_PERSON = "Sample Person"
MAX_NAME_ATTEMPTS = 100


def _sample_for(prompt: Prompt, env: RenderEnv) -> str:
    if prompt.type == "choice":
        return prompt.options[0]
    if prompt.type == "date":
        return env.now.date().isoformat()
    if prompt.type == "context":
        return env.default_context
    if prompt.type == "project":
        return next(iter(env.projects), "")
    if prompt.type == "person":
        return SAMPLE_PERSON
    return f"[{prompt.id}]"


def sample_answers(template: Template, answers: Mapping[str, Any], env: RenderEnv) -> dict[str, str]:
    """The caller's answers for this template's prompts (stale keys from an
    older version of the template are dropped), plus a sample for every
    required prompt left blank. Optional or defaulted prompts stay blank so
    the renderer applies their default."""
    ids = {p.id for p in template.prompts} | set(SHADOWABLE)
    out = {k: v for k, v in answers.items() if k in ids and isinstance(v, str) and v.strip()}
    for p in template.prompts:
        if p.id not in out and p.default is None and not p.optional:
            out[p.id] = _sample_for(p, env)
    return out


def would_be_path(rel_path: str) -> str:
    """The path ``vault_write.write_new`` would pick right now: ``rel_path``,
    else ``<stem>-2``, ``-3``, … Raises InvalidPath for a path outside the vault."""
    p = PurePosixPath(rel_path)
    for n in range(1, MAX_NAME_ATTEMPTS + 1):
        candidate = rel_path if n == 1 else str(p.with_name(f"{p.stem}-{n}{p.suffix}"))
        if not vault_write.resolve_safe(candidate).exists():
            return candidate
    raise RenderError(f"no free file name near {rel_path}")


@dataclass(frozen=True)
class DryRunResult:
    prompts: tuple[Prompt, ...]
    answers: dict[str, str]
    note: RenderedNote | None
    would_be_filed_at: str | None
    diagnostics: tuple[Diagnostic, ...]
    error: str | None

    @property
    def ok(self) -> bool:
        return self.note is not None and self.error is None

    def to_json(self) -> dict[str, Any]:
        n = self.note
        return {
            "ok": self.ok,
            "prompts": [p.to_json() for p in self.prompts],
            "answers": self.answers,
            "rendered": None if n is None else {
                "path": n.path, "folder": n.folder, "filename": n.filename, "title": n.title,
                "frontmatter": n.frontmatter, "body": n.body, "markdown": n.markdown(),
            },
            "wouldBeFiledAt": self.would_be_filed_at,
            "diagnostics": [d.to_json() for d in self.diagnostics],
            "error": self.error,
        }


def dry_run(
    source: str,
    answers: Mapping[str, Any],
    *,
    template_id: str = "draft",
    env: RenderEnv | None = None,
) -> DryRunResult:
    diagnostics = tuple(lint(source, template_id))
    parsed = parse_template(source, template_id)
    if parsed.template is None:
        first = next((d for d in parsed.diagnostics if d.severity == "error"), None)
        message = f"line {first.line}: {first.message}" if first else "the template has errors"
        return DryRunResult((), {}, None, None, diagnostics, f"template has errors: {message}")
    template = parsed.template
    if env is None:
        from ghostbrain.templates.env import build_env

        env = build_env()
    used = sample_answers(template, answers, env)
    try:
        note = render(template, used, env)
        target = would_be_path(note.path)
    except AnswerError as e:
        return DryRunResult(template.prompts, used, None, None, diagnostics, f"{e.field}: {e}")
    except (RenderError, vault_write.InvalidPath) as e:
        return DryRunResult(template.prompts, used, None, None, diagnostics, str(e))
    return DryRunResult(template.prompts, used, note, target, diagnostics, None)
