# B3 Risk Policy + Approvals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Risky changes by assistants, MCP tools, plugins and worker jobs wait as **pending** until the user approves them on the Changes screen. A pending change writes nothing. Approving it writes it against the current file, refusing (unless forced) when the note changed since the proposal. Rejecting it closes it. A nav badge shows how many changes are waiting.

**Architecture:** A new `ghostbrain/vault_write/risk.py` holds the rules (spec B §3) as one pure function, `evaluate(ProposedChange) -> list[str]`. It becomes the **default** hold policy behind B2's `set_hold_policy` hook, so every write the change log records goes through it. A non-empty reason list makes B2's `_write` store a `pending` row and write nothing. `ghostbrain/changes/approve.py` approves a pending row by re-running the write path as the change's own actor with the hold skipped (`write(..., approved_change=id)`), which turns the pending row into the applied row. B2's Revert then works on it unchanged. Write routes report `status: "pending"` so plugins, the MCP tool and the editor know nothing was written. On the desktop, a polled `usePendingChanges` query feeds both the sidebar badge and a Pending section at the top of B2's Changes screen. The guarded editor puts its buffer back on the saved text when an assistant save comes back held, so the held text can't slip through as a later user keystroke.

**Tech Stack:** Python 3.11 stdlib (`re`, `difflib`, `sqlite3`), FastAPI, pytest; React 18 + TanStack Query 5 + zustand, Vitest + Testing Library, `tsc -b`.

**Spec:** `docs/superpowers/specs/2026-10-09-ai-changes-revert-design.md` (§3 risk policy, §4 statuses, §5 approve/reject routes, §6 Pending section and nav badge, the "Approving a stale pending change" error row, and the risk-rule testing row). It builds on B2's plan, `docs/superpowers/plans/2026-10-10-b2-changes-revert.md` (read its Tasks 1, 2, 3, 6, 9 and 10 Interfaces first), and A3's plan, `docs/superpowers/plans/2026-10-09-a3-page-history.md` (Task 1–3 Interfaces, `LineDiffView`, `actorLabel`).

## Global Constraints

- **B3 must be built on a branch that already contains B2 (change log + Changes screen), and therefore A3 (page history).** Branch from `feat/b2-changes-revert`, or from `main` once B2 is merged. Before Task 1, run `cd "$B3" && python -c "from ghostbrain.vault_write import set_hold_policy, ProposedChange, records_change; from ghostbrain.changes import log, revert; import ghostbrain.history as h; print(log.record, revert.revert, h.put_blob)"` and `test -f "$B3/desktop/src/renderer/screens/changes.tsx"`. Both must succeed. If either fails, stop: B2 or A3 is missing.
- Every command runs from the B3 worktree root. Export it once per shell: `export B3=/absolute/path/to/your/b3/worktree`. The commands below use `cd "$B3" && …`. Never run the app, and never touch `~/ghostbrain` or `~/.ghostbrain`. The root `conftest.py` sandboxes `GHOSTBRAIN_STATE_DIR` and `VAULT_PATH` per test.
- B2's interfaces are used **exactly** as its plan defines them: `changes.log.record/get/list_changes/set_status/counts/last_after_blob/referenced_blobs/mark_degraded/ChangeLogError/Change` (with `.current_path`, `.to_api()`); `changes.revert.Flip/read_current/matches_blob/drift/changed_since/ChangeNotFound/VersionGone/RevertError/_lock`; `vault_write.ProposedChange(actor, op, rel_path, dest_path, before, after, reason)`, `HoldPolicy`, `set_hold_policy`, `records_change`, `write(..., verbatim=)`, `WriteResult(status, change_id, etag, path, updated, history_ok)`; the `/v1/changes` list/detail shapes; `ChangesScreen`, `useChanges`, `useChange`, `ChangeSummary`, `ChangesListResponse`, `ChangeDetailResponse`, `ChangeActionResponse`; `GuardedSave.attributeNext`.
- **User decisions (2026-10-09), verbatim from the spec:** connector ingest stays audit-only (worker creates are never evaluated, because B2 never records them); assistant-created *new* notes apply immediately and are revertible (only the risk rules hold changes); plugins may edit `90-meta` but those changes are **always pending** (a path rule, no hard block).
- **Risk rules (spec §3), applied to every change B2 records** (any actor except `user` and `restore`, and not a `worker:*` create):
  - Path: anything under `90-meta/` (config, routing, prompts, templates, accounts); the Stable profile files `80-profile/working-style.md` and `80-profile/preferences.md`; anything under `90-meta/templates/` (spec C's templates folder). Both the source and a move destination are checked. Matching is case-insensitive, because macOS and Windows vaults are.
  - Content, **only on lines the change adds**: HTML `<script`, `on…=` event handlers, `javascript:` URLs, template expressions (`{{ name }}`, `{{ a.b | filter: x }}`), and executable fences (`dataviewjs` anywhere; `js` / `javascript` inside a template file).
  - Deletes and moves of files the actor didn't create. "Created" means an `applied` `create` row by that actor at that path, possibly followed by that actor's own `applied` moves. Exception: `worker:jot-router`, whose job is filing the user's jots.
  - A failing rule or an unreadable change log **holds** the change (fail closed).
- Statuses used: `pending` (held), `applied` (approved), `rejected`. A stale approval returns 409 and leaves the row `pending`. `conflicted` stays unused (see Decisions).
- Approval is **user-only** (403 for any other actor header), like revert. Approve and reject need no etag. The write they trigger is checked against the bytes the proposal was made against.
- Approval writes **as the change's own actor** with `approved_change=<id>`. The hold policy is skipped, the before-version is snapshotted (A3; a history failure refuses the write), and the pending row becomes `applied` with fresh `before_blob`/`after_blob`. No second row is added.
- No new pip or npm dependency.
- Python tests run with `python -m pytest`. Every new CI-safe file under `tests/` goes into the fixed list in `.github/workflows/ci.yml`. Files under `ghostbrain/api/tests/` are picked up automatically. The CI backend installs only `[dev,api]`.
- Desktop gates: `npm run typecheck` (tsc -b), `npx vitest run`, `npm run lint` (`--max-warnings 0`). Windows release builds rerun the desktop tests, so assertions must not depend on POSIX paths, line endings, the time zone or the locale.
- No real people's or employer names in code, fixtures or copy.

## Review Focus

1. **The jot router filing the user's inbox jots.** The ownership rule would hold every routing move, since the router never creates jots, and routing would silently stop. It must stay applied. Pinned in Task 2 (`test_the_jot_router_may_move_your_jots`, `test_jot_routing_is_never_held`).
2. **Approving after the user edited the note since the proposal.** It must refuse with a diff of what changed, write nothing and keep the row pending. A forced approval must keep the user's version in page history. Pinned in Task 3 (`test_approving_a_stale_proposal_refuses_and_writes_nothing`, `test_forced_approval_keeps_the_overwritten_version_in_history`) and Task 5 over HTTP (`test_stale_approval_is_409_until_forced`).
3. **An assistant Accept in the editor that comes back held, with the user still typing.** The queued keystrokes contain the held text. Saving them as the user would write the change without approval. Pinned in Task 8 (`a held change is not marked saved and drops text queued on top of it`, `a held assistant change puts the editor back on the saved text and says why`).
4. **Protected paths written with different case** (`90-Meta/…`, `80-profile/Preferences.md`) on a case-insensitive vault. They are the same files and must be held. Pinned in Task 2 (`test_path_rules` cases).
5. **A plugin moving its own note into a subfolder, then deleting it.** Ownership must follow its own moves, or every plugin clean-up turns into an approval prompt. Moving someone else's note must not transfer ownership. Pinned in Task 1 (`test_created_by_follows_the_actors_own_moves`, `test_moving_someone_elses_note_does_not_make_it_yours`) and Task 2 (`test_a_plugin_may_move_and_delete_its_own_notes`).

---

## File Structure

| File | Responsibility |
|---|---|
| `ghostbrain/changes/log.py` | + `created_by` (ownership walk), `apply_pending` (pending → applied) |
| `ghostbrain/changes/__init__.py` | Re-export the two new functions |
| `ghostbrain/vault_write/risk.py` (new) | The risk rules: `evaluate(ProposedChange) -> list[str]`, reason strings, `added_lines` |
| `ghostbrain/vault_write/writer.py` | Risk rules are the default hold policy; `approved_change` parameter; `_mark_approved` |
| `ghostbrain/changes/revert.py` | `held_flip`; `expected_state` covers pending rows (drift for the detail route) |
| `ghostbrain/changes/approve.py` (new) | `approve` / `reject`, `StaleProposal`, `NotApprovable` |
| `ghostbrain/api/repo/note.py`, `ghostbrain/api/repo/notes_manual.py`, `ghostbrain/api/repo/generated_docs.py`, `ghostbrain/api/models/docs.py` | Write results carry `status` / `changeId`; `delete_jot` returns its `WriteResult` |
| `ghostbrain/api/routes/notes.py` | `DELETE /v1/notes/{id}` answers 202 when held |
| `ghostbrain/mcp/tools.py` | `poltergeist_write_doc` tells the agent when a doc waits for approval |
| `ghostbrain/api/routes/changes.py` | `POST /v1/changes/{id}/approve`, `POST /v1/changes/{id}/reject` |
| `desktop/src/shared/api-types.ts` | `ChangeRejectResponse`; `status` / `changeId` on save responses |
| `desktop/src/renderer/lib/api/hooks.ts` | `PENDING_CHANGES_PATH`, `usePendingChanges`, `useApproveChange`, `useRejectChange` |
| `desktop/src/renderer/components/PendingChangesBadge.tsx` (new), `desktop/src/renderer/components/Sidebar.tsx` | Nav badge |
| `desktop/src/renderer/components/PendingChanges.tsx` (new), `desktop/src/renderer/screens/changes.tsx` | Pending section with Approve / Reject |
| `desktop/src/renderer/lib/use-guarded-save.ts`, `desktop/src/renderer/components/GuardedNoteEditor.tsx` | Held saves reset the buffer |
| `.github/workflows/ci.yml` | `tests/test_vault_write_risk.py`, `tests/test_changes_approve.py`, `tests/test_mcp_tools.py` |

---

### Task 1: Change log — ownership walk and pending → applied

**Files:**
- Modify: `ghostbrain/changes/log.py`
- Modify: `ghostbrain/changes/__init__.py`
- Test: `tests/test_changes_log.py` (append)

**Interfaces:**
- Consumes: B2 Task 1 (`_connect`, `record`, `set_status`, `get`, the `changes` table).
- Produces (importable from `ghostbrain.changes` and `ghostbrain.changes.log`):
  - `created_by(path: str, actor: str) -> bool`: true when `actor` has an `applied` `create` row at `path`, or reached `path` through a chain (at most `MAX_OWNERSHIP_HOPS = 50`) of its own `applied` `move` rows that starts at such a create. Raises `ChangeLogError`.
  - `apply_pending(change_id: int, *, before_blob: str | None, after_blob: str | None) -> bool`: compare-and-set `pending` → `applied`. It sets both blob columns, keeps `pending_bytes_blob` and `risk_reasons`, and clears `resolved_ts`. Returns `False` when the row is not pending.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_changes_log.py`:

```python
def test_created_by_follows_the_actors_own_moves():
    changes.record(actor="plugin:familiar", rel_path="F/a.md", op="create", after_blob=B)
    assert changes.created_by("F/a.md", "plugin:familiar") is True
    assert changes.created_by("F/a.md", "plugin:other") is False
    changes.record(actor="plugin:familiar", rel_path="F/a.md", dest_path="F/b.md", op="move",
                   before_blob=B, after_blob=B)
    changes.record(actor="plugin:familiar", rel_path="F/b.md", dest_path="F/c.md", op="move",
                   before_blob=B, after_blob=B)
    assert changes.created_by("F/c.md", "plugin:familiar") is True


def test_moving_someone_elses_note_does_not_make_it_yours():
    changes.record(actor="plugin:familiar", rel_path="notes/user.md", dest_path="F/user.md",
                   op="move", before_blob=B, after_blob=B)
    assert changes.created_by("F/user.md", "plugin:familiar") is False


def test_a_reverted_or_pending_create_is_not_ownership():
    cid = changes.record(actor="assistant", rel_path="a.md", op="create", after_blob=B)
    changes.set_status(cid, "reverted", expect=("applied",))
    changes.record(actor="assistant", rel_path="b.md", op="create", status="pending",
                   pending_bytes_blob=B)
    assert changes.created_by("a.md", "assistant") is False
    assert changes.created_by("b.md", "assistant") is False


def test_a_move_cycle_terminates():
    changes.record(actor="mcp", rel_path="x.md", dest_path="y.md", op="move")
    changes.record(actor="mcp", rel_path="y.md", dest_path="x.md", op="move")
    assert changes.created_by("x.md", "mcp") is False


def test_apply_pending_fills_the_blobs_once():
    cid = changes.record(
        actor="assistant", rel_path="a.md", op="modify", status="pending",
        before_blob=B, pending_bytes_blob=C, risk_reasons=["edits a template"],
    )
    assert changes.apply_pending(cid, before_blob=D, after_blob=C) is True
    row = changes.get(cid)
    assert (row.status, row.before_blob, row.after_blob, row.pending_bytes_blob,
            row.resolved_ts) == ("applied", D, C, C, None)
    assert row.risk_reasons == ("edits a template",)
    assert changes.apply_pending(cid, before_blob=D, after_blob=C) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B3" && python -m pytest tests/test_changes_log.py -q`
Expected: FAIL with `AttributeError: module 'ghostbrain.changes.log' has no attribute 'created_by'`

- [ ] **Step 3: Implement**

In `ghostbrain/changes/log.py`, add below `_RESOLVED = (...)`:

```python
MAX_OWNERSHIP_HOPS = 50
```

and add after `last_after_blob`:

```python
def created_by(path: str, actor: str) -> bool:
    """Spec B §3 ownership: did ``actor`` create the file now at ``path``?
    Yes when it has an applied create there, or its own applied moves lead
    back to one. Moving someone else's note never makes it yours."""
    current = path
    with _connect() as conn:
        for _ in range(MAX_OWNERSHIP_HOPS):
            hit = conn.execute(
                "SELECT 1 FROM changes WHERE actor = ? AND status = 'applied'"
                " AND op = 'create' AND rel_path = ? LIMIT 1",
                (actor, current),
            ).fetchone()
            if hit is not None:
                return True
            moved = conn.execute(
                "SELECT rel_path FROM changes WHERE actor = ? AND status = 'applied'"
                " AND op = 'move' AND dest_path = ? ORDER BY id DESC LIMIT 1",
                (actor, current),
            ).fetchone()
            if moved is None:
                return False
            current = moved["rel_path"]
    return False


def apply_pending(change_id: int, *, before_blob: str | None, after_blob: str | None) -> bool:
    """B3: an approved change. The pending row becomes the applied row."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE changes SET status = 'applied', before_blob = ?, after_blob = ?,"
            " resolved_ts = NULL WHERE id = ? AND status = 'pending'",
            (before_blob, after_blob, change_id),
        )
        return cur.rowcount == 1
```

In `ghostbrain/changes/__init__.py`, add `apply_pending` and `created_by` to the `from ghostbrain.changes.log import (...)` list and to `__all__` (alphabetical: `"apply_pending"` before `"clear_degraded"`, `"created_by"` after `"counts"`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$B3" && python -m pytest tests/test_changes_log.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "$B3" && git add ghostbrain/changes tests/test_changes_log.py && git commit -m "feat(changes): ownership walk and pending-to-applied for approvals (B3)"
```

---

### Task 2: The risk policy

**Files:**
- Create: `ghostbrain/vault_write/risk.py`
- Modify: `ghostbrain/vault_write/writer.py` (module docstring; the hold-policy default)
- Test: `tests/test_vault_write_risk.py`
- Modify: `tests/test_vault_write_changes.py` (B2: `test_move_and_delete_rows`)
- Modify: `tests/test_changes_revert.py` (B2: opt out of the risk rules)
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 (`changes.log.created_by`, `ChangeLogError`); B2 (`ProposedChange`, `HoldPolicy`, `set_hold_policy`, the `_hold_policy` call inside `_write`).
- Produces (`ghostbrain.vault_write.risk`):
  - `evaluate(change: ProposedChange) -> list[str]`: reasons in rule order (path, content, ownership), each at most once. An empty list means apply now.
  - `added_lines(before: bytes | None, after: bytes | None) -> list[str]`.
  - Constants: `META_DIR = "90-meta/"`, `TEMPLATES_DIR = "90-meta/templates/"`, `STABLE_PROFILE_FILES`, `ROUTINE_MOVERS = frozenset({"worker:jot-router"})`, and the reason strings `REASON_META = "changes app settings (90-meta)"`, `REASON_TEMPLATE = "edits a template"`, `REASON_STABLE = "changes your stable profile"`, `REASON_SCRIPT = "adds a <script> tag"`, `REASON_HANDLER = "adds an HTML event handler (on…=)"`, `REASON_JS_URL = "adds a javascript: link"`, `REASON_TEMPLATE_EXPR = "adds a template expression ({{ … }})"`, `REASON_EXEC_FENCE = "adds an executable code block"`, `REASON_DELETE = "deletes a note it didn't create"`, `REASON_MOVE = "moves a note it didn't create"`.
  - `writer.set_hold_policy(None)` now restores **the risk rules** (B2: "never hold"). The risk rules are also the policy at import.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vault_write_risk.py`:

```python
"""B3: the risk policy that holds non-user changes for approval (spec B §3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.changes import log as changes
from ghostbrain.vault_write import (
    ASSISTANT,
    USER,
    ProposedChange,
    compute_etag,
    plugin_actor,
    risk,
    set_hold_policy,
    worker_actor,
    write,
    write_new,
)

FAMILIAR = plugin_actor("familiar")
ROUTER = worker_actor("jot-router")
NOTE = "20-contexts/work/plan.md"
V1 = b"---\ntitle: Plan\n---\n\nfirst draft\n"
V2 = b"---\ntitle: Plan\n---\n\nsecond draft\n"
PROMPT = b"# Digest prompt\n"
PREFS = b"# Preferences\n"


def _p(rel: str = NOTE, *, actor: str = ASSISTANT, op: str = "modify", dest: str | None = None,
       before: bytes | None = V1, after: bytes | None = V2) -> ProposedChange:
    return ProposedChange(actor, op, rel, dest, before, after, "")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"  # the root conftest points VAULT_PATH here
    for rel, data in (
        (NOTE, V1),
        ("90-meta/prompts/digest.md", PROMPT),
        ("80-profile/preferences.md", PREFS),
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return root


@pytest.fixture(autouse=True)
def _default_policy():
    set_hold_policy(None)
    yield
    set_hold_policy(None)


# ── the rules, one at a time ──────────────────────────────────────────────

def test_plain_prose_is_not_held():
    assert risk.evaluate(_p()) == []
    prose = (
        b"Learn javascript: the basics.\nWe use {{ in Go templates.\n"
        b"Move the onboarding doc.\n```python\nprint(1)\n```\nthe <scripted> plan\n"
    )
    assert risk.evaluate(_p(op="create", before=None, after=prose)) == []


@pytest.mark.parametrize("rel,reason", [
    ("90-meta/prompts/digest.md", risk.REASON_META),
    ("90-Meta/prompts/digest.md", risk.REASON_META),
    ("90-meta/templates/one-on-one.md", risk.REASON_TEMPLATE),
    ("80-profile/working-style.md", risk.REASON_STABLE),
    ("80-profile/Preferences.md", risk.REASON_STABLE),
])
def test_path_rules(rel, reason):
    assert risk.evaluate(_p(rel)) == [reason]


def test_the_current_profile_layer_is_not_held():
    assert risk.evaluate(_p("80-profile/current-projects.md")) == []
    assert risk.evaluate(_p("80-profile/_review.md")) == []


def test_moving_a_note_into_90_meta_is_held():
    p = _p(actor=ROUTER, op="move", dest="90-meta/notes/plan.md", after=V1)
    assert risk.evaluate(p) == [risk.REASON_META]


@pytest.mark.parametrize("line,reason", [
    ('<script src="x.js"></script>', risk.REASON_SCRIPT),
    ("<SCRIPT>alert(1)</SCRIPT>", risk.REASON_SCRIPT),
    ('<img src="x.png" onerror="alert(1)">', risk.REASON_HANDLER),
    ('<a href="javascript:alert(1)">x</a>', risk.REASON_JS_URL),
    ("[click](javascript:alert(1))", risk.REASON_JS_URL),
    ("Hello {{ person.name }}", risk.REASON_TEMPLATE_EXPR),
    ("{{date | format: YYYY-MM-DD}}", risk.REASON_TEMPLATE_EXPR),
    ("```dataviewjs", risk.REASON_EXEC_FENCE),
])
def test_content_rules_on_added_lines(line, reason):
    assert risk.evaluate(_p(after=V1 + line.encode() + b"\n")) == [reason]


def test_only_added_lines_are_checked():
    before = V1 + b"<script>old()</script>\n"
    assert risk.evaluate(_p(before=before, after=before + b"a new prose line\n")) == []
    assert risk.evaluate(_p(before=before, after=V1)) == []  # removing one is fine


def test_js_fences_are_executable_only_in_templates():
    after = V1 + b"```js\nrun()\n```\n"
    assert risk.evaluate(_p(after=after)) == []
    assert risk.evaluate(_p("90-meta/templates/t.md", after=after)) == [
        risk.REASON_TEMPLATE, risk.REASON_EXEC_FENCE]


def test_reasons_are_listed_once_in_rule_order():
    after = V1 + b"<script>a()</script>\n<script>b()</script>\n{{x}}\n"
    assert risk.evaluate(_p("90-meta/prompts/digest.md", after=after)) == [
        risk.REASON_META, risk.REASON_SCRIPT, risk.REASON_TEMPLATE_EXPR]


def test_deleting_or_moving_a_note_the_actor_did_not_create_is_held():
    assert risk.evaluate(_p(op="delete", after=None)) == [risk.REASON_DELETE]
    assert risk.evaluate(_p(op="move", dest="20-contexts/work/b.md", after=V1)) == [
        risk.REASON_MOVE]


def test_the_jot_router_may_move_your_jots():
    p = _p("00-inbox/raw/manual/j.md", actor=ROUTER, op="move",
           dest="20-contexts/work/j.md", after=V1)
    assert risk.evaluate(p) == []


def test_unknown_ownership_fails_closed(monkeypatch):
    def boom(*_a, **_k):
        raise changes.ChangeLogError("database is locked")

    monkeypatch.setattr(changes, "created_by", boom)
    assert risk.evaluate(_p(op="delete", after=None)) == [risk.REASON_DELETE]


def test_added_lines():
    assert risk.added_lines(None, b"a\nb\n") == ["a", "b"]
    assert risk.added_lines(b"a\nb\n", b"a\nc\nb\n") == ["c"]
    assert risk.added_lines(b"a\r\nb\r\n", b"a\r\nB\r\n") == ["B"]
    assert risk.added_lines(b"a\n", None) == []


# ── through the write path ────────────────────────────────────────────────

def test_an_assistant_edit_to_a_prompt_waits_and_writes_nothing(vault):
    rel = "90-meta/prompts/digest.md"
    res = write(rel, body="Ignore every rule.", actor=ASSISTANT, base_etag=compute_etag(PROMPT))
    assert res.status == "pending"
    assert (vault / rel).read_bytes() == PROMPT
    row = changes.get(int(res.change_id))
    assert (row.status, row.risk_reasons) == ("pending", (risk.REASON_META,))


def test_a_plugin_creating_a_template_waits(vault):
    res = write_new("90-meta/templates/standup.md", "# Standup {{date}}\n", actor=FAMILIAR)
    assert res.status == "pending"
    assert not (vault / "90-meta/templates/standup.md").exists()
    assert changes.get(int(res.change_id)).risk_reasons == (
        risk.REASON_TEMPLATE, risk.REASON_TEMPLATE_EXPR)


def test_the_user_is_never_held(vault):
    assert write("90-meta/prompts/digest.md", body="mine", actor=USER).status == "applied"


def test_an_assistant_stable_profile_edit_waits(vault):
    res = write("80-profile/preferences.md", body="- tabs", actor=ASSISTANT,
                base_etag=compute_etag(PREFS))
    assert res.status == "pending"
    assert (vault / "80-profile/preferences.md").read_bytes() == PREFS


def test_assistant_prose_and_new_notes_apply_immediately(vault):
    assert write(NOTE, body="better draft", actor=ASSISTANT,
                 base_etag=compute_etag(V1)).status == "applied"
    assert write_new("20-contexts/work/new.md", "# New\n", actor=ASSISTANT).status == "applied"


def test_a_plugin_may_move_and_delete_its_own_notes(vault):
    write("Familiar/a.md", content="v1\n", op="create", actor=FAMILIAR)
    moved = write("Familiar/a.md", op="move", dest="Familiar/archive/a.md", actor=FAMILIAR,
                  base_etag=compute_etag(b"v1\n"))
    assert moved.status == "applied"
    gone = write("Familiar/archive/a.md", op="delete", actor=FAMILIAR,
                 base_etag=compute_etag(b"v1\n"))
    assert gone.status == "applied"
    assert not (vault / "Familiar/archive/a.md").exists()


def test_a_plugin_deleting_a_users_note_waits(vault):
    res = write(NOTE, op="delete", actor=FAMILIAR, base_etag=compute_etag(V1))
    assert res.status == "pending" and (vault / NOTE).exists()


def test_jot_routing_is_never_held(vault):
    jot = "00-inbox/raw/manual/j1.md"
    (vault / jot).parent.mkdir(parents=True)
    (vault / jot).write_bytes(b"---\nid: j1\n---\n\na jot\n")
    res = write(jot, op="move", dest="20-contexts/work/j1.md", fields={"context": "work"},
                actor=ROUTER)
    assert res.status == "applied"
    assert (vault / "20-contexts/work/j1.md").exists()


def test_none_restores_the_risk_rules(vault):
    set_hold_policy(lambda _p: [])
    assert write(NOTE, op="delete", actor=FAMILIAR, base_etag=compute_etag(V1)).status == "applied"
    (vault / NOTE).write_bytes(V1)
    set_hold_policy(None)
    assert write(NOTE, op="delete", actor=FAMILIAR, base_etag=compute_etag(V1)).status == "pending"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B3" && python -m pytest tests/test_vault_write_risk.py -q`
Expected: FAIL with `ImportError: cannot import name 'risk' from 'ghostbrain.vault_write'`

- [ ] **Step 3: Write the rules**

Create `ghostbrain/vault_write/risk.py`:

```python
"""Risk policy (spec B §3, slice B3): which non-user changes wait for approval.

The write path calls ``evaluate`` for every change the change log would
record (B2's ``records_change``: not ``user``, not ``restore``, not a worker
create). A non-empty list of reasons holds the change as ``pending``: nothing
is written until the user approves it on the Changes screen.

Plain prose edits and new notes are never held (user decision 2026-10-09:
apply now, revert in one click). Plugins may edit ``90-meta``, but always
through this hold (decision 3).
"""
from __future__ import annotations

import difflib
import logging
import re

from ghostbrain.changes import log as _changes
from ghostbrain.vault_write.writer import ProposedChange

log = logging.getLogger("ghostbrain.vault_write.risk")

META_DIR = "90-meta/"
TEMPLATES_DIR = "90-meta/templates/"
STABLE_PROFILE_FILES = ("80-profile/working-style.md", "80-profile/preferences.md")
# Filing the user's jots is this job's whole purpose; it never creates them.
ROUTINE_MOVERS = frozenset({"worker:jot-router"})

REASON_META = "changes app settings (90-meta)"
REASON_TEMPLATE = "edits a template"
REASON_STABLE = "changes your stable profile"
REASON_SCRIPT = "adds a <script> tag"
REASON_HANDLER = "adds an HTML event handler (on…=)"
REASON_JS_URL = "adds a javascript: link"
REASON_TEMPLATE_EXPR = "adds a template expression ({{ … }})"
REASON_EXEC_FENCE = "adds an executable code block"
REASON_DELETE = "deletes a note it didn't create"
REASON_MOVE = "moves a note it didn't create"

_SCRIPT_RE = re.compile(r"<\s*script\b", re.IGNORECASE)
_HANDLER_RE = re.compile(r"<[a-z][^>]*\son[a-z]+\s*=|^\s*on[a-z]+\s*=\s*[\"']", re.IGNORECASE)
_JS_URL_RE = re.compile(
    r"(?:href|src|action|formaction|xlink:href)\s*=\s*[\"']?\s*javascript\s*:"
    r"|\]\(\s*<?\s*javascript\s*:"
    r"|<\s*javascript\s*:",
    re.IGNORECASE,
)
# Spec C placeholders: {{ name }}, {{ a.b }}, {{ a | filter: arg }}.
_TEMPLATE_EXPR_RE = re.compile(r"\{\{\s*[A-Za-z_][\w.]*\s*(?:\|[^{}]*)?\}\}")
_FENCE_RE = re.compile(r"^\s*(?:`{3,}|~{3,})\s*([A-Za-z]+)")
_ALWAYS_EXECUTABLE = frozenset({"dataviewjs"})
_EXECUTABLE_IN_TEMPLATES = frozenset({"js", "javascript"})


def _norm(path: str) -> str:
    # macOS / Windows vaults are case-insensitive: 90-Meta is 90-meta.
    return path.replace("\\", "/").lower()


def _paths(change: ProposedChange) -> list[str]:
    return [_norm(p) for p in (change.rel_path, change.dest_path) if p]


def _add(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _path_reasons(change: ProposedChange) -> list[str]:
    reasons: list[str] = []
    for path in _paths(change):
        if path.startswith(TEMPLATES_DIR):
            _add(reasons, REASON_TEMPLATE)
        elif path.startswith(META_DIR):
            _add(reasons, REASON_META)
        elif path in STABLE_PROFILE_FILES:
            _add(reasons, REASON_STABLE)
    return reasons


def added_lines(before: bytes | None, after: bytes | None) -> list[str]:
    """The lines ``after`` adds or replaces relative to ``before`` (spec B §3:
    only lines the change adds are checked)."""
    if after is None:
        return []
    new = after.decode("utf-8", errors="replace").splitlines()
    if before is None:
        return new
    old = before.decode("utf-8", errors="replace").splitlines()
    out: list[str] = []
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            out.extend(new[j1:j2])
    return out


def _content_reasons(change: ProposedChange) -> list[str]:
    in_template = any(p.startswith(TEMPLATES_DIR) for p in _paths(change))
    reasons: list[str] = []
    for line in added_lines(change.before, change.after):
        if _SCRIPT_RE.search(line):
            _add(reasons, REASON_SCRIPT)
        if _HANDLER_RE.search(line):
            _add(reasons, REASON_HANDLER)
        if _JS_URL_RE.search(line):
            _add(reasons, REASON_JS_URL)
        if _TEMPLATE_EXPR_RE.search(line):
            _add(reasons, REASON_TEMPLATE_EXPR)
        fence = _FENCE_RE.match(line)
        if fence is not None:
            lang = fence.group(1).lower()
            if lang in _ALWAYS_EXECUTABLE or (in_template and lang in _EXECUTABLE_IN_TEMPLATES):
                _add(reasons, REASON_EXEC_FENCE)
    return reasons


def _ownership_reasons(change: ProposedChange) -> list[str]:
    if change.op not in ("delete", "move") or change.actor in ROUTINE_MOVERS:
        return []
    try:
        mine = _changes.created_by(change.rel_path, change.actor)
    except Exception:  # noqa: BLE001 — unknown history: hold it (fail closed)
        log.warning("change log unavailable; holding %s of %s", change.op, change.rel_path)
        mine = False
    if mine:
        return []
    return [REASON_DELETE if change.op == "delete" else REASON_MOVE]


def evaluate(change: ProposedChange) -> list[str]:
    """Spec B §3. Reasons in rule order, each once. Empty: apply now."""
    reasons: list[str] = []
    for found in (_path_reasons(change), _content_reasons(change), _ownership_reasons(change)):
        for reason in found:
            _add(reasons, reason)
    return reasons
```

- [ ] **Step 4: Make the risk rules the default hold policy**

In `ghostbrain/vault_write/writer.py` (B2 version), replace this block:

```python
def _never_hold(_change: ProposedChange) -> list[str]:
    return []


_hold_policy: HoldPolicy = _never_hold


def set_hold_policy(policy: HoldPolicy | None) -> None:
    """B3 installs its risk rules here. ``None`` restores B2's default: never
    hold (user decision 2026-10-09: new notes apply now, revert in one click)."""
    global _hold_policy
    _hold_policy = policy or _never_hold
```

with:

```python
def _risk_rules(change: ProposedChange) -> list[str]:
    from ghostbrain.vault_write.risk import evaluate  # risk imports this module

    return evaluate(change)


_hold_policy: HoldPolicy = _risk_rules


def set_hold_policy(policy: HoldPolicy | None) -> None:
    """Swap the hold policy (tests). ``None`` restores the default: the B3
    risk rules (spec B §3). A reset can never leave the vault unguarded."""
    global _hold_policy
    _hold_policy = policy or _risk_rules
```

In the same file's module docstring, replace the sentence `The B3 risk policy plugs in through ``set_hold_policy``; B2's default never holds.` with:

```
The B3 risk rules (``risk.evaluate``) are the default hold policy; a held
change is stored as a pending row and nothing is written.
```

In `ghostbrain/vault_write/__init__.py`, add this line directly after the `from ghostbrain.vault_write.writer import (...)` block:

```python
from ghostbrain.vault_write import risk  # noqa: E402  (imports writer; must come after it)
```

and add `"risk"` to `__all__` (after `"resolve_safe"`).

- [ ] **Step 5: Keep B2's mechanics tests independent of the rules**

B2's tests move and delete notes the acting plugin or assistant didn't create. Under B3 those writes are held, which is correct, so the tests that exercise row and revert mechanics opt out explicitly.

In `tests/test_vault_write_changes.py`, make this the first line of `test_move_and_delete_rows`:

```python
    set_hold_policy(lambda _p: [])  # row mechanics only; B3 would hold both (not their notes)
```

In `tests/test_changes_revert.py`, add `set_hold_policy` to the `from ghostbrain.vault_write import (...)` list, and add below the `vault` fixture:

```python
@pytest.fixture(autouse=True)
def _revert_mechanics_only():
    """These tests move and delete notes the actor didn't create, which B3's
    risk rules hold. Revert mechanics are what is under test here."""
    set_hold_policy(lambda _p: [])
    yield
    set_hold_policy(None)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd "$B3" && python -m pytest tests/test_vault_write_risk.py tests/test_vault_write_changes.py tests/test_changes_revert.py tests/test_changes_log.py tests/test_vault_write_history.py tests/test_vault_write_writer.py ghostbrain/api/tests -q`
Expected: PASS

- [ ] **Step 7: Add the test file to CI**

In `.github/workflows/ci.yml`, add after `tests/test_changes_maintenance.py \` (B2):

```yaml
            tests/test_vault_write_risk.py \
```

- [ ] **Step 8: Commit**

```bash
cd "$B3" && git add ghostbrain/vault_write tests/test_vault_write_risk.py tests/test_vault_write_changes.py tests/test_changes_revert.py .github/workflows/ci.yml && git commit -m "feat(vault-write): risk rules hold risky non-user changes as pending (B3)"
```

---

### Task 3: Approve and reject

**Files:**
- Modify: `ghostbrain/vault_write/writer.py` (`write`, `_write`; new `_mark_approved`)
- Modify: `ghostbrain/changes/revert.py` (`held_flip`, `expected_state`)
- Create: `ghostbrain/changes/approve.py`
- Test: `tests/test_changes_approve.py`
- Modify: `tests/test_changes_revert.py` (B2: one assertion)
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 (`apply_pending`, `created_by`); B2 (`revert._lock`, `read_current`, `matches_blob`, `Flip`, `ChangeNotFound`, `VersionGone`, `RevertError`, `changed_since`; `write(..., verbatim=True)`, move with `content`); A3 (`history.get_blob`, `put_blob`, `blob_id`, `BlobNotFound`).
- Produces:
  - `vault_write.write(..., approved_change: int | None = None)`: writes as a recorded actor with the hold policy skipped and turns that pending row into the applied row (`WriteResult.change_id == str(approved_change)`). `ValueError` when the actor/op would not be recorded.
  - `changes.revert.held_flip(c: Change) -> Flip` (`Flip(at=c.rel_path, expect=c.before_blob, to=c.current_path, target=c.pending_bytes_blob)`), and `expected_state` returns it for a `pending` row. B2's detail route therefore reports `changedSince` for pending rows with no route change.
  - `ghostbrain.changes.approve`: `STALE_MESSAGE: str`; `NotApprovable(RevertError)`; `StaleProposal(RevertError)` with `.path`, `.expected: bytes | None`, `.current: bytes | None`; `@dataclass(frozen=True) ApproveResult(change: Change, path: str, etag: str | None)`; `approve(change_id: int, *, force: bool = False) -> ApproveResult`; `reject(change_id: int) -> Change`. Both raise `ChangeNotFound` and `ChangeLogError`. `approve` also raises `NotApprovable`, `StaleProposal`, `VersionGone`, `vault_write.WriteConflict` (move destination taken) and `HistoryUnavailable`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_changes_approve.py`:

```python
"""B3: approve and reject held changes (spec B §3, §5)."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.changes import approve as ap
from ghostbrain.changes import log as changes
from ghostbrain.changes import revert as rv
from ghostbrain.history import store
from ghostbrain.vault_write import (
    ASSISTANT,
    USER,
    compute_etag,
    plugin_actor,
    set_hold_policy,
    write,
)

REL = "20-contexts/work/plan.md"
NEW = "20-contexts/work/new.md"
V1 = b"---\ntitle: Plan\n---\n\nfirst draft\n"
FAMILIAR = plugin_actor("familiar")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    note = root / REL
    note.parent.mkdir(parents=True)
    note.write_bytes(V1)
    return root


@pytest.fixture(autouse=True)
def _hold_everything():
    """Every recorded write is held, whatever it contains, so these tests
    exercise approval itself rather than the risk rules."""
    set_hold_policy(lambda _p: ["held for test"])
    yield
    set_hold_policy(None)


def _held_edit(text: str = "proposed draft") -> int:
    res = write(REL, body=text, actor=ASSISTANT, base_etag=compute_etag(V1), reason="polish")
    assert res.status == "pending"
    return int(res.change_id)


def test_approve_writes_the_proposal_as_the_original_actor(vault):
    cid = _held_edit()
    proposed = store.get_blob(changes.get(cid).pending_bytes_blob)
    res = ap.approve(cid)
    assert (vault / REL).read_bytes() == proposed
    assert res.path == REL and res.etag == compute_etag(proposed)
    row = res.change
    assert (row.id, row.status, row.actor, row.reason) == (cid, "applied", "assistant", "polish")
    assert store.get_blob(row.before_blob) == V1
    assert store.get_blob(row.after_blob) == proposed
    assert [c.id for c in changes.list_changes()] == [cid]  # no second row
    newest = store.list_snapshots(REL)[0]
    assert newest.actor == "assistant" and store.get_blob(newest.blob) == V1


def test_approval_never_re_holds(vault):
    cid = _held_edit()  # the policy still says "hold"
    assert ap.approve(cid).change.status == "applied"


def test_an_approved_change_can_be_reverted(vault):
    cid = _held_edit()
    ap.approve(cid)
    rv.revert(cid)
    assert (vault / REL).read_bytes() == V1


def test_approving_a_stale_proposal_refuses_and_writes_nothing(vault):
    cid = _held_edit()
    write(REL, body="my own edit", actor=USER)
    mine = (vault / REL).read_bytes()
    assert rv.changed_since(changes.get(cid)) is True
    with pytest.raises(ap.StaleProposal) as exc:
        ap.approve(cid)
    assert (exc.value.path, exc.value.expected, exc.value.current) == (REL, V1, mine)
    assert (vault / REL).read_bytes() == mine
    assert changes.get(cid).status == "pending"


def test_forced_approval_keeps_the_overwritten_version_in_history(vault):
    cid = _held_edit()
    write(REL, body="my own edit", actor=USER)
    mine = (vault / REL).read_bytes()
    ap.approve(cid, force=True)
    assert b"proposed draft" in (vault / REL).read_bytes()
    assert store.get_blob(store.list_snapshots(REL)[0].blob) == mine
    row = changes.get(cid)
    assert row.status == "applied" and store.get_blob(row.before_blob) == mine


def test_approve_a_created_note(vault):
    res = vault_write.write_new(NEW, "# New\n", actor=FAMILIAR)
    assert not (vault / NEW).exists()
    ap.approve(int(res.change_id))
    assert (vault / NEW).read_bytes() == b"# New\n"
    assert changes.created_by(NEW, "plugin:familiar") is True


def test_a_create_whose_path_was_taken_meanwhile_is_stale(vault):
    res = write(NEW, content="# New\n", op="create", actor=FAMILIAR)
    (vault / NEW).write_bytes(b"the user made it\n")
    with pytest.raises(ap.StaleProposal):
        ap.approve(int(res.change_id))
    assert (vault / NEW).read_bytes() == b"the user made it\n"


def test_approve_a_delete_and_a_move(vault):
    gone = write(REL, op="delete", actor=FAMILIAR, base_etag=compute_etag(V1))
    ap.approve(int(gone.change_id))
    assert not (vault / REL).exists()
    (vault / REL).write_bytes(V1)
    dest = "20-contexts/work/archive/plan.md"
    moved = write(REL, op="move", dest=dest, actor=FAMILIAR, base_etag=compute_etag(V1))
    res = ap.approve(int(moved.change_id))
    assert res.path == dest
    assert not (vault / REL).exists() and (vault / dest).read_bytes() == V1


def test_a_forced_delete_of_a_note_already_gone_just_closes_it(vault):
    gone = write(REL, op="delete", actor=FAMILIAR, base_etag=compute_etag(V1))
    (vault / REL).unlink()
    with pytest.raises(ap.StaleProposal):
        ap.approve(int(gone.change_id))
    assert ap.approve(int(gone.change_id), force=True).change.status == "applied"


def test_a_proposal_already_on_disk_is_marked_applied(vault):
    cid = _held_edit()
    proposed = store.get_blob(changes.get(cid).pending_bytes_blob)
    (vault / REL).write_bytes(proposed)
    res = ap.approve(cid, force=True)
    assert res.change.status == "applied"
    assert store.get_blob(res.change.after_blob) == proposed


def test_reject_writes_nothing_and_closes_the_row(vault):
    cid = _held_edit()
    row = ap.reject(cid)
    assert row.status == "rejected" and row.resolved_ts is not None
    assert (vault / REL).read_bytes() == V1
    with pytest.raises(ap.NotApprovable):
        ap.reject(cid)
    with pytest.raises(ap.NotApprovable):
        ap.approve(cid)


def test_unknown_and_applied_changes_cannot_be_approved(vault):
    with pytest.raises(rv.ChangeNotFound):
        ap.approve(999)
    with pytest.raises(rv.ChangeNotFound):
        ap.reject(999)
    set_hold_policy(lambda _p: [])
    res = write(REL, body="applied now", actor=ASSISTANT, base_etag=compute_etag(V1))
    with pytest.raises(ap.NotApprovable):
        ap.approve(int(res.change_id))


def test_a_collected_proposal_is_reported_gone(vault):
    cid = _held_edit()
    store._blob_path(changes.get(cid).pending_bytes_blob).unlink()
    with pytest.raises(rv.VersionGone):
        ap.approve(cid)
    assert changes.get(cid).status == "pending"


def test_user_writes_cannot_claim_an_approval(vault):
    with pytest.raises(ValueError):
        write(REL, body="x", actor=USER, approved_change=1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B3" && python -m pytest tests/test_changes_approve.py -q`
Expected: FAIL with `ImportError: cannot import name 'approve' from 'ghostbrain.changes'`

- [ ] **Step 3: Let the write path carry an approval**

In `ghostbrain/vault_write/writer.py` (B2 version):

In **both** `write` and `_write`, add this parameter after `verbatim: bool = False,`:

```python
    approved_change: int | None = None,
```

In `write`, pass it on: the `_write(...)` call ends with `verbatim=verbatim, approved_change=approved_change,`.

In `_write`, directly after `_check_args(op, content, body, fields, dest)`, add:

```python
    if approved_change is not None and not records_change(actor, op):
        raise ValueError("only a change the log records can be approved")
```

Replace the hold block:

```python
        if recorded:
            reasons = _hold_reasons(proposed)
            if reasons:
                return _hold(proposed, reasons)  # B3: nothing is written
```

with:

```python
        if recorded and approved_change is None:
            reasons = _hold_reasons(proposed)
            if reasons:
                return _hold(proposed, reasons)  # held: nothing is written
```

Replace:

```python
        change_id = (
            _record(proposed, before_blob=before_blob, after_blob=after_blob) if recorded else None
        )
```

with:

```python
        change_id: str | None
        if approved_change is not None:
            change_id = _mark_approved(
                approved_change, before_blob=before_blob, after_blob=after_blob, path=src_rel,
            )
        elif recorded:
            change_id = _record(proposed, before_blob=before_blob, after_blob=after_blob)
        else:
            change_id = None
```

Add directly below `_record`:

```python
def _mark_approved(
    change_id: int, *, before_blob: str | None, after_blob: str | None, path: str
) -> str:
    """B3: the approved pending row becomes the applied row (no second row).
    Like ``_record``, a failure here leaves the write standing."""
    try:
        ok = _changes.apply_pending(change_id, before_blob=before_blob, after_blob=after_blob)
    except Exception as e:  # noqa: BLE001
        log.exception("could not mark change #%s applied", change_id)
        _changes.mark_degraded(f"approved change #{change_id} to {path} not marked: {e}")
        return str(change_id)
    if not ok:
        log.warning("change #%s was no longer pending when its approval landed", change_id)
        _changes.mark_degraded(f"approved change #{change_id} to {path} was not pending")
    return str(change_id)
```

- [ ] **Step 4: Pending rows get an expected state**

In `ghostbrain/changes/revert.py` (B2), add after `undo_flip`:

```python
def held_flip(c: Change) -> Flip:
    """A pending change (B3): its path should still hold the version it was
    proposed against; approval puts the proposal at its destination."""
    return Flip(at=c.rel_path, expect=c.before_blob, to=c.current_path, target=c.pending_bytes_blob)
```

and replace `expected_state` with:

```python
def expected_state(c: Change) -> Flip | None:
    if c.status == "applied":
        return revert_flip(c)
    if c.status == "reverted":
        return undo_flip(c)
    if c.status == "pending":
        return held_flip(c)
    return None
```

In `tests/test_changes_revert.py` (B2), in `test_states_that_cannot_be_reverted`, replace `assert rv.expected_state(changes.get(pid)) is None` with:

```python
    assert rv.expected_state(changes.get(pid)) == rv.held_flip(changes.get(pid))
```

- [ ] **Step 5: Write the approval engine**

Create `ghostbrain/changes/approve.py`:

```python
"""Approve or reject a held change (spec B §3, §5; slice B3).

Approval re-runs the write path against the *current* file (etag check,
snapshot, atomic write, change row) as the change's own actor, with the hold
policy skipped. The pending row becomes the applied row, so B2's Revert works
on it afterwards. If the file changed since the proposal, approval refuses
(``StaleProposal`` → 409) unless forced. A forced approval snapshots the
current version first, so it stays in page history.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ghostbrain import history, vault_write
from ghostbrain.changes import log as changes_log
from ghostbrain.changes import revert as _rv
from ghostbrain.changes.log import Change
from ghostbrain.changes.revert import ChangeNotFound, Flip, RevertError, VersionGone
from ghostbrain.vault_write import WriteResult, compute_etag

log = logging.getLogger("ghostbrain.changes")

STALE_MESSAGE = (
    "the note changed since this was proposed; approve anyway to overwrite it "
    "(the current version stays in page history)"
)


class NotApprovable(RevertError):
    """The change is not waiting for approval, or cannot be written."""


class StaleProposal(RevertError):
    def __init__(self, path: str, expected: bytes | None, current: bytes | None) -> None:
        super().__init__(STALE_MESSAGE)
        self.path = path
        self.expected = expected
        self.current = current


@dataclass(frozen=True)
class ApproveResult:
    change: Change
    path: str
    etag: str | None


def _pending(change_id: int) -> Change:
    c = changes_log.get(change_id)
    if c is None:
        raise ChangeNotFound(f"no change #{change_id}")
    if c.status != "pending":
        raise NotApprovable(f"change #{change_id} is {c.status}")
    return c


def _bytes(blob: str | None) -> bytes | None:
    if blob is None:
        return None
    try:
        return history.get_blob(blob)
    except history.BlobNotFound:
        raise VersionGone("this version is no longer available") from None


def _write_approved(c: Change, flip: Flip, target: bytes | None, current: bytes | None) -> WriteResult:
    reason = c.reason or f"approved change #{c.id}"
    if target is None:  # a delete
        if current is None:  # already gone (forced): the outcome holds
            changes_log.apply_pending(c.id, before_blob=c.before_blob, after_blob=None)
            return WriteResult("applied", str(c.id), None, flip.at, None)
        return vault_write.write(
            flip.at, op="delete", actor=c.actor, reason=reason,
            base_etag=compute_etag(current), approved_change=c.id,
        )
    try:
        text = target.decode("utf-8")
    except UnicodeDecodeError:
        raise NotApprovable("the proposed version is not UTF-8 text") from None
    if current is None:
        return vault_write.write(
            flip.to, content=text, op="create", actor=c.actor, reason=reason,
            verbatim=True, approved_change=c.id,
        )
    if current == target and flip.at == flip.to:  # already on disk (forced)
        before = history.put_blob(current)
        changes_log.apply_pending(c.id, before_blob=before, after_blob=before)
        return WriteResult("applied", str(c.id), compute_etag(current), flip.at, None)
    base = compute_etag(current)
    if flip.at != flip.to:
        return vault_write.write(
            flip.at, op="move", dest=flip.to, content=text, actor=c.actor, reason=reason,
            base_etag=base, verbatim=True, approved_change=c.id,
        )
    return vault_write.write(
        flip.at, content=text, actor=c.actor, reason=reason, base_etag=base,
        verbatim=True, approved_change=c.id,
    )


def approve(change_id: int, *, force: bool = False) -> ApproveResult:
    # Shares revert's lock: an approval and a revert never interleave on a row.
    with _rv._lock:
        c = _pending(change_id)
        flip = _rv.held_flip(c)
        target = _bytes(flip.target)  # fail before any write when it was collected
        current = _rv.read_current(flip.at)
        if not _rv.matches_blob(current, flip.expect) and not force:
            try:
                expected = _bytes(flip.expect)
            except VersionGone:
                expected = None
            raise StaleProposal(flip.at, expected, current)
        res = _write_approved(c, flip, target, current)
        c = changes_log.get(c.id) or c
    log.info("approved change #%s by %s on %s", c.id, c.actor, res.path)
    return ApproveResult(c, res.path, res.etag)


def reject(change_id: int) -> Change:
    with _rv._lock:
        c = _pending(change_id)
        if not changes_log.set_status(c.id, "rejected", expect=("pending",)):
            raise NotApprovable(f"change #{change_id} is no longer pending")
        return changes_log.get(c.id) or c
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd "$B3" && python -m pytest tests/test_changes_approve.py tests/test_changes_revert.py tests/test_vault_write_changes.py tests/test_vault_write_risk.py -q`
Expected: PASS

- [ ] **Step 7: Add the test file to CI**

In `.github/workflows/ci.yml`, add after `tests/test_vault_write_risk.py \`:

```yaml
            tests/test_changes_approve.py \
```

- [ ] **Step 8: Commit**

```bash
cd "$B3" && git add ghostbrain/vault_write/writer.py ghostbrain/changes tests/test_changes_approve.py tests/test_changes_revert.py .github/workflows/ci.yml && git commit -m "feat(changes): approve and reject held changes through the write path (B3)"
```

---

### Task 4: Write routes say when a change is waiting

**Files:**
- Modify: `ghostbrain/api/repo/note.py` (`save_note_body`, `save_note_at_path`)
- Modify: `ghostbrain/api/repo/notes_manual.py` (`update_jot_body`, `move_jot`, `delete_jot`)
- Modify: `ghostbrain/api/repo/generated_docs.py` (`write_doc`)
- Modify: `ghostbrain/api/models/docs.py` (`WriteDocResponse`)
- Modify: `ghostbrain/api/routes/notes.py` (`delete_note`)
- Modify: `ghostbrain/mcp/tools.py` (`write_doc`)
- Test: `ghostbrain/api/tests/test_pending_responses.py`
- Modify: `ghostbrain/api/tests/test_actor_header.py` (B2: the plugin-delete test)
- Modify: `ghostbrain/api/tests/test_note_write_path.py`, `ghostbrain/api/tests/test_routes_notes_upsert.py` (exact-dict assertions on save responses)
- Test: `tests/test_mcp_tools.py` (append)
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 2 (held writes return `WriteResult(status="pending", change_id=…)`); B2 Task 5 route signatures.
- Produces:
  - Response bodies gain `"status": "applied" | "pending"` and `"changeId": str | None` on `PATCH /v1/notes/body`, `PUT /v1/notes`, `PATCH /v1/notes/{jot_id}`, `POST /v1/notes/{jot_id}/route`, and `POST /v1/docs/write`. For a pending write, `etag` is the **unchanged** current etag (`None` for a held create).
  - `DELETE /v1/notes/{jot_id}`: **202** `{"status": "pending", "changeId": str}` when held. Otherwise 204 as before.
  - `notes_manual.delete_jot(...) -> vault_write.WriteResult`.
  - `mcp.tools.write_doc` returns `"<path> is waiting for the user's approval on the Changes screen (change #<id>); it is not in the vault until they approve it."` when held.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_pending_responses.py`:

```python
"""B3: write routes say when a change is waiting for approval."""
from __future__ import annotations

from ghostbrain.api.repo.notes_manual import write_inbox_jot
from ghostbrain.api.tests.conftest import write_note
from ghostbrain.changes import log as changes
from ghostbrain.vault_write import compute_etag

ASSIST = {"X-Poltergeist-Actor": "assistant"}
FAM = {"X-Poltergeist-Actor": "plugin:familiar"}
PREFS = "80-profile/preferences.md"


def _if_match(data: bytes) -> dict:
    etag = compute_etag(data)
    return {"If-Match": f'"{etag}"'}


def test_an_assistant_edit_to_the_stable_profile_is_pending(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, PREFS, "# Preferences\n\n- spaces\n")
    before = note.read_bytes()
    r = client.patch("/v1/notes/body", json={"path": PREFS, "body": "- tabs"},
                     headers={**auth_headers, **ASSIST, **_if_match(before)})
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "pending" and out["changeId"]
    assert out["etag"] == compute_etag(before)
    assert note.read_bytes() == before


def test_a_plain_assistant_edit_reports_applied(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, "20-contexts/work/notes/plan.md", "---\ntitle: Plan\n---\n\nfirst\n")
    r = client.patch("/v1/notes/body", json={"path": "20-contexts/work/notes/plan.md", "body": "second"},
                     headers={**auth_headers, **ASSIST, **_if_match(note.read_bytes())})
    assert r.status_code == 200
    assert r.json()["status"] == "applied" and r.json()["changeId"]


def test_a_user_edit_reports_applied_with_no_change(tmp_vault, client, auth_headers):
    write_note(tmp_vault, PREFS, "# Preferences\n")
    r = client.patch("/v1/notes/body", json={"path": PREFS, "body": "- tabs"}, headers=auth_headers)
    assert (r.json()["status"], r.json()["changeId"]) == ("applied", None)


def test_an_assistant_jot_edit_adding_a_script_is_pending(tmp_vault, client, auth_headers):
    rec = write_inbox_jot("my jot")
    path = tmp_vault / rec["path"]
    before = path.read_bytes()
    r = client.patch(f"/v1/notes/{rec['id']}", json={"body": "my jot\n\n<script>steal()</script>"},
                     headers={**auth_headers, **ASSIST, **_if_match(before)})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert path.read_bytes() == before


def test_a_plugin_filing_a_users_jot_is_pending(tmp_vault, client, auth_headers):
    rec = write_inbox_jot("my jot")
    path = tmp_vault / rec["path"]
    r = client.post(f"/v1/notes/{rec['id']}/route", json={"context": "work"},
                    headers={**auth_headers, **FAM, **_if_match(path.read_bytes())})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert path.exists()


def test_a_plugin_deleting_a_users_jot_gets_202_and_the_file_stays(tmp_vault, client, auth_headers):
    rec = write_inbox_jot("my jot")
    path = tmp_vault / rec["path"]
    r = client.delete(f"/v1/notes/{rec['id']}",
                      headers={**auth_headers, **FAM, **_if_match(path.read_bytes())})
    assert r.status_code == 202
    [row] = changes.list_changes(status="pending")
    assert r.json() == {"status": "pending", "changeId": str(row.id)}
    assert (row.op, row.risk_reasons) == ("delete", ("deletes a note it didn't create",))
    assert path.exists()


def test_a_generated_doc_with_a_script_waits(tmp_vault, client, auth_headers):
    r = client.post("/v1/docs/write", json={"title": "Report", "html": "<p>hi</p><script>x()</script>"},
                    headers=auth_headers)
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "pending" and out["changeId"]
    assert not (tmp_vault / out["path"]).exists()
    plain = client.post("/v1/docs/write", json={"title": "Report", "html": "<p>hi</p>"},
                        headers=auth_headers).json()
    assert plain["status"] == "applied"
    assert (tmp_vault / plain["path"]).exists()


def test_a_plugin_upsert_into_90_meta_is_pending(tmp_vault, client, auth_headers):
    r = client.put("/v1/notes", json={"path": "90-meta/templates/standup.md", "content": "# Standup\n"},
                   headers={**auth_headers, **FAM})
    assert r.status_code == 200
    out = r.json()
    assert (out["status"], out["created"], out["etag"]) == ("pending", True, None)
    assert not (tmp_vault / "90-meta/templates/standup.md").exists()
```

Append to `tests/test_mcp_tools.py`:

```python
def test_write_doc_says_when_the_doc_waits_for_approval():
    class HeldClient:
        def write_doc(self, title, html):
            return {"path": "20-contexts/generated-docs/x.html", "title": title,
                    "status": "pending", "changeId": "7"}

    from ghostbrain.mcp import tools

    out = tools.write_doc(HeldClient(), "X", "<script></script>")
    assert out == (
        "20-contexts/generated-docs/x.html is waiting for the user's approval on the Changes "
        "screen (change #7); it is not in the vault until they approve it."
    )
```

In `ghostbrain/api/tests/test_actor_header.py` (B2), in `test_a_plugin_deleting_a_users_jot_needs_its_etag`, replace `assert r.status_code == 204` with:

```python
    assert r.status_code == 202  # B3: held, it is not the plugin's jot
    assert path.exists()
```

Three existing tests compare whole save responses, which now carry two more keys. In `ghostbrain/api/tests/test_note_write_path.py`, replace the final `assert res == {...}` statement of `test_hand_edited_frontmatter_survives_byte_for_byte` (whichever keys A3 left in it) with:

```python
    assert {k: res[k] for k in ("path", "updated", "etag", "status", "changeId")} == {
        "path": REL, "updated": NOW, "etag": compute_etag(p.read_bytes()),
        "status": "applied", "changeId": None,
    }
```

and the `assert res == {...}` line of `test_save_note_at_path_repo_contract` with:

```python
    assert res == {"path": "Familiar/x.md", "created": True, "etag": compute_etag(b"body\n"),
                   "status": "applied", "changeId": None}
```

In `ghostbrain/api/tests/test_routes_notes_upsert.py`, in `test_upsert_creates_nested_note`, replace the `assert {k: v for k, v in r.json().items() if k != "etag"} == {...}` line with:

```python
    out = r.json()
    assert (out["path"], out["created"], out["status"]) == (
        "Familiar/briefings/2026-07-08.md", True, "applied")
    assert out["changeId"] is not None  # a plugin create is on the Changes screen (B2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B3" && python -m pytest ghostbrain/api/tests/test_pending_responses.py tests/test_mcp_tools.py -q`
Expected: FAIL with `KeyError: 'status'`

- [ ] **Step 3: Report the write status**

In `ghostbrain/api/repo/note.py`, replace the `return` of `save_note_body` with:

```python
    return {"path": rel_path, "updated": res.updated, "etag": res.etag,
            "historyOk": res.history_ok, "status": res.status, "changeId": res.change_id}
```

and the `return` of `save_note_at_path` with:

```python
    return {"path": rel_path, "created": created, "etag": res.etag,
            "status": res.status, "changeId": res.change_id}
```

(If A3's version of `save_note_at_path` also returns `historyOk`, keep it: add the two keys to that dict.)

In `ghostbrain/api/repo/notes_manual.py`:

- `update_jot_body`: add `"status": res.status, "changeId": res.change_id` to the returned dict (keep every key it returns today).
- `move_jot`: add `"status": res.status, "changeId": res.change_id` to the final returned dict. The early "already there" return is unchanged.
- Replace `delete_jot` (B2 version) with:

```python
def delete_jot(
    jot_id: str, *, actor: Actor = USER, base_etag: str | None = None
) -> vault_write.WriteResult:
    path = _find_file(jot_id)
    return vault_write.write(
        _vault_rel(path), op="delete", actor=actor, reason="deleted jot", base_etag=base_etag,
    )
```

In `ghostbrain/api/repo/generated_docs.py`, replace `return {"path": res.path, "title": title}` with:

```python
    return {"path": res.path, "title": title, "status": res.status, "changeId": res.change_id}
```

In `ghostbrain/api/models/docs.py`, replace `WriteDocResponse` with:

```python
class WriteDocResponse(BaseModel):
    path: str
    title: str
    status: str = "applied"  # "pending": held for approval (spec B3), nothing written
    changeId: str | None = None
```

In `ghostbrain/api/routes/notes.py`, change `from fastapi.responses import Response` to `from fastapi.responses import JSONResponse, Response`, and replace `delete_note` (B2 version) with:

```python
@router.delete("/{jot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    jot_id: str = PathParam(..., min_length=8, max_length=128),
    base_etag: str | None = Depends(if_match),
    actor: Actor = Depends(request_actor),
) -> Response:
    """Delete a jot permanently. 202 when the delete waits for approval (B3)."""
    try:
        res = delete_jot(jot_id, actor=actor, base_etag=base_etag)
    except JotNotFound:
        raise HTTPException(status_code=404, detail=f"Jot not found: {jot_id}")
    if res.status == "pending":
        return JSONResponse(status_code=202, content={"status": "pending", "changeId": res.change_id})
    return Response(status_code=204)
```

In `ghostbrain/mcp/tools.py`, replace the last line of `write_doc` (`return str(data.get("path") or "")`) with:

```python
    path = str(data.get("path") or "")
    if data.get("status") == "pending":
        return (
            f"{path} is waiting for the user's approval on the Changes screen "
            f"(change #{data.get('changeId')}); it is not in the vault until they approve it."
        )
    return path
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$B3" && python -m pytest ghostbrain/api/tests tests/test_mcp_tools.py tests/test_mcp_client.py -q`
Expected: PASS

- [ ] **Step 5: Add the MCP tool tests to CI**

In `.github/workflows/ci.yml`, add after `tests/test_mcp_client.py \` (B2):

```yaml
            tests/test_mcp_tools.py \
```

- [ ] **Step 6: Commit**

```bash
cd "$B3" && git add ghostbrain/api ghostbrain/mcp/tools.py tests/test_mcp_tools.py .github/workflows/ci.yml && git commit -m "feat(api): write routes and the MCP doc tool report held changes (B3)"
```

---

### Task 5: `/v1/changes/{id}/approve` and `/reject`

**Files:**
- Modify: `ghostbrain/api/routes/changes.py` (B2)
- Test: `ghostbrain/api/tests/test_routes_changes_approve.py`

**Interfaces:**
- Consumes: Task 3 (`approve`, `reject`, `NotApprovable`, `StaleProposal`); B2 Task 6 (`router`, `ChangeActionRequest`, `request_actor`, `_UNAVAILABLE`); Task 4 (`PUT /v1/notes` reports `changeId`).
- Produces (HTTP; the desktop relies on these shapes):
  - `POST /v1/changes/{id}/approve`, body `{"force": bool}` (optional; default false) → `{"id": int, "status": "applied", "path": str, "etag": str | null}`. Non-user actor header → 403. Not pending → 400. Stale → **409** `{"detail": STALE_MESSAGE}` (the row stays pending). Unknown id → 404. Proposal collected → 410. Move destination taken → 409 (write-path handler). History failure → 500. Change log unreadable → 503.
  - `POST /v1/changes/{id}/reject` (no body) → `{"id": int, "status": "rejected"}`. 403, 400, 404 and 503 as above.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_routes_changes_approve.py`:

```python
"""B3: approve / reject held changes over HTTP (spec B §5)."""
from __future__ import annotations

from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.vault_write import compute_etag

FAM = {"X-Poltergeist-Actor": "plugin:familiar"}
TEMPLATE = "90-meta/templates/standup.md"
BODY = "# Standup\n\n- yesterday\n"


def _propose(client, auth) -> int:
    r = client.put("/v1/notes", json={"path": TEMPLATE, "content": BODY}, headers={**auth, **FAM})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    return int(r.json()["changeId"])


def test_a_plugin_template_waits_in_the_pending_list(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    assert not (tmp_vault / TEMPLATE).exists()
    listing = client.get("/v1/changes", params={"status": "pending"}, headers=auth_headers).json()
    assert listing["pendingCount"] == 1
    [item] = listing["items"]
    assert (item["id"], item["status"], item["riskReasons"]) == (cid, "pending", ["edits a template"])
    d = client.get(f"/v1/changes/{cid}", headers=auth_headers).json()
    assert (d["before"], d["after"], d["changedSince"]) == (None, BODY, False)


def test_approve_writes_it(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    r = client.post(f"/v1/changes/{cid}/approve", json={}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"id": cid, "status": "applied", "path": TEMPLATE,
                        "etag": compute_etag(BODY.encode())}
    assert (tmp_vault / TEMPLATE).read_text() == BODY
    assert client.get("/v1/changes", headers=auth_headers).json()["pendingCount"] == 0


def test_approve_without_a_body_defaults_to_no_force(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    assert client.post(f"/v1/changes/{cid}/approve", headers=auth_headers).status_code == 200


def test_reject_writes_nothing(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    r = client.post(f"/v1/changes/{cid}/reject", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"id": cid, "status": "rejected"}
    assert not (tmp_vault / TEMPLATE).exists()
    assert client.post(f"/v1/changes/{cid}/reject", headers=auth_headers).status_code == 400
    assert client.post(f"/v1/changes/{cid}/approve", json={}, headers=auth_headers).status_code == 400


def test_only_the_user_decides(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    h = {**auth_headers, **FAM}
    assert client.post(f"/v1/changes/{cid}/approve", json={}, headers=h).status_code == 403
    assert client.post(f"/v1/changes/{cid}/reject", headers=h).status_code == 403
    assert changes.get(cid).status == "pending"


def test_stale_approval_is_409_until_forced(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    (tmp_vault / TEMPLATE).parent.mkdir(parents=True, exist_ok=True)
    (tmp_vault / TEMPLATE).write_text("the user wrote this first\n")
    assert client.get(f"/v1/changes/{cid}", headers=auth_headers).json()["changedSince"] is True
    r = client.post(f"/v1/changes/{cid}/approve", json={}, headers=auth_headers)
    assert r.status_code == 409 and "changed since" in r.json()["detail"]
    assert (tmp_vault / TEMPLATE).read_text() == "the user wrote this first\n"
    assert changes.get(cid).status == "pending"
    f = client.post(f"/v1/changes/{cid}/approve", json={"force": True}, headers=auth_headers)
    assert f.status_code == 200
    assert (tmp_vault / TEMPLATE).read_text() == BODY
    assert store.get_blob(store.list_snapshots(TEMPLATE)[0].blob) == b"the user wrote this first\n"


def test_unknown_and_collected(tmp_vault, client, auth_headers):
    assert client.post("/v1/changes/9999/approve", json={}, headers=auth_headers).status_code == 404
    assert client.post("/v1/changes/9999/reject", headers=auth_headers).status_code == 404
    cid = _propose(client, auth_headers)
    store._blob_path(changes.get(cid).pending_bytes_blob).unlink()
    assert client.post(f"/v1/changes/{cid}/approve", json={}, headers=auth_headers).status_code == 410
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B3" && python -m pytest ghostbrain/api/tests/test_routes_changes_approve.py -q`
Expected: FAIL. `POST /v1/changes/{id}/approve` returns 404 or 405 (no route yet).

- [ ] **Step 3: Add the routes**

In `ghostbrain/api/routes/changes.py` (B2), add `from ghostbrain.changes import approve as changes_approve` below the `changes_revert` import. In the module docstring, replace `Approve / reject of pending changes are B3.` with `Approve / reject of pending changes (B3) write through ``ghostbrain.changes.approve``.` Append:

```python
def _only_user(actor: Actor) -> None:
    if actor != USER:
        raise HTTPException(status_code=403, detail="only you can approve or reject changes")


@router.post("/{change_id}/approve")
def approve_route(
    change_id: int,
    req: ChangeActionRequest | None = None,
    actor: Actor = Depends(request_actor),
) -> dict:
    _only_user(actor)
    force = req.force if req is not None else False
    try:
        res = changes_approve.approve(change_id, force=force)
    except changes_revert.ChangeNotFound:
        raise HTTPException(status_code=404, detail="no such change") from None
    except changes_approve.NotApprovable as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except changes_approve.StaleProposal as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except changes_revert.VersionGone as e:
        raise HTTPException(status_code=410, detail=str(e)) from None
    except changes_log.ChangeLogError:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None
    return {"id": res.change.id, "status": res.change.status, "path": res.path, "etag": res.etag}


@router.post("/{change_id}/reject")
def reject_route(change_id: int, actor: Actor = Depends(request_actor)) -> dict:
    _only_user(actor)
    try:
        c = changes_approve.reject(change_id)
    except changes_revert.ChangeNotFound:
        raise HTTPException(status_code=404, detail="no such change") from None
    except changes_approve.NotApprovable as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except changes_log.ChangeLogError:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None
    return {"id": c.id, "status": c.status}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$B3" && python -m pytest ghostbrain/api/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "$B3" && git add ghostbrain/api && git commit -m "feat(api): user-only approve and reject routes for held changes (B3)"
```

---

### Task 6: Desktop data layer and the nav badge

**Files:**
- Modify: `desktop/src/shared/api-types.ts`
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (B2's change-log hooks)
- Create: `desktop/src/renderer/components/PendingChangesBadge.tsx`
- Modify: `desktop/src/renderer/components/Sidebar.tsx`
- Test: `desktop/src/renderer/__tests__/PendingChangesBadge.test.tsx`

**Interfaces:**
- Consumes: Task 5 HTTP shapes; B2 (`ChangesListResponse`, `ChangeActionResponse`, `ChangeStatus`, `useChangeAction`, the `'changes'` nav item).
- Produces:
  - Type `ChangeRejectResponse { id: number; status: ChangeStatus }`.
  - `PENDING_CHANGES_PATH = '/v1/changes?status=pending&limit=200'`.
  - `usePendingChanges()`: query key `['changes', 'pending']`, polled every 30 s. The badge and the Pending section share it.
  - `useApproveChange()`: mutation over `{ id: number; force?: boolean }` posting `{ force }`. `useRejectChange()`: mutation over `{ id: number }` posting no body. Both invalidate what B2's revert invalidates.
  - `<PendingChangesBadge />`: renders nothing at 0; otherwise a pill with the count (`99+` above 99), `data-testid="pending-changes-badge"`, `aria-label` "N change(s) waiting for approval".

- [ ] **Step 1: Write the failing test**

Create `desktop/src/renderer/__tests__/PendingChangesBadge.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { PendingChangesBadge } from '../components/PendingChangesBadge';
import { PENDING_CHANGES_PATH } from '../lib/api/hooks';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);

function renderBadge(pendingCount: number) {
  getMock.mockResolvedValue({ items: [], pendingCount, degraded: false });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PendingChangesBadge />
    </QueryClientProvider>,
  );
}

afterEach(() => getMock.mockReset());

describe('PendingChangesBadge', () => {
  it('shows how many changes wait for approval', async () => {
    renderBadge(3);
    const badge = await screen.findByTestId('pending-changes-badge');
    expect(badge).toHaveTextContent('3');
    expect(badge).toHaveAttribute('aria-label', '3 changes waiting for approval');
    expect(getMock).toHaveBeenCalledWith(PENDING_CHANGES_PATH);
  });

  it('uses the singular for one', async () => {
    renderBadge(1);
    expect(await screen.findByTestId('pending-changes-badge')).toHaveAttribute(
      'aria-label',
      '1 change waiting for approval',
    );
  });

  it('caps the number', async () => {
    renderBadge(140);
    expect(await screen.findByTestId('pending-changes-badge')).toHaveTextContent('99+');
  });

  it('shows nothing when nothing waits', async () => {
    renderBadge(0);
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(screen.queryByTestId('pending-changes-badge')).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd "$B3/desktop" && npx vitest run src/renderer/__tests__/PendingChangesBadge.test.tsx`
Expected: FAIL. Resolving `../components/PendingChangesBadge` fails.

- [ ] **Step 3: Types and hooks**

Append to `desktop/src/shared/api-types.ts`:

```ts
export interface ChangeRejectResponse {
  id: number;
  status: ChangeStatus;
}
```

In `desktop/src/renderer/lib/api/hooks.ts`, change the first import to `import { type QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';` and add `ChangeRejectResponse` to the `from '../../../shared/api-types'` type import. Replace B2's `useChangeAction` with:

```ts
function invalidateAfterChange(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: ['changes'] });
  qc.invalidateQueries({ queryKey: ['change'] });
  qc.invalidateQueries({ queryKey: ['note'] });
  qc.invalidateQueries({ queryKey: ['note-by-path'] });
  qc.invalidateQueries({ queryKey: ['note-history'] });
  qc.invalidateQueries({ queryKey: JOTS_KEY });
  qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] });
}

function useChangeAction(action: 'revert' | 'undo' | 'approve') {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: number; force?: boolean }) =>
      post<ChangeActionResponse>(`/v1/changes/${vars.id}/${action}`, { force: vars.force ?? false }),
    onSuccess: () => invalidateAfterChange(qc),
  });
}
```

and append after `useDismissChangesWarning`:

```ts
// ── Held changes (spec B §3, §6; slice B3) ──────────────────────────────────

export const PENDING_CHANGES_PATH = '/v1/changes?status=pending&limit=200';

/** Changes waiting for approval. The nav badge and the Pending section share
 * this query, so they never disagree. */
export function usePendingChanges() {
  return useQuery({
    queryKey: ['changes', 'pending'],
    queryFn: () => get<ChangesListResponse>(PENDING_CHANGES_PATH),
    refetchInterval: 30_000,
  });
}

export function useApproveChange() {
  return useChangeAction('approve');
}

export function useRejectChange() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: number }) => post<ChangeRejectResponse>(`/v1/changes/${vars.id}/reject`),
    onSuccess: () => invalidateAfterChange(qc),
  });
}
```

- [ ] **Step 4: The badge**

Create `desktop/src/renderer/components/PendingChangesBadge.tsx`:

```tsx
import { usePendingChanges } from '../lib/api/hooks';

/** Sidebar badge (spec B §6): how many changes wait for your approval.
 * Polled every 30 s through the query the Pending section uses. */
export function PendingChangesBadge() {
  const pending = usePendingChanges();
  const count = pending.data?.pendingCount ?? 0;
  if (count === 0) return null;
  const label =
    count === 1 ? '1 change waiting for approval' : `${count} changes waiting for approval`;
  return (
    <span
      data-testid="pending-changes-badge"
      aria-label={label}
      title={label}
      className="rounded-full bg-neon/20 px-[6px] font-mono text-10 font-medium text-ink-0"
    >
      {count > 99 ? '99+' : String(count)}
    </span>
  );
}
```

In `desktop/src/renderer/components/Sidebar.tsx`, add `import { PendingChangesBadge } from './PendingChangesBadge';`, and in the `NAV_ITEMS.map` badge expression replace the final `) : null` with:

```tsx
              ) : item.id === 'changes' ? (
                <PendingChangesBadge />
              ) : null
```

- [ ] **Step 5: Run the tests, typecheck and lint**

Run: `cd "$B3/desktop" && npx vitest run src/renderer && npm run typecheck && npm run lint`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd "$B3" && git add desktop/src && git commit -m "feat(desktop): pending-changes hooks and the Changes nav badge (B3)"
```

---

### Task 7: The Pending section on the Changes screen

**Files:**
- Create: `desktop/src/renderer/components/PendingChanges.tsx`
- Modify: `desktop/src/renderer/screens/changes.tsx` (B2)
- Test: `desktop/src/renderer/__tests__/PendingChanges.test.tsx`
- Modify: `desktop/src/renderer/__tests__/ChangesScreen.test.tsx` (B2: append one test)

**Interfaces:**
- Consumes: Task 6 (`usePendingChanges`, `useApproveChange`, `useRejectChange`, `PENDING_CHANGES_PATH`); B2 (`useChange`, `ChangeDetailResponse` with `before`/`after`/`current`/`changedSince`); A3 (`LineDiffView`, `actorLabel`); `useNoteView().open`, `formatRelativeTime`, `toast`, `ApiError`, `Btn`.
- Produces: `<PendingChanges />`, a `region` named "waiting for your approval" holding one card per pending change (`data-testid="pending-<id>"`). It renders nothing when none wait. Each card shows the actor chip, path, proposed op, reason, time, risk reasons (a list named "why it waits"), the proposed diff (`pending-diff-<id>`) and **approve** / **reject**. A 409 on approve shows an alert with the drift diff (`pending-drift-<id>`), **approve anyway**, **reject** and **cancel**.

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/PendingChanges.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { PendingChanges } from '../components/PendingChanges';
import { PENDING_CHANGES_PATH } from '../lib/api/hooks';
import { useToasts } from '../stores/toast';
import type { ChangeDetailResponse, ChangeSummary } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

const HELD: ChangeSummary = {
  id: 7, ts: '2026-10-10T09:00:00+00:00', actor: 'plugin:familiar',
  path: '90-meta/templates/standup.md', destPath: null, op: 'create', reason: 'plugin write-back',
  status: 'pending', riskReasons: ['edits a template'], resolvedTs: null,
};

function setup(items: ChangeSummary[], detail: Partial<ChangeDetailResponse> = {}) {
  getMock.mockImplementation(async (path: string) => {
    if (path === PENDING_CHANGES_PATH) return { items, pendingCount: items.length, degraded: false };
    if (path === '/v1/changes/7') {
      return { ...HELD, before: null, after: '# Standup', current: null, changedSince: false, diff: '', ...detail };
    }
    throw new Error(`unexpected GET ${path}`);
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PendingChanges />
    </QueryClientProvider>,
  );
}

const messages = () => useToasts.getState().toasts.map((t) => t.message);

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  useToasts.setState({ toasts: [] });
});

describe('PendingChanges', () => {
  it('lists held changes with the actor, the reasons and the proposed diff', async () => {
    setup([HELD]);
    const card = await screen.findByTestId('pending-7');
    expect(within(card).getByText('⧉ familiar')).toBeInTheDocument();
    expect(within(card).getByText('would create')).toBeInTheDocument();
    expect(within(within(card).getByRole('list', { name: 'why it waits' })).getByText('edits a template'))
      .toBeInTheDocument();
    expect(await screen.findByTestId('pending-diff-7')).toHaveTextContent('+ # Standup');
    expect(screen.getByRole('region', { name: 'waiting for your approval' })).toBeInTheDocument();
  });

  it('renders nothing when nothing waits', async () => {
    setup([]);
    await waitFor(() => expect(getMock).toHaveBeenCalledWith(PENDING_CHANGES_PATH));
    expect(screen.queryByRole('region', { name: 'waiting for your approval' })).toBeNull();
  });

  it('approves', async () => {
    postMock.mockResolvedValue({ id: 7, status: 'applied', path: HELD.path, etag: 'e' });
    setup([HELD]);
    const card = await screen.findByTestId('pending-7');
    fireEvent.click(within(card).getByRole('button', { name: 'approve' }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/v1/changes/7/approve', { force: false }));
    await waitFor(() => expect(messages().some((m) => m.startsWith('approved'))).toBe(true));
  });

  it('a stale approval shows what changed and can be forced', async () => {
    postMock
      .mockRejectedValueOnce(new client.ApiError('the note changed since this was proposed', 409))
      .mockResolvedValueOnce({ id: 7, status: 'applied', path: HELD.path, etag: 'e' });
    setup([HELD], { current: 'the user wrote this', changedSince: true });
    const card = await screen.findByTestId('pending-7');
    fireEvent.click(within(card).getByRole('button', { name: 'approve' }));
    const alert = await within(card).findByRole('alert');
    expect(alert).toHaveTextContent('changed since');
    expect(await screen.findByTestId('pending-drift-7')).toHaveTextContent('+ the user wrote this');
    fireEvent.click(within(card).getByRole('button', { name: 'approve anyway' }));
    await waitFor(() => expect(postMock).toHaveBeenLastCalledWith('/v1/changes/7/approve', { force: true }));
  });

  it('rejects', async () => {
    postMock.mockResolvedValue({ id: 7, status: 'rejected' });
    setup([HELD]);
    const card = await screen.findByTestId('pending-7');
    fireEvent.click(within(card).getByRole('button', { name: 'reject' }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/v1/changes/7/reject'));
    await waitFor(() => expect(messages().some((m) => m.startsWith('rejected'))).toBe(true));
  });

  it('reports a failed approval', async () => {
    postMock.mockRejectedValue(new client.ApiError('history unavailable', 500));
    setup([HELD]);
    const card = await screen.findByTestId('pending-7');
    fireEvent.click(within(card).getByRole('button', { name: 'approve' }));
    await waitFor(() => expect(messages()).toContain('approve failed: history unavailable'));
  });
});
```

Append inside `describe('ChangesScreen', …)` in `desktop/src/renderer/__tests__/ChangesScreen.test.tsx` (B2):

```tsx
  it('shows held changes above the history and keeps them out of it', async () => {
    const held: ChangeSummary = {
      ...AI, id: 9, status: 'pending', riskReasons: ['edits a template'], reason: 'held one',
    };
    setup(list({ items: [held, AI, PLUGIN], pendingCount: 1 }));
    expect(await screen.findByTestId('pending-9')).toBeInTheDocument();
    expect(screen.queryByTestId('change-9')).toBeNull();
    expect(screen.getByTestId('change-2')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B3/desktop" && npx vitest run src/renderer/__tests__/PendingChanges.test.tsx src/renderer/__tests__/ChangesScreen.test.tsx`
Expected: FAIL. Resolving `../components/PendingChanges` fails, and the ChangesScreen test finds no `pending-9`.

- [ ] **Step 3: The component**

Create `desktop/src/renderer/components/PendingChanges.tsx`:

```tsx
import { useState } from 'react';
import { ApiError } from '../lib/api/client';
import { useApproveChange, useChange, usePendingChanges, useRejectChange } from '../lib/api/hooks';
import { formatRelativeTime } from '../lib/format';
import { actorLabel } from './HistoryDrawer';
import { LineDiffView } from './LineDiffView';
import { Btn } from './Btn';
import { useNoteView } from '../stores/note-view';
import { toast } from '../stores/toast';
import type { ChangeOp, ChangeSummary } from '../../shared/api-types';

const PROPOSED_OP: Record<ChangeOp, string> = {
  create: 'would create',
  modify: 'would edit',
  delete: 'would delete',
  move: 'would move',
};

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

function PendingCard({ change }: { change: ChangeSummary }) {
  const detail = useChange(change.id);
  const approve = useApproveChange();
  const reject = useRejectChange();
  const openNote = useNoteView((s) => s.open);
  const [stale, setStale] = useState(false);
  const busy = approve.isPending || reject.isPending;
  const canOpen = change.op !== 'create' && change.path.endsWith('.md');
  const d = detail.data;

  const onApprove = async (force: boolean) => {
    try {
      await approve.mutateAsync({ id: change.id, force });
      toast.success('approved — the change is in your notes now');
    } catch (err) {
      if (!force && err instanceof ApiError && err.status === 409) {
        setStale(true);
        void detail.refetch();
        return;
      }
      toast.error(`approve failed: ${message(err)}`);
    }
  };

  const onReject = async () => {
    try {
      await reject.mutateAsync({ id: change.id });
      toast.success('rejected — nothing was written');
    } catch (err) {
      toast.error(`reject failed: ${message(err)}`);
    }
  };

  return (
    <li data-testid={`pending-${change.id}`} className="rounded-sm border border-hairline bg-paper p-3">
      <div className="flex items-center gap-3 text-12">
        <span className="flex-shrink-0 rounded-sm bg-fog px-[6px] py-[1px] font-mono text-10 text-ink-1">
          {actorLabel(change.actor)}
        </span>
        {canOpen ? (
          <button
            type="button"
            onClick={() => openNote(change.path)}
            className="min-w-0 cursor-pointer truncate border-none bg-transparent p-0 text-left text-ink-0 hover:underline"
          >
            {change.path}
          </button>
        ) : (
          <span className="min-w-0 truncate text-ink-0">{change.path}</span>
        )}
        <span className="flex-shrink-0 text-ink-2">
          {PROPOSED_OP[change.op]}
          {change.destPath ? ` → ${change.destPath}` : ''}
        </span>
        <span className="min-w-0 flex-1 truncate text-ink-2">{change.reason}</span>
        <span className="flex-shrink-0 font-mono text-10 text-ink-3">{formatRelativeTime(change.ts)}</span>
      </div>
      <ul aria-label="why it waits" className="m-0 mt-2 flex list-none flex-wrap gap-2 p-0">
        {change.riskReasons.map((r) => (
          <li key={r} className="rounded-sm bg-oxblood/10 px-[6px] py-[1px] text-11 text-oxblood">
            {r}
          </li>
        ))}
      </ul>
      {d && (
        <LineDiffView
          testId={`pending-diff-${change.id}`}
          className="mt-2 max-h-[320px]"
          oldText={d.before ?? ''}
          newText={d.after ?? ''}
          legend="- now · + proposed"
        />
      )}
      {d?.changedSince && !stale && (
        <p className="m-0 mt-2 text-11 text-ink-2">this note changed since the change was proposed</p>
      )}
      {stale ? (
        <div role="alert" className="mt-2 rounded-sm border border-oxblood/30 bg-oxblood/10 p-2 text-12">
          <p className="m-0 mb-2 text-ink-0">
            This note changed since the change was proposed. Approve anyway? The current version stays
            in page history.
          </p>
          {d && (
            <LineDiffView
              testId={`pending-drift-${change.id}`}
              className="mb-2 max-h-[240px]"
              oldText={d.before ?? ''}
              newText={d.current ?? ''}
              legend="- when proposed · + on disk now"
            />
          )}
          <div className="flex gap-2">
            <Btn variant="danger" size="sm" disabled={busy} onClick={() => void onApprove(true)}>
              approve anyway
            </Btn>
            <Btn variant="ghost" size="sm" disabled={busy} onClick={() => void onReject()}>
              reject
            </Btn>
            <Btn variant="ghost" size="sm" onClick={() => setStale(false)}>
              cancel
            </Btn>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex gap-2">
          <Btn variant="primary" size="sm" disabled={busy} onClick={() => void onApprove(false)}>
            approve
          </Btn>
          <Btn variant="ghost" size="sm" disabled={busy} onClick={() => void onReject()}>
            reject
          </Btn>
        </div>
      )}
    </li>
  );
}

/** Spec B §6 (slice B3): risky changes held for your approval. */
export function PendingChanges() {
  const pending = usePendingChanges();
  const items = (pending.data?.items ?? []).filter((c) => c.status === 'pending');
  if (items.length === 0) return null;
  return (
    <section aria-label="waiting for your approval" className="mb-6">
      <h2 className="m-0 mb-2 font-mono text-10 uppercase tracking-eyebrow text-oxblood">
        waiting for your approval · {items.length}
      </h2>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {items.map((c) => (
          <PendingCard key={c.id} change={c} />
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 4: Put it on the screen**

In `desktop/src/renderer/screens/changes.tsx` (B2), add `import { PendingChanges } from '../components/PendingChanges';`. Insert `<PendingChanges />` directly before the `<div className="mb-4 flex flex-wrap items-center gap-2">` that holds the filter chips (after the degraded alert). Replace the `ChangesScreen` doc comment with:

```tsx
/** Spec B §6: changes held for approval (B3) on top, then every assistant /
 * MCP / plugin / job change with a diff and one-click revert (B2). */
```

- [ ] **Step 5: Run the full desktop gates**

Run: `cd "$B3/desktop" && npx vitest run && npm run typecheck && npm run lint`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd "$B3" && git add desktop/src && git commit -m "feat(desktop): Pending section with approve, reject and stale-approval prompt (B3)"
```

---

### Task 8: A held assistant save never slips through the editor

**Files:**
- Modify: `desktop/src/shared/api-types.ts` (`UpdateNoteBodyResponse`, `UpdateJotResponse`)
- Modify: `desktop/src/renderer/lib/use-guarded-save.ts` (B2 version)
- Modify: `desktop/src/renderer/components/GuardedNoteEditor.tsx`
- Test: `desktop/src/renderer/__tests__/use-guarded-save.test.tsx` (append)
- Test: `desktop/src/renderer/__tests__/GuardedNoteEditor.test.tsx` (append)

**Interfaces:**
- Consumes: Task 4 (`status` on `PATCH /v1/notes/body` and `PATCH /v1/notes/{id}`); B2 Task 9 (`sendAs`, `queuedActorRef`, `attributeNext`, the `actor` argument of `run` / `handleConflict`).
- Produces:
  - `UpdateNoteBodyResponse` and `UpdateJotResponse` gain `status?: 'applied' | 'pending'` and `changeId?: string | null`.
  - `SaveTarget.send` resolves `{ etag?: string | null; status?: 'applied' | 'pending' }`.
  - `useGuardedSave(initial, target, onError?, onHeld?: (diskBody: string) => void)`. When a save comes back `pending`, the body is **not** marked saved (the etag stays), text queued behind it is dropped, and `onHeld` gets the last saved body.
  - `GuardedNoteEditor` remounts the editor on that body and shows the toast `The assistant’s change is waiting for your approval on the Changes screen.`

- [ ] **Step 1: Write the failing tests**

Append inside `describe('useGuardedSave', …)` in `desktop/src/renderer/__tests__/use-guarded-save.test.tsx`:

```tsx
  it('a held change is not marked saved and drops text queued on top of it', async () => {
    const first = deferred<{ etag: string; status: 'pending' }>();
    const send = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce({ etag: 'e2' });
    const onHeld = vi.fn();
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }, undefined, onHeld),
    );
    act(() => {
      result.current.attributeNext('assistant');
      result.current.save('ai text');
    });
    act(() => result.current.save('ai text + a keystroke'));
    await act(async () => first.resolve({ etag: 'e1', status: 'pending' }));
    expect(onHeld).toHaveBeenCalledWith('a');
    expect(send).toHaveBeenCalledTimes(1);
    act(() => result.current.save('typed later'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls[1]).toEqual(['typed later', 'e1']);
  });

  it('a held auto-resolve resend is reported too', async () => {
    const send = vi
      .fn()
      .mockRejectedValueOnce(conflict())
      .mockResolvedValueOnce({ etag: 'e5', status: 'pending' });
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'a', etag: 'e5' });
    const onHeld = vi.fn();
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }, undefined, onHeld),
    );
    act(() => {
      result.current.attributeNext('assistant');
      result.current.save('ai text');
    });
    await waitFor(() => expect(onHeld).toHaveBeenCalledWith('a'));
    expect(result.current.conflict).toBeNull();
  });
```

In `desktop/src/renderer/__tests__/GuardedNoteEditor.test.tsx`, add `import { useToasts } from '../stores/toast';` to the imports, and append inside `describe('GuardedNoteEditor', …)`:

```tsx
  it('a held assistant change puts the editor back on the saved text and says why', async () => {
    const send = vi.fn().mockResolvedValue({ etag: E1, status: 'pending' });
    const fetchLatest = vi.fn();
    const getEditor = setup(send, fetchLatest);
    await typeTail(getEditor);
    await waitFor(() => expect(send).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText(/my tail/)).toBeNull());
    expect(screen.getByText('original line')).toBeInTheDocument();
    expect(useToasts.getState().toasts.map((t) => t.message)).toContain(
      'The assistant’s change is waiting for your approval on the Changes screen.',
    );
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B3/desktop" && npx vitest run src/renderer/__tests__/use-guarded-save.test.tsx src/renderer/__tests__/GuardedNoteEditor.test.tsx`
Expected: FAIL. `onHeld` is never called, and the editor keeps "my tail".

- [ ] **Step 3: Types**

In `desktop/src/shared/api-types.ts`, add to both `UpdateNoteBodyResponse` and `UpdateJotResponse`:

```ts
  /** 'pending': held for your approval (spec B3); nothing was written. */
  status?: 'applied' | 'pending';
  changeId?: string | null;
```

- [ ] **Step 4: The guarded save**

In `desktop/src/renderer/lib/use-guarded-save.ts`, change `SaveTarget.send`'s return type to `Promise<{ etag?: string | null; status?: 'applied' | 'pending' }>`. Change the hook signature to:

```ts
export function useGuardedSave(
  initial: { body: string; etag: string | null },
  target: SaveTarget,
  onError?: (err: Error) => void,
  /** A save came back held for approval (B3): nothing was written. Called
   * with the last saved body, which is what is on disk. */
  onHeld?: (diskBody: string) => void,
): GuardedSave {
```

Below `onErrorRef.current = onError;` add:

```ts
  const onHeldRef = useRef(onHeld);
  onHeldRef.current = onHeld;
```

Replace B2's `handleConflict` and `run` with:

```ts
  /** Resolves true when the resent change was held for approval (B3). */
  const handleConflict = async (
    mine: string,
    allowAutoResolve: boolean,
    actor?: WriteActor,
  ): Promise<boolean> => {
    let latest: { body: string; etag?: string | null };
    try {
      latest = await targetRef.current.fetchLatest();
    } catch (err) {
      onErrorRef.current?.(asError(err));
      // Keystrokes may have landed in the conflict while we awaited.
      setConflict({ mine: conflictRef.current?.mine ?? mine, theirs: '', theirsEtag: null, unread: true });
      return false;
    }
    if (sameBody(latest.body, mine)) {
      // Disk already holds my text: nothing to resolve, just take its etag.
      markSaved(mine, latest.etag);
      const c = conflictRef.current;
      if (c && sameBody(c.mine, mine)) setConflict(null);
      return false;
    }
    if (allowAutoResolve && sameBody(latest.body, baseBodyRef.current)) {
      try {
        const res = await sendAs(mine, latest.etag ?? null, actor);
        if (res.status === 'pending') {
          markSaved(baseBodyRef.current, latest.etag);
          return true;
        }
        markSaved(mine, res.etag);
      } catch (err) {
        if (isConflict(err)) return handleConflict(mine, false, actor);
        onErrorRef.current?.(asError(err));
      }
      return false;
    }
    setConflict({
      mine: conflictRef.current?.mine ?? mine,
      theirs: latest.body,
      theirsEtag: latest.etag ?? null,
    });
    return false;
  };

  const run = async (body: string, actor?: WriteActor): Promise<void> => {
    inFlightRef.current = true;
    let held = false;
    try {
      const res = await sendAs(body, etagRef.current, actor);
      // B3: a held change wrote nothing; the disk still matches the last save.
      if (res.status === 'pending') held = true;
      else markSaved(body, res.etag);
    } catch (err) {
      if (isConflict(err)) held = await handleConflict(body, true, actor);
      else onErrorRef.current?.(asError(err));
    } finally {
      inFlightRef.current = false;
    }
    const next = queuedRef.current;
    const nextActor = queuedActorRef.current ?? undefined;
    queuedRef.current = null;
    queuedActorRef.current = null;
    if (held) {
      // Text queued behind a held change still contains it. Saving that as a
      // keystroke would write the change without approval, so drop it and
      // put the editor back on what is on disk.
      onHeldRef.current?.(baseBodyRef.current);
      return;
    }
    if (next === null) return;
    if (conflictRef.current) setConflict({ ...conflictRef.current, mine: next });
    else await run(next, nextActor);
  };
```

In `keepMine`, the existing `if (isConflict(err)) await handleConflict(...)` line keeps working unchanged (its boolean result is ignored: a user save is never held).

- [ ] **Step 5: The editor**

In `desktop/src/renderer/components/GuardedNoteEditor.tsx`, add `import { toast } from '../stores/toast';` and add this fourth argument to the `useGuardedSave(...)` call (after `onSaveError,`):

```tsx
    (diskBody) => {
      setDoc((d) => ({ body: diskBody, nonce: d.nonce + 1 }));
      toast.info('The assistant’s change is waiting for your approval on the Changes screen.');
    },
```

- [ ] **Step 6: Run the full desktop gates**

Run: `cd "$B3/desktop" && npx vitest run && npm run typecheck && npm run lint`
Expected: PASS

- [ ] **Step 7: Run the full backend suite once more**

Run: `cd "$B3" && python -m pytest ghostbrain/api/tests tests/test_changes_log.py tests/test_vault_write_changes.py tests/test_changes_revert.py tests/test_changes_maintenance.py tests/test_changes_approve.py tests/test_vault_write_risk.py tests/test_mcp_client.py tests/test_mcp_tools.py tests/test_vault_write_history.py tests/test_vault_write_writer.py tests/test_vault_write_text.py tests/test_history_store.py tests/test_history_retention.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
cd "$B3" && git add desktop/src && git commit -m "feat(desktop): a held assistant save resets the editor instead of slipping through (B3)"
```

---

## Manual check (after Task 8, by the user, not the agent)

Agents must not run the app.
- Ask chat to write a doc that includes a `<script>`. The agent says it is waiting for approval, the nav badge shows 1 within 30 s, and the Changes screen shows it under "waiting for your approval". Approve: the doc appears in the History list as ⌁ mcp "created". Revert it.
- Let a plugin write into `90-meta/templates/`. It waits. Edit the same file yourself, then Approve: the "changed since" prompt shows your text. "approve anyway" keeps your text in page history.
- In a jot, accept a docs-panel proposal that adds `{{ date }}`. The editor goes back to your text and the toast points to the Changes screen.

## Self-review

- **Spec coverage.** §3 path rules (90-meta, Stable profile files, templates folder) → Task 2. Content rules on added lines (`<script`, `on…=`, `javascript:`, `{{ … }}`, executable fences) → Task 2. Deletes and moves of files the actor didn't create → Tasks 1 and 2. "Plain prose edits and new notes … applied immediately" → Task 2 tests. "Approving re-runs steps 2, 5, 6 and 7 against the current file … conflict diff instead of writing" → Task 3 (stale check, snapshot, atomic write, row update) and Task 7 (drift diff). §4 statuses `pending`/`applied`/`rejected` → Tasks 1 and 3. §5 approve/reject routes → Task 5. §6 Pending section with actor, path, reason, risk reasons, diff, Approve/Reject → Task 7; nav badge polled every 30 s → Task 6. Error row "Approving a stale pending change: a conflict diff, never a blind write" → Tasks 3, 5 and 7. Testing row "each path and content rule, plus prose that must not be held" → Task 2; "approve or reject pending, stale approve" → Tasks 3 and 5; Vitest "pending approve or reject … badge count" → Tasks 6 and 7. Decision 3 (plugins in 90-meta always pending) → Task 2 and Task 5 tests.
- **Placeholder scan.** Every code step carries full code. Edits to B2-owned code quote the exact block replaced.
- **Type consistency.** `approved_change` is `int` in Python, `change_id` stays `str` in `WriteResult`. `changeId` is `str | None` in every JSON body and `string | null` in TS. The approve route returns B2's `ChangeActionResponse` shape; reject returns `ChangeRejectResponse`. `held_flip` is defined in Task 3 and used by `approve.py`, B2's `drift`, and therefore the detail route's `changedSince`. `PENDING_CHANGES_PATH` is shared by the hook and both tests.
- **Review Focus.** All five lines are pinned by named tests in their owning tasks.

## Decisions on ambiguities (resolved in this plan)

1. **The risk rules are the default hold policy, not installed at import.** B2's tests reset the policy with `set_hold_policy(None)`. If that meant "never hold", every later test, and any code path that resets it, would leave the vault unguarded. Now `None` restores the risk rules.
2. **`worker:jot-router` is exempt from the ownership rule.** Its job is moving the user's jots. Every other actor, workers included, is held when deleting or moving a note it didn't create. Path and content rules still apply to the router.
3. **Template expressions are held in any note, not just template files.** A `{{ … }}` placeholder is harmless in a plain note, but the spec lists it as a content rule without a path limit, and a note can be saved as a template later. `js` / `javascript` fences are held only inside templates, as the spec says. `dataviewjs` is held anywhere.
4. **A stale approval returns 409 and leaves the row `pending`.** The user can then reject it, or approve anyway (which snapshots the current version first). The `conflicted` status from spec §4 stays unused. A pending row that can still be approved or rejected is simpler than a fourth state with the same two buttons.
5. **Approval writes as the change's own actor, not as the user,** and reuses the pending row as the applied row. That keeps the Changes screen honest (it shows "⧉ familiar created …", not "you"), lets B2's Revert work on it unchanged, and records ownership for later deletes and moves.
6. **Held responses keep their status codes** (200 with `status: "pending"`), except `DELETE /v1/notes/{id}`, which answers 202, because its 204 has no body to carry the status.
7. **The editor drops keystrokes typed during a held assistant save.** The queued body contains the held text, and saving it as the user would bypass approval. The window is the length of one save round-trip, and the toast explains what happened.
8. **Ownership is "created by this actor, then moved only by it".** A user who deletes a plugin's note and makes a new one at the same path is a gap: the plugin still counts as its creator. Closing it would need per-path lineage the change log does not keep.
