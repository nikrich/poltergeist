"""Route an event to one of the configured contexts.

Strategy: path-first (free, instant), LLM fallback (only when no rule matches).

- ``route_event(event)`` returns ``(context, confidence, reasoning)``.
- For events with a ``metadata.projectPath`` that matches a rule in
  ``routing.yaml:claude_code.project_paths``, confidence is 1.0 and we never
  call the LLM.
- Otherwise we ask the router LLM (Haiku) to classify.
- If the LLM returns ``"needs_review"`` or confidence < ``reject_below``, we
  fall through and the caller routes to the review queue.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from typing import Any

import yaml

from ghostbrain.llm import client as llm
from ghostbrain.paths import vault_path
from ghostbrain.profile.claude_md import detect_context

log = logging.getLogger("ghostbrain.worker.router")

ROUTER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["context", "confidence", "reasoning"],
    "properties": {
        "context": {
            "type": "string",
            "enum": [
                "sanlam", "codeship", "reducedrecipes", "personal",
                "needs_review",
            ],
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string", "maxLength": 400},
        "secondary_contexts": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
    },
}


@dataclasses.dataclass
class RoutingDecision:
    context: str
    confidence: float
    reasoning: str
    method: str  # "path" | "llm" | "fallback"
    secondary_contexts: list[str] = dataclasses.field(default_factory=list)


def route_event(
    event: dict,
    *,
    content_excerpt: str | None = None,
    routing: dict | None = None,
    config: dict | None = None,
) -> RoutingDecision:
    routing = routing or _load_yaml("routing.yaml")
    config = config or _load_yaml("config.yaml")

    fast = _fast_route(event, routing)
    if fast is not None:
        return fast

    excerpt = content_excerpt or _build_excerpt_from_event(event)
    has_real_content = bool(
        content_excerpt and content_excerpt.strip()
        or event.get("title")
        or event.get("body")
    )
    if not excerpt.strip() or not has_real_content:
        return RoutingDecision(
            context="needs_review",
            confidence=0.0,
            reasoning="no classifiable content",
            method="fallback",
        )

    return _route_via_llm(event, excerpt, config)


def _fast_route(event: dict, routing: dict) -> RoutingDecision | None:
    """Source-specific path-first lookup. Returns None when no rule matches."""
    source = event.get("source") or ""
    metadata = event.get("metadata") or {}

    # Any event carrying a projectPath benefits from claude_code.project_paths
    # — Claude sessions, Obsidian-driven manual events, future IDE hooks etc.
    project_path = metadata.get("projectPath")
    if project_path:
        ctx = detect_context(Path(project_path), routing=routing)
        if ctx:
            log.info("path-routed event=%s ctx=%s path=%s",
                     event.get("id"), ctx, project_path)
            return RoutingDecision(
                context=ctx,
                confidence=1.0,
                reasoning=f"matched routing.yaml rule for {project_path}",
                method="path",
            )

    if source == "github":
        org = metadata.get("org") or _org_from_repo(metadata.get("repo"))
        if org:
            ctx = (routing.get("github") or {}).get("orgs", {}).get(org)
            if ctx:
                log.info("path-routed event=%s ctx=%s github org=%s",
                         event.get("id"), ctx, org)
                return RoutingDecision(
                    context=ctx,
                    confidence=1.0,
                    reasoning=f"matched github org rule for {org}",
                    method="path",
                )

    if source == "jira":
        site = metadata.get("site")
        if site:
            ctx = (routing.get("jira") or {}).get("sites", {}).get(site)
            if ctx:
                log.info("path-routed event=%s ctx=%s jira site=%s",
                         event.get("id"), ctx, site)
                return RoutingDecision(
                    context=ctx,
                    confidence=1.0,
                    reasoning=f"matched jira site rule for {site}",
                    method="path",
                )

    if source == "confluence":
        space = metadata.get("space")
        if space:
            ctx = (routing.get("confluence") or {}).get("spaces", {}).get(space)
            if ctx:
                log.info("path-routed event=%s ctx=%s confluence space=%s",
                         event.get("id"), ctx, space)
                return RoutingDecision(
                    context=ctx,
                    confidence=1.0,
                    reasoning=f"matched confluence space rule for {space}",
                    method="path",
                )

    if source == "gmail":
        # Sender domain has the strongest signal: an email from
        # @sanlam.co.za is sanlam regardless of label noise. Fall back to
        # label prefixes (e.g. "sanlam/policies") and exact label match.
        from_domain = (metadata.get("from_domain") or "").lower()
        if from_domain:
            domains = (routing.get("gmail") or {}).get("sender_domains", {}) or {}
            ctx = domains.get(from_domain)
            if ctx:
                log.info("path-routed event=%s ctx=%s gmail domain=%s",
                         event.get("id"), ctx, from_domain)
                return RoutingDecision(
                    context=ctx,
                    confidence=1.0,
                    reasoning=f"matched gmail sender_domain rule for {from_domain}",
                    method="path",
                )

        labels = [str(l) for l in (metadata.get("labels") or [])]
        prefixes = (routing.get("gmail") or {}).get("label_prefixes", {}) or {}
        for label in labels:
            for prefix, ctx in prefixes.items():
                if label.startswith(prefix):
                    log.info("path-routed event=%s ctx=%s gmail label=%s",
                             event.get("id"), ctx, label)
                    return RoutingDecision(
                        context=ctx,
                        confidence=1.0,
                        reasoning=f"matched gmail label_prefix {prefix} (label={label})",
                        method="path",
                    )

    if source == "slack":
        # Workspace slug is the strongest signal — every message in
        # workspace `sft` is sanlam, regardless of channel or sender.
        slug = (metadata.get("workspace_slug") or "").lower()
        if slug:
            workspaces = (routing.get("slack") or {}).get("workspaces", {}) or {}
            cfg = workspaces.get(slug) or {}
            ctx = cfg.get("context") if isinstance(cfg, dict) else cfg
            if ctx:
                log.info("path-routed event=%s ctx=%s slack workspace=%s",
                         event.get("id"), ctx, slug)
                return RoutingDecision(
                    context=ctx,
                    confidence=1.0,
                    reasoning=f"matched slack workspace rule for {slug}",
                    method="path",
                )

    if source == "calendar":
        provider = metadata.get("provider")
        account = metadata.get("account")
        if provider and account:
            ctx = (
                ((routing.get("calendar") or {}).get(provider) or {})
                .get("accounts", {})
                .get(account)
            )
            if ctx:
                log.info("path-routed event=%s ctx=%s calendar=%s/%s",
                         event.get("id"), ctx, provider, account)
                return RoutingDecision(
                    context=ctx,
                    confidence=1.0,
                    reasoning=(
                        f"matched calendar.{provider}.accounts rule for {account}"
                    ),
                    method="path",
                )

    return None


def _org_from_repo(repo: str | None) -> str | None:
    if not repo or "/" not in repo:
        return None
    return repo.split("/", 1)[0]


def _route_via_llm(event: dict, excerpt: str, config: dict) -> RoutingDecision:
    prompt_template = _read_prompt("router.md")
    prompt = prompt_template.replace("{{content}}", excerpt)

    thresholds = (config.get("thresholds") or {})
    reject_below = float(thresholds.get("reject_below", 0.5))

    try:
        result = llm.run(
            prompt,
            model=(config.get("llm") or {}).get("router_model", "haiku"),
            json_schema=ROUTER_JSON_SCHEMA,
        )
        payload = result.as_json()
    except llm.LLMError as e:
        log.warning("router LLM failed for event=%s: %s", event.get("id"), e)
        return RoutingDecision(
            context="needs_review",
            confidence=0.0,
            reasoning=f"router LLM error: {e}",
            method="fallback",
        )

    ctx = payload.get("context", "needs_review")
    conf = float(payload.get("confidence", 0.0))
    reason = payload.get("reasoning", "")
    secondary = payload.get("secondary_contexts", []) or []

    if ctx == "needs_review" or conf < reject_below:
        log.info("LLM routed to review event=%s conf=%.2f", event.get("id"), conf)

    return RoutingDecision(
        context=ctx,
        confidence=conf,
        reasoning=reason,
        method="llm",
        secondary_contexts=list(secondary)[:3],
    )


def _build_excerpt_from_event(event: dict) -> str:
    parts: list[str] = []
    if event.get("title"):
        parts.append(f"Title: {event['title']}")
    if event.get("source"):
        parts.append(f"Source: {event['source']}")
    if event.get("type"):
        parts.append(f"Type: {event['type']}")
    body = event.get("body")
    if body:
        parts.append(f"\n{body}")
    return "\n".join(parts)


def _load_yaml(name: str) -> dict:
    f = vault_path() / "90-meta" / name
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


def _read_prompt(name: str) -> str:
    f = vault_path() / "90-meta" / "prompts" / name
    if not f.exists():
        raise FileNotFoundError(
            f"missing prompt {name}; re-run `ghostbrain-bootstrap`"
        )
    return f.read_text(encoding="utf-8")
