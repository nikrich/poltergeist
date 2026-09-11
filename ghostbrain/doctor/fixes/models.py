"""`setup fetch-model [base.en|small.en|medium.en]` — download a whisper.cpp ggml model."""
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

import httpx

from ghostbrain.recorder.transcribe import DEFAULT_MODEL_DIR  # noqa: F401 — monkeypatched in tests

BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
MODELS: dict[str, int] = {          # approximate sizes, shown before downloading
    "base.en": 142 * 1024 * 1024,
    "small.en": 466 * 1024 * 1024,
    "medium.en": 1533 * 1024 * 1024,
}
DEFAULT_NAME = "medium.en"


class FetchError(RuntimeError):
    pass


def _content_length(resp: httpx.Response) -> int | None:
    raw = resp.headers.get("content-length")
    return int(raw) if raw and raw.isdigit() else None


def download(name: str, dest_dir: Path, *, base_url: str = BASE_URL,
             progress: Callable[[int, int], None]) -> Path:
    filename = f"ggml-{name}.bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / filename
    part = dest_dir / f".{filename}.part"
    try:
        with httpx.stream("GET", f"{base_url}/{filename}", follow_redirects=True, timeout=60.0) as resp:
            if resp.status_code != 200:
                raise FetchError(f"HTTP {resp.status_code} for {filename}")
            total = _content_length(resp) or 0
            done = 0
            with part.open("wb") as f:
                for chunk in resp.iter_bytes(1024 * 1024):
                    f.write(chunk)
                    done += len(chunk)
                    progress(done, total)
        if total and done != total:
            raise FetchError(f"download incomplete: {done} of {total} bytes")
        os.replace(part, final)
    except (httpx.HTTPError, OSError) as e:
        part.unlink(missing_ok=True)
        raise FetchError(str(e)) from e
    except FetchError:
        part.unlink(missing_ok=True)
        raise
    return final


def _print_progress(done: int, total: int) -> None:
    mb = done / (1024 * 1024)
    if total:
        print(f"\r  {mb:7.0f} MB / {total / (1024 * 1024):.0f} MB ({100 * done / total:3.0f}%)", end="", flush=True)
    else:
        print(f"\r  {mb:7.0f} MB", end="", flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = [] if argv is None else argv
    name = argv[0] if argv else DEFAULT_NAME
    if name not in MODELS:
        print(f"unknown model {name!r}; choose from {', '.join(MODELS)}", file=sys.stderr)
        return 2
    env = os.environ.get("GHOSTBRAIN_WHISPER_MODEL")
    if env:
        print(f"GHOSTBRAIN_WHISPER_MODEL is set ({env}); nothing to fetch")
        return 0
    from ghostbrain.doctor.fixes import models as _self  # resolve monkeypatched DEFAULT_MODEL_DIR  # noqa: PLW0406, I001

    dest_dir = Path(_self.DEFAULT_MODEL_DIR)
    if (dest_dir / f"ggml-{name}.bin").exists():
        print(f"ggml-{name}.bin already present in {dest_dir}")
        return 0
    print(f"downloading ggml-{name}.bin (~{MODELS[name] // (1024 * 1024)} MB) to {dest_dir}")
    try:
        out = download(name, dest_dir, progress=_print_progress)
    except FetchError as e:
        print(f"\ndownload failed: {e}", file=sys.stderr)
        return 1
    print(f"\nsaved {out}")
    return 0
