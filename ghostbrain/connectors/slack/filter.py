"""LLM-driven keep/skip decision for Slack messages.

The full-pull connector pulls every message the user can read. Without
filtering, that floods the worker queue with bot pings, deploy
notifications, and casual chatter. This module asks Claude to rate each
message 0–3:

    0 = skip (bot noise, automated, off-topic)
    1 = low signal (FYI, maybe-keep)
    2 = signal (decisions, blockers, questions, action requests)
    3 = must-keep (anything addressed to the user, commitments, urgent)

Anything ≥1 is kept by default; the caller can raise the threshold.

Always-keep paths (mentions of self, DMs, the user's own messages, thread
replies to a thread the user participated in) bypass this filter entirely
— this LLM call is only for ambient channel chatter where the cost of
dropping a low-signal message is low.

Batches of ~50 messages per call keep the prompt short and predictable,
and let one LLM round-trip cover a typical day's worth of ambient chatter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ghostbrain.llm import client as llm

log = logging.getLogger("ghostbrain.connectors.slack.filter")

BATCH_SIZE = 25
KEEP_THRESHOLD = 1   # keep score >= this
# Per-batch ceiling, not a target. We rely on Claude Code's session-level
# budgeting and the user's plan-level quota for actual cost control; this
# cap is a runaway-safety belt for buggy prompts. The previous 0.10 was
# tripped by a single long-message batch (0.128 used) and tanked the run.
DEFAULT_BUDGET_USD = 2.00

_SYSTEM_PROMPT = """You are a triage gate for an executive's Slack feed.

You rate each message 0 to 3:
  0 = skip. Bot/automated noise, deploy/CI status, channel join/leave,
      generic announcements with no action implication, off-topic banter.
  1 = low signal. FYI-style info, link drops without context, low-stakes
      conversation worth indexing but not acting on.
  2 = signal. Decisions, blockers, technical discussion, questions to the
      team, action items, status updates from teammates, anything someone
      might reference back to.
  3 = must-keep. Direct asks for the user, commitments, deadlines, urgent
      problems, threads the user is leading.

You return exactly the JSON the schema requires — an array of integers
matching the input order. Nothing else."""

_USER_PROMPT_HEADER = """Rate each of the following Slack messages 0–3. Return one integer per message in input order.

Context for the user receiving this feed:
- They are a senior engineer at a fintech (Sanlam Digisure).
- "Hands-off" channels: random, gifs, anything social — score these 0 unless someone is asking the user directly.
- Bot/automation senders (Apps with no human name) → 0 unless it's a CI failure mentioning a repo the user maintains.
- Anything in a DM is already always-kept upstream; don't apply DM bias here.

Messages:
"""

def _build_schema(expected_count: int) -> dict:
    """Schema with minItems == maxItems == batch length.

    Forces the LLM to emit exactly one integer per input message — if it
    tries to return 49 scores for 50 messages, the JSON-schema validator
    rejects the response and Claude is asked to try again. Previously
    this off-by-one (rare but recurring) made us fall back to keep-all,
    which leaks noise the gate would otherwise filter.
    """
    return {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "minItems": expected_count,
                "maxItems": expected_count,
                "items": {"type": "integer", "minimum": 0, "maximum": 3},
            }
        },
        "required": ["scores"],
        "additionalProperties": False,
    }


@dataclass
class FilterableMessage:
    """The minimum a message needs to be rated.

    The connector decides what to put here — usually channel name, sender
    display name, and the text. Truncate long text to keep the prompt
    bounded; the model doesn't need full message bodies to triage.
    """
    channel: str
    sender: str
    text: str
    is_bot: bool = False


def score_messages(
    messages: list[FilterableMessage],
    *,
    batch_size: int = BATCH_SIZE,
    budget_usd: float = DEFAULT_BUDGET_USD,
    _llm_run=llm.run,
) -> list[int]:
    """Return a parallel list of scores (0–3) for each message.

    The ``_llm_run`` parameter is a test seam — tests inject a fake to
    avoid shelling out to ``claude``. In production it defaults to
    ``llm.run``.
    """
    if not messages:
        return []

    out: list[int] = []
    for start in range(0, len(messages), batch_size):
        batch = messages[start : start + batch_size]
        scores = _score_batch(batch, budget_usd=budget_usd, _llm_run=_llm_run)
        if len(scores) != len(batch):
            log.warning(
                "slack filter: LLM returned %d scores for %d messages; "
                "falling back to keep-all for this batch",
                len(scores), len(batch),
            )
            scores = [KEEP_THRESHOLD] * len(batch)
        out.extend(scores)
    return out


def _score_batch(
    batch: list[FilterableMessage],
    *,
    budget_usd: float,
    _llm_run,
) -> list[int]:
    rendered = "\n".join(
        f"[{i}] #{m.channel} <{m.sender}{' (bot)' if m.is_bot else ''}>: "
        f"{_truncate(m.text, 280)}"
        for i, m in enumerate(batch)
    )
    prompt = _USER_PROMPT_HEADER + rendered

    try:
        result = _llm_run(
            prompt,
            model="haiku",
            json_schema=_build_schema(len(batch)),
            system_prompt=_SYSTEM_PROMPT,
            budget_usd=budget_usd,
        )
    except llm.LLMError as e:
        log.warning(
            "slack filter LLM call failed (%s); keeping all messages in batch",
            e,
        )
        return [KEEP_THRESHOLD] * len(batch)

    parsed = result.as_json()
    raw = parsed.get("scores") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        log.warning("slack filter: unexpected LLM response shape: %r", parsed)
        return [KEEP_THRESHOLD] * len(batch)
    return [_clamp_score(s) for s in raw]


def _clamp_score(s) -> int:
    try:
        v = int(s)
    except (TypeError, ValueError):
        return KEEP_THRESHOLD
    return max(0, min(3, v))


def _truncate(text: str, limit: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
