"""Vault filesystem aggregates."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.paths import queue_dir, state_dir, vault_path


def _walk_size(root: Path) -> tuple[int, int]:
    """Returns (markdown_count, total_bytes) for the subtree."""
    md_count = 0
    total_bytes = 0
    for path in root.rglob("*"):
        if path.is_file():
            total_bytes += path.stat().st_size
            if path.suffix == ".md":
                md_count += 1
    return md_count, total_bytes


def _max_last_run() -> str | None:
    """Newest timestamp across all <connector>.last_run files."""
    state = state_dir()
    if not state.exists():
        return None
    last_runs: list[str] = []
    for path in state.glob("*.last_run"):
        try:
            ts = path.read_text().strip()
        except OSError:
            continue
        if ts:
            last_runs.append(ts)
    return max(last_runs) if last_runs else None


def _inbox_count() -> int:
    """Total captures sitting in <vault>/00-inbox/raw/<source>/."""
    inbox = vault_path() / "00-inbox" / "raw"
    if not inbox.exists():
        return 0
    return sum(1 for _ in inbox.glob("*/*.md"))


def get_vault_stats() -> dict:
    vault = vault_path()
    queue = queue_dir() / "pending"
    if vault.exists():
        md_count, total_bytes = _walk_size(vault)
    else:
        md_count, total_bytes = 0, 0
    pending_count = sum(1 for p in queue.iterdir() if p.is_file()) if queue.exists() else 0
    return {
        "totalNotes": md_count,
        "queuePending": pending_count,
        "vaultSizeBytes": total_bytes,
        "lastSyncAt": _max_last_run(),
        "indexedCount": _inbox_count(),
    }
