#!/usr/bin/env bash
# Claude Code SessionEnd hook for ghostbrain.
#
# Wired up via ~/.claude/settings.json:
#   "hooks": {
#     "SessionEnd": [{
#       "matcher": "*",
#       "hooks": [{
#         "type": "command",
#         "command": "/path/to/ghost-brain/orchestration/hooks/session-end.sh",
#         "shell": "bash"
#       }]
#     }]
#   }
#
# Reads JSON from stdin: {session_id, transcript_path, cwd, hook_event_name, reason}
# Writes a normalized event JSON into the ghostbrain queue's pending/.

set -euo pipefail

VAULT_PATH="${VAULT_PATH:-$HOME/ghostbrain/vault}"
QUEUE_DIR="$VAULT_PATH/90-meta/queue/pending"
# Stable home for transcript snapshots. Claude Code prunes ~/.claude/projects
# aggressively, so by the time the worker processes the event the source jsonl
# is often gone. Copy it here at hook time so the worker always has it.
TRANSCRIPTS_DIR="$VAULT_PATH/90-meta/queue/transcripts"
mkdir -p "$QUEUE_DIR" "$TRANSCRIPTS_DIR"

PAYLOAD="$(cat)"

# Pull fields out of the hook payload. python3 is preferred over jq because
# it ships with macOS and is available even on a fresh laptop.
SESSION_ID=$(printf '%s' "$PAYLOAD" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("session_id",""))')
TRANSCRIPT=$(printf '%s' "$PAYLOAD" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("transcript_path",""))')
CWD=$(printf '%s' "$PAYLOAD" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("cwd",""))')
REASON=$(printf '%s' "$PAYLOAD" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("reason",""))')

if [[ -z "$SESSION_ID" ]]; then
    echo "session-end.sh: missing session_id; skipping" >&2
    exit 0
fi

# Reasons we DON'T want to ingest:
#   resume — session is just being suspended, not finished.
case "$REASON" in
    resume) echo "session-end.sh: reason=resume, skipping" >&2; exit 0 ;;
esac

TS="$(date -u +%Y%m%dT%H%M%SZ)"
EVENT_ID="claudecode-${SESSION_ID}"
TS_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
OUT="$QUEUE_DIR/${TS}-claude-code-${SESSION_ID}.json"

# Copy the transcript snapshot now while we know it exists. If it's gone
# already (race with Claude's cleanup, or a stub session), don't fail — the
# worker will fall back to a metadata-only note exactly like it does today.
SAFE_TRANSCRIPT=""
if [[ -n "$TRANSCRIPT" && -f "$TRANSCRIPT" ]]; then
    SAFE_TRANSCRIPT="$TRANSCRIPTS_DIR/${SESSION_ID}.jsonl"
    cp -f "$TRANSCRIPT" "$SAFE_TRANSCRIPT" 2>/dev/null || SAFE_TRANSCRIPT=""
fi

/usr/bin/python3 - "$OUT" "$EVENT_ID" "$SESSION_ID" "$TRANSCRIPT" "$SAFE_TRANSCRIPT" "$CWD" "$REASON" "$TS_ISO" <<'PY'
import json
import sys
out, event_id, session_id, transcript, safe_transcript, cwd, reason, ts_iso = sys.argv[1:]
# Worker prefers the snapshot under metadata.transcriptPath. Keeping the
# original under rawData.transcript_path so we can audit which sessions
# survived the copy.
preferred = safe_transcript or transcript
event = {
    "id": event_id,
    "source": "claude-code",
    "type": "session",
    "subtype": reason or "ended",
    "timestamp": ts_iso,
    "title": f"Claude Code session {session_id[:8]}",
    "rawData": {
        "session_id": session_id,
        "transcript_path": transcript,
        "transcript_snapshot": safe_transcript or None,
        "cwd": cwd,
        "reason": reason,
    },
    "metadata": {
        "projectPath": cwd,
        "sessionId": session_id,
        "transcriptPath": preferred,
    },
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(event, f, indent=2)
PY

echo "session-end.sh: queued $OUT (snapshot=${SAFE_TRANSCRIPT:-none})" >&2
exit 0
