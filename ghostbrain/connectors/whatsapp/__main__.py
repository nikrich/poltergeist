"""CLI: `python -m ghostbrain.connectors.whatsapp` — one run, prints the result."""
from __future__ import annotations

import logging
from dataclasses import asdict

from ghostbrain.connectors.whatsapp import runner


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = runner.run()
    print(asdict(result))
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
