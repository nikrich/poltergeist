# Ghost Brain

A fully automated personal knowledge system. Captures everything Jannik does (Claude conversations, GitHub, Jira, Confluence, Slack, Gmail, Teams, Calendar) into Obsidian, processes it intelligently, and serves it back as a daily digest.

## For Claude Code

**Read [spec/SPEC.md](./spec/SPEC.md) before doing anything.**

Then start with **Phase 1** in Section 9. Each phase has explicit acceptance criteria — do not skip ahead. Commit after each phase.

## Status

Phase: **1 — Foundation complete**

## Tech Stack

- Python 3.11+ (worker, connectors, processing pipeline)
- Anthropic API (Claude Sonnet for LLM tasks; Haiku for routing)
- Obsidian (vault, dashboards, daily notes)
- Obsidian plugins: Dataview, Templater, Periodic Notes, Local REST API
- macOS launchd (orchestration)
- Filesystem queue (no external broker)

## Setup

### 1. Install the package

```bash
cd /Users/jannik/development/nikrich/ghost-brain
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # required from Phase 3 onwards
export VAULT_PATH="$HOME/ghostbrain/vault"   # default; override if you want
```

Add the `export ANTHROPIC_API_KEY=...` line to `~/.zshrc` (or wherever you keep
secrets) so launchd-spawned children inherit it. The launchd plist also accepts
inline `EnvironmentVariables` if you prefer that route.

### 3. Bootstrap the vault

```bash
ghostbrain-bootstrap
# or: python -m ghostbrain.bootstrap
```

This creates `~/ghostbrain/vault/` with the directory tree from SPEC §3.1,
plus seed files for `routing.yaml`, `config.yaml`, and the prompt stubs.
Idempotent — safe to re-run.

### 4. Install Obsidian plugins (manual)

Open the vault in Obsidian, then in **Settings → Community plugins**:

- Dataview
- Templater
- Periodic Notes
- Local REST API

(These are not installable from the CLI; they have to come from the in-app
community plugin browser.)

### 5. Run the worker

**Foreground (for development / debugging):**

```bash
ghostbrain-worker
# or: python -m ghostbrain.worker.main
```

**Under launchd (production / always-on):**

```bash
mkdir -p ~/Library/LaunchAgents logs
cp orchestration/launchd/com.jannik.ghostbrain.worker.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jannik.ghostbrain.worker.plist
```

Stop it with `launchctl unload ~/Library/LaunchAgents/com.jannik.ghostbrain.worker.plist`.

## Verifying Phase 1

```bash
# 1. Bootstrap the vault if you haven't.
ghostbrain-bootstrap

# 2. Drop a synthetic event in pending/.
cat > "$HOME/ghostbrain/vault/90-meta/queue/pending/$(date -u +%Y%m%dT%H%M%SZ)-manual-test.json" <<'EOF'
{
  "id": "manual-test-1",
  "source": "manual",
  "type": "note",
  "timestamp": "2026-05-07T10:00:00Z",
  "title": "Phase 1 verification",
  "body": "hello"
}
EOF

# 3. Start the worker in another terminal.
ghostbrain-worker

# 4. Within 10s, watch the file move:
ls "$HOME/ghostbrain/vault/90-meta/queue/done/"

# 5. Tail the audit log:
tail -f "$HOME/ghostbrain/vault/90-meta/audit/"*.jsonl
```

You should see an `event_processed` line with `status: "success"`.

## Tests

```bash
pytest
```

The Phase 1 smoke test exercises the full enqueue → claim → process → done flow.

## Repo Layout

```
ghost-brain/
├── spec/SPEC.md                       # source of truth — read first
├── pyproject.toml
├── ghostbrain/                        # Python package
│   ├── paths.py                       # vault/queue/audit/state path resolution
│   ├── bootstrap.py                   # vault tree creator (idempotent)
│   ├── connectors/
│   │   └── _base.py                   # base Connector class
│   └── worker/
│       ├── main.py                    # run loop (Phase 1 stub pipeline)
│       └── audit.py                   # JSONL audit log writer
├── orchestration/launchd/             # launchd plists (created, not loaded)
└── tests/
    └── test_worker_smoke.py
```

See `spec/SPEC.md` Section 11 for the planned full layout.

## Contributing

This is a personal project intended to be open-sourced once Phase 14 is complete. Until then, contributions go via issues and PRs to Jannik directly.

## License

MIT (planned, not yet applied).
