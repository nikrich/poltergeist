#!/usr/bin/env bash
#
# Unload + remove the ghostbrain launchd plists from ~/Library/LaunchAgents.
# Run this when you're cutting over to the in-app scheduler — until then the
# launchd jobs are what keep your vault current, so don't run it lightly.
#
# Symmetric with the original install step (orchestration/launchd/install.sh
# if present). This script does NOT delete the templates in
# orchestration/launchd/ — only the installed copies in LaunchAgents.
#
# Usage:
#   scripts/disable-launchd.sh            # interactive, asks before each plist
#   scripts/disable-launchd.sh --yes      # non-interactive

set -euo pipefail

AGENT_DIR="$HOME/Library/LaunchAgents"
PREFIX="com.ghostbrain."

shopt -s nullglob
plists=("$AGENT_DIR"/${PREFIX}*.plist)
shopt -u nullglob

if [[ ${#plists[@]} -eq 0 ]]; then
  echo "No ghostbrain LaunchAgents found in $AGENT_DIR."
  exit 0
fi

assume_yes=false
if [[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]]; then
  assume_yes=true
fi

echo "Found ${#plists[@]} ghostbrain LaunchAgent(s):"
for p in "${plists[@]}"; do
  echo "  - $(basename "$p")"
done
echo

if ! $assume_yes; then
  read -r -p "Unload and delete these? [y/N] " reply
  if [[ ! "$reply" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
  fi
fi

for p in "${plists[@]}"; do
  label=$(basename "$p" .plist)
  echo "→ unloading $label"
  launchctl unload "$p" 2>/dev/null || echo "  (already unloaded)"
  rm -f "$p"
  echo "  removed."
done

echo
echo "Done. Switch on 'Run scheduler in-app' in GhostBrain → Settings → Background."
echo "If anything looks wrong, the templates in orchestration/launchd/ can"
echo "reinstall the plists."
