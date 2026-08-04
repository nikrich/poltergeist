"""``ghostbrain-recorder-recover`` — sweep orphan manual recordings.

Transcribes any ``*-manual.wav`` files under ``~/ghostbrain/recorder/recordings/``
that don't yet have a transcript in the vault, derives a title with the LLM,
and files the markdown under ``20-contexts/<ctx>/calendar/transcripts/``.

Idempotent: each transcript is stamped with the source wav filename in its
frontmatter, so re-running the command skips already-filed recordings.
"""
from __future__ import annotations

import argparse
import logging

from ghostbrain.recorder.manual import load_config, run_recovery_pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recover orphan manual recordings — transcribe + file.",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print the manual-recording config and exit.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config()
    if args.show_config:
        print(f"enabled        : {cfg.enabled}")
        print(f"context        : {cfg.context}")
        print(f"recordings_dir : {cfg.recordings_dir}")
        return

    recovered = run_recovery_pass(cfg)
    if not recovered:
        print("nothing to recover")
        return
    print(f"recovered {len(recovered)} recording(s):")
    for path in recovered:
        print(f"  → {path}")


if __name__ == "__main__":
    main()
