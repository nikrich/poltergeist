# One-Click Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download installer → open app → backend fully works: vault auto-bootstraps on first run, the bundled binary doubles as the full `ghostbrain` CLI, and the vault's context list is user configuration instead of Jannik's hardcoded workspaces.

**Architecture:** All behavior lives in the Python sidecar so dev (`python -m ghostbrain.api`) and frozen (PyInstaller `ghostbrain-api`) builds share one code path. A new `ghostbrain/routing_config.py` is the single source of truth for the context list (read from `routing.yaml:contexts`, legacy fallback for old vaults). `ghostbrain/api/__main__.py` grows a first-run `ensure_vault()` and a busybox-style subcommand table mirroring `[project.scripts]`. The desktop app adds one optional macOS Settings action that writes a `poltergeist` PATH shim.

**Tech Stack:** Python 3.11 (pytest, PyYAML, tomllib), PyInstaller spec, Electron/TypeScript (vitest) for the shim only.

**Spec:** `docs/superpowers/specs/2026-07-14-one-click-install-design.md`

## Global Constraints

- Legacy context tuple `("sanlam", "codeship", "reducedrecipes", "personal")` may appear in exactly ONE place in `ghostbrain/`: the fallback in `ghostbrain/routing_config.py` (enforced by Task 6's guard test).
- New-vault default contexts are exactly `("personal", "work")`.
- `needs_review` is never a configured context: the router schema appends it; the notes API excludes it.
- Sidecar startup must not crash-loop: first-run bootstrap failures are logged and the server still boots (Electron `sidecar.ts` auto-respawns on exit).
- All subcommand imports in `ghostbrain/api/__main__.py` stay lazy (inside the dispatch path) — the frozen `ghostbrain-api mcp` subprocess must not pay for the API app stack (see the module docstring of `tests/test_api_main_dispatch.py`).
- Never rewrite an existing `routing.yaml` wholesale — only append the `contexts:` block when the key is absent (preserves user comments/edits).
- Run Python tests from the repo root with the project venv active: `source .venv/bin/activate` (create via `python3.11 -m venv .venv && pip install -e ".[dev,api]"` if missing). Desktop tests: `cd desktop && npm test`.
- Commit after every task; never commit unrelated working-tree changes (`git add` explicit paths only — the branch has unrelated in-flight work).

---

### Task 1: `routing_config.contexts()` accessor

**Files:**
- Create: `ghostbrain/routing_config.py`
- Test: `tests/test_routing_config.py`

**Interfaces:**
- Consumes: `ghostbrain.paths.vault_path()` (existing; reads `$VAULT_PATH` per call).
- Produces (used by Tasks 2, 3, 4, 5, 6):
  - `LEGACY_CONTEXTS: tuple[str, ...]` — the legacy four; the only allowed home of those literals.
  - `DEFAULT_CONTEXTS: tuple[str, ...] == ("personal", "work")`
  - `contexts(root: Path | None = None) -> tuple[str, ...]` — configured list from `<root or vault_path()>/90-meta/routing.yaml`, else `LEGACY_CONTEXTS`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_routing_config.py
"""routing_config.contexts(): the single source of truth for the context list.

routing.yaml's `contexts:` key drives the router enum, notes-API validation,
digests, and metrics. Missing/invalid values fall back to the legacy four so
pre-existing vaults keep working untouched.
"""
from __future__ import annotations

from pathlib import Path

from ghostbrain import routing_config


def _write_routing(vault: Path, body: str) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")


def test_configured_contexts_are_returned_in_order(vault):
    _write_routing(vault, "version: 1\ncontexts:\n  - alpha\n  - beta\n")
    assert routing_config.contexts() == ("alpha", "beta")


def test_missing_key_falls_back_to_legacy(vault):
    _write_routing(vault, "version: 1\n")
    assert routing_config.contexts() == routing_config.LEGACY_CONTEXTS


def test_missing_file_falls_back_to_legacy(vault):
    assert routing_config.contexts() == routing_config.LEGACY_CONTEXTS


def test_empty_list_falls_back_to_legacy(vault):
    _write_routing(vault, "contexts: []\n")
    assert routing_config.contexts() == routing_config.LEGACY_CONTEXTS


def test_non_list_falls_back_to_legacy(vault):
    _write_routing(vault, "contexts: banana\n")
    assert routing_config.contexts() == routing_config.LEGACY_CONTEXTS


def test_non_string_entries_fall_back_to_legacy(vault):
    _write_routing(vault, "contexts:\n  - alpha\n  - 42\n")
    assert routing_config.contexts() == routing_config.LEGACY_CONTEXTS


def test_entries_are_stripped(vault):
    _write_routing(vault, 'contexts:\n  - " alpha "\n  - beta\n')
    assert routing_config.contexts() == ("alpha", "beta")


def test_explicit_root_overrides_vault_path(vault, tmp_path):
    other = tmp_path / "other-vault"
    _write_routing(other, "contexts:\n  - solo\n")
    assert routing_config.contexts(root=other) == ("solo",)


def test_default_contexts_are_neutral():
    assert routing_config.DEFAULT_CONTEXTS == ("personal", "work")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routing_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostbrain.routing_config'`

- [ ] **Step 3: Write the implementation**

```python
# ghostbrain/routing_config.py
"""Vault-level routing configuration accessors.

The context *list* lives in routing.yaml under a top-level ``contexts:`` key.
This module is the single source of truth for reading it — the router schema,
notes-API validation, digests, and metrics all derive their list from here.

Back-compat: vaults whose routing.yaml predates the key fall back to the
legacy hardcoded four. That tuple may exist NOWHERE else in ghostbrain/
(enforced by tests/test_no_hardcoded_contexts.py).
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.routing_config")

# Fallback for vaults without a `contexts:` key. Do not add call sites — use
# contexts() instead.
LEGACY_CONTEXTS: tuple[str, ...] = ("sanlam", "codeship", "reducedrecipes", "personal")

# Seeded into brand-new vaults by bootstrap.
DEFAULT_CONTEXTS: tuple[str, ...] = ("personal", "work")

_warned = False


def contexts(root: Path | None = None) -> tuple[str, ...]:
    """Configured context list from routing.yaml, or the legacy fallback.

    ``needs_review`` is never part of this list: callers that want it (the
    router enum, digest ordering) append it themselves.
    """
    global _warned
    f = (root or vault_path()) / "90-meta" / "routing.yaml"
    raw: dict = {}
    try:
        loaded = yaml.safe_load(f.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = loaded
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001 — malformed YAML must not kill callers
        log.warning("could not read %s: %s", f, e)

    value = raw.get("contexts")
    if (
        isinstance(value, list)
        and value
        and all(isinstance(c, str) and c.strip() for c in value)
    ):
        return tuple(c.strip() for c in value)

    if not _warned:
        log.warning(
            "no valid `contexts:` list in %s — falling back to legacy contexts %s. "
            "Add a `contexts:` key (or run ghostbrain-bootstrap) to configure.",
            f,
            LEGACY_CONTEXTS,
        )
        _warned = True
    return LEGACY_CONTEXTS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_routing_config.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/routing_config.py tests/test_routing_config.py
git commit -m "feat: routing_config.contexts() — context list as vault config"
```

---

### Task 2: Bootstrap seeds contexts from config, neutral seed templates

**Files:**
- Modify: `ghostbrain/bootstrap.py`
- Test: `tests/test_bootstrap_contexts.py` (create)

**Interfaces:**
- Consumes: `routing_config.contexts(root=...)`, `routing_config.DEFAULT_CONTEXTS` (Task 1).
- Produces: `bootstrap(root=None)` unchanged signature, new behavior: fresh vault → `DEFAULT_CONTEXTS` folders + `contexts:` key in seeded routing.yaml; existing vault → in-effect contexts' folders ensured + `contexts:` block appended to routing.yaml if absent. Module constant `CONTEXTS` is deleted.

Background: `bootstrap.py:16` defines `CONTEXTS`; `bootstrap():904` iterates it; `SEED_FILES` string literals mention the four contexts in the routing.yaml seed, the router prompt seed, and the daily/weekly digest prompt seeds.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bootstrap_contexts.py
"""bootstrap(): context folders and seeds come from configuration.

Fresh vault → neutral DEFAULT_CONTEXTS. Existing vault → whatever
routing_config resolves (configured or legacy fallback), and routing.yaml
gains the `contexts:` key by APPEND (user edits/comments preserved).
"""
from __future__ import annotations

import yaml

from ghostbrain import routing_config
from ghostbrain.bootstrap import bootstrap


def test_fresh_vault_seeds_default_contexts(vault):
    root = bootstrap()
    for ctx in routing_config.DEFAULT_CONTEXTS:
        assert (root / "20-contexts" / ctx / "_index.md").exists()
    routing = yaml.safe_load((root / "90-meta" / "routing.yaml").read_text())
    assert routing["contexts"] == list(routing_config.DEFAULT_CONTEXTS)


def test_fresh_vault_has_no_legacy_context_folders(vault):
    root = bootstrap()
    assert not (root / "20-contexts" / "sanlam").exists()


def test_seeded_files_do_not_mention_legacy_contexts(vault):
    root = bootstrap()
    for f in root.rglob("*"):
        if f.is_file() and f.suffix in (".md", ".yaml"):
            body = f.read_text(encoding="utf-8")
            for name in ("sanlam", "codeship", "reducedrecipes"):
                assert name not in body, f"{name} leaked into seed {f}"


def test_router_prompt_seed_uses_contexts_placeholder(vault):
    root = bootstrap()
    prompt = (root / "90-meta" / "prompts" / "router.md").read_text()
    assert "{{contexts}}" in prompt


def test_existing_vault_without_key_gets_contexts_appended(vault):
    root = bootstrap()  # first boot: default contexts
    routing_file = root / "90-meta" / "routing.yaml"
    # Simulate a legacy vault: strip the contexts key, keep a user comment.
    body = routing_file.read_text()
    stripped = "\n".join(
        line for line in body.splitlines()
        if not line.startswith("contexts:") and not line.startswith("  - ")
    )
    routing_file.write_text("# user comment to preserve\n" + stripped + "\n")

    bootstrap()

    after = routing_file.read_text()
    assert "# user comment to preserve" in after
    routing = yaml.safe_load(after)
    # Key absent → legacy fallback list is what gets recorded.
    assert routing["contexts"] == list(routing_config.LEGACY_CONTEXTS)


def test_existing_vault_with_key_is_untouched(vault):
    root = bootstrap()
    routing_file = root / "90-meta" / "routing.yaml"
    routing_file.write_text("contexts:\n  - alpha\n")

    bootstrap()

    assert routing_file.read_text() == "contexts:\n  - alpha\n"
    assert (root / "20-contexts" / "alpha" / "_index.md").exists()


def test_bootstrap_is_idempotent(vault):
    a = bootstrap()
    before = sorted(str(p.relative_to(a)) for p in a.rglob("*"))
    b = bootstrap()
    after = sorted(str(p.relative_to(b)) for p in b.rglob("*"))
    assert a == b
    assert before == after
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bootstrap_contexts.py -v`
Expected: FAIL — fresh vault seeds `sanlam/...` folders, no `contexts:` key in seeded routing.yaml.

- [ ] **Step 3: Implement in `ghostbrain/bootstrap.py`**

3a. Imports and constant: delete line 16 (`CONTEXTS: tuple[str, ...] = (...)`) and add:

```python
import re

from ghostbrain import routing_config
```

3b. Context resolution + seed rendering helpers (place above `bootstrap()`):

```python
def _resolve_contexts(root: Path) -> tuple[str, ...]:
    """Context list for this bootstrap run.

    Existing vault (routing.yaml present) → configured list, or the legacy
    fallback via routing_config. Fresh vault → neutral defaults.
    """
    if (root / "90-meta" / "routing.yaml").exists():
        return routing_config.contexts(root=root)
    return routing_config.DEFAULT_CONTEXTS


def _render_seed(body: str, contexts: tuple[str, ...]) -> str:
    """Substitute context markers in seed templates."""
    return (
        body.replace("__CONTEXTS_CSV__", ", ".join(contexts))
        .replace("__CONTEXTS_YAML__", "\n".join(f"  - {c}" for c in contexts))
        .replace(
            "__CONTEXT_BULLETS__",
            "\n".join(f"- **{c}** — TODO: describe this context." for c in contexts),
        )
    )


def _ensure_contexts_key(root: Path, contexts: tuple[str, ...]) -> None:
    """Append a `contexts:` block to an existing routing.yaml lacking one.

    Append-only on purpose: rewriting via yaml.dump would destroy the user's
    comments. A top-level key at EOF is valid YAML.
    """
    f = root / "90-meta" / "routing.yaml"
    if not f.exists():
        return
    body = f.read_text(encoding="utf-8")
    if re.search(r"(?m)^contexts\s*:", body):
        return
    block = (
        "\n# The vault's contexts (workspaces). Single source of truth — the\n"
        "# router, digests, and notes API all derive their list from here.\n"
        "contexts:\n" + "\n".join(f"  - {c}" for c in contexts) + "\n"
    )
    f.write_text(body + block, encoding="utf-8")
```

3c. In `bootstrap()` (currently `bootstrap.py:893`): resolve contexts FIRST (before any files are written — `_resolve_contexts` must see the pre-run state), then swap the loop and seed writes:

```python
def bootstrap(root: Path | None = None) -> Path:
    """Create the vault tree and seed files. Idempotent.

    Returns the resolved vault root.
    """
    root = (root or vault_path()).expanduser().resolve()
    contexts = _resolve_contexts(root)
    root.mkdir(parents=True, exist_ok=True)

    for rel in TOP_LEVEL_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)

    for ctx in contexts:          # was: for ctx in CONTEXTS
        ctx_root = root / "20-contexts" / ctx
        ctx_root.mkdir(parents=True, exist_ok=True)
        for sub in CONTEXT_SUBDIRS:
            (ctx_root / sub).mkdir(parents=True, exist_ok=True)
        # Per-context index + profile stubs.
        _write_if_absent(ctx_root / "_index.md", f"# {ctx.title()} context\n")
        _write_if_absent(
            ctx_root / "_profile.md",
            f"# {ctx.title()} profile\n\nContext-specific profile, populated in Phase 6.\n",
        )

    # Per-context daily digest folder gets a placeholder so Obsidian shows it.
    (root / "10-daily" / "by-context").mkdir(parents=True, exist_ok=True)

    for rel, body in SEED_FILES.items():
        _write_if_absent(root / rel, _render_seed(body, contexts))

    _ensure_contexts_key(root, contexts)

    log.info("Vault ready at %s", root)
    return root
```

3d. Neutralize every context mention inside `SEED_FILES` literals and comments. Find them all with:

Run: `grep -n "sanlam\|codeship\|reducedrecipes" ghostbrain/bootstrap.py`

Apply these replacements (content-based — line numbers will have shifted):

| Current seed text | Replacement |
|---|---|
| `Available contexts: sanlam, codeship, reducedrecipes, personal — see` (router prompt seed) | `Available contexts: {{contexts}} — see` |
| `` `context` ∈ `{sanlam, codeship, reducedrecipes, personal, needs_review}`. `` (router prompt seed) | `` `context` must be one of the available contexts above, or `needs_review`. `` |
| The context bullet list in the daily-digest prompt seed (`- **sanlam** — the user's primary employer / day-job work.` and its 3 sibling bullets) | `__CONTEXT_BULLETS__` (single line replacing all four bullets) |
| `# Routing rules — maps source signals to one of: sanlam, codeship, reducedrecipes, personal.` (routing.yaml seed header) | `# Routing rules — maps source signals to one of the contexts listed below.` |
| Every `# TODO:` example naming a real context (e.g. `# TODO: "your-org": sanlam`, `# TODO: e.g. "PROJ": sanlam`, `#     context: sanlam`) | same line with the context replaced by `your-context` |
| Any seed body that enumerates per-context sections or bullets (e.g. the CLAUDE.md/profile seed's `## sanlam` … `## personal` sections — the 3d grep shows every occurrence) | Replace the whole enumerated block with the single line `__CONTEXT_SECTIONS__`, and add this marker to `_render_seed`: `.replace("__CONTEXT_SECTIONS__", "\n\n".join(f"## {c}\n- TODO: what belongs to this context." for c in contexts))` |

Then add the `contexts:` block to the routing.yaml seed itself, directly under `version: 1`:

```yaml
version: 1

# The vault's contexts (workspaces). Single source of truth — the router,
# digests, and notes API all derive their list from here.
contexts:
__CONTEXTS_YAML__
```

3e. Re-run the grep from 3d. Expected: zero matches in `bootstrap.py`.

- [ ] **Step 4: Run the new tests and the existing suite**

Run: `pytest tests/test_bootstrap_contexts.py -v && pytest tests/ -x -q`
Expected: new tests pass. Existing tests keep passing because the `vault` fixture's tmp vault has no routing.yaml → every accessor falls back to the legacy four; any test that calls `bootstrap()` AND asserts on legacy context folders will now fail — update those assertions to use `routing_config.DEFAULT_CONTEXTS` (fresh-vault bootstraps now seed neutral contexts; that behavior change is the point of the feature).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/bootstrap.py tests/test_bootstrap_contexts.py
git commit -m "feat: bootstrap seeds contexts from routing.yaml config, neutral defaults"
```

---

### Task 3: Router — dynamic schema enum + prompt injection

**Files:**
- Modify: `ghostbrain/worker/router.py:30-51` (schema), `:249-260` (`_route_via_llm`)
- Test: `tests/test_router_contexts.py` (create)

**Interfaces:**
- Consumes: `routing_config.contexts()` (Task 1).
- Produces: `router_json_schema(contexts: tuple[str, ...]) -> dict` (module-level function replacing the `ROUTER_JSON_SCHEMA` constant). `{{contexts}}` placeholder substitution in the router prompt.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_router_contexts.py
"""Router derives its context enum and prompt from routing_config."""
from __future__ import annotations

import json

from ghostbrain import routing_config
from ghostbrain.worker import router as router_mod


def _configure(vault, ctxs: list[str]) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("contexts:\n" + "\n".join(f"  - {c}" for c in ctxs))


def test_schema_enum_is_configured_contexts_plus_needs_review(vault):
    _configure(vault, ["alpha", "beta"])
    schema = router_mod.router_json_schema(routing_config.contexts())
    assert schema["properties"]["context"]["enum"] == ["alpha", "beta", "needs_review"]


def test_llm_route_uses_configured_enum_and_injects_prompt(vault, monkeypatch):
    _configure(vault, ["alpha", "beta"])
    prompts = vault / "90-meta" / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "router.md").write_text(
        "Contexts: {{contexts}}\n\n{{content}}", encoding="utf-8"
    )

    captured: dict = {}

    class FakeResult:
        def as_json(self):
            return {"context": "alpha", "confidence": 0.9, "reasoning": "r"}

    def fake_run(prompt, *, model, json_schema):
        captured["prompt"] = prompt
        captured["schema"] = json_schema
        return FakeResult()

    monkeypatch.setattr(router_mod.llm, "run", fake_run)

    decision = router_mod._route_via_llm({"id": "e1"}, "hello world", config={})

    assert decision.context == "alpha"
    assert "Contexts: alpha, beta" in captured["prompt"]
    assert captured["schema"]["properties"]["context"]["enum"] == [
        "alpha", "beta", "needs_review",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_router_contexts.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'router_json_schema'`

- [ ] **Step 3: Implement in `ghostbrain/worker/router.py`**

Add the import:

```python
from ghostbrain import routing_config
```

Replace the `ROUTER_JSON_SCHEMA` constant (lines 30-51) with:

```python
def router_json_schema(contexts: tuple[str, ...]) -> dict[str, Any]:
    """JSON schema for the routing LLM call, enum built from configuration."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["context", "confidence", "reasoning"],
        "properties": {
            "context": {
                "type": "string",
                "enum": [*contexts, "needs_review"],
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "reasoning": {"type": "string", "maxLength": 400},
            "secondary_contexts": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
        },
    }
```

In `_route_via_llm` (currently `router.py:249`), build both from configuration:

```python
def _route_via_llm(event: dict, excerpt: str, config: dict) -> RoutingDecision:
    ctxs = routing_config.contexts()
    prompt_template = _read_prompt("router.md")
    prompt = (
        prompt_template
        .replace("{{content}}", excerpt)
        # New seeds carry {{contexts}}; on legacy prompts (no placeholder)
        # this is a no-op and the hardcoded list in the prompt stays —
        # consistent with the legacy-fallback contexts.
        .replace("{{contexts}}", ", ".join(ctxs))
    )
    ...
        result = llm.run(
            prompt,
            model=(config.get("llm") or {}).get("router_model", "haiku"),
            json_schema=router_json_schema(ctxs),
        )
    ...everything else unchanged...
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_router_contexts.py tests/test_router.py tests/test_routing_config.py -v` (if `tests/test_router.py` doesn't exist, run `pytest tests/ -q -k router`)
Expected: PASS. If any existing test imports `ROUTER_JSON_SCHEMA`, update it to `router_json_schema(routing_config.contexts())`.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/worker/router.py tests/test_router_contexts.py
git commit -m "feat: router enum + prompt derive contexts from routing.yaml"
```

---

### Task 4: Notes API validates against configured contexts

**Files:**
- Modify: `ghostbrain/api/routes/notes.py:33-37` (constant), `:178-181` (validation)
- Test: `tests/test_notes_route_contexts.py` (create)

**Interfaces:**
- Consumes: `routing_config.contexts()` (Task 1).
- Produces: no new public surface; `_KNOWN_CONTEXTS` constant is deleted.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notes_route_contexts.py
"""POST /v1/notes/{id}/route validates against configured contexts."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from ghostbrain.api.routes import notes as notes_mod


def _configure(vault, ctxs: list[str]) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("contexts:\n" + "\n".join(f"  - {c}" for c in ctxs))


def test_configured_context_is_accepted_needs_review_is_not(vault):
    _configure(vault, ["alpha", "beta"])
    assert notes_mod._known_contexts() == {"alpha", "beta"}


def test_route_note_rejects_unconfigured_context(vault, monkeypatch):
    _configure(vault, ["alpha"])
    req = notes_mod.RouteNoteRequest(context="sanlam")
    with pytest.raises(HTTPException) as exc:
        notes_mod.route_note(req, jot_id="a" * 12)
    assert exc.value.status_code == 400
    assert "sanlam" in exc.value.detail
```

Note: if `RouteNoteRequest` has additional required fields, fill them with minimal valid values (open `notes.py` to check the model).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_notes_route_contexts.py -v`
Expected: FAIL — `AttributeError: ... has no attribute '_known_contexts'`

- [ ] **Step 3: Implement in `ghostbrain/api/routes/notes.py`**

Add the import, delete the `_KNOWN_CONTEXTS` constant and its sync-comment (lines 33-37), add:

```python
from ghostbrain import routing_config


def _known_contexts() -> set[str]:
    """Valid targets for manual re-routes.

    "needs_review" is intentionally excluded: it is a fallback state, not a
    user-selectable destination.
    """
    return set(routing_config.contexts())
```

In `route_note` (line ~178):

```python
    valid = _known_contexts()
    if req.context not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"unknown context: {req.context!r}; valid: {sorted(valid)}",
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_notes_route_contexts.py -v && pytest tests/ -q -k notes`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/routes/notes.py tests/test_notes_route_contexts.py
git commit -m "feat: notes re-route validation uses configured contexts"
```

---

### Task 5: Digests + anticipation iterate configured contexts

**Files:**
- Modify: `ghostbrain/worker/digest.py:35-37` + `_ordered_contexts` (~line 855)
- Modify: `ghostbrain/worker/weekly_digest.py:41-43` + `_quiet_contexts` (~265) + `_ordered_contexts` (~400)
- Modify: `ghostbrain/metrics/anticipation.py:37-39` + the two `for ctx in KNOWN_CONTEXTS` loops (~71, ~79)
- Test: `tests/test_digest_contexts.py` (create)

**Interfaces:**
- Consumes: `routing_config.contexts()` (Task 1).
- Produces: all three `KNOWN_CONTEXTS` module constants deleted.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_digest_contexts.py
"""Digest ordering and anticipation iterate configured contexts."""
from __future__ import annotations

from ghostbrain.metrics import anticipation as anticipation_mod
from ghostbrain.worker import digest as digest_mod
from ghostbrain.worker import weekly_digest as weekly_mod


def _configure(vault, ctxs: list[str]) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("contexts:\n" + "\n".join(f"  - {c}" for c in ctxs))


def test_daily_ordering_uses_configured_then_alpha_extras(vault):
    _configure(vault, ["beta", "alpha"])
    ordered = digest_mod._ordered_contexts(
        {"alpha": [], "beta": [], "zzz": [], "needs_review": []}
    )
    assert ordered == ["beta", "alpha", "needs_review", "zzz"]


def test_weekly_quiet_contexts_use_configured_list(vault):
    _configure(vault, ["alpha", "beta"])
    quiet = weekly_mod._quiet_contexts({"alpha": 10, "needs_review": 0})
    assert quiet == ["beta"]  # beta has 0 events; needs_review never counts


def test_weekly_ordering_uses_configured_list(vault):
    _configure(vault, ["beta", "alpha"])
    ordered = weekly_mod._ordered_contexts({"alpha": 1, "beta": 2, "zzz": 3})
    assert ordered == ["beta", "alpha", "zzz"]


def test_anticipation_only_considers_configured_contexts(vault):
    _configure(vault, ["alpha"])
    # No audit data at all → no anticipations, but critically no crash and
    # no iteration over legacy contexts.
    assert anticipation_mod.detect_anticipations() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_digest_contexts.py -v`
Expected: FAIL — ordering follows the legacy tuple, `beta` missing from quiet list.

- [ ] **Step 3: Implement**

In **`ghostbrain/worker/digest.py`**: add `from ghostbrain import routing_config`, delete the `KNOWN_CONTEXTS` constant (lines 35-37), and in `_ordered_contexts`:

```python
def _ordered_contexts(by_context: dict[str, list]) -> list[str]:
    """Stable ordering: configured contexts first, then anything else alphabetically."""
    seen = set(by_context.keys())
    out: list[str] = []
    for ctx in (*routing_config.contexts(), "needs_review"):
        if ctx in seen:
            out.append(ctx)
            seen.discard(ctx)
    out.extend(sorted(seen))
    return out
```

In **`ghostbrain/worker/weekly_digest.py`**: same import, delete the constant (lines 41-43), then:

```python
def _quiet_contexts(activity_by_context: dict[str, int]) -> list[str]:
    """Configured contexts with fewer than QUIET_THRESHOLD events all week."""
    out: list[str] = []
    for ctx in routing_config.contexts():
        if activity_by_context.get(ctx, 0) < QUIET_THRESHOLD:
            out.append(ctx)
    return out
```

(the explicit `needs_review` skip is now unnecessary — it is never in `contexts()`), and:

```python
def _ordered_contexts(activity: dict[str, int]) -> list[str]:
    seen = set(activity.keys())
    out: list[str] = []
    for ctx in (*routing_config.contexts(), "needs_review"):
        if ctx in seen:
            out.append(ctx)
            seen.discard(ctx)
    out.extend(sorted(seen))
    return out
```

In **`ghostbrain/metrics/anticipation.py`**: same import, delete the constant (lines 37-39), and in `detect_anticipations` replace both loops:

```python
    known = routing_config.contexts()
    ...
        for ctx in known:
            by_weekday_ctx[(cur.weekday(), ctx)].append(per_ctx.get(ctx, 0))
    ...
    for ctx in known:
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_digest_contexts.py tests/test_digest.py tests/test_anticipation.py -v`
Expected: PASS — existing tests still pass because the fixture vault has no routing.yaml → legacy fallback preserves current ordering (`tests/test_digest.py:116` relies on sanlam-before-codeship).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/worker/digest.py ghostbrain/worker/weekly_digest.py ghostbrain/metrics/anticipation.py tests/test_digest_contexts.py
git commit -m "feat: digests and anticipation iterate configured contexts"
```

---

### Task 6: Guard test — legacy names live in exactly one file

**Files:**
- Test: `tests/test_no_hardcoded_contexts.py` (create)

**Interfaces:**
- Consumes: nothing (pure filesystem scan).
- Produces: regression guard; will fail CI if anyone re-hardcodes a context name in `ghostbrain/`.

- [ ] **Step 1: Write the test**

```python
# tests/test_no_hardcoded_contexts.py
"""The legacy context names may appear in ghostbrain/ ONLY in
routing_config.py (the back-compat fallback). Everything else must go
through routing_config.contexts().
"""
from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "ghostbrain"
ALLOWED = {PACKAGE / "routing_config.py"}
NAMES = ("sanlam", "codeship", "reducedrecipes")  # "personal" is a legit default


def test_legacy_context_names_only_in_routing_config():
    offenders: list[str] = []
    for f in PACKAGE.rglob("*.py"):
        if f in ALLOWED or "__pycache__" in f.parts:
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        for name in NAMES:
            if name in body:
                offenders.append(f"{f.relative_to(PACKAGE.parent)}: {name}")
    assert not offenders, (
        "hardcoded context names found (use ghostbrain.routing_config.contexts()):\n"
        + "\n".join(offenders)
    )
```

- [ ] **Step 2: Run it**

Run: `pytest tests/test_no_hardcoded_contexts.py -v`
Expected: PASS if Tasks 2-5 were thorough. If it FAILS, the failure lists the stragglers — fix each by switching it to `routing_config.contexts()` (code) or neutral wording (comments/seeds), then re-run until green. Do not add files to `ALLOWED`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_no_hardcoded_contexts.py
git commit -m "test: guard against re-hardcoding context names"
```

---

### Task 7: `ensure_vault()` — first-run bootstrap in the sidecar

**Files:**
- Modify: `ghostbrain/api/__main__.py` (new function + one call in `_run_api_server`)
- Test: `tests/test_api_main_dispatch.py` (extend)

**Interfaces:**
- Consumes: `ghostbrain.paths.vault_path()`, `ghostbrain.bootstrap.bootstrap()` (lazy import).
- Produces: `ensure_vault() -> None` in `ghostbrain.api.__main__`, called first in `_run_api_server()`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_api_main_dispatch.py`)

```python
def test_ensure_vault_bootstraps_when_missing(vault):
    from ghostbrain.api.__main__ import ensure_vault

    assert not (vault / "90-meta" / "routing.yaml").exists()
    ensure_vault()
    assert (vault / "90-meta" / "routing.yaml").exists()


def test_ensure_vault_is_noop_when_vault_exists(vault):
    from ghostbrain.api.__main__ import ensure_vault

    marker = vault / "90-meta" / "routing.yaml"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("sentinel: true\n", encoding="utf-8")

    ensure_vault()

    assert marker.read_text() == "sentinel: true\n"
    # No other bootstrap artifacts were created.
    assert not (vault / "20-contexts").exists()


def test_ensure_vault_swallows_bootstrap_errors(vault, monkeypatch):
    import ghostbrain.bootstrap as bootstrap_mod
    from ghostbrain.api.__main__ import ensure_vault

    def boom() -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(bootstrap_mod, "bootstrap", boom)
    ensure_vault()  # must not raise — sidecar would crash-loop otherwise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_main_dispatch.py -v -k ensure_vault`
Expected: FAIL — `ImportError: cannot import name 'ensure_vault'`

- [ ] **Step 3: Implement in `ghostbrain/api/__main__.py`**

Add above `_run_api_server()`:

```python
def ensure_vault() -> None:
    """First-run bootstrap: create the vault if it doesn't exist yet.

    Failure is logged, never raised — the Electron parent auto-respawns the
    sidecar on exit, so raising here would crash-loop; a degraded-but-up API
    surfaces the problem in the app instead.
    """
    from ghostbrain.paths import vault_path

    marker = vault_path() / "90-meta" / "routing.yaml"
    if marker.exists():
        return
    try:
        import ghostbrain.bootstrap as bootstrap_mod

        root = bootstrap_mod.bootstrap()
        log.info("first run: bootstrapped vault at %s", root)
    except Exception:  # noqa: BLE001 — see docstring
        log.exception("vault bootstrap failed — continuing so the API can surface it")
```

First line of `_run_api_server()` (before the uvicorn/app imports):

```python
def _run_api_server() -> int:
    ensure_vault()
    # Import the app stack lazily, ... (existing comment/code unchanged)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api_main_dispatch.py -v`
Expected: all pass (including the two pre-existing dispatch tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/__main__.py tests/test_api_main_dispatch.py
git commit -m "feat: sidecar bootstraps the vault on first run"
```

---

### Task 8: PyInstaller spec bundles the whole `ghostbrain` package

**Files:**
- Modify: `packaging/sidecar.spec:68-77`

**Interfaces:**
- Consumes/Produces: nothing at the Python level; packaged-build behavior only.

- [ ] **Step 1: Edit the spec**

Replace these lines (keep the `ghostbrain.mcp` comment block above `collect_all('mcp'...)` if separate; adjust only the ghostbrain collect lines):

```python
# Scheduler picks up runner shims and the worker/recorder modules dynamically.
# Pull each in so PyInstaller's static analyzer doesn't skip them.
hiddenimports += collect_submodules('ghostbrain.connectors')
hiddenimports += collect_submodules('ghostbrain.worker')
hiddenimports += collect_submodules('ghostbrain.recorder')
hiddenimports += collect_submodules('ghostbrain.profile')
```

with:

```python
# The frozen binary is the whole product: HTTP sidecar, MCP server, first-run
# bootstrap, and every ghostbrain-* CLI via the subcommand multiplexer in
# ghostbrain.api.__main__. Collect the entire package so no runtime-dispatched
# module (bootstrap, metrics, semantic, future additions) is silently missing.
hiddenimports += collect_submodules('ghostbrain')
```

Also delete the now-redundant `hiddenimports += collect_submodules('ghostbrain.mcp')` line further down (the whole-package collect covers it); keep its explanatory comment attached to the `collect_all('mcp')`/`copy_metadata` lines that remain.

- [ ] **Step 2: Sanity-check the spec parses**

Run: `python -c "compile(open('packaging/sidecar.spec').read(), 'sidecar.spec', 'exec')" && echo OK`
Expected: `OK` (full packaged verification happens in Task 11's manual check).

- [ ] **Step 3: Commit**

```bash
git add packaging/sidecar.spec
git commit -m "build: bundle the entire ghostbrain package in the sidecar"
```

---

### Task 9: CLI multiplexer — the bundled binary is the CLI

**Files:**
- Modify: `ghostbrain/api/__main__.py:123-135` (`main()`)
- Test: `tests/test_api_main_dispatch.py` (extend)

**Interfaces:**
- Consumes: every `[project.scripts]` entry in `pyproject.toml` (existing `main()` functions).
- Produces: `SUBCOMMANDS: dict[str, str]` mapping subcommand → `"module:function"`, exactly mirroring `pyproject.toml` scripts minus the `ghostbrain-` prefix. `main(["<sub>", ...rest])` dispatches with shifted argv; unknown subcommand → exit 2; no argv → HTTP server (unchanged).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_api_main_dispatch.py`)

```python
def test_subcommands_exactly_mirror_pyproject_scripts():
    import tomllib

    from ghostbrain.api.__main__ import SUBCOMMANDS

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    )
    scripts: dict[str, str] = pyproject["project"]["scripts"]
    expected = {
        name.removeprefix("ghostbrain-"): target for name, target in scripts.items()
    }
    assert SUBCOMMANDS == expected


def test_dispatch_shifts_argv_and_returns_zero(monkeypatch):
    import ghostbrain.bootstrap as bootstrap_mod

    seen: dict = {}

    def fake_main() -> None:
        seen["argv"] = list(sys.argv)

    monkeypatch.setattr(bootstrap_mod, "main", fake_main)
    old_argv = list(sys.argv)
    try:
        rc = main(["bootstrap", "--verbose"])
    finally:
        sys.argv = old_argv

    assert rc == 0
    assert seen["argv"] == ["ghostbrain-bootstrap", "--verbose"]


def test_unknown_subcommand_exits_2_and_lists_available(capsys):
    rc = main(["frobnicate"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "frobnicate" in err
    assert "bootstrap" in err  # the available list is printed
```

Add `from pathlib import Path` to the test file's imports if missing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_main_dispatch.py -v -k "subcommand or dispatch or unknown"`
Expected: FAIL — `ImportError: cannot import name 'SUBCOMMANDS'` / exit-2 path missing.

- [ ] **Step 3: Implement in `ghostbrain/api/__main__.py`**

Replace `main()` (lines 123-135) with:

```python
# The packaged build ships ONE executable, so it doubles as the whole
# ghostbrain CLI. Keys mirror [project.scripts] in pyproject.toml minus the
# "ghostbrain-" prefix; values are "module:function". Kept in lockstep by
# tests/test_api_main_dispatch.py::test_subcommands_exactly_mirror_pyproject_scripts.
# All imports stay lazy: `ghostbrain-api mcp` must not pay for the API stack
# (see module docstring of the test file).
SUBCOMMANDS: dict[str, str] = {
    "bootstrap": "ghostbrain.bootstrap:main",
    "worker": "ghostbrain.worker.main:main",
    "claude-md": "ghostbrain.profile.claude_md:main",
    "digest": "ghostbrain.worker.digest:main",
    "weekly-digest": "ghostbrain.worker.weekly_digest:main",
    "github-fetch": "ghostbrain.connectors.github.__main__:main",
    "jira-fetch": "ghostbrain.connectors.jira.__main__:main",
    "confluence-fetch": "ghostbrain.connectors.confluence.__main__:main",
    "profile-apply": "ghostbrain.profile.apply:main",
    "profile-decay": "ghostbrain.profile.decay:main",
    "calendar-fetch": "ghostbrain.connectors.calendar.__main__:main",
    "calendar-auth": "ghostbrain.connectors.calendar.auth_cli:main",
    "gmail-fetch": "ghostbrain.connectors.gmail.__main__:main",
    "gmail-auth": "ghostbrain.connectors.gmail.auth_cli:main",
    "slack-fetch": "ghostbrain.connectors.slack.__main__:main",
    "slack-token-add": "ghostbrain.connectors.slack.token_cli:main",
    "joplin-fetch": "ghostbrain.connectors.joplin.__main__:main",
    "microsoft-auth": "ghostbrain.connectors.microsoft.graph.auth_cli:main",
    "outlook-mail-fetch": "ghostbrain.connectors.microsoft.outlook_mail.__main__:main",
    "teams-chat-fetch": "ghostbrain.connectors.microsoft.teams_chat.__main__:main",
    "teams-meetings-fetch": "ghostbrain.connectors.microsoft.teams_meetings.__main__:main",
    "transcribe": "ghostbrain.recorder.main:main",
    "recorder": "ghostbrain.recorder.daemon_cli:main",
    "recorder-recover": "ghostbrain.recorder.recover_cli:main",
    "metrics": "ghostbrain.metrics.main:main",
    "semantic-refresh": "ghostbrain.semantic.main:main",
    "mcp": "ghostbrain.mcp.__main__:main",
}


def _dispatch(name: str, rest: list[str]) -> int:
    import importlib

    mod_name, func_name = SUBCOMMANDS[name].split(":")
    mod = importlib.import_module(mod_name)
    # Entry-point mains read sys.argv themselves; present the same argv they
    # would see as a pip-installed console script.
    sys.argv = [f"ghostbrain-{name}", *rest]
    rc = getattr(mod, func_name)()
    return rc if isinstance(rc, int) else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in SUBCOMMANDS:
        return _dispatch(argv[0], argv[1:])
    if argv and argv[0] in ("help", "--help", "-h"):
        print(
            "usage: ghostbrain-api [subcommand] [args...]\n\n"
            "With no subcommand, serves the Poltergeist HTTP sidecar API.\n"
            "Subcommands:\n  " + "\n  ".join(sorted(SUBCOMMANDS))
        )
        return 0
    if argv:
        print(
            f"unknown subcommand: {argv[0]!r}\n"
            f"available: {', '.join(sorted(SUBCOMMANDS))}",
            file=sys.stderr,
        )
        return 2
    return _run_api_server()
```

Verify against `pyproject.toml:67-94` that the table matches every script (the parity test enforces this); the packaged/dev server boot is unaffected because `desktop/src/main/sidecar.ts:39` spawns the frozen binary with `args: []` and dev uses `-m ghostbrain.api` with no extra args.

Note the pre-existing `test_main_dispatches_mcp_subcommand` keeps passing: `_dispatch` resolves `getattr(mod, "main")` at call time, so its monkeypatch of `ghostbrain.mcp.__main__.main` still intercepts.

- [ ] **Step 4: Run the whole test file**

Run: `pytest tests/test_api_main_dispatch.py -v`
Expected: all pass, including the two pre-existing dispatch tests and Task 7's `ensure_vault` tests.

- [ ] **Step 5: Integration sanity check (dev venv)**

Run: `python -m ghostbrain.api --help && VAULT_PATH=$(mktemp -d)/vault python -m ghostbrain.api bootstrap`
Expected: help text lists subcommands; bootstrap prints `Vault bootstrapped at: ...` and exits 0.

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/__main__.py tests/test_api_main_dispatch.py
git commit -m "feat: ghostbrain-api multiplexes every ghostbrain-* CLI subcommand"
```

---

### Task 10: macOS PATH shim ("Install command line tool")

**Files:**
- Create: `desktop/src/main/cli-shim.ts`
- Modify: `desktop/src/main/index.ts` (one `ipcMain.handle`), `desktop/src/preload/index.ts` (bridge entry), `desktop/src/shared/types.ts` (`GbBridge`), `desktop/src/renderer/screens/settings.tsx` (row in `BackgroundSettings`)
- Test: `desktop/src/main/__tests__/cli-shim.test.ts`

**Interfaces:**
- Consumes: bundled binary at `join(process.resourcesPath, 'sidecar', 'ghostbrain-api', 'ghostbrain-api')` (same resolution as `sidecar.ts:36`).
- Produces: `installCliShim(opts: CliShimOptions): Promise<CliShimResult>`; IPC channel `gb:cli:install`; `window.gb.cli.install(): Promise<{ path: string; onPath: boolean }>`.

- [ ] **Step 1: Write the failing test**

```typescript
// desktop/src/main/__tests__/cli-shim.test.ts
import { mkdtemp, readFile, stat, chmod, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { installCliShim } from '../cli-shim';

describe('installCliShim', () => {
  it('writes an executable wrapper into the first writable candidate', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'shim-'));
    const result = await installCliShim({
      binaryPath: '/Applications/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api',
      candidates: [join(dir, 'bin')],
      pathEnv: `${join(dir, 'bin')}:/usr/bin`,
    });

    expect(result.path).toBe(join(dir, 'bin', 'poltergeist'));
    expect(result.onPath).toBe(true);
    const body = await readFile(result.path, 'utf8');
    expect(body).toBe(
      '#!/bin/sh\nexec "/Applications/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api" "$@"\n',
    );
    const mode = (await stat(result.path)).mode & 0o777;
    expect(mode).toBe(0o755);
  });

  it('falls through to the next candidate when a dir is unwritable', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'shim-'));
    const locked = join(dir, 'locked');
    await mkdir(locked);
    await chmod(locked, 0o444);
    const fallback = join(dir, 'fallback');

    const result = await installCliShim({
      binaryPath: '/x/ghostbrain-api',
      candidates: [locked, fallback],
      pathEnv: '/usr/bin',
    });

    expect(result.path).toBe(join(fallback, 'poltergeist'));
    expect(result.onPath).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/main/__tests__/cli-shim.test.ts`
Expected: FAIL — cannot resolve `../cli-shim`.

- [ ] **Step 3: Implement `desktop/src/main/cli-shim.ts`**

```typescript
import { chmod, mkdir, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { delimiter, join } from 'node:path';

export interface CliShimOptions {
  /** Absolute path to the bundled ghostbrain-api binary. */
  binaryPath: string;
  /** Install locations, tried in order. Defaults to /usr/local/bin then ~/.local/bin. */
  candidates?: string[];
  /** PATH to check membership against. Defaults to process.env.PATH. */
  pathEnv?: string;
}

export interface CliShimResult {
  /** Where the `poltergeist` wrapper was written. */
  path: string;
  /** Whether its directory is already on PATH. */
  onPath: boolean;
}

/**
 * Write a `poltergeist` shell wrapper that execs the bundled sidecar binary,
 * so connector auth / fetch commands need no Python install (VS Code's
 * "install code command" pattern). macOS-only for now.
 */
export async function installCliShim(opts: CliShimOptions): Promise<CliShimResult> {
  const candidates = opts.candidates ?? ['/usr/local/bin', join(homedir(), '.local', 'bin')];
  const script = `#!/bin/sh\nexec "${opts.binaryPath}" "$@"\n`;
  let lastErr: unknown = new Error('no install candidates');
  for (const dir of candidates) {
    const target = join(dir, 'poltergeist');
    try {
      await mkdir(dir, { recursive: true });
      await writeFile(target, script, 'utf8');
      await chmod(target, 0o755);
      const pathEnv = opts.pathEnv ?? process.env.PATH ?? '';
      return { path: target, onPath: pathEnv.split(delimiter).includes(dir) };
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/main/__tests__/cli-shim.test.ts`
Expected: 2 passed

- [ ] **Step 5: Wire IPC + bridge + settings row**

`desktop/src/main/index.ts` — next to the other `gb:shell:*` handlers (~line 205):

```typescript
import { installCliShim } from './cli-shim';   // top of file with the other './' imports

ipcMain.handle('gb:cli:install', () =>
  installCliShim({
    binaryPath: join(process.resourcesPath, 'sidecar', 'ghostbrain-api', 'ghostbrain-api'),
  }),
);
```

(`join` is already imported in `index.ts`; if not, add it to the existing `node:path` import.)

`desktop/src/preload/index.ts` — add to the bridge object:

```typescript
  cli: {
    install: () => ipcRenderer.invoke('gb:cli:install'),
  },
```

`desktop/src/shared/types.ts` — add to `GbBridge` (alongside `shell:`, ~line 53):

```typescript
  cli: {
    install: () => Promise<{ path: string; onPath: boolean }>;
  };
```

`desktop/src/renderer/screens/settings.tsx` — inside `BackgroundSettings()`'s returned JSX, after the existing rows, add (matching the `SettingRow`/`Btn` pattern used in `VaultSettings`):

```tsx
      {window.gb.platform === 'darwin' && <CliShimRow />}
```

and the component (near the other private components at the bottom):

```tsx
function CliShimRow() {
  const [status, setStatus] = useState<string | null>(null);
  const onInstall = async () => {
    try {
      const res = await window.gb.cli.install();
      setStatus(
        res.onPath
          ? `installed at ${res.path}`
          : `installed at ${res.path} — add its folder to your PATH`,
      );
    } catch {
      setStatus('install failed — check folder permissions');
    }
  };
  return (
    <SettingRow
      label="command line tool"
      sub={status ?? "installs a `poltergeist` command for connector setup (runs the bundled backend CLI)."}
      control={
        <Btn variant="secondary" size="sm" onClick={() => void onInstall()}>
          install
        </Btn>
      }
    />
  );
}
```

(`useState`, `SettingRow`, and `Btn` are already imported/defined in `settings.tsx`.)

- [ ] **Step 6: Typecheck, lint, full desktop tests**

Run: `cd desktop && npm run typecheck && npm run lint && npm test`
Expected: clean. (Reminder: `tsc --noEmit` is a no-op in this repo — `npm run typecheck` is the real check.)

- [ ] **Step 7: Commit**

```bash
git add desktop/src/main/cli-shim.ts desktop/src/main/__tests__/cli-shim.test.ts desktop/src/main/index.ts desktop/src/preload/index.ts desktop/src/shared/types.ts desktop/src/renderer/screens/settings.tsx
git commit -m "feat(desktop): install poltergeist CLI shim from settings (macOS)"
```

---

### Task 11: Docs + full-suite + packaged-build verification

**Files:**
- Modify: `README.md` (install section), `docs/install/macos-launchd.md`, `docs/install/windows.md`, `docs/install/linux.md` (one paragraph each)

- [ ] **Step 1: Update docs**

In `README.md`'s install/quickstart section, replace the pip-first instructions with:

```markdown
## Install

Grab the installer for your OS from [GitHub Releases](https://github.com/nikrich/ghost-brain/releases)
(macOS `.dmg`, Windows `Setup.exe`, Linux `.AppImage`/`.deb`). The app is
self-contained: on first launch it creates the vault at `~/ghostbrain/vault/`
and everything except LLM features works immediately. LLM features (chat,
digests) additionally need the [Claude Code CLI](https://claude.com/claude-code)
installed and logged in.

Connector setup (gmail, slack, github, …) uses the bundled CLI — no Python
install needed. On macOS, Settings → background → "command line tool" installs
a `poltergeist` command; elsewhere invoke the bundled binary directly
(e.g. `<install dir>/resources/sidecar/ghostbrain-api/ghostbrain-api gmail-auth you@example.com`).
The developer setup (`pip install -e .`) is only for working on Poltergeist itself.
```

In each `docs/install/*.md`, add a short note at the top that the desktop app is self-contained (auto-bootstraps the vault; `ghostbrain-api <subcommand>` replaces the pip-installed `ghostbrain-*` commands) and that these pages cover the headless/pip setup.

- [ ] **Step 2: Full test suites**

Run: `pytest tests/ -q && cd desktop && npm test && cd ..`
Expected: everything green.

- [ ] **Step 3: Manual packaged verification (macOS)**

```bash
pyinstaller packaging/sidecar.spec --distpath desktop/resources/sidecar --workpath packaging/build --noconfirm
cd desktop && npm run pack:unsigned && cd ..
# Fresh-machine simulation:
TMP_VAULT=$(mktemp -d)/vault
VAULT_PATH="$TMP_VAULT" open desktop/dist/mac-arm64/Poltergeist.app
```

Verify: app opens with a working (empty) vault at `$TMP_VAULT`; `ls "$TMP_VAULT/20-contexts"` shows `personal work`; then:

```bash
"desktop/dist/mac-arm64/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api" --help
```

shows the subcommand list, and `... bootstrap` exits 0. Finally launch the app WITHOUT `VAULT_PATH` and confirm the existing vault behaves exactly as before (legacy contexts intact).

- [ ] **Step 4: Commit**

```bash
git add README.md docs/install/macos-launchd.md docs/install/windows.md docs/install/linux.md
git commit -m "docs: one-click install — self-contained app, bundled CLI"
```

---

## Drift Addendum (2026-07-14, worktree based on origin/main)

The plan above was drafted against the `feat/plugin-system` tree. The execution
worktree is based on `origin/main`, where the chat-project-folders feature has
landed. These amendments override the corresponding task text; everything not
mentioned stands.

### Task 3 (router) — REPLACED

Main already builds the router enum dynamically: `router.py:65
build_router_schema()` deep-copies `ROUTER_JSON_SCHEMA` and sets the enum to
`projects_repo.active_destinations() + ["needs_review"]`, where destinations are
contexts plus active `context/slug` projects. The context list now lives in
`ghostbrain/api/repo/projects.py:18 KNOWN_CONTEXTS`. Amended task:

1. In `ghostbrain/api/repo/projects.py`: delete the `KNOWN_CONTEXTS` constant;
   add `from ghostbrain import routing_config`; replace its two internal uses
   (`get_project`'s context validation ~line 76, `active_destinations()` ~line
   124) with `routing_config.contexts()`.
2. In `ghostbrain/worker/router.py`: replace `projects_repo.KNOWN_CONTEXTS` in
   `parse_destination` (~line 82) with `routing_config.contexts()`; in the
   `ROUTER_JSON_SCHEMA` constant replace the hardcoded four-name enum with
   `"enum": ["needs_review"]` and add the comment
   `# Placeholder — build_router_schema() replaces this with the live destination list.`
   `build_router_schema()` itself needs no change. Keep the `{{contexts}}`
   prompt injection from the original Task 3 text in `_route_via_llm` (~line
   290): inject `", ".join(routing_config.contexts())`.
3. Tests (same TDD flow): assert `build_router_schema()`'s enum equals
   configured contexts + `["needs_review"]` when the vault's routing.yaml
   configures `["alpha", "beta"]` and no projects registry exists; keep the
   prompt-injection test from the original task, but capture the schema passed
   to `llm.run` and assert it came from `build_router_schema()` (enum matches
   configured contexts + needs_review). Drop the planned new
   `router_json_schema(contexts)` function entirely.
4. `route_note`'s optional `req.project` validation in notes.py (Task 4) is
   pre-existing behavior — leave it untouched.

### New Task 5b: remaining production references (dispatch after Task 5)

- `ghostbrain/api/repo/answer.py:39` (`PROMPT_TEMPLATE`): replace the sentence
  `The user is a software engineer working across four contexts: sanlam (day-job/employer), codeship (consulting + product), reducedrecipes (side project), and personal projects.`
  with `The user is a software engineer working across these contexts: {contexts}.`
  and pass `contexts=", ".join(routing_config.contexts())` at the single
  `PROMPT_TEMPLATE.format(...)` call site. Test: format the template via the
  existing call path with a configured vault and assert the configured names
  appear in the prompt.
- `ghostbrain/profile/apply.py:152`: build the default current-projects.md body
  as `"# Current projects\n\n" + "".join(f"## {c}\n\n" for c in routing_config.contexts())`.
  The `personal` fallback in `_pick_context` stays (the guard test does not
  cover "personal"). Update the module docstring's context enumeration to
  neutral wording. Test: with contexts `["alpha"]` and no existing file, the
  created doc has `## alpha` and no legacy headings.
- `ghostbrain/semantic/regions.py`: delete the four legacy entries from
  `_BASE` (keep `"poltergeist"` — product accent, not a context); legacy
  contexts then flow through the existing hash→ramp path like any other
  context. Cosmetic color change for existing vaults, accepted. Update
  `ghostbrain/semantic/tests/test_regions.py` if it pins legacy colors.
- Neutralize remaining docstring/comment/example mentions (use `acme` /
  `your-context` / `example.com` wording): `ghostbrain/api/models/search.py:13`,
  `ghostbrain/connectors/gmail/connector.py:312`,
  `ghostbrain/connectors/joplin/__init__.py:12`,
  `ghostbrain/connectors/slack/connector.py:9`,
  `ghostbrain/metrics/inverse_search.py:23-24`,
  `ghostbrain/llm/agent.py:156` (generic wikilink example),
  `ghostbrain/worker/router.py:198-199,230` comments.
- Commit: `refactor: remaining context references derive from routing_config`

### Task 6 (guard test) — amended scope

Package-internal test suites (`ghostbrain/api/tests/`, `ghostbrain/semantic/tests/`)
legitimately use legacy names as fixtures. Amend the scan loop's skip condition to:

```python
        if f in ALLOWED or "__pycache__" in f.parts or "tests" in f.parts:
            continue
```

### Task 2 note

`bootstrap.py` on main has ~17 legacy-name mentions (a superset of the table in
Task 2 step 3d — e.g. projects-related seeds). The 3d grep loop is authoritative:
repeat until zero matches; the Task 6 guard enforces it.

### Environment note

The worktree venv is `.venv/` in the worktree root; run Python tests as
`.venv/bin/python -m pytest ...` from the worktree root. Full suite = `pytest`
default testpaths (`tests/` + `ghostbrain/api/tests/`).
