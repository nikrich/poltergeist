"""``ghostbrain-semantic-refresh`` CLI."""

from __future__ import annotations

import argparse
import logging

from ghostbrain.semantic.refresh import (
    DEFAULT_MIN_SIMILARITY,
    DEFAULT_TOP_K,
    refresh,
)
from ghostbrain.worker.audit import audit_log


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed every vault note + write related: frontmatter."
    )
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                        help=f"Top related notes to surface (default {DEFAULT_TOP_K}).")
    parser.add_argument("--min-similarity", type=float,
                        default=DEFAULT_MIN_SIMILARITY,
                        help=f"Cosine threshold (default {DEFAULT_MIN_SIMILARITY}).")
    parser.add_argument("--cross-context", action="store_true",
                        help="Only surface related notes from other contexts.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    result = refresh(
        top_k=args.top_k,
        min_similarity=args.min_similarity,
        cross_context_only=args.cross_context,
    )

    audit_log(
        "semantic_refresh",
        embedded=result.embedded,
        reused=result.reused,
        linked=result.linked,
        skipped=result.skipped,
        total=result.total,
    )

    print(f"semantic refresh complete:")
    print(f"  embedded: {result.embedded}")
    print(f"  reused:   {result.reused}")
    print(f"  linked:   {result.linked}")
    print(f"  skipped:  {result.skipped}")
    print(f"  total:    {result.total}")


if __name__ == "__main__":
    main()
