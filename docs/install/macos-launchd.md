# macOS launchd setup (legacy)

> Use this only if you're running the worker without the desktop app. The
> desktop app's built-in scheduler replaces all of this.

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
