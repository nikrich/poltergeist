"""`ghostbrain-api doctor [--json]` — run every first-run check."""
from __future__ import annotations

import argparse
import sys

from ghostbrain import doctor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostbrain-doctor")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    results = doctor.run_checks(doctor.current_platform())
    if args.json:
        print(doctor.to_json(results, platform=doctor.current_platform()))
    else:
        print(doctor.render_table(results))
    return 1 if any(r.status == "fail" for r in results) else 0
