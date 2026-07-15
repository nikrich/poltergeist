"""Weekly profile-diff applier.

Reads the past 7 days of `<vault>/80-profile/_proposed/*.jsonl`, groups
proposals by ``(field, operation, normalized after-text)``, and acts:

- 3+ corroborating proposals on the **Current** layer (current-projects)
  → auto-apply.
- Any proposals targeting **Stable** layer fields (working-style,
  preferences) → write to ``80-profile/_review.md`` for monthly review.
  Stable changes never auto-apply, regardless of count.
- Contradictions of existing Stable values → ``_review.md`` too.
- 1-2 proposals on Current → discard with audit.

The current-projects.md format uses H2 headings per configured context
(see ``routing_config.contexts()``). The applier appends new bullets
under the heading that matches the proposal's most-frequent context
across its corroborating set, falling back to "personal" if unknown.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ghostbrain import routing_config
from ghostbrain.paths import vault_path
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.profile.apply")

CORROBORATION_THRESHOLD = 3
STABLE_FIELDS = ("working-style", "preferences")
CURRENT_FIELDS = ("current-projects", "people", "decisions")
LOOKBACK_DAYS = 7


@dataclasses.dataclass
class ApplyResult:
    applied: list[str]            # human-readable lines applied
    deferred_for_review: list[str]
    discarded_count: int


def apply_weekly(target_date: date | None = None) -> ApplyResult:
    target_date = target_date or date.today()
    floor = target_date - timedelta(days=LOOKBACK_DAYS)

    proposals = list(_iter_proposals(floor, target_date))
    log.info("read %d proposal(s) from %s..%s", len(proposals), floor, target_date)

    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for p in proposals:
        key = (p["field"], p["operation"], _normalize(p["after"]))
        grouped[key].append(p)

    applied: list[str] = []
    deferred: list[str] = []
    discarded = 0

    review_lines: list[str] = []
    current_projects_additions: list[tuple[str, list[dict]]] = []

    for (field, operation, _norm), group in grouped.items():
        if field in STABLE_FIELDS:
            # Always defer — Stable layer is manual review only.
            deferred.append(_format_summary(group, label="stable"))
            review_lines.extend(_format_review(group, label="stable layer"))
            continue

        if operation == "contradict":
            deferred.append(_format_summary(group, label="contradict"))
            review_lines.extend(_format_review(group, label="contradiction"))
            continue

        if len(group) < CORROBORATION_THRESHOLD:
            discarded += len(group)
            continue

        if field == "current-projects" and operation == "add":
            current_projects_additions.append((group[0]["after"], group))
            applied.append(_format_summary(group, label="add current-project"))
            continue

        # Other current fields: write to review for now (people / decisions
        # need their own writers — out of scope for this phase).
        deferred.append(_format_summary(group, label=f"{field}/{operation}"))
        review_lines.extend(_format_review(group, label=f"{field}/{operation}"))

    if current_projects_additions:
        _apply_current_projects(current_projects_additions)

    if review_lines:
        _write_review(target_date, review_lines)

    audit_log(
        "profile_apply_run",
        target_date.isoformat(),
        applied=len(applied),
        deferred=len(deferred),
        discarded=discarded,
        proposals_read=len(proposals),
    )

    log.info(
        "profile apply: %d applied, %d deferred, %d discarded",
        len(applied), len(deferred), discarded,
    )
    return ApplyResult(
        applied=applied,
        deferred_for_review=deferred,
        discarded_count=discarded,
    )


def _iter_proposals(start: date, end: date) -> Iterable[dict]:
    proposed_dir = vault_path() / "80-profile" / "_proposed"
    if not proposed_dir.exists():
        return
    for f in sorted(proposed_dir.glob("*.jsonl")):
        try:
            day = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if day < start or day > end:
            continue
        with f.open("r", encoding="utf-8") as h:
            for line in h:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    log.warning("malformed proposal line in %s: %r", f, line[:120])


def _apply_current_projects(additions: list[tuple[str, list[dict]]]) -> None:
    """Append new bullets under the right H2 in current-projects.md.

    The H2 heading is chosen by the most common context referenced in the
    parent notes of the corroborating proposals; falls back to ``personal``
    when none of the parents tell us a context.
    """
    target = vault_path() / "80-profile" / "current-projects.md"
    body = target.read_text(encoding="utf-8") if target.exists() else (
        "# Current projects\n\n"
        + "".join(f"## {c}\n\n" for c in routing_config.contexts())
    )

    for after, group in additions:
        ctx = _pick_context(group)
        bullet = f"- {after}"
        body = _insert_bullet_under_h2(body, ctx, bullet)
        audit_log(
            "profile_diff_applied",
            event_id=group[0].get("parent_event_id", ""),
            field="current-projects",
            after=after,
            context=ctx,
            corroboration=len(group),
        )

    target.write_text(body, encoding="utf-8")


def _insert_bullet_under_h2(body: str, heading: str, bullet: str) -> str:
    """Insert ``bullet`` at the end of the section under ``## <heading>``.

    Creates the heading if it doesn't exist. Avoids inserting an exact
    duplicate of the bullet text.
    """
    target_heading = heading.lower().strip()
    lines = body.splitlines()
    sections: list[tuple[int, int, str]] = []  # (start, end, heading_text)

    # Index H2 headings.
    h2_indices: list[int] = [
        i for i, line in enumerate(lines) if re.match(r"^##\s+\S", line)
    ]
    for i, idx in enumerate(h2_indices):
        end = h2_indices[i + 1] if i + 1 < len(h2_indices) else len(lines)
        heading_text = lines[idx][3:].strip().lower()
        sections.append((idx, end, heading_text))

    matching = next((s for s in sections if s[2] == target_heading), None)
    if matching is None:
        # Append a new section at the end.
        lines.extend(["", f"## {heading}", "", bullet])
        return "\n".join(lines) + "\n"

    start, end, _ = matching
    section_text = "\n".join(lines[start:end])
    if bullet in section_text:
        return body  # don't duplicate

    # Find the last non-blank line within the section and insert after it.
    insert_at = end
    for i in range(end - 1, start, -1):
        if lines[i].strip():
            insert_at = i + 1
            break
    new_lines = lines[:insert_at] + [bullet] + lines[insert_at:]
    return "\n".join(new_lines) + ("\n" if not body.endswith("\n") else "")


def _pick_context(group: list[dict]) -> str:
    """Pick an H2 heading bucket for the proposed addition."""
    contexts: list[str] = []
    for p in group:
        path = p.get("parent_note_path") or ""
        ctx = _context_from_path(path)
        if ctx:
            contexts.append(ctx)
    if not contexts:
        return "personal"
    # Most frequent.
    counts: dict[str, int] = defaultdict(int)
    for c in contexts:
        counts[c] += 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _context_from_path(path: str) -> str | None:
    if not path:
        return None
    p = str(path)
    marker = "/20-contexts/"
    if marker not in p:
        return None
    rest = p.split(marker, 1)[1]
    return rest.split("/", 1)[0] if rest else None


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace + strip punctuation. Used for grouping."""
    text = re.sub(r"\s+", " ", text or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return text


def _format_summary(group: list[dict], *, label: str) -> str:
    head = group[0]
    return f"[{label} ×{len(group)}] {head['field']} → {head['after']}"


def _format_review(group: list[dict], *, label: str) -> list[str]:
    head = group[0]
    out = [
        "",
        f"### {head['field']} / {head['operation']} ({label})",
        "",
        f"- **After:** {head['after']}",
    ]
    if head.get("before"):
        out.insert(-1, f"- **Before:** {head['before']}")
    out.append(f"- **Corroborating sessions:** {len(group)}")
    out.append("- **Evidence:**")
    for p in group[:3]:
        ev = (p.get("evidence") or "").strip()
        if ev:
            out.append(f"  - \"{ev[:160]}\"")
    return out


def _write_review(target_date: date, lines: list[str]) -> None:
    out = vault_path() / "80-profile" / "_review.md"
    header = f"# Profile diffs awaiting review\n\nLast updated: {target_date.isoformat()}\n"
    if out.exists():
        existing = out.read_text(encoding="utf-8")
    else:
        existing = header
    block = [
        "",
        f"## {target_date.isoformat()} batch",
        "",
        *lines,
        "",
    ]
    out.write_text(existing.rstrip() + "\n" + "\n".join(block) + "\n",
                   encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly profile-diff applier.")
    parser.add_argument("--date", help="ISO date (YYYY-MM-DD). Default: today.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    target = date.fromisoformat(args.date) if args.date else date.today()
    result = apply_weekly(target)

    print(f"profile-apply for {target.isoformat()}:")
    print(f"  applied:    {len(result.applied)}")
    for line in result.applied:
        print(f"    {line}")
    print(f"  deferred:   {len(result.deferred_for_review)}")
    for line in result.deferred_for_review:
        print(f"    {line}")
    print(f"  discarded:  {result.discarded_count}")


if __name__ == "__main__":
    main()
