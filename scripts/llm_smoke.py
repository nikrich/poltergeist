"""Standalone smoke for ghostbrain.llm.client.

Three deliberate `claude -p` calls so we can see actual cost / cache behavior
under our production config (Haiku, minimal --system-prompt, JSON schema).

Run: .venv/bin/python scripts/llm_smoke.py
"""

from __future__ import annotations

import json
import sys
import time

from ghostbrain.llm import client


ROUTER_LIKE = """\
Classify this content into one of: work, consulting, side-project, personal, needs_review.

Content: The user is iterating on a Python worker that ingests Obsidian vault events
under ~/dev/example. They use pytest, frontmatter,
and the watchdog library.
"""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["context", "confidence", "reasoning"],
    "properties": {
        "context": {
            "type": "string",
            "enum": ["work", "consulting", "side-project",
                     "personal", "needs_review"],
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string", "maxLength": 200},
    },
}


def run_one(label: str, prompt: str, **kwargs) -> client.LLMResult:
    print(f"\n=== {label} ===", flush=True)
    t0 = time.time()
    r = client.run(prompt, **kwargs)
    wall_ms = int((time.time() - t0) * 1000)
    usage = r.raw.get("usage") or {}
    print(f"  model:                         {r.model}")
    print(f"  cost_usd (reported):           ${r.cost_usd:.4f}")
    print(f"  duration_ms (claude reported): {r.duration_ms}")
    print(f"  duration_ms (subprocess wall): {wall_ms}")
    print(f"  input_tokens:                  {usage.get('input_tokens', 0)}")
    print(f"  output_tokens:                 {usage.get('output_tokens', 0)}")
    print(f"  cache_creation_input_tokens:   {usage.get('cache_creation_input_tokens', 0)}")
    print(f"  cache_read_input_tokens:       {usage.get('cache_read_input_tokens', 0)}")
    print(f"  result text:                   {r.text[:200]}")
    print(f"  structured:                    {r.structured}")
    try:
        parsed = r.as_json()
        print(f"  as_json():                     {parsed}")
    except Exception as e:
        print(f"  as_json() FAILED:              {e}")
    return r


def main() -> int:
    print("Running 3 real `claude -p` calls. This costs ~Max quota.")
    print("If cost_usd is huge on every call, our --system-prompt isn't")
    print("stripping the global context as expected.\n")

    r1 = run_one(
        "Call 1: Haiku, router-like prompt, JSON schema (cache miss expected)",
        ROUTER_LIKE, model="haiku", json_schema=SCHEMA,
    )
    r2 = run_one(
        "Call 2: same prompt, same schema (cache hit expected)",
        ROUTER_LIKE, model="haiku", json_schema=SCHEMA,
    )
    r3 = run_one(
        "Call 3: trivial prompt, no schema (cache hit on system prompt)",
        "Respond with the single word 'test'.",
        model="haiku",
    )

    total = r1.cost_usd + r2.cost_usd + r3.cost_usd
    print("\n=== Summary ===")
    print(f"  Total cost across 3 calls: ${total:.4f}")
    print(f"  Avg per call:              ${total/3:.4f}")
    print(f"  Cache miss → hit delta:    "
          f"${r1.cost_usd:.4f} → ${r2.cost_usd:.4f}")

    # Try to verify which model was actually used.
    if "haiku" not in r1.model.lower():
        print(f"\n  WARNING: --model haiku was IGNORED. Got {r1.model!r} instead.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
