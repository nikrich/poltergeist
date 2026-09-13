#!/usr/bin/env bash
# Build the native macOS capture helper (ghostbrain-capture, ScreenCaptureKit)
# and stage it where the desktop app and the sidecar expect it.
#
#   scripts/build-native-macos.sh            # -> desktop/resources/bin/ghostbrain-capture
#   scripts/build-native-macos.sh --install  # ...and ~/.local/bin/ghostbrain-capture (ad-hoc signed)
#
# Env:
#   CODESIGN_IDENTITY   identity for `codesign -s` (default "-" = ad-hoc). Note that every
#                       ad-hoc rebuild changes the code signature, which makes macOS re-ask
#                       for Screen Recording the next time the helper runs from a terminal.
#   ALLOW_NON_ARM64=1   skip the arm64 guard (the shipped desktop build is arm64-only).
set -euo pipefail

usage() { sed -n '2,12p' "$0"; exit 2; }

INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    -h|--help) usage ;;
    *) echo "unknown argument: $arg" >&2; usage ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="$ROOT/native/macos/ghostbrain-capture"
STAGE_DIR="$ROOT/desktop/resources/bin"
STAGE="$STAGE_DIR/ghostbrain-capture"
IDENTITY="${CODESIGN_IDENTITY:--}"

# --- guards -------------------------------------------------------------------
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: this script only runs on macOS" >&2; exit 1
fi
if [[ "$(uname -m)" != "arm64" && "${ALLOW_NON_ARM64:-0}" != "1" ]]; then
  echo "error: expected an arm64 host (desktop build is arm64-only); set ALLOW_NON_ARM64=1 to override" >&2; exit 1
fi
if ! command -v swift >/dev/null 2>&1; then
  echo "error: swift not found — install Xcode 16 or newer (xcode-select --install is not enough)" >&2; exit 1
fi
if command -v xcodebuild >/dev/null 2>&1; then
  XCODE_VER="$(xcodebuild -version 2>/dev/null | awk 'NR==1 {print $2}')"
  XCODE_MAJOR="${XCODE_VER%%.*}"
  if [[ -n "$XCODE_MAJOR" && "$XCODE_MAJOR" -lt 16 ]]; then
    echo "error: Xcode >= 16 required for the macOS 15 SDK (found $XCODE_VER)" >&2; exit 1
  fi
else
  # Command-line-tools-only setups: fall back to the Swift version.
  if ! swift --version 2>&1 | grep -qE 'Swift version ([6-9]|[1-9][0-9])\.'; then
    echo "error: Swift 6 or newer required" >&2; exit 1
  fi
fi

# --- build ---------------------------------------------------------------------
echo "==> swift build -c release ($PKG)"
swift build -c release --package-path "$PKG"
BIN="$PKG/.build/release/ghostbrain-capture"
[[ -x "$BIN" ]] || { echo "error: build did not produce $BIN" >&2; exit 1; }

sign() {
  # strip invalidates the linker's ad-hoc signature; always re-sign the copy.
  codesign --force --sign "$IDENTITY" --identifier tech.codeship.ghostbrain.capture --timestamp=none "$1" 2>/dev/null \
    || codesign --force --sign "$IDENTITY" --identifier tech.codeship.ghostbrain.capture "$1"
}

echo "==> staging $STAGE"
mkdir -p "$STAGE_DIR"
cp -f "$BIN" "$STAGE"
strip -x "$STAGE"
chmod 755 "$STAGE"
sign "$STAGE"

if [[ "$INSTALL" == "1" ]]; then
  DEST="$HOME/.local/bin/ghostbrain-capture"
  echo "==> installing $DEST"
  mkdir -p "$HOME/.local/bin"
  cp -f "$STAGE" "$DEST"
  chmod 755 "$DEST"
  sign "$DEST"
  if [[ "$IDENTITY" == "-" ]]; then
    echo "    (ad-hoc signed: a rebuild re-triggers the Screen Recording prompt when run from a terminal)"
  fi
fi

# --- smoke ---------------------------------------------------------------------
echo "==> smoke: ghostbrain-capture --version"
"$STAGE" --version
if [[ "$INSTALL" == "1" ]]; then
  "$HOME/.local/bin/ghostbrain-capture" --version >/dev/null
  echo "    installed to $HOME/.local/bin/ghostbrain-capture"
fi
echo "done"
