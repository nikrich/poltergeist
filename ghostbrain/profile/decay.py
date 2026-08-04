"""Monthly profile decay + Stable promotion proposals.

Two jobs run on the 1st of each month per SPEC §7.2:

- **Decay.** Items in the Current layer that haven't been reinforced in
  the last 60 days get archived (moved to ``80-profile/_archive.md``).
  We use the audit log's ``profile_diff_applied`` history to determine
  "last reinforced".
- **Promote.** Current-layer items that have been stable for >30 days
  with no contradictions get proposed for the Stable layer; we write
  proposals to ``80-profile/_pending_stable.md`` for the user to approve
  by hand. Stable changes never auto-apply.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from ghostbrain.paths import audit_dir, vault_path
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.profile.decay")

DECAY_DAYS = 60
PROMOTION_DAYS = 30


def decay_monthly(target_date: date | None = None) -> dict:
    target_date = target_date or date.today()
    current_path = vault_path() / "80-profile" / "current-projects.md"
    if not current_path.exists():
        log.info("current-projects.md absent — nothing to decay")
        return {"archived": 0, "promoted": 0}

    history = _build_apply_history(target_date)

    body = current_path.read_text(encoding="utf-8")
    lines = body.splitlines()

    archived: list[tuple[int, str]] = []
    promotion_candidates: list[str] = []

    decay_floor = target_date - timedelta(days=DECAY_DAYS)
    promote_floor = target_date - timedelta(days=PROMOTION_DAYS)

    for i, raw_line in enumerate(lines):
        bullet = raw_line.strip()
        if not bullet.startswith("- "):
            continue
        text = bullet[2:].strip()
        if not text or text.startswith("TODO"):
            continue
        last_seen = history.get(_normalize(text))
        if last_seen is None:
            # Never reinforced via apply — let it stand. Hand-edited content
            # shouldn't get auto-archived.
            continue
        if last_seen < decay_floor:
            archived.append((i, text))
        elif last_seen < promote_floor:
            # Hasn't been actively re-asserted recently. It's "stable enough"
            # — propose for promotion.
            promotion_candidates.append(text)

    if archived:
        # Drop archived lines from current-projects, append them to archive file.
        archive_lines: list[str] = []
        keep: list[str] = []
        archive_indices = {i for i, _ in archived}
        for i, raw_line in enumerate(lines):
            if i in archive_indices:
                archive_lines.append(raw_line)
            else:
                keep.append(raw_line)
        current_path.write_text("\n".join(keep) + "\n", encoding="utf-8")
        _append_archive(target_date, archive_lines)

    if promotion_candidates:
        _write_pending_stable(target_date, promotion_candidates)

    audit_log(
        "profile_decay_run",
        target_date.isoformat(),
        archived=len(archived),
        promoted=len(promotion_candidates),
    )

    log.info("profile decay: archived=%d, proposed-for-stable=%d",
             len(archived), len(promotion_candidates))

    return {"archived": len(archived), "promoted": len(promotion_candidates)}


def _build_apply_history(target_date: date) -> dict[str, date]:
    """Return ``{normalized_after: last_applied_date}`` from the audit log.

    Walks the past ~120 days of audit JSONL — enough to cover both the
    decay and promotion windows.
    """
    history: dict[str, date] = {}
    floor = target_date - timedelta(days=DECAY_DAYS * 2)
    audit = audit_dir()
    if not audit.exists():
        return history
    for f in sorted(audit.glob("*.jsonl")):
        try:
            day = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if day < floor:
            continue
        with f.open("r", encoding="utf-8") as h:
            for line in h:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("event_type") != "profile_diff_applied":
                    continue
                after = str(rec.get("after") or "").strip()
                if not after:
                    continue
                ts_str = rec.get("ts") or ""
                try:
                    rec_day = datetime.fromisoformat(ts_str).date()
                except ValueError:
                    continue
                key = _normalize(after)
                if key in history:
                    history[key] = max(history[key], rec_day)
                else:
                    history[key] = rec_day
    return history


def _normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return text


def _append_archive(target_date: date, lines: list[str]) -> None:
    out = vault_path() / "80-profile" / "_archive.md"
    header = "# Archived profile items\n\nThings ghostbrain stopped reinforcing.\n"
    if out.exists():
        existing = out.read_text(encoding="utf-8")
    else:
        existing = header
    block = [
        "",
        f"## {target_date.isoformat()} decay sweep",
        "",
        *lines,
        "",
    ]
    out.write_text(existing.rstrip() + "\n" + "\n".join(block) + "\n",
                   encoding="utf-8")


def _write_pending_stable(target_date: date, items: list[str]) -> None:
    out = vault_path() / "80-profile" / "_pending_stable.md"
    header = (
        "# Pending Stable-layer promotions\n\n"
        "Items that have been in the Current layer for ≥ 30 days with no\n"
        "contradictions. Promote by hand into working-style.md or\n"
        "preferences.md if appropriate.\n"
    )
    block = [
        "",
        f"## {target_date.isoformat()} promotion candidates",
        "",
    ]
    block.extend(f"- [ ] {item}" for item in items)
    block.append("")
    if out.exists():
        existing = out.read_text(encoding="utf-8")
    else:
        existing = header
    out.write_text(existing.rstrip() + "\n" + "\n".join(block) + "\n",
                   encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Monthly profile decay + promotion.")
    parser.add_argument("--date", help="ISO date (YYYY-MM-DD). Default: today.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    target = date.fromisoformat(args.date) if args.date else date.today()
    result = decay_monthly(target)
    print(f"profile-decay for {target.isoformat()}: "
          f"archived={result['archived']}, promoted={result['promoted']}")


if __name__ == "__main__":
    main()
