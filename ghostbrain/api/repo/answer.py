"""Ask-the-archive: semantic retrieval + Claude synthesis.

Pipeline:
1. Run the existing semantic search to get the top-K matching notes.
2. Load each note's body, capped to keep the LLM prompt bounded.
3. Send query + sources to ``claude -p sonnet`` with a strict
   "cite [N], say so if you don't know" prompt.
4. Return ``{answer (markdown), sources}``. Citations live inside the
   markdown as ``[1]``, ``[2]`` markers — the UI turns those into
   clickable links into the source list.

No streaming yet — the wrapper around ``claude -p`` is request/response.
A typical 8-source ask runs ~5-15s on sonnet.
"""
from __future__ import annotations

import logging
from pathlib import Path

import frontmatter

from ghostbrain.api.repo.search import search as semantic_search
from ghostbrain.llm.client import LLMError, LLMTimeout, run as llm_run
from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.api.answer")

PER_NOTE_CHAR_CAP = 3000
DEFAULT_MODEL = "sonnet"
PROMPT_TEMPLATE = """You are answering a question using ONLY the user's own vault notes below.
The user is a software engineer working across four contexts: sanlam (Sanlam Digital), codeship (codeship.tech client + product), reducedrecipes, and personal projects.

Question: {question}

Sources (numbered — refer to these by [N] when citing):

{sources}

Rules:
1. Answer in markdown. Be specific and concrete — use the user's own terminology, project names, decisions verbatim.
2. Cite every concrete claim with [N], where N is the source number above. Use multiple markers like [1][3] when a claim is supported by several sources.
3. If the sources don't contain the answer, say so plainly. Do NOT invent facts. Better to say "the vault doesn't cover this yet" than to guess.
4. Use short headings and bullets. Avoid filler ("Based on the sources provided...").
5. Lead with the answer; details follow.

Answer:"""


def _load_body(rel_path: str) -> tuple[str, str]:
    """Returns (title, body-capped). Empty strings on read failure."""
    path = vault_path() / rel_path
    if not path.exists():
        return "", ""
    try:
        post = frontmatter.load(path)
    except Exception as e:  # noqa: BLE001
        log.warning("could not parse %s: %s", rel_path, e)
        return "", ""
    title = str(post.metadata.get("title") or path.stem)
    body = (post.content or "").strip()
    if len(body) > PER_NOTE_CHAR_CAP:
        body = body[:PER_NOTE_CHAR_CAP] + "\n\n[…truncated]"
    return title, body


def _build_sources_block(hits: list[dict]) -> tuple[str, list[dict]]:
    """Returns (formatted-source-text, sources-list-for-response)."""
    lines: list[str] = []
    enriched: list[dict] = []
    for idx, hit in enumerate(hits, start=1):
        title, body = _load_body(hit["path"])
        if not title and not body:
            # Skip dead links; the search index can lag deletions.
            continue
        lines.append(
            f"[{idx}] {title}  ·  {hit['path']}\n"
            f"score={hit['score']:.3f}\n"
            f"---\n"
            f"{body}\n"
        )
        enriched.append({
            **hit,
            "title": title or hit.get("title", ""),
        })
    return "\n".join(lines), enriched


def answer(q: str, limit: int = 8) -> dict:
    """Run the full RAG: search → load → synthesize."""
    search_result = semantic_search(q=q, limit=limit)
    hits = search_result.get("items") or []

    if not hits:
        return {
            "query": q,
            "answer": "_The vault doesn't have any notes that match this question yet._",
            "sources": [],
            "error": None,
        }

    sources_block, enriched = _build_sources_block(hits)
    if not enriched:
        return {
            "query": q,
            "answer": "_Search returned matches but none could be loaded — the index may be stale._",
            "sources": [],
            "error": None,
        }

    prompt = PROMPT_TEMPLATE.format(question=q.strip(), sources=sources_block)
    try:
        result = llm_run(prompt, model=DEFAULT_MODEL)
    except LLMTimeout as e:
        return {
            "query": q,
            "answer": "",
            "sources": enriched,
            "error": f"LLM timed out: {e}",
        }
    except LLMError as e:
        return {
            "query": q,
            "answer": "",
            "sources": enriched,
            "error": f"LLM error: {e}",
        }

    answer_text = (result.text or "").strip()
    if not answer_text:
        answer_text = "_The model returned an empty answer. Try a more specific query._"

    return {
        "query": q,
        "answer": answer_text,
        "sources": enriched,
        "error": None,
    }
