"""Caption/OCR an image attachment via the shared claude -p vision wrapper.

The chat agent is MCP-only (no vision input), so an attached image can't reach
it live. We caption the image at upload time and store the caption as the note
body; the agent grounds on that text. Same wrapper jots' photo-extraction uses.
"""
from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

from ghostbrain.api.repo import attachment_extract
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

# An image-only PDF costs one vision call per embedded image; cap it, and skip
# icons/logos too small to carry content.
MAX_PDF_IMAGES = 10
_MIN_PDF_IMAGE_PX = 64

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


def caption_pdf_images(content: bytes | Path) -> str:
    """Caption the embedded images of an image-only PDF (a scan, or a design
    exported as one picture), with a "## Page N" heading per page when there is
    more than one. "" if the PDF can't be read or nothing captions. Never raises."""
    from pypdf import PdfReader

    pages: list[tuple[int, list[str]]] = []
    try:
        reader = PdfReader(str(content) if isinstance(content, Path) else io.BytesIO(content))
        if reader.is_encrypted:
            reader.decrypt("")
        budget = MAX_PDF_IMAGES
        with tempfile.TemporaryDirectory() as tmp:
            for n, page in enumerate(reader.pages, 1):
                captions: list[str] = []
                for i, img in enumerate(page.images):
                    if budget <= 0:
                        break
                    path = _pdf_image_file(img, Path(tmp) / f"p{n}-{i}")
                    if path is None:
                        continue
                    budget -= 1
                    if caption := caption_image(path):
                        captions.append(caption)
                if captions:
                    pages.append((n, captions))
    except Exception as e:  # noqa: BLE001 — best-effort, like caption_image
        log.warning("pdf image caption failed: %s", e)
        return ""
    if len(reader.pages) == 1:
        return "\n\n".join(c for _, captions in pages for c in captions)
    return "\n\n".join(
        f"## Page {n}\n\n" + "\n\n".join(captions) for n, captions in pages
    )


def _pdf_image_file(img, stem: Path) -> Path | None:
    """Write one pypdf image to disk in a format the vision call accepts, or
    None for an image too small to matter or one that won't decode."""
    try:
        pil = img.image
        if pil is not None and min(pil.size) < _MIN_PDF_IMAGE_PX:
            return None
        ext = Path(img.name).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            path = stem.with_suffix(ext)
            path.write_bytes(img.data)
        else:  # e.g. JPEG 2000 / TIFF — re-encode
            path = stem.with_suffix(".png")
            pil.save(path, "PNG")
        return path
    except Exception as e:  # noqa: BLE001 — one bad image shouldn't sink the rest
        log.warning("skipping undecodable pdf image %s: %s", getattr(img, "name", "?"), e)
        return None


def extract_or_caption(filename: str, mime: str, content: bytes | Path) -> str:
    """attachment_extract.extract_text, except an image-only PDF falls back to
    captioning its images. Raises ExtractionError when neither yields text."""
    try:
        return attachment_extract.extract_text(filename, mime, content)
    except attachment_extract.NoTextError:
        if attachment_extract.classify(filename, mime) != "pdf":
            raise
        if caption := caption_pdf_images(content):
            return caption
        raise
