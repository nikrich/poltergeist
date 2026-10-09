"""In-memory link index over the vault, refreshed incrementally per file.

A refresh stats every indexed file and re-parses only files whose
(st_mtime_ns, st_size) signature changed — size catches two saves inside one
coarse mtime tick. Even with nothing changed, the stat walk of a 30k-note
vault costs a few hundred ms, so it never runs on the request path:

- The first build of a large vault (~8 s for 30k notes) runs on a background
  thread; ``ensure_fresh()`` returns False until it is done and callers answer
  "indexing" rather than block.
- Once ready, ``ensure_fresh()`` returns True at once and serves the current
  data. At most once per ``refresh_interval`` seconds it also starts an
  incremental refresh on a background thread (single-flight: nothing starts
  while a refresh is running), so edits show up on a later request.
- ``refresh()`` is the synchronous, unthrottled variant.
- ``note_changed(rel)`` re-indexes one file at once; the API's own note and
  jot writes call it so their links are visible on the next request.

Consumers: GET /v1/vault/suggest + /backlinks and build_graph (A2), the
ego-graph route (A6), live queries (C2). Not persisted — memory only.
"""
from __future__ import annotations

import logging
import os
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from ghostbrain.paths import vault_path
from ghostbrain.vault_index.parse import NoteEntry, parse_note

log = logging.getLogger("ghostbrain.vault_index")

# Raw connector dumps (00-inbox/raw/<connector>) and 90-meta are not pages a
# user links to; manual jots awaiting routing are.
INDEXED_ROOTS: tuple[str, ...] = (
    "00-inbox/raw/manual",
    "10-daily",
    "20-contexts",
    "30-cross-context",
)
PEOPLE_DIR = "30-cross-context/people"
DEFAULT_REFRESH_INTERVAL = 2.0
MAX_READ_CHARS = 2_000_000


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    exists: bool
    kind: str
    weight: float
    snippet: str


def _inbound_key(target: str) -> str:
    """Bare names resolve case-insensitively, so they are keyed lower-case."""
    return target if "/" in target else target.lower()


class LinkIndex:
    def __init__(
        self,
        root: Path,
        *,
        roots: tuple[str, ...] = INDEXED_ROOTS,
        refresh_interval: float = DEFAULT_REFRESH_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = Path(root)
        self.refresh_interval = refresh_interval
        self._roots = roots
        self._clock = clock
        self._entries: dict[str, NoteEntry] = {}
        self._inbound: dict[str, set[str]] = {}  # _inbound_key(target) -> source paths
        self._by_name: dict[str, set[str]] = {}  # lower-case filename -> paths
        self._data_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._build_guard = threading.Lock()
        self._build_thread: threading.Thread | None = None
        self._refresh_thread: threading.Thread | None = None
        self._last_refresh: float | None = None
        self._generation = 0
        self._ready = False

    # ── state ────────────────────────────────────────────────────────────
    @property
    def generation(self) -> int:
        return self._generation

    @property
    def ready(self) -> bool:
        return self._ready

    # ── refresh ──────────────────────────────────────────────────────────
    def _scan(self) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for top in self._roots:
            base = self.root / top
            if not base.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for name in filenames:
                    if not name.endswith(".md") or name.startswith("."):
                        continue
                    full = os.path.join(dirpath, name)
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    rel = Path(full).relative_to(self.root).as_posix()
                    out[rel] = (st.st_mtime_ns, st.st_size)
        return out

    def _read(self, rel: str, sig: tuple[int, int]) -> NoteEntry | None:
        try:
            with open(self.root / rel, encoding="utf-8", errors="replace") as fh:
                text = fh.read(MAX_READ_CHARS)
        except OSError:
            return None
        try:
            return parse_note(rel, text, mtime_ns=sig[0], size=sig[1])
        except Exception:  # noqa: BLE001 — one bad note must not stop the index
            log.exception("link index: could not parse %s", rel)
            return None

    def _add(self, entry: NoteEntry) -> None:
        self._entries[entry.path] = entry
        for link in entry.links:
            self._inbound.setdefault(_inbound_key(link.target), set()).add(entry.path)
        name = PurePosixPath(entry.path).name.lower()
        self._by_name.setdefault(name, set()).add(entry.path)

    def _drop(self, rel: str) -> None:
        entry = self._entries.pop(rel, None)
        if entry is None:
            return
        for link in entry.links:
            key = _inbound_key(link.target)
            sources = self._inbound.get(key)
            if sources is not None:
                sources.discard(rel)
                if not sources:
                    del self._inbound[key]
        name = PurePosixPath(rel).name.lower()
        paths = self._by_name.get(name)
        if paths is not None:
            paths.discard(rel)
            if not paths:
                del self._by_name[name]

    def _refresh_locked(self) -> None:
        stats = self._scan()
        with self._data_lock:
            known = {p: (e.mtime_ns, e.size) for p, e in self._entries.items()}
        changed = [p for p, sig in stats.items() if known.get(p) != sig]
        removed = [p for p in known if p not in stats]
        parsed = [e for e in (self._read(p, stats[p]) for p in changed) if e is not None]
        if parsed or removed:
            with self._data_lock:
                # note_changed() may have re-indexed a path since the snapshot;
                # only apply changes to entries still as this scan saw them.
                for rel in removed:
                    if self._sig(rel) == known.get(rel):
                        self._drop(rel)
                for entry in parsed:
                    if self._sig(entry.path) == known.get(entry.path):
                        self._drop(entry.path)
                        self._add(entry)
                self._generation += 1
        self._last_refresh = self._clock()
        self._ready = True

    def _sig(self, rel: str) -> tuple[int, int] | None:
        entry = self._entries.get(rel)
        return None if entry is None else (entry.mtime_ns, entry.size)

    def _indexable_rel(self, rel: str) -> str | None:
        """Vault-relative posix key for ``rel`` if _scan() would index it, else None."""
        pure = PurePosixPath(rel.strip().replace("\\", "/"))
        if (
            pure.is_absolute()
            or not pure.parts
            or any(part in ("..", "") or ":" in part or part.startswith(".") for part in pure.parts)
            or not pure.name.endswith(".md")
        ):
            return None
        key = pure.as_posix()
        return key if self._under_indexed_root(key) else None

    def note_changed(self, rel: str) -> None:
        """Re-index one note right after the app wrote (or removed) it.

        The read-your-writes path for the API's own saves, so a backlink shows
        up on the next request instead of after a background refresh. Re-stats
        and re-parses only ``rel``; drops it if the file is gone or not under an
        indexed root. No-op until the cold build is done (it will see the file).
        Never raises.
        """
        try:
            if not self._ready:
                return
            key = self._indexable_rel(rel)
            if key is None:  # never indexed (outside the roots, hidden, not .md)
                return
            try:
                st = os.stat(self.root / key)
                sig: tuple[int, int] | None = (st.st_mtime_ns, st.st_size) if stat.S_ISREG(st.st_mode) else None
            except OSError:
                sig = None
            entry = self._read(key, sig) if sig is not None else None
            with self._data_lock:
                current = self._sig(key)
                if sig is None:
                    if current is None:
                        return
                    self._drop(key)
                elif entry is None or current == sig:
                    return  # unreadable now (keep the last good parse) or unchanged
                else:
                    self._drop(key)
                    self._add(entry)
                self._generation += 1
        except Exception:  # noqa: BLE001 — a save must never fail on the index
            log.exception("link index: note_changed failed for %s", rel)

    def refresh(self) -> None:
        """Synchronous incremental refresh, ignoring the throttle."""
        with self._refresh_lock:
            self._refresh_locked()

    def _build_safely(self) -> None:
        try:
            self.refresh()
        except Exception:  # noqa: BLE001 — logged; the next ensure_fresh retries
            log.exception("link index build failed for %s", self.root)

    def _start_build(self) -> None:
        with self._build_guard:
            if self._ready:
                return
            if self._build_thread is not None and self._build_thread.is_alive():
                return
            thread = threading.Thread(target=self._build_safely, name="link-index-build", daemon=True)
            self._build_thread = thread
            thread.start()

    def wait_until_ready(self, timeout: float) -> bool:
        thread = self._build_thread
        if not self._ready and thread is not None:
            thread.join(timeout=timeout)
        return self._ready

    def _refresh_in_background(self) -> None:
        if not self._refresh_lock.acquire(blocking=False):  # a refresh is already running
            return
        try:
            self._refresh_locked()
        except Exception:  # noqa: BLE001 — logged; a later ensure_fresh retries
            log.exception("link index refresh failed for %s", self.root)
        finally:
            self._refresh_lock.release()

    def _start_refresh(self) -> None:
        """Start one background incremental refresh unless one is in flight."""
        with self._build_guard:
            if self._refresh_lock.locked():
                return
            if self._refresh_thread is not None and self._refresh_thread.is_alive():
                return
            thread = threading.Thread(
                target=self._refresh_in_background, name="link-index-refresh", daemon=True
            )
            self._refresh_thread = thread
            thread.start()

    def _join_refresh(self, timeout: float) -> bool:
        """Wait for the in-flight background refresh (tests). True = none running."""
        thread = self._refresh_thread
        if thread is not None:
            thread.join(timeout=timeout)
            return not thread.is_alive()
        return True

    def ensure_fresh(self, wait: float = 0.25) -> bool:
        """Request-path freshness check. False = cold build still running."""
        if not self._ready:
            self._start_build()
            return self.wait_until_ready(wait) if wait > 0 else self._ready
        last = self._last_refresh
        if last is not None and self._clock() - last < self.refresh_interval:
            return True
        self._start_refresh()  # off the request path; serve current data now
        return True

    # ── queries ──────────────────────────────────────────────────────────
    def get(self, path: str) -> NoteEntry | None:
        with self._data_lock:
            return self._entries.get(path)

    def entries(self) -> list[NoteEntry]:
        with self._data_lock:
            return list(self._entries.values())

    def _resolve(self, target: str) -> str:
        if target in self._entries:
            return target
        if "/" not in target:
            candidates = self._by_name.get(target.lower())
            if candidates and len(candidates) == 1:
                return next(iter(candidates))
        return target

    def resolve(self, target: str) -> str:
        with self._data_lock:
            return self._resolve(target)

    def _under_indexed_root(self, path: str) -> bool:
        return any(path == r or path.startswith(r + "/") for r in self._roots)

    def exists(self, path: str) -> bool:
        with self._data_lock:
            if path in self._entries:
                return True
        if self._under_indexed_root(path):
            return False
        pure = PurePosixPath(path)
        # A part with ":" is a drive letter ("C:/x.md") or an NTFS stream; on
        # Windows ``root / pure`` would swap the drive and stat outside the vault.
        if pure.is_absolute() or ".." in pure.parts or any(":" in part for part in pure.parts):
            return False
        return (self.root / pure).is_file()

    def outgoing(self, path: str) -> list[Edge]:
        with self._data_lock:
            entry = self._entries.get(path)
            if entry is None:
                return []
            resolved = [(self._resolve(link.target), link) for link in entry.links]
        return [
            Edge(path, target, self.exists(target), link.kind, link.weight, link.snippet)
            for target, link in resolved
        ]

    def backlinks(self, path: str) -> list[Edge]:
        out: list[Edge] = []
        with self._data_lock:
            sources = set(self._inbound.get(path, ()))
            name = PurePosixPath(path).name.lower()
            if self._resolve(name) == path:
                sources |= self._inbound.get(name, set())
            for src in sorted(sources):
                if src == path:
                    continue
                entry = self._entries.get(src)
                if entry is None:
                    continue
                for link in entry.links:
                    if self._resolve(link.target) == path:
                        out.append(Edge(src, path, True, link.kind, link.weight, link.snippet))
        return out

    def ghosts(self) -> dict[str, int]:
        with self._data_lock:
            pairs = [(self._resolve(key), len(srcs)) for key, srcs in self._inbound.items()]
        out: dict[str, int] = {}
        for target, n in pairs:
            if not self.exists(target):
                out[target] = out.get(target, 0) + n
        return out


_INDEXES: dict[Path, LinkIndex] = {}
_INDEXES_LOCK = threading.Lock()


def get_link_index(root: Path | None = None) -> LinkIndex:
    """One index per resolved vault root (tests switch VAULT_PATH per test)."""
    key = Path(root if root is not None else vault_path()).resolve()
    with _INDEXES_LOCK:
        index = _INDEXES.get(key)
        if index is None:
            index = LinkIndex(key)
            _INDEXES[key] = index
        return index


def note_written(rel: str, root: Path | None = None) -> None:
    """Re-index ``rel`` in the index for ``root`` (default vault_path()) if this
    process has one; never creates an index. Called by vault_write after every
    write. Never raises."""
    try:
        key = Path(root if root is not None else vault_path()).resolve()
        with _INDEXES_LOCK:
            index = _INDEXES.get(key)
        if index is not None:
            index.note_changed(rel)
    except Exception:  # noqa: BLE001
        log.exception("link index: note_written failed for %s", rel)


def warm_link_index() -> None:
    """Start the background build so the first suggestion doesn't wait. Never raises."""
    try:
        get_link_index().ensure_fresh(wait=0)
    except Exception:  # noqa: BLE001
        log.exception("link index warm-up failed")
