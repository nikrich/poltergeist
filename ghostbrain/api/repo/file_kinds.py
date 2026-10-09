"""File-kind classification + size caps shared by chat attachments and the docs library."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.api.repo import attachment_caption, attachment_extract

MAX_TEXT_BYTES = 1_000_000
MAX_DOC_BYTES = 20_000_000
MAX_IMAGE_BYTES = 20_000_000

# Extension → fenced-code language. Markdown extensions map to "" (inline as-is).
LANG_BY_EXT = {
    ".md": "", ".markdown": "",
    ".txt": "", ".text": "", ".log": "",
    ".py": "py", ".js": "js", ".ts": "ts", ".tsx": "tsx", ".jsx": "jsx",
    ".go": "go", ".rs": "rs", ".java": "java", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".sh": "sh", ".rb": "rb", ".sql": "sql", ".html": "html",
    ".css": "css", ".xml": "xml", ".toml": "toml", ".ini": "ini",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".csv": "", ".tsv": "",
}
TEXT_EXTENSIONS = set(LANG_BY_EXT)


def classify(filename: str, mime: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext in TEXT_EXTENSIONS or mime.startswith("text/"):
        return "text"
    if attachment_caption.is_image(filename, mime):
        return "image"
    return attachment_extract.classify(filename, mime)  # "pdf" | "docx" | "xlsx" | None


def cap_for(kind: str) -> int:
    if kind == "text":
        return MAX_TEXT_BYTES
    if kind == "image":
        return MAX_IMAGE_BYTES
    return MAX_DOC_BYTES


def text_body(filename: str, content: bytes) -> str:
    text = content.decode("utf-8")  # may raise UnicodeDecodeError (caller decides)
    ext = Path(filename).suffix.lower()
    lang = LANG_BY_EXT.get(ext, "")
    if ext in (".md", ".markdown"):
        return text
    return f"```{lang}\n{text}\n```" if lang else text
