#!/usr/bin/env bash
# Turn the raw Playwright recording into shippable assets:
#   media/poltergeist-demo.mp4  — H.264, padded dark frame, for the website
#   media/poltergeist-demo.gif  — optimized looping GIF, for the GitHub README
#
# Usage: scripts/demo/postprocess.sh   (run after scripts/demo/record.mjs)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# here = <repo>/desktop/scripts/demo → repo root is three levels up.
media="$(cd "$here/../../.." && pwd)/media"
src="$media/poltergeist-demo.webm"
mp4="$media/poltergeist-demo.mp4"
gif="$media/poltergeist-demo.gif"
pal="$media/.raw/palette.png"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg not found — install with: brew install ffmpeg" >&2
  exit 1
fi
if [[ ! -f "$src" ]]; then
  echo "missing $src — run scripts/demo/record.mjs first" >&2
  exit 1
fi

bg="0x0E0F12"   # app background — padding blends into the page

echo "[demo] encoding MP4 → $mp4"
# Pad a 48px dark margin so the window has breathing room; clean H.264 for web.
ffmpeg -y -i "$src" \
  -vf "pad=iw+96:ih+96:48:48:color=${bg},format=yuv420p" \
  -c:v libx264 -profile:v high -crf 18 -preset slow -movflags +faststart -an \
  "$mp4"

echo "[demo] generating GIF palette"
# 2-pass palette for clean colors; 800px wide / 12fps keeps the README GIF
# small enough to inline-autoplay on GitHub.
gif_filter="fps=12,scale=800:-1:flags=lanczos"
ffmpeg -y -i "$src" \
  -vf "${gif_filter},palettegen=stats_mode=diff" "$pal"

echo "[demo] encoding GIF → $gif"
ffmpeg -y -i "$src" -i "$pal" \
  -lavfi "${gif_filter}[v];[v][1:v]paletteuse=dither=bayer:bayer_scale=3" \
  "$gif"

echo
echo "[demo] done:"
ls -lh "$mp4" "$gif" | awk '{print "  " $9 "  (" $5 ")"}'
