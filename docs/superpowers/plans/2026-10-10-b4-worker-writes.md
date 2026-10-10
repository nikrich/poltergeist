# B4 Worker Modifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The three worker jobs that rewrite existing notes (decision reversals, the weekly profile applier, and semantic `related:` links) write through the single vault write path as `worker:<job>`. Their edits stop reformatting frontmatter, never overwrite a note the user saved meanwhile, land in page history, and (reversal and profile) appear on the Changes screen with one-click Revert.

**Architecture:** A small helper module, `ghostbrain/vault_write/jobs.py`, gives jobs two read-compute-write loops: `update_fields` (frontmatter keys) and `rewrite_text` (whole text). Both write against the etag they read and start over on `WriteConflict`, so a user save between the read and the write is never lost. The write path gains `bump_updated` (derived-link writes leave `updated:` alone, as before) and an "unlisted" actor set for `worker:semantic-refresh`, whose high-volume `related:` updates go to page history but not to the Changes screen. `worker/reversal.py` patches `contradicts` / `reversalReasons` / `reversed_by` with `update_fields`. `profile/apply.py` rewrites `current-projects.md` and `_review.md` with `rewrite_text`. `semantic/refresh.py` sets `related:` with `update_fields` through a numpy-free helper.

**Tech Stack:** Python 3.11 stdlib, PyYAML (already a dependency), pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-ai-changes-revert-design.md` (§1 writer table row "`worker/reversal.py`, `profile/apply.py` → `write(fields=…/body=…, actor=worker:<job>)`", §2 "Worker jobs: they call `vault_write.write` in-process with `worker:<job>`", Testing row "Every migrated writer: a golden test that the bytes written equal the previous behaviour, except for the intended no-reformat fix", slice B4). It builds on B2's plan, `docs/superpowers/plans/2026-10-10-b2-changes-revert.md` (Task 2 Interfaces: `records_change`, `set_hold_policy`, the B2 `_write`) and A3's plan, `docs/superpowers/plans/2026-10-09-a3-page-history.md` (Task 3: `_snapshot`, `HistoryUnavailable`).

## Global Constraints

- **B4 must be built on a branch that already contains B2 (change log), and therefore A3 (page history).** Branch from `feat/b2-changes-revert`, or from `main` once B2 is merged. Before Task 1, run `cd "$B4" && python -c "from ghostbrain.vault_write import set_hold_policy, records_change, HistoryUnavailable, worker_actor; from ghostbrain.vault_write.writer import _snapshot; from ghostbrain.changes import log; print(log.list_changes)"`. It must print without an error. If it fails, stop: B2 or A3 is missing.
- B3 (risk policy) is **not** required. If B3 is already merged into the base, `write` / `_write` also carry `approved_change`. Keep it and add `bump_updated` next to it. Everything in this plan treats `status == "pending"` as "held, nothing written" whichever policy is installed.
- Every command runs from the B4 worktree root. Export it once per shell: `export B4=/absolute/path/to/your/b4/worktree`. The commands below use `cd "$B4" && …`. Never run the app, and never touch `~/ghostbrain` or `~/.ghostbrain`. The root `conftest.py` sandboxes `GHOSTBRAIN_STATE_DIR` and `VAULT_PATH`. The `vault` fixture in `tests/conftest.py` bootstraps a vault at `tmp_path` and reloads the worker modules, so import them **inside** each test.
- Actors: `worker:reversal`, `worker:profile-apply`, `worker:semantic-refresh` (all via `vault_write.worker_actor(job)`).
- **Who gets a change row** (B2 rule, unchanged except one addition): every worker *modify* is recorded, every worker *create* is ingest and is not (user decision 1). B4 adds `UNLISTED_ACTORS = {"worker:semantic-refresh"}`: its modifies are not recorded either. They still get page history.
- Derived-link writes (reversal, semantic refresh) pass `bump_updated=False`: before B4 they never touched `updated:`, and they still don't. The profile applier rewrites whole text, so `updated` handling doesn't apply to it.
- Byte parity: reversal and semantic refresh change **only** their own keys' lines (the intended no-reformat fix replaces `frontmatter.dumps`). The profile applier's output is byte-identical to the previous algorithm, including its universal-newline reading of the file.
- Job write failures: reversal and semantic refresh log and continue per note (best-effort, as their docstrings promise). The profile applier lets errors propagate, as before, so the scheduler reports the run failed.
- Python tests run with `python -m pytest`. Every new CI-safe file under `tests/` goes into the fixed list in `.github/workflows/ci.yml`. The CI backend installs only `[dev,api]`: no numpy. `ghostbrain.semantic.refresh` imports numpy only inside functions, and B4's semantic test never calls those functions.
- No new pip or npm dependency. No desktop changes: B2's Changes screen already labels `worker:*` actors (`⚙ reversal`) and filters them under "⚙ jobs".
- No real people's or employer names in code, fixtures or copy.

## Review Focus

1. **The user saves a decision note in the editor while the reversal job links it.** The job's write must not overwrite the save. It must re-read and merge its key into the user's version. Pinned in Task 1 (`test_a_user_save_between_read_and_write_is_kept`, `test_gives_up_after_three_attempts`).
2. **Hand-formatted frontmatter** (comments, flow lists `[a, b]`, quoted titles) on decision notes and on every note semantic refresh touches. Only the job's own keys may change. Before B4, `frontmatter.dumps` rewrote the whole block. Pinned in Task 2 (`test_only_the_link_lines_are_added`) and Task 4 (`test_only_the_related_lines_change`, `test_an_existing_related_block_is_replaced_in_place`).
3. **`updated:` moving when a job adds derived links.** It would reorder "recently edited" lists every 15 minutes. Pinned in Task 1 (`test_update_fields_appends_only_the_new_key`, `test_bump_updated_is_opt_in`) and Task 2.
4. **One bad note** (history store failing, frontmatter that is not a mapping, a note deleted mid-run) must not abort the reversal pipeline or the 15-minute semantic refresh. Pinned in Task 2 (`test_a_history_failure_is_logged_not_raised`) and Task 4 (`test_a_failing_note_is_skipped_not_raised`, `test_missing_or_malformed_notes_are_skipped`).
5. **A job write held for approval** (B3 installed, or any hold policy). The job must carry on and leave the file untouched. Pinned in Task 1 (`test_a_held_job_write_leaves_the_note_alone`), Task 2 (`test_a_held_link_writes_nothing`) and Task 3 (`test_a_held_profile_write_leaves_the_file_alone`).

---

## File Structure

| File | Responsibility |
|---|---|
| `ghostbrain/vault_write/writer.py` | `bump_updated` parameter; `UNLISTED_ACTORS` in `records_change` |
| `ghostbrain/vault_write/jobs.py` (new) | `update_fields`, `rewrite_text`: etag-guarded read-compute-write loops for worker jobs |
| `ghostbrain/vault_write/__init__.py` | Re-export `UNLISTED_ACTORS` |
| `ghostbrain/worker/reversal.py` | `contradicts` / `reversalReasons` / `reversed_by` via `update_fields` as `worker:reversal` |
| `ghostbrain/profile/apply.py` | `current-projects.md` / `_review.md` via `rewrite_text` as `worker:profile-apply` |
| `ghostbrain/semantic/refresh.py` | `related:` via `_apply_related` → `update_fields` as `worker:semantic-refresh` |
| `.github/workflows/ci.yml` | Four new test files plus the existing `tests/test_reversal.py` and `tests/test_profile_apply.py` |

---

### Task 1: Write-path support for worker jobs

**Files:**
- Modify: `ghostbrain/vault_write/writer.py` (B2 version: `_edit_bytes`, `write`, `_write`, `records_change`)
- Modify: `ghostbrain/vault_write/__init__.py`
- Create: `ghostbrain/vault_write/jobs.py`
- Test: `tests/test_vault_write_jobs.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: B2 (`write`, `read`, `resolve_safe`, `records_change`, `set_hold_policy`, `WriteResult`, `WriteConflict`, `MalformedNote`); A3 (`history.store.list_snapshots`, `get_blob`).
- Produces:
  - `vault_write.write(..., bump_updated: bool = True)`. With `False`, a `body` / `fields` edit leaves an existing `updated:` key alone.
  - `writer.UNLISTED_ACTORS: frozenset[str] = frozenset({"worker:semantic-refresh"})`, re-exported from `ghostbrain.vault_write`. `records_change(actor, op)` is `False` for them.
  - `ghostbrain.vault_write.jobs`:
    - `MAX_ATTEMPTS = 3`.
    - `update_fields(rel_path: str, compute: Callable[[dict[str, Any]], Mapping[str, Any]], *, actor: Actor, reason: str, bump_updated: bool = False, attempts: int = MAX_ATTEMPTS) -> WriteResult | None`. `compute(metadata)` returns the fields to set. `{}` means no write (returns `None`). Raises `FileMissing`, `MalformedNote`, `HistoryUnavailable`, and `WriteConflict` after `attempts` conflicting tries.
    - `rewrite_text(rel_path: str, transform: Callable[[str | None], str | None], *, actor: Actor, reason: str, attempts: int = MAX_ATTEMPTS) -> WriteResult | None`. `transform(current text, or None when missing)` returns the new text. `None` or unchanged means no write. A missing file is created. Writes are `verbatim`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vault_write_jobs.py`:

```python
"""B4: helpers for worker jobs that modify existing notes."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.vault_write import (
    UNLISTED_ACTORS,
    USER,
    WriteConflict,
    records_change,
    set_hold_policy,
    worker_actor,
    write,
)
from ghostbrain.vault_write import jobs

REL = "20-contexts/work/decisions/d1.md"
V1 = (
    b"---\nid: d1\n"
    b'title: "Use Postgres"   # chosen in review\n'
    b"tags: [db, infra]\nupdated: 2026-01-02\n---\n\n# Use Postgres\n"
)
JOB = worker_actor("reversal")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"  # the root conftest points VAULT_PATH here
    (root / REL).parent.mkdir(parents=True)
    (root / REL).write_bytes(V1)
    return root


@pytest.fixture(autouse=True)
def _no_holds():
    """These tests are about the helpers; hold mechanics are B2/B3's."""
    set_hold_policy(lambda _p: [])
    yield
    set_hold_policy(None)


def test_update_fields_appends_only_the_new_key(vault):
    res = jobs.update_fields(REL, lambda meta: {"reversed_by": ["[[x]]"]}, actor=JOB, reason="linked")
    assert res is not None and res.status == "applied"
    assert (vault / REL).read_bytes() == V1.replace(b"---\n\n#", b"reversed_by:\n- '[[x]]'\n---\n\n#", 1)
    [row] = changes.list_changes()
    assert (row.actor, row.op, row.reason) == ("worker:reversal", "modify", "linked")


def test_bump_updated_is_opt_in(vault):
    jobs.update_fields(REL, lambda meta: {"related": ["[[y]]"]}, actor=JOB, reason="r",
                       bump_updated=True)
    assert b"updated: 2026-01-02" not in (vault / REL).read_bytes()


def test_nothing_to_change_writes_nothing(vault):
    assert jobs.update_fields(REL, lambda meta: {}, actor=JOB, reason="r") is None
    assert (vault / REL).read_bytes() == V1
    assert changes.list_changes() == []


def test_a_user_save_between_read_and_write_is_kept(vault):
    seen: list[dict] = []

    def compute(meta):
        seen.append(dict(meta))
        if len(seen) == 1:
            write(REL, fields={"reversed_by": ["[[mine]]"]}, actor=USER)  # the user, mid-job
        existing = list(meta.get("reversed_by") or [])
        return {"reversed_by": [*existing, "[[job]]"]}

    jobs.update_fields(REL, compute, actor=JOB, reason="linked")
    assert len(seen) == 2
    assert vault_write.read(REL).metadata()["reversed_by"] == ["[[mine]]", "[[job]]"]


def test_gives_up_after_three_attempts(vault):
    n = {"i": 0}

    def compute(_meta):
        n["i"] += 1
        (vault / REL).write_bytes(V1 + f"outside edit {n['i']}\n".encode())
        return {"x": n["i"]}

    with pytest.raises(WriteConflict):
        jobs.update_fields(REL, compute, actor=JOB, reason="r")
    assert n["i"] == jobs.MAX_ATTEMPTS


def test_a_held_job_write_leaves_the_note_alone(vault):
    set_hold_policy(lambda _p: ["held for test"])
    res = jobs.update_fields(REL, lambda meta: {"reversed_by": ["[[x]]"]}, actor=JOB, reason="r")
    assert res is not None and res.status == "pending"
    assert (vault / REL).read_bytes() == V1


def test_rewrite_text_is_verbatim_and_recorded(vault):
    rel = "80-profile/current-projects.md"
    (vault / rel).parent.mkdir(parents=True)
    (vault / rel).write_bytes(b"# Current projects\n\n## work\n")
    actor = worker_actor("profile-apply")
    res = jobs.rewrite_text(rel, lambda t: t + "- ship it", actor=actor, reason="added")
    assert (vault / rel).read_bytes() == b"# Current projects\n\n## work\n- ship it"
    row = changes.get(int(res.change_id))
    assert (row.actor, row.op) == ("worker:profile-apply", "modify")


def test_rewrite_text_creates_a_missing_file_without_a_row(vault):
    rel = "80-profile/_review.md"
    res = jobs.rewrite_text(rel, lambda t: "# Review\n" if t is None else t,
                            actor=worker_actor("profile-apply"), reason="r")
    assert res.status == "applied" and res.change_id is None  # a worker create is ingest
    assert (vault / rel).read_bytes() == b"# Review\n"


def test_rewrite_text_unchanged_writes_nothing(vault):
    assert jobs.rewrite_text(REL, lambda t: t, actor=JOB, reason="r") is None
    assert jobs.rewrite_text(REL, lambda t: None, actor=JOB, reason="r") is None
    assert (vault / REL).read_bytes() == V1


def test_semantic_refresh_is_unlisted():
    assert "worker:semantic-refresh" in UNLISTED_ACTORS
    assert records_change("worker:semantic-refresh", "modify") is False
    assert records_change("worker:reversal", "modify") is True


def test_an_unlisted_job_still_gets_page_history(vault):
    actor = worker_actor("semantic-refresh")
    res = jobs.update_fields(REL, lambda m: {"related": ["[[a]]"]}, actor=actor, reason="related")
    assert res.change_id is None and changes.list_changes() == []
    [snap] = store.list_snapshots(REL)
    assert snap.actor == "worker:semantic-refresh" and store.get_blob(snap.blob) == V1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B4" && python -m pytest tests/test_vault_write_jobs.py -q`
Expected: FAIL with `ImportError: cannot import name 'UNLISTED_ACTORS' from 'ghostbrain.vault_write'`

- [ ] **Step 3: `bump_updated` and unlisted actors in the writer**

In `ghostbrain/vault_write/writer.py` (B2 version):

Replace the head of `_edit_bytes` up to and including its `if (` condition with:

```python
def _edit_bytes(
    current: bytes,
    *,
    body: str | None,
    fields: Mapping[str, Any] | None,
    suffix: str,
    bump_updated: bool = True,
) -> tuple[bytes, str | None]:
    parsed = parse_note(_decode(current))
    edits = dict(fields or {})
    updated = edits["updated"] if isinstance(edits.get("updated"), str) else None
    if (
        bump_updated
        and "updated" not in edits
        and parsed.has_frontmatter
        and find_key_block(lines_of(parsed.fm_inner), "updated") is not None
    ):
```

(The rest of `_edit_bytes` is unchanged.)

In **both** `write` and `_write`, add this parameter after `verbatim: bool = False,` (after `approved_change` too, if B3 is in the base):

```python
    bump_updated: bool = True,
```

In `write`, pass it on: add `bump_updated=bump_updated,` to the `_write(...)` call. In `_write`, replace the line

```python
                data, updated = _edit_bytes(current, body=body, fields=fields, suffix=src.suffix)
```

with:

```python
                data, updated = _edit_bytes(
                    current, body=body, fields=fields, suffix=src.suffix, bump_updated=bump_updated,
                )
```

Replace B2's `records_change` with:

```python
# Derived metadata refreshed in bulk (semantic `related:` links, every 15
# minutes). Listing each would bury the Changes screen, the same reason
# connector ingest is unlisted (decision 1); page history still keeps them.
UNLISTED_ACTORS: frozenset[str] = frozenset({"worker:semantic-refresh"})


def records_change(actor: Actor, op: Op) -> bool:
    """Spec B §1 step 7: user (and restore) writes get no row. A worker
    *creating* a note is connector ingest: audit log only (decision 1).
    Unlisted derived-metadata jobs get page history only (slice B4)."""
    if actor in (USER, RESTORE) or actor in UNLISTED_ACTORS:
        return False
    return not (actor.startswith("worker:") and op == "create")
```

In `ghostbrain/vault_write/__init__.py`, add `UNLISTED_ACTORS` to the `ghostbrain.vault_write.writer` import list and to `__all__` (after `"USER"`).

- [ ] **Step 4: The job helpers**

Create `ghostbrain/vault_write/jobs.py`:

```python
"""Helpers for in-process worker jobs that change existing notes (slice B4).

Jobs write as ``worker:<job>`` through the single write path, so their edits
are minimal-diff, locked, snapshotted in page history and (except the
unlisted derived-metadata jobs) listed on the Changes screen. Both helpers
read the note, compute the change, and write it against the etag they read.
If the user saves in between, the write path refuses (WriteConflict) and the
helper starts over from the fresh file, so a job never overwrites an edit.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ghostbrain.vault_write.actor import Actor
from ghostbrain.vault_write.errors import MalformedNote, WriteConflict
from ghostbrain.vault_write.etag import compute_etag
from ghostbrain.vault_write.writer import WriteResult, read, resolve_safe, write

MAX_ATTEMPTS = 3


def _gave_up(rel_path: str, attempts: int) -> WriteConflict:
    return WriteConflict(None, f"{rel_path} kept changing; gave up after {attempts} attempts")


def update_fields(
    rel_path: str,
    compute: Callable[[dict[str, Any]], Mapping[str, Any]],
    *,
    actor: Actor,
    reason: str,
    bump_updated: bool = False,
    attempts: int = MAX_ATTEMPTS,
) -> WriteResult | None:
    """Set frontmatter keys. ``compute(metadata)`` returns the fields to set;
    ``{}`` means there is nothing to do (no write, ``None``)."""
    for _ in range(attempts):
        snap = read(rel_path)
        fields = dict(compute(snap.metadata()))
        if not fields:
            return None
        try:
            return write(
                rel_path, fields=fields, actor=actor, reason=reason,
                base_etag=snap.etag, bump_updated=bump_updated,
            )
        except WriteConflict:
            continue  # someone saved in between: recompute from their version
    raise _gave_up(rel_path, attempts)


def _read_text(rel_path: str) -> tuple[str | None, bytes | None]:
    try:
        data = resolve_safe(rel_path).read_bytes()
    except FileNotFoundError:
        return None, None
    try:
        return data.decode("utf-8"), data
    except UnicodeDecodeError as e:
        raise MalformedNote(f"file is not valid UTF-8: {e}") from None


def rewrite_text(
    rel_path: str,
    transform: Callable[[str | None], str | None],
    *,
    actor: Actor,
    reason: str,
    attempts: int = MAX_ATTEMPTS,
) -> WriteResult | None:
    """Replace the whole text. ``transform(current or None when missing)``
    returns the new text; ``None`` or unchanged means no write. The bytes are
    written verbatim. A missing file is created (a worker create: no row)."""
    for _ in range(attempts):
        text, data = _read_text(rel_path)
        new = transform(text)
        if new is None or new == text:
            return None
        try:
            if data is None:
                return write(
                    rel_path, content=new, op="create", actor=actor, reason=reason, verbatim=True,
                )
            return write(
                rel_path, content=new, actor=actor, reason=reason,
                base_etag=compute_etag(data), verbatim=True,
            )
        except WriteConflict:
            continue
    raise _gave_up(rel_path, attempts)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd "$B4" && python -m pytest tests/test_vault_write_jobs.py tests/test_vault_write_changes.py tests/test_vault_write_writer.py tests/test_vault_write_text.py tests/test_vault_write_history.py -q`
Expected: PASS

- [ ] **Step 6: Add the test file to CI**

In `.github/workflows/ci.yml`, add after `tests/test_changes_maintenance.py \` (B2):

```yaml
            tests/test_vault_write_jobs.py \
```

- [ ] **Step 7: Commit**

```bash
cd "$B4" && git add ghostbrain/vault_write tests/test_vault_write_jobs.py .github/workflows/ci.yml && git commit -m "feat(vault-write): etag-guarded helpers for worker jobs; bump_updated; unlisted semantic refresh (B4)"
```

---

### Task 2: Decision reversals as `worker:reversal`

**Files:**
- Modify: `ghostbrain/worker/reversal.py`
- Test: `tests/test_reversal_vault_write.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 (`jobs.update_fields`); `vault_write.worker_actor`, `VaultWriteError`, `HistoryUnavailable`, `set_hold_policy`; B2 (`changes.log.list_changes`).
- Produces:
  - `reversal.REVERSAL_ACTOR = worker_actor("reversal")`.
  - `check_for_reversals(...)`: same signature and `ReversalResult` as before. The new note gains `contradicts` (+ `reversalReasons`), each contradicted note gains a `reversed_by` entry, with only those lines changed and `updated:` untouched. If the new note can't be linked, it returns an empty result. A failing old note is logged and skipped.
  - Private helpers `_vault_rel(path: Path) -> str | None`, `_add_backlink(meta: dict, link: str) -> dict`, `_patch(rel: str, compute, *, reason: str) -> bool` (True when applied or held).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reversal_vault_write.py`:

```python
"""B4: decision reversals write through the vault write path as worker:reversal."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.llm.client import LLMResult
from ghostbrain.vault_write import set_hold_policy

DECISIONS = "20-contexts/work/calendar/artifacts/decisions"
NOW = datetime.now(timezone.utc)
RULING = [{"contradicts_id": "old-1", "reasoning": "earlier said DynamoDB; new picks Postgres"}]


def _llm(payload: dict) -> LLMResult:
    return LLMResult(text=json.dumps(payload), structured=None, model="haiku", cost_usd=0.0,
                     duration_ms=1, session_id="s", raw={})


def _decision(vault: Path, artifact_id: str, title: str, created: datetime, *, extra: str = "") -> Path:
    path = vault / DECISIONS / f"{artifact_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: {artifact_id}\n"
        "context: work\n"
        "type: artifact\n"
        "artifactType: decision\n"
        f"created: '{created.isoformat()}'\n"
        f'title: "{title}"   # from the recorder\n'
        "tags: [db, infra]\n"
        f"{extra}"
        "---\n\n"
        f"# {title}\n\nBody.\n",
        encoding="utf-8",
    )
    return path


def _dump(fields: dict) -> str:
    return yaml.safe_dump(fields, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _run(new_path: Path, reversals: list[dict]):
    from ghostbrain.worker import reversal

    with patch("ghostbrain.worker.reversal.llm.run", return_value=_llm({"reversals": reversals})):
        return reversal.check_for_reversals(new_path)


@pytest.fixture(autouse=True)
def _reset_policy():
    yield
    set_hold_policy(None)


def test_only_the_link_lines_are_added(vault: Path) -> None:
    from ghostbrain.worker import reversal

    old = _decision(vault, "old-1", "Use DynamoDB", NOW - timedelta(days=10),
                    extra="updated: 2026-01-02\n")
    new = _decision(vault, "new-1", "Use Postgres", NOW)
    old_before, new_before = old.read_text(), new.read_text()
    result = _run(new, RULING)
    assert result.contradicted_paths == [old]
    old_link, new_link = reversal._wikilink_for(old), reversal._wikilink_for(new)
    assert old.read_text() == old_before.replace(
        "---\n\n#", _dump({"reversed_by": [new_link]}) + "---\n\n#", 1)
    assert new.read_text() == new_before.replace(
        "---\n\n#",
        _dump({"contradicts": [old_link], "reversalReasons": [RULING[0]["reasoning"]]}) + "---\n\n#",
        1,
    )


def test_reversal_changes_are_listed_and_snapshotted(vault: Path) -> None:
    _decision(vault, "old-1", "Use DynamoDB", NOW - timedelta(days=10))
    new = _decision(vault, "new-1", "Use Postgres", NOW)
    _run(new, RULING)
    rows = changes.list_changes(actor="worker:reversal")
    assert sorted(r.rel_path for r in rows) == [f"{DECISIONS}/new-1.md", f"{DECISIONS}/old-1.md"]
    assert {r.op for r in rows} == {"modify"}
    assert all(store.list_snapshots(r.rel_path) for r in rows)


def test_an_existing_backlink_is_not_duplicated(vault: Path) -> None:
    from ghostbrain.worker import reversal

    new = _decision(vault, "new-1", "Use Postgres", NOW)
    link = reversal._wikilink_for(new)
    old = _decision(vault, "old-1", "Use DynamoDB", NOW - timedelta(days=10),
                    extra=f"reversed_by:\n- '{link}'\n")
    before = old.read_bytes()
    _run(new, RULING)
    assert old.read_bytes() == before
    assert [r.rel_path for r in changes.list_changes(actor="worker:reversal")] == [
        f"{DECISIONS}/new-1.md"]


def test_a_held_link_writes_nothing(vault: Path) -> None:
    set_hold_policy(lambda _p: ["held for test"])
    old = _decision(vault, "old-1", "Use DynamoDB", NOW - timedelta(days=10))
    new = _decision(vault, "new-1", "Use Postgres", NOW)
    before = (old.read_bytes(), new.read_bytes())
    result = _run(new, RULING)
    assert result.contradicted_paths == [old]
    assert (old.read_bytes(), new.read_bytes()) == before
    assert len(changes.list_changes(status="pending")) == 2


def test_a_history_failure_is_logged_not_raised(vault: Path, monkeypatch) -> None:
    from ghostbrain.vault_write import HistoryUnavailable, writer

    def boom(*_a, **_k):
        raise HistoryUnavailable("history unavailable: disk full")

    monkeypatch.setattr(writer, "_snapshot", boom)
    old = _decision(vault, "old-1", "Use DynamoDB", NOW - timedelta(days=10))
    new = _decision(vault, "new-1", "Use Postgres", NOW)
    before = (old.read_bytes(), new.read_bytes())
    result = _run(new, RULING)
    assert result.contradicted_paths == []
    assert (old.read_bytes(), new.read_bytes()) == before
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B4" && python -m pytest tests/test_reversal_vault_write.py -q`
Expected: FAIL. `test_only_the_link_lines_are_added` fails because `frontmatter.dumps` rewrote the block (the comment is gone, `tags` became a block list), and `list_changes(actor="worker:reversal")` is empty.

- [ ] **Step 3: Route the patches through the write path**

In `ghostbrain/worker/reversal.py`:

Add to the module docstring, after its first paragraph:

```
Both patches go through the vault write path as ``worker:reversal`` (spec B,
slice B4): only the link keys' lines change, ``updated:`` is untouched, the
previous version lands in page history, and the change is listed on the
Changes screen with Revert.
```

Below `from ghostbrain.paths import vault_path`, add:

```python
from ghostbrain.vault_write import HistoryUnavailable, VaultWriteError, worker_actor
from ghostbrain.vault_write.jobs import update_fields
```

Below `DEFAULT_MAX_CANDIDATES = 25  # cap LLM input size`, add:

```python
REVERSAL_ACTOR = worker_actor("reversal")
```

In `check_for_reversals`, replace everything from the comment `# Patch the new artifact with \`contradicts:\` pointers.` down to (not including) the final `log.info("decision %s reverses %d earlier decision(s)", …)` with:

```python
    new_rel = _vault_rel(new_artifact_path)
    if new_rel is None:
        log.warning("new artifact %s is outside the vault; not linking it", new_artifact_path)
        return empty
    new_link = _wikilink_for(new_artifact_path)
    reasons = list(reasonings.values())

    def _contradicts(_meta: dict[str, Any]) -> dict[str, Any]:
        fields: dict[str, Any] = {"contradicts": rev_links}
        if reasons:
            fields["reversalReasons"] = reasons
        return fields

    # Patch the new artifact with `contradicts:` pointers.
    if not _patch(new_rel, _contradicts,
                  reason=f"reverses {len(contradicted)} earlier decision(s)"):
        return empty

    # Patch each contradicted artifact with a `reversed_by:` pointer.
    for cand in [by_id[k] for k in reasonings if k in by_id]:
        old_rel = _vault_rel(cand.path)
        if old_rel is None:
            continue
        _patch(old_rel, lambda meta: _add_backlink(meta, new_link),
               reason=f"reversed by {new_link}")
```

Add these helpers in the `# Internals` section, before `_gather_candidates`:

```python
def _vault_rel(path: Path) -> str | None:
    root = vault_path()
    for candidate in (path, path.resolve()):
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            continue
    return None


def _add_backlink(meta: dict[str, Any], link: str) -> dict[str, Any]:
    raw = meta.get("reversed_by")
    existing = list(raw) if isinstance(raw, list) else ([raw] if raw else [])
    if link in existing:
        return {}
    return {"reversed_by": [*existing, link]}


def _patch(rel: str, compute, *, reason: str) -> bool:
    """One frontmatter patch as worker:reversal. True when applied or held
    for approval; False (logged) when it could not be written."""
    try:
        res = update_fields(rel, compute, actor=REVERSAL_ACTOR, reason=reason, bump_updated=False)
    except (VaultWriteError, HistoryUnavailable, OSError) as e:
        log.warning("could not link reversal on %s: %s", rel, e)
        return False
    if res is not None and res.status == "pending":
        log.info("reversal link on %s waits for approval (change #%s)", rel, res.change_id)
    return True
```

`frontmatter` is still used to read the new note and the candidates; keep that import.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$B4" && python -m pytest tests/test_reversal_vault_write.py tests/test_reversal.py -q`
Expected: PASS

- [ ] **Step 5: Add the test files to CI**

In `.github/workflows/ci.yml`, add after `tests/test_vault_write_jobs.py \`:

```yaml
            tests/test_reversal.py \
            tests/test_reversal_vault_write.py \
```

- [ ] **Step 6: Commit**

```bash
cd "$B4" && git add ghostbrain/worker/reversal.py tests/test_reversal_vault_write.py .github/workflows/ci.yml && git commit -m "feat(worker): reversal links write through vault_write as worker:reversal (B4)"
```

---

### Task 3: The weekly profile applier as `worker:profile-apply`

**Files:**
- Modify: `ghostbrain/profile/apply.py`
- Test: `tests/test_profile_apply_vault_write.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 (`jobs.rewrite_text`); `vault_write.worker_actor`, `set_hold_policy`, `WriteResult`; B2 (`changes.log.list_changes`, `changes.revert.revert`); A3 (`store.list_snapshots`).
- Produces:
  - `apply.PROFILE_ACTOR = worker_actor("profile-apply")`, `CURRENT_PROJECTS_REL = "80-profile/current-projects.md"`, `REVIEW_REL = "80-profile/_review.md"`.
  - `apply_weekly(...)`: same signature and `ApplyResult`. Each `profile_diff_applied` audit line gains `status` (`applied`, `pending` or `unchanged`). `_apply_current_projects(additions) -> None` and `_write_review(target_date, lines) -> None` write through `rewrite_text`. The bytes equal the old algorithm's output, which read the file with universal newlines.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_apply_vault_write.py`:

```python
"""B4: the weekly profile applier writes through the vault write path."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.vault_write import set_hold_policy

DAY = date(2026, 5, 7)
CP = "80-profile/current-projects.md"
REVIEW = "80-profile/_review.md"


def _proposal(field: str, after: str, *, op: str = "add", parent_path: str = "") -> dict:
    return {
        "field": field, "operation": op, "before": "", "after": after,
        "evidence": "...", "confidence": 0.92, "proposed_at": "2026-05-07T10:00:00Z",
        "parent_event_id": "x", "parent_session_id": None, "parent_note_path": parent_path,
    }


def _write_proposed(vault: Path, proposals: list[dict]) -> None:
    out = vault / "80-profile" / "_proposed" / "2026-05-05.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(p) + "\n" for p in proposals), encoding="utf-8")


def _three_adds(vault: Path, text: str = "Ship the importer") -> None:
    parent = str(vault / "20-contexts" / "work" / "x" / "p.md")
    _write_proposed(vault, [_proposal("current-projects", text, parent_path=parent) for _ in range(3)])


def _audit_statuses(vault: Path) -> list[str]:
    out: list[str] = []
    for f in sorted((vault / "90-meta" / "audit").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("event_type") == "profile_diff_applied":
                out.append(rec.get("status"))
    return out


@pytest.fixture(autouse=True)
def _reset_policy():
    yield
    set_hold_policy(None)


def test_current_projects_bytes_match_the_old_algorithm(vault: Path) -> None:
    from ghostbrain.profile import apply as ap

    original = (
        "---\nupdated: 2026-01-01  # hand-kept\n---\n# Current projects\n\n"
        "## work\n\n- Existing thing\n\n## personal\n"
    )
    (vault / CP).write_text(original, encoding="utf-8")
    _three_adds(vault)
    ap.apply_weekly(target_date=DAY)
    assert (vault / CP).read_text(encoding="utf-8") == ap._insert_bullet_under_h2(
        original, "work", "- Ship the importer")


def test_the_change_is_listed_as_the_profile_job_and_revertible(vault: Path) -> None:
    from ghostbrain.changes import revert as rv
    from ghostbrain.profile import apply as ap

    before = (vault / CP).read_bytes()  # seeded by bootstrap
    _three_adds(vault)
    ap.apply_weekly(target_date=DAY)
    [row] = changes.list_changes(actor="worker:profile-apply")
    assert (row.rel_path, row.op) == (CP, "modify")
    assert row.reason == "added 1 current project(s) from your sessions"
    [snap] = store.list_snapshots(CP)
    assert snap.actor == "worker:profile-apply" and store.get_blob(snap.blob) == before
    assert _audit_statuses(vault) == ["applied"]
    rv.revert(row.id)
    assert (vault / CP).read_bytes() == before


def test_stable_proposals_append_to_the_review_file(vault: Path) -> None:
    from ghostbrain.profile import apply as ap

    (vault / REVIEW).write_text("# Profile diffs awaiting review\n", encoding="utf-8")
    cp_before = (vault / CP).read_bytes()
    parent = str(vault / "20-contexts" / "work" / "x" / "p.md")
    _write_proposed(vault, [
        _proposal("preferences", "Use ruff over flake8", op="update", parent_path=parent)
        for _ in range(5)
    ])
    ap.apply_weekly(target_date=DAY)
    assert "Use ruff over flake8" in (vault / REVIEW).read_text(encoding="utf-8")
    assert (vault / CP).read_bytes() == cp_before
    [row] = changes.list_changes(actor="worker:profile-apply")
    assert (row.rel_path, row.reason) == (REVIEW, "queued 1 profile change(s) for review")


def test_a_missing_current_projects_is_created_and_not_listed(vault: Path) -> None:
    from ghostbrain.profile import apply as ap

    (vault / CP).unlink()
    _three_adds(vault)
    ap.apply_weekly(target_date=DAY)
    assert "- Ship the importer" in (vault / CP).read_text(encoding="utf-8")
    assert changes.list_changes(actor="worker:profile-apply") == []  # a worker create is ingest


def test_a_held_profile_write_leaves_the_file_alone(vault: Path) -> None:
    from ghostbrain.profile import apply as ap

    set_hold_policy(lambda _p: ["held for test"])
    before = (vault / CP).read_bytes()
    _three_adds(vault)
    result = ap.apply_weekly(target_date=DAY)
    assert len(result.applied) == 1
    assert (vault / CP).read_bytes() == before
    [row] = changes.list_changes(status="pending")
    assert row.rel_path == CP
    assert _audit_statuses(vault) == ["pending"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B4" && python -m pytest tests/test_profile_apply_vault_write.py -q`
Expected: FAIL. `list_changes(actor="worker:profile-apply")` is empty, and the audit lines have no `status`.

- [ ] **Step 3: Route the writes through the write path**

In `ghostbrain/profile/apply.py`:

Add to the end of the module docstring:

```

Both files are written through the vault write path as ``worker:profile-apply``
(spec B, slice B4): against the etag just read (a user edit in between is
re-read, never overwritten), snapshotted in page history, and listed on the
Changes screen.
```

Below `from ghostbrain.worker.audit import audit_log`, add:

```python
from ghostbrain.vault_write import WriteResult, worker_actor
from ghostbrain.vault_write.jobs import rewrite_text
```

Below `LOOKBACK_DAYS = 7`, add:

```python
PROFILE_ACTOR = worker_actor("profile-apply")
CURRENT_PROJECTS_REL = "80-profile/current-projects.md"
REVIEW_REL = "80-profile/_review.md"
```

Replace `_apply_current_projects` with:

```python
def _universal_newlines(text: str) -> str:
    """What ``Path.read_text`` used to hand this module; keeps the output
    byte-identical to the pre-B4 applier."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _status(res: WriteResult | None, rel: str) -> str:
    if res is None:
        return "unchanged"
    if res.status == "pending":
        log.info("profile change to %s waits for approval (change #%s)", rel, res.change_id)
    return res.status


def _apply_current_projects(additions: list[tuple[str, list[dict]]]) -> None:
    """Append new bullets under the right H2 in current-projects.md.

    The H2 heading is chosen by the most common context referenced in the
    parent notes of the corroborating proposals; falls back to ``personal``
    when none of the parents tell us a context.
    """

    def transform(current: str | None) -> str:
        body = _universal_newlines(current) if current is not None else (
            "# Current projects\n\n"
            + "".join(f"## {c}\n\n" for c in routing_config.contexts())
        )
        for after, group in additions:
            body = _insert_bullet_under_h2(body, _pick_context(group), f"- {after}")
        return body

    res = rewrite_text(
        CURRENT_PROJECTS_REL, transform, actor=PROFILE_ACTOR,
        reason=f"added {len(additions)} current project(s) from your sessions",
    )
    status = _status(res, CURRENT_PROJECTS_REL)
    for after, group in additions:
        audit_log(
            "profile_diff_applied",
            event_id=group[0].get("parent_event_id", ""),
            field="current-projects",
            after=after,
            context=_pick_context(group),
            corroboration=len(group),
            status=status,
        )
```

Replace `_write_review` with:

```python
def _write_review(target_date: date, lines: list[str]) -> None:
    header = f"# Profile diffs awaiting review\n\nLast updated: {target_date.isoformat()}\n"
    block = [
        "",
        f"## {target_date.isoformat()} batch",
        "",
        *lines,
        "",
    ]
    count = sum(1 for line in lines if line.startswith("### "))

    def transform(current: str | None) -> str:
        existing = _universal_newlines(current) if current is not None else header
        return existing.rstrip() + "\n" + "\n".join(block) + "\n"

    res = rewrite_text(
        REVIEW_REL, transform, actor=PROFILE_ACTOR,
        reason=f"queued {count} profile change(s) for review",
    )
    _status(res, REVIEW_REL)
```

(`_format_review` starts each group with an `### <field> / <operation>` line, so `count` is the number of groups queued.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$B4" && python -m pytest tests/test_profile_apply_vault_write.py tests/test_profile_apply.py -q`
Expected: PASS

- [ ] **Step 5: Add the test files to CI**

In `.github/workflows/ci.yml`, add after `tests/test_reversal_vault_write.py \`:

```yaml
            tests/test_profile_apply.py \
            tests/test_profile_apply_vault_write.py \
```

- [ ] **Step 6: Commit**

```bash
cd "$B4" && git add ghostbrain/profile/apply.py tests/test_profile_apply_vault_write.py .github/workflows/ci.yml && git commit -m "feat(profile): weekly applier writes through vault_write as worker:profile-apply (B4)"
```

---

### Task 4: Semantic `related:` links as `worker:semantic-refresh`

**Files:**
- Modify: `ghostbrain/semantic/refresh.py`
- Test: `tests/test_semantic_related_write.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 (`jobs.update_fields`, `UNLISTED_ACTORS`); `vault_write.worker_actor`, `VaultWriteError`, `HistoryUnavailable`; A3 (`store.list_snapshots`).
- Produces:
  - `refresh.SEMANTIC_ACTOR = worker_actor("semantic-refresh")`.
  - `refresh._apply_related(rel: str, wikilinks: list[str]) -> bool`: sets `related:` (only that key's lines; `updated:` untouched). Returns `True` only when the note was written. It never raises: a missing, malformed or unwritable note is logged and returns `False`.
  - `_write_related_frontmatter(...)` uses it; `RefreshResult.linked` still counts notes written.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_semantic_related_write.py`:

```python
"""B4: semantic refresh writes related: through the vault write path.

No numpy here: these tests call the write helper directly, so they run in CI
(the [dev,api] install)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ghostbrain.changes import log as changes
from ghostbrain.history import store

REL = "20-contexts/work/notes/plan.md"
V1 = (
    "---\nid: plan\n"
    'title: "Plan"   # pinned\n'
    "tags: [a, b]\nupdated: 2026-01-02\n---\n\n# Plan\n"
).encode()


def _refresh():
    from ghostbrain.semantic import refresh

    return refresh


@pytest.fixture
def note(vault: Path) -> Path:
    p = vault / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(V1)
    return p


def test_only_the_related_lines_change(note: Path) -> None:
    links = ["[[20-contexts/work/notes/other]]", "[[20-contexts/personal/x]]"]
    assert _refresh()._apply_related(REL, links) is True
    dump = yaml.safe_dump({"related": links}, default_flow_style=False, allow_unicode=True,
                          sort_keys=False)
    assert note.read_text() == V1.decode().replace("---\n\n#", dump + "---\n\n#", 1)


def test_unchanged_links_write_nothing(note: Path) -> None:
    r = _refresh()
    assert r._apply_related(REL, ["[[a]]"]) is True
    after = note.read_bytes()
    assert r._apply_related(REL, ["[[a]]"]) is False
    assert note.read_bytes() == after


def test_an_existing_related_block_is_replaced_in_place(vault: Path) -> None:
    p = vault / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nid: plan\nrelated:\n- '[[old]]'\nsource: manual\n---\n\nbody\n")
    assert _refresh()._apply_related(REL, ["[[new]]"]) is True
    assert p.read_text() == "---\nid: plan\nrelated:\n- '[[new]]'\nsource: manual\n---\n\nbody\n"


def test_unlisted_but_kept_in_page_history(note: Path) -> None:
    _refresh()._apply_related(REL, ["[[a]]"])
    assert changes.list_changes() == []
    [snap] = store.list_snapshots(REL)
    assert snap.actor == "worker:semantic-refresh" and store.get_blob(snap.blob) == V1


def test_a_failing_note_is_skipped_not_raised(note: Path, monkeypatch) -> None:
    from ghostbrain.vault_write import HistoryUnavailable, writer

    def boom(*_a, **_k):
        raise HistoryUnavailable("history unavailable: disk full")

    monkeypatch.setattr(writer, "_snapshot", boom)
    assert _refresh()._apply_related(REL, ["[[a]]"]) is False
    assert note.read_bytes() == V1


def test_missing_or_malformed_notes_are_skipped(vault: Path) -> None:
    r = _refresh()
    assert r._apply_related("20-contexts/work/gone.md", ["[[a]]"]) is False
    bad = vault / "20-contexts/work/bad.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("---\n- not: a mapping\n---\n\nbody\n")
    assert r._apply_related("20-contexts/work/bad.md", ["[[a]]"]) is False
    assert bad.read_text() == "---\n- not: a mapping\n---\n\nbody\n"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B4" && python -m pytest tests/test_semantic_related_write.py -q`
Expected: FAIL with `AttributeError: module 'ghostbrain.semantic.refresh' has no attribute '_apply_related'`

- [ ] **Step 3: Route `related:` through the write path**

In `ghostbrain/semantic/refresh.py`:

Add to the module docstring, after its bullet list:

```

``related:`` is written through the vault write path as
``worker:semantic-refresh`` (spec B, slice B4): only that key's lines change,
``updated:`` is untouched, and the previous version lands in page history. The
job is unlisted on the Changes screen (bulk derived metadata, like ingest).
```

Below `from ghostbrain.semantic.projection import build_layout, load_layout, save_layout`, add:

```python
from ghostbrain.vault_write import HistoryUnavailable, VaultWriteError, worker_actor
from ghostbrain.vault_write.jobs import update_fields
```

Below `SKIP_DIR_PARTS: tuple[str, ...] = ()`, add:

```python
SEMANTIC_ACTOR = worker_actor("semantic-refresh")
```

In `_write_related_frontmatter`, replace everything after `if not related:` / `continue` to the end of the loop body (the `full_path` lookup, `frontmatter.load`, the `wikilinks` comparison, `full_path.write_text(...)` and `written += 1`) with:

```python
        wikilinks = [_wikilink_for(p) for p, _ in related]
        if _apply_related(rel, wikilinks):
            written += 1
```

Add after `_write_related_frontmatter`:

```python
def _apply_related(rel: str, wikilinks: list[str]) -> bool:
    """Set ``related:`` on one note through the write path (slice B4).

    True only when the note was written. Never raises: a missing, malformed
    or unwritable note is logged and skipped, so one bad note can't stop a
    refresh that runs every 15 minutes."""
    rel_posix = Path(rel).as_posix()

    def compute(meta: dict) -> dict:
        return {} if meta.get("related") == wikilinks else {"related": wikilinks}

    try:
        res = update_fields(
            rel_posix, compute, actor=SEMANTIC_ACTOR, reason="updated related notes",
            bump_updated=False,
        )
    except (VaultWriteError, HistoryUnavailable, OSError) as e:
        log.warning("could not update related: on %s: %s", rel_posix, e)
        return False
    return res is not None and res.status == "applied"
```

`frontmatter` is still used by `_extract_text_and_context`; keep that import.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$B4" && python -m pytest tests/test_semantic_related_write.py -q`
Expected: PASS

If numpy and sentence-transformers' test doubles are available locally (the `[semantic]` extra), also run the numpy-dependent suite: `cd "$B4" && python -c "import numpy" && python -m pytest tests/test_semantic.py -q`. Expected: PASS. CI does not run it.

- [ ] **Step 5: Add the test file to CI and run the whole B4 set**

In `.github/workflows/ci.yml`, add after `tests/test_profile_apply_vault_write.py \`:

```yaml
            tests/test_semantic_related_write.py \
```

Run: `cd "$B4" && python -m pytest tests/test_vault_write_jobs.py tests/test_reversal.py tests/test_reversal_vault_write.py tests/test_profile_apply.py tests/test_profile_apply_vault_write.py tests/test_semantic_related_write.py tests/test_vault_write_changes.py tests/test_changes_revert.py tests/test_vault_write_writer.py tests/test_vault_write_text.py tests/test_vault_write_history.py ghostbrain/api/tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd "$B4" && git add ghostbrain/semantic/refresh.py tests/test_semantic_related_write.py .github/workflows/ci.yml && git commit -m "feat(semantic): related: links write through vault_write as worker:semantic-refresh (B4)"
```

---

## Manual check (after Task 4, by the user, not the agent)

Agents must not run the app.
- Record a meeting that reverses an earlier decision. Both decision notes appear on the Changes screen under ⚙ reversal, with only the link lines in the diff. Revert one.
- After the weekly profile job runs, `current-projects.md` appears under ⚙ profile-apply. Open the note's page history: the previous version is there.
- After a semantic refresh, open a note whose related links changed: its page history shows a `worker:semantic-refresh` version, and the Changes screen does not list it.

## Self-review

- **Spec coverage.** §1 writer table "`worker/reversal.py`, `profile/apply.py` → `write(fields=…/body=…, actor=worker:<job>)`" → Tasks 2 and 3 (reversal with `fields`; profile with whole-text `content`, because the applier's algorithm is a whole-text transform). The user's brief adds `semantic/refresh.py` → Task 4. §2 "Worker jobs call `vault_write.write` in-process with `worker:<job>`" → all three, through Task 1's helpers. §1 step 2 etag check for workers ("`base_etag` required for actor != worker" makes it optional) → Task 1 sends it anyway and retries, so a job never overwrites a user save. Step 5 snapshot → A3 inside the write path, pinned in Tasks 1, 3 and 4. Step 7 change row → B2, pinned for reversal and profile. Decision 1 (ingest unlisted) → worker creates stay unlisted (Task 3 test), and semantic refresh joins them (Decisions). Testing row "golden test that the bytes written equal the previous behaviour, except for the intended no-reformat fix" → Task 3 (byte-identical), Tasks 2 and 4 (only the job's keys change: the intended fix).
- **Placeholder scan.** Every code step carries full code. Edits to B2-owned code quote the exact lines replaced.
- **Type consistency.** `update_fields` / `rewrite_text` return `WriteResult | None` everywhere. `bump_updated` defaults to `True` in `write` (B1–B3 behaviour) and to `False` in `update_fields` (jobs). `UNLISTED_ACTORS` is a `frozenset[str]` of full actor strings, matched against the parsed actor. Actor names are built with `worker_actor(...)` in each module and asserted as literal strings in tests.
- **Review Focus.** All five lines are pinned by named tests in their owning tasks.

## Decisions on ambiguities (resolved in this plan)

1. **Semantic refresh is unlisted on the Changes screen** but keeps page history. It rewrites `related:` on many notes every 15 minutes, and listing each would bury the screen. That is the same reason the user gave for keeping connector ingest off it (decision 1). It isn't an LLM job, and it only touches derived links. To list it instead, remove it from `UNLISTED_ACTORS`.
2. **Jobs always send `base_etag` and retry three times on conflict,** though the spec makes the etag optional for workers. A job's read-compute-write spans an LLM call or an embedding pass, and without the etag a user save in that window would be silently overwritten.
3. **Derived-link writes leave `updated:` alone** (`bump_updated=False`), matching their pre-B4 behaviour. Bumping it on every `related:` refresh would reorder "recently edited" views every 15 minutes.
4. **The profile applier rewrites whole text** (`content=`, verbatim) rather than `body=`. Its transform works on the whole file, frontmatter included, and the golden test pins byte parity with the old algorithm, including its universal-newline read.
5. **Failure handling follows each job's existing contract.** Reversal and semantic refresh are best-effort: log and continue per note. If the new decision note can't be linked, nothing else is patched. The profile applier propagates errors, so the scheduler reports a failed run, as before.
6. **A held job write** (B3 present) is logged and treated as done for that run. The proposal waits on the Changes screen, and the job does not retry it.
7. **Out of scope:** `profile/claude_md.py`, `profile/decay.py` and the digest writers. B1 deferred only these three jobs, and the others write app-owned files, not the user's notes.
