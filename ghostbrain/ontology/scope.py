"""Which vault notes belong to a project: keyword and semantic discovery, then
one bulk `binding` backlog item. Bindings are human-ratified, never inferred."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import frontmatter

from ghostbrain.paths import vault_path

SCAN_ROOTS = ("20-contexts", "00-inbox/raw")   # context copies first: they win the dedupe
BODY_SCAN_CHARS = 50_000
SEMANTIC_LIMIT = 50


@dataclass(frozen=True)
class ArtefactRef:
    aid: str
    path: str
    title: str
    band: str = "in"      # "in" (strong signal) | "unsure" (weak signal)
    mentions: int = 0


def artefact_key(path: str, meta: dict) -> str:
    for field in ("id", "doc_id"):
        value = meta.get(field)
        if value:
            return str(value)
    return Path(path).stem


def is_generated(path: str, meta: dict) -> bool:
    return meta.get("type") == "ontology" or "/ontology/" in path


def _parse(text: str) -> tuple[dict, str]:
    try:
        post = frontmatter.loads(text)
    except Exception:  # noqa: BLE001 - malformed frontmatter: treat body as text
        return {}, text
    return dict(post.metadata), post.content


def read_artefact(rel_path: str) -> tuple[dict, str] | None:
    p = vault_path() / rel_path
    if not p.is_file():
        return None
    return _parse(p.read_text(encoding="utf-8", errors="replace"))


def _title(meta: dict, body: str, path: str) -> str:
    if meta.get("title"):
        return str(meta["title"])
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return Path(path).stem


_EMBED = re.compile(r"!\[\[[^\]]*\]\]")
_WIKILINK = re.compile(r"\[\[([^\]]*)\]\]")


def strip_links(body: str) -> str:
    """Drop embeds; keep only the alias of `[[target|alias]]` and nothing of `[[target]]`."""
    body = _EMBED.sub(" ", body)
    return _WIKILINK.sub(lambda m: m.group(1).split("|", 1)[1] if "|" in m.group(1) else " ", body)


def _match_title(meta: dict, body: str, path: str) -> str:
    """The title as text to match seeds against: link targets never count."""
    return strip_links(_title(meta, body, path))


def content_matches(pattern: re.Pattern, meta: dict, body: str, path: str) -> bool:
    """A seed must appear in the note's own content: title or body text. Other
    frontmatter (related:, parent:, tags) and wikilink targets never count."""
    return bool(pattern.search(_match_title(meta, body, path))
                or pattern.search(strip_links(body[:BODY_SCAN_CHARS])))


def _rank(rel: str) -> int:
    """Lower wins the dedupe: context copies beat raw inbox copies."""
    return 0 if rel.startswith(SCAN_ROOTS[0] + "/") else 1


def _default_search(q: str, limit: int) -> list[str]:
    from ghostbrain.api.repo import search  # noqa: PLC0415
    return [hit["path"] for hit in search.search(q, limit=limit)["items"]]


def _classify(pattern: re.Pattern, meta: dict, body: str, rel: str,
              project_dir: str | None) -> tuple[str, int]:
    """Band and body-mention count. Strong signals: seed in the title or a
    heading, 3+ body mentions, or living in the project's own folder. Anything
    without a real content mention (links never count) is at most unsure."""
    if project_dir and rel.startswith(project_dir + "/"):
        return "in", len(pattern.findall(strip_links(body[:BODY_SCAN_CHARS])))
    if not content_matches(pattern, meta, body, rel):
        return "unsure", 0
    mentions = len(pattern.findall(strip_links(body[:BODY_SCAN_CHARS])))
    in_heading = any(pattern.search(strip_links(line)) for line in body.splitlines()
                     if line.lstrip().startswith("#"))
    strong = pattern.search(_match_title(meta, body, rel)) or in_heading or mentions >= 3
    return ("in" if strong else "unsure"), mentions


def _read_text(p: Path) -> str | None:
    if not p.is_file():  # directory named *.md, broken symlink
        return None
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:  # permission denied, vanished mid-scan
        return None


def _vault_relative_dir(root: Path, project_dir: str | None) -> str | None:
    """`project_dir` as a clean vault-relative posix path, or None if it is
    empty or points outside the vault."""
    if not project_dir:
        return None
    base = root.resolve()
    try:
        rel = (base / project_dir).resolve().relative_to(base)
    except ValueError:
        return None
    return rel.as_posix() if rel.parts else None


def find_artefacts(seeds: list[str], *, limit: int = 500,
                   search_fn: Callable[[str, int], list[str]] | None = None,
                   project_dir: str | None = None) -> list[ArtefactRef]:
    seeds = [s.strip() for s in seeds if s.strip()]
    if not seeds:
        return []
    pattern = re.compile(r"\b(" + "|".join(re.escape(s) for s in seeds) + r")\b", re.IGNORECASE)
    search_fn = search_fn or _default_search
    root = vault_path()
    project_dir = _vault_relative_dir(root, project_dir)
    found: dict[str, ArtefactRef] = {}

    def add(rel: str, meta: dict, body: str, *, semantic: bool) -> None:
        if is_generated(rel, meta):
            return
        band, mentions = _classify(pattern, meta, body, rel, project_dir)
        if band != "in" and not semantic and not content_matches(pattern, meta, body, rel):
            return   # keyword scan: no content mention and not in the project folder
        aid = artefact_key(rel, meta)
        current = found.get(aid)
        if current is None:
            if len(found) < limit:
                found[aid] = ArtefactRef(aid, rel, _title(meta, body, rel), band, mentions)
            return
        best_band = "in" if "in" in (band, current.band) else "unsure"
        best_mentions = max(mentions, current.mentions)
        if _rank(rel) < _rank(current.path):
            found[aid] = ArtefactRef(aid, rel, _title(meta, body, rel), best_band, best_mentions)
        else:
            found[aid] = ArtefactRef(aid, current.path, current.title, best_band, best_mentions)

    # The project's own folder first: those notes are in even without a seed
    # mention, and must not be crowded out of `limit`.
    if project_dir:
        base = root.resolve()
        for p in sorted((base / project_dir).rglob("*.md")):
            raw = _read_text(p)
            if raw is not None:
                add(p.relative_to(base).as_posix(), *_parse(raw), semantic=False)

    # Semantic hits next so the keyword scan can never crowd them out of `limit`.
    for seed in seeds:
        try:
            hits = search_fn(seed, SEMANTIC_LIMIT)
        except Exception:  # noqa: BLE001 - semantic index missing/cold: keywords still work
            hits = []
        for rel in hits:
            loaded = read_artefact(rel)
            if loaded is not None:
                add(rel, *loaded, semantic=True)

    # Keyword scan: cheap raw-text match first; frontmatter is parsed only for matches.
    for base in SCAN_ROOTS:
        for p in sorted((root / base).rglob("*.md")):
            raw = _read_text(p)
            if raw is None or not pattern.search(raw[:BODY_SCAN_CHARS]):
                continue
            add(p.relative_to(root).as_posix(), *_parse(raw), semantic=False)
    return list(found.values())


def propose_binding(store, project_uuid: str, refs: list[ArtefactRef]) -> int | None:
    known = {b["aid"] for b in store.bindings(project_uuid)}
    fresh = [r for r in refs if r.aid not in known]
    if not fresh:
        return None
    for r in fresh:
        store.upsert_binding(project_uuid, r.aid, r.path, r.title, "proposed")
    return store.add_item(project_uuid, "binding", payload={
        "artefacts": [{"aid": r.aid, "path": r.path, "title": r.title} for r in fresh]})
