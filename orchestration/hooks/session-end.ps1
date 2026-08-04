# Claude Code SessionEnd hook for ghostbrain — PowerShell port for Windows.
#
# Wired up via %USERPROFILE%\.claude\settings.json:
#   "hooks": {
#     "SessionEnd": [{
#       "matcher": "*",
#       "hooks": [{
#         "type": "command",
#         "command": "powershell -ExecutionPolicy Bypass -File C:\\path\\to\\ghost-brain\\orchestration\\hooks\\session-end.ps1",
#         "shell": "powershell"
#       }]
#     }]
#   }
#
# Reads JSON from stdin: {session_id, transcript_path, cwd, hook_event_name, reason}
# Writes a normalized event JSON into the ghostbrain queue's pending/.

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Resolve vault path (env var override, else Windows default)
# ---------------------------------------------------------------------------
if ($env:VAULT_PATH) {
    $VaultPath = $env:VAULT_PATH
} else {
    $VaultPath = Join-Path $env:USERPROFILE "ghostbrain\vault"
}

$QueueDir      = Join-Path $VaultPath "90-meta\queue\pending"
$TranscriptsDir = Join-Path $VaultPath "90-meta\queue\transcripts"

# Create directories if they don't exist
New-Item -ItemType Directory -Force -Path $QueueDir      | Out-Null
New-Item -ItemType Directory -Force -Path $TranscriptsDir | Out-Null

# ---------------------------------------------------------------------------
# Read JSON payload from stdin
# ---------------------------------------------------------------------------
$RawPayload = [Console]::In.ReadToEnd()

try {
    $Payload = $RawPayload | ConvertFrom-Json
} catch {
    [Console]::Error.WriteLine("session-end.ps1: failed to parse stdin JSON: $_")
    exit 0
}

$SessionId      = if ($Payload.session_id)      { $Payload.session_id }      else { "" }
$TranscriptPath = if ($Payload.transcript_path) { $Payload.transcript_path } else { "" }
$Cwd            = if ($Payload.cwd)             { $Payload.cwd }             else { "" }
$Reason         = if ($Payload.reason)          { $Payload.reason }          else { "" }

# ---------------------------------------------------------------------------
# Guard: missing session_id
# ---------------------------------------------------------------------------
if (-not $SessionId) {
    [Console]::Error.WriteLine("session-end.ps1: missing session_id; skipping")
    exit 0
}

# ---------------------------------------------------------------------------
# Guard: reason == "resume" — session is being suspended, not finished
# ---------------------------------------------------------------------------
if ($Reason -eq "resume") {
    [Console]::Error.WriteLine("session-end.ps1: reason=resume, skipping")
    exit 0
}

# ---------------------------------------------------------------------------
# Timestamps (UTC)
#   Ts    — filename component: yyyyMMddTHHmmssZ
#   TsIso — event field:        yyyy-MM-ddTHH:mm:ssZ
# ---------------------------------------------------------------------------
$Now   = [System.DateTime]::UtcNow
$Ts    = $Now.ToString("yyyyMMdd'T'HHmmss'Z'")
$TsIso = $Now.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")

$EventId = "claudecode-$SessionId"

$OutFile = Join-Path $QueueDir "$Ts-claude-code-$SessionId.json"

# ---------------------------------------------------------------------------
# Copy transcript snapshot while we know the source exists.
# Claude Code prunes ~/.claude/projects aggressively — copy now so the worker
# always has it. If the copy fails (race, permissions, empty path), fall back
# to $null so the worker sees transcript_snapshot: null exactly like the bash
# version does when safe_transcript is empty.
# ---------------------------------------------------------------------------
$SafeTranscript = $null
if ($TranscriptPath -and (Test-Path -LiteralPath $TranscriptPath -PathType Leaf)) {
    $SnapshotDest = Join-Path $TranscriptsDir "$SessionId.jsonl"
    try {
        Copy-Item -LiteralPath $TranscriptPath -Destination $SnapshotDest -Force
        $SafeTranscript = $SnapshotDest
    } catch {
        $SafeTranscript = $null
    }
}

# ---------------------------------------------------------------------------
# Title: first 8 chars of session_id (safe for short IDs)
# ---------------------------------------------------------------------------
$First8 = if ($SessionId.Length -ge 8) { $SessionId.Substring(0, 8) } else { $SessionId }
$Title  = "Claude Code session $First8"

# ---------------------------------------------------------------------------
# Build the event object.
# metadata.transcriptPath prefers the snapshot, falls back to original path —
# same logic as the bash version's `preferred = safe_transcript or transcript`.
# ---------------------------------------------------------------------------
$Preferred = if ($SafeTranscript) { $SafeTranscript } else { $TranscriptPath }

$Event = [ordered]@{
    id        = $EventId
    source    = "claude-code"
    type      = "session"
    subtype   = if ($Reason) { $Reason } else { "ended" }
    timestamp = $TsIso
    title     = $Title
    rawData   = [ordered]@{
        session_id          = $SessionId
        transcript_path     = $TranscriptPath
        transcript_snapshot = $SafeTranscript   # $null when no snapshot (serialises to JSON null)
        cwd                 = $Cwd
        reason              = $Reason
    }
    metadata  = [ordered]@{
        projectPath    = $Cwd
        sessionId      = $SessionId
        transcriptPath = $Preferred
    }
}

# ---------------------------------------------------------------------------
# Serialise to JSON (depth 4 for the nested structure) and write BOM-less
# UTF-8 — Python's json.load crashes on a BOM in some configurations.
# ---------------------------------------------------------------------------
$Json = $Event | ConvertTo-Json -Depth 4

[System.IO.File]::WriteAllText(
    $OutFile,
    $Json,
    [System.Text.UTF8Encoding]::new($false)   # $false = no BOM
)

# ---------------------------------------------------------------------------
# Status line on stderr — stdout must stay silent for Claude Code hooks
# ---------------------------------------------------------------------------
$SnapshotLabel = if ($SafeTranscript) { $SafeTranscript } else { "none" }
[Console]::Error.WriteLine("session-end.ps1: queued $OutFile (snapshot=$SnapshotLabel)")

exit 0
