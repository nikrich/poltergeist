#!/usr/bin/env python3
"""Post-PyInstaller trim of the bundled ArcadeDB runtime.

1. Deletes server-only jars the embedded engine never loads (verified in the
   2026-10-10 spike: a frozen build still passes Cypher + vector checks).
2. Strips the macOS/Windows native libs out of lz4-java: Apple notarization
   rejects unsigned Mach-O files inside archives; lz4-java falls back to its
   pure-Java codec.

Usage: prune-arcadedb.py <sidecar bundle dir>
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

UNUSED_PREFIXES = (
    "arcadedb-studio-", "arcadedb-console-", "arcadedb-graphql-", "arcadedb-postgresw-",
    "arcadedb-redisw-", "arcadedb-mcp-", "arcadedb-bolt-", "arcadedb-server-",
    "undertow-core-", "swagger-core-", "swagger-models-", "swagger-annotations-",
)
STRIP_PREFIXES = ("net/jpountz/util/darwin/", "net/jpountz/util/windows/")


def _strip_jar(jar: Path) -> int:
    tmp = jar.with_suffix(".jar.tmp")
    removed = 0
    with zipfile.ZipFile(jar) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if info.filename.startswith(STRIP_PREFIXES):
                removed += 1
                continue
            dst.writestr(info, src.read(info.filename))
    tmp.replace(jar)
    return removed


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    dirs = [p for p in Path(argv[0]).rglob("jars") if p.parent.name == "arcadedb_embedded"]
    if not dirs:
        print(f"prune-arcadedb: no arcadedb_embedded/jars under {argv[0]}", file=sys.stderr)
        return 2
    for jars in dirs:
        for jar in sorted(jars.glob("*.jar")):
            if jar.name.startswith(UNUSED_PREFIXES):
                jar.unlink()
                print(f"pruned {jar.name}")
            elif jar.name.startswith("lz4-java-"):
                print(f"stripped {_strip_jar(jar)} native libs from {jar.name}")
        if not list(jars.glob("arcadedb-engine-*.jar")):
            print(f"prune-arcadedb: no arcadedb-engine jar left in {jars}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
