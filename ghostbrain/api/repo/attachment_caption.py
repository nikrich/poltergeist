"""Caption/OCR an image attachment via the shared claude -p vision wrapper.

The chat agent is MCP-only (no vision input), so an attached image can't reach
it live. We caption the image at upload time and store the caption as the note
body; the agent grounds on that text. Same wrapper jots' photo-extraction uses.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ghostbrain.llm import client as llm_client

log = logging.getLogger("ghostbrain.api.repo.attachment_caption")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
IMAGE_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}

_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpeg",
    "image/jpg": ".jpeg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

CAPTION_PROMPT = (
    "Transcribe and concisely describe the readable content of this image as "
    "plain markdown — any text verbatim, plus a short description of diagrams, "
    "charts, or UI. No preamble, no commentary — just the content."
)


def is_image(filename: str, mime: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS or mime in IMAGE_MIMES


def image_ext(filename: str, mime: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return ".jpeg" if ext == ".jpg" else ext
    return _MIME_TO_EXT.get(mime, ".png")


def caption_image(abs_path: str | Path) -> str:
    """Caption text for the image, or "" if the vision call fails/returns empty.
    Never raises — the caller stores a placeholder note on empty."""
    try:
        result = llm_client.run(
            CAPTION_PROMPT, image_paths=[str(abs_path)], model="sonnet"
        )
    except Exception as e:  # noqa: BLE001 — captioning is best-effort; never block the send
        log.warning("image caption failed for %s: %s", abs_path, e)
        return ""
    return (getattr(result, "text", "") or "").strip()
