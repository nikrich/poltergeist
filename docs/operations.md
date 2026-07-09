# Operations guide

Day-2 operation of Poltergeist: digests, the profile system, LLM configuration, and install verification.

> **Note on command names.** CLI binaries and the Python package use the `ghostbrain-` prefix — Poltergeist's original codename. The commands below are correct as written.

- [Daily digest](#daily-digest)
- [Weekly digest](#weekly-digest)
- [Profile and CLAUDE.md generation](#profile-and-claudemd-generation)
- [Profile auto-update](#profile-auto-update)
- [LLM client configuration](#llm-client-configuration)
- [Verifying the install](#verifying-the-install)

## Daily digest

Once a day at 06:30 (when the scheduler or launchd timer is active), the worker generates a digest of yesterday's activity at `<vault>/10-daily/<date>.md`. Per-context digests at `<vault>/10-daily/by-context/<ctx>-<date>.md` are emitted only when a context had >= 5 events or >= 2 artifacts that day.

Run it manually:

```bash
ghostbrain-digest                     # for today
ghostbrain-digest --date 2026-05-08   # for any specific date
```

The digest reads:

- Yesterday's audit log (`90-meta/audit/<date>.jsonl`).
- Frontmatter of every routed/inbox note from yesterday.

It writes a markdown file with frontmatter + an LLM-generated body following the prompt in `<vault>/90-meta/prompts/digest.md`. Tone and structure are tunable by editing that file.

Schedule it via launchd (after templating the plist with your paths):

```bash
launchctl load ~/Library/LaunchAgents/com.ghostbrain.digest.plist
```

## Weekly digest

Where the daily digest answers "what happened yesterday", the weekly answers "what's drifting, what's recurring, who needs unblocking" — strategic patterns that don't show up in any single day.

Aggregates the past 7 days of:

- Daily digest summaries
- Transcript-derived artifacts (decisions, action items, unresolved questions, specs)
- Stale PRs/tickets and check-in suggestions
- Per-context + per-source event volumes

Renders a compact week-in-review with wikilinks (clickable in Obsidian) under `<vault>/10-daily/weekly/YYYY-Www.md`. Sections it produces (skipped silently when empty): At a glance, Decisions made, Action items still open, Risks not moving, Recurring themes, People to follow up with, Quiet this week, System health.

### Run

```bash
ghostbrain-weekly-digest [--week-end 2026-05-10]
```

By default it summarises the most recently completed week (week ending on the most recent Sunday). Pass `--week-end YYYY-MM-DD` for a specific Sunday.

### Schedule

Run weekly via launchd or cron. A reasonable default is Sunday evening so the digest is waiting for you Monday morning.

## Profile and CLAUDE.md generation

The profile lives in `<vault>/80-profile/`. Hand-write:

- `working-style.md` — how you work, decision style, communication preferences.
- `preferences.md` — tools, languages, what you don't want.
- `current-projects.md` — active work, **with H2 headings per context**. The generator filters this file to the heading matching the project's context.
- Per-context profile in `<vault>/20-contexts/<ctx>/_profile.md`.

Routing of project paths to contexts is in `routing.yaml` under `claude_code.project_paths` (longest-prefix match wins).

Regenerate per-project `CLAUDE.md`:

```bash
# One project:
ghostbrain-claude-md /path/to/your/project

# Every project under configured roots (default: ~/code, ~/development):
ghostbrain-claude-md --all
```

To schedule a nightly regen, install `com.ghostbrain.claudemd.plist` — runs daily at 02:00.

### Contexts

The four default contexts are placeholders for the typical split: **work / employer**, **personal company / consulting**, **side product**, and **personal life**. Renaming them requires editing `ghostbrain/bootstrap.py:CONTEXTS` and any references in your local profile content; full configurability is [Phase 14](../spec/SPEC.md#phase-14--open-source-packaging-final) work.

## Profile auto-update

Each Claude Code session, after extraction, calls the profile-updater LLM with the session digest + your current profile. It proposes diffs as JSON lines under `<vault>/80-profile/_proposed/<date>.jsonl`. Nothing changes the profile yet.

A weekly job (`ghostbrain-profile-apply`, scheduled Sunday 22:00) groups the past 7 days of proposals by `(field, operation, normalized after-text)`:

- **3+ corroborating proposals on `current-projects`** → auto-applied as bullets under the right context heading. Audit logs each.
- **Stable layer** (`working-style`, `preferences`) → never auto-applies. All proposals land in `<vault>/80-profile/_review.md` for you to apply by hand.
- **1-2 proposals on Current** → discarded. Coincidences shouldn't change your profile.
- **Contradictions of existing facts** → `_review.md`.

A monthly job (`ghostbrain-profile-decay`, scheduled day-1 22:00):

- Items in Current not reinforced in 60 days → archived to `_archive.md`. Hand-edited items (no audit history) are left alone.
- Items stable for 30+ days → proposed for the Stable layer in `_pending_stable.md`. You promote by hand.

To enable both:

```bash
launchctl load ~/Library/LaunchAgents/com.ghostbrain.profile-weekly.plist
launchctl load ~/Library/LaunchAgents/com.ghostbrain.profile-monthly.plist
```

Manual triggers (any time):

```bash
ghostbrain-profile-apply [--date 2026-05-08]
ghostbrain-profile-decay [--date 2026-05-08]
```

## LLM client configuration

`ghostbrain.llm.client.run()` shells out to `claude -p` so calls inherit your Claude subscription login — no API key required. To keep cost (and quota consumption) low it strips the default Claude Code system prompt with `--system-prompt` and pins a tiny auto-generated one. Models are configurable in `config.yaml`:

```yaml
llm:
  router_model: haiku       # cheap routing fallback
  extractor_model: sonnet   # extraction wants nuance
  digest_model: sonnet
```

A `--max-budget-usd` cap is set on each call as belt-and-suspenders. To use the metered Anthropic API instead of a subscription, see [SPEC §12.1](../spec/SPEC.md#121-llm-backend-and-costs).

## Verifying the install

```bash
ghostbrain-bootstrap

# Drop a synthetic event:
cat > "$VAULT_PATH/90-meta/queue/pending/manual-test.json" <<'EOF'
{
  "id": "manual-test-1",
  "source": "manual",
  "type": "note",
  "timestamp": "2026-05-07T10:00:00Z",
  "title": "Verification",
  "body": "hi"
}
EOF

# Run the worker:
ghostbrain-worker
```

In another terminal you should see the file move within ~5 seconds:

```bash
ls "$VAULT_PATH/90-meta/queue/done/"
tail -f "$VAULT_PATH/90-meta/audit/"*.jsonl
```

The audit log should contain an `event_processed` line with `status: "success"`.

Run the test suite with:

```bash
pytest
```
