# macOS launchd setup (legacy)

> The desktop app is self-contained — it auto-bootstraps the vault on first
> launch and bundles the whole CLI as `ghostbrain-api <subcommand>` (no
> Python install needed). This page covers the headless/pip setup only: use
> it if you're running the worker without the desktop app, where
> `ghostbrain-api <subcommand>` is replaced by the pip-installed
> `ghostbrain-<subcommand>` scripts. The desktop app's built-in scheduler
> replaces all of this. For the full macOS install guide (including the
> meeting recorder and its permissions) see [macos.md](./macos.md).

> **Recorder under launchd:** the native capture helper needs Screen
> Recording + Microphone permission, and macOS attributes that permission to
> the process that launched it. Run `ghostbrain-capture request-permissions`
> once from the same environment (the launchd job's Python, or Terminal for a
> quick test) and check the recorder log for exit code 4/5 if recordings
> start but produce silence. The launchd job must be a LaunchAgent in the
> user's GUI session, never a root LaunchDaemon.

The plists in `orchestration/launchd/` are templates with two placeholders:
`__REPO_ROOT__` (your local clone path) and `__VAULT_PATH__` (your vault).
Substitute and install them with:

```bash
mkdir -p logs ~/Library/LaunchAgents

for f in orchestration/launchd/*.plist; do
  sed \
    -e "s|__REPO_ROOT__|$PWD|g" \
    -e "s|__VAULT_PATH__|${VAULT_PATH:-$HOME/ghostbrain/vault}|g" \
    "$f" > "$HOME/Library/LaunchAgents/$(basename $f)"
done

launchctl load ~/Library/LaunchAgents/com.ghostbrain.worker.plist
launchctl load ~/Library/LaunchAgents/com.ghostbrain.claudemd.plist
```

Stop them with `launchctl unload <path>`.
