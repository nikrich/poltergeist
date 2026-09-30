#!/usr/bin/env bash
# Point this clone's git hooks at the versioned hooks in scripts/hooks/.
# Idempotent; run once after cloning. Undo with: git config --unset core.hooksPath
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
chmod +x scripts/hooks/*
git config core.hooksPath scripts/hooks
echo "git hooks → scripts/hooks ($(ls scripts/hooks | tr '\n' ' '))"
