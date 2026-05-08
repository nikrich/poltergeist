"""``ghostbrain-recorder`` — run the autonomous meeting recorder daemon."""

from __future__ import annotations

import argparse
import logging
import sys

from ghostbrain.recorder.daemon import run_loop, run_once, DaemonConfig
from ghostbrain.recorder import state as state_mod


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autonomous meeting recorder. Watches calendar, "
                    "auto-records eligible meetings, transcribes + links to vault."
    )
    parser.add_argument("--once", action="store_true",
                        help="Run a single tick and exit (debugging).")
    parser.add_argument("--show-config", action="store_true",
                        help="Print the loaded config and exit.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.show_config:
        cfg = DaemonConfig.load()
        print(f"poll_interval_s : {cfg.poll_interval_s}")
        print(f"end_grace_s     : {cfg.end_grace_s}")
        print(f"audio_device    : {cfg.audio_device}")
        print(f"fallback_output : {cfg.fallback_output or '(none)'}")
        print(f"policy.enabled  : {cfg.policy.enabled}")
        print(f"excluded_titles : {list(cfg.policy.excluded_titles)}")
        print(f"excluded_ctxs   : {list(cfg.policy.excluded_contexts)}")
        print(f"included_ctxs   : {list(cfg.policy.included_contexts) or '(all)'}")
        print(f"calendars       : {cfg.macos_accounts}")
        return

    if args.once:
        cfg = DaemonConfig.load()
        st = state_mod.load()
        run_once(cfg, st)
        return

    run_loop()


if __name__ == "__main__":
    main()
