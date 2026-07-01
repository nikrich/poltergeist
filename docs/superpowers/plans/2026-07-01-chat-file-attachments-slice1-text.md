# Chat File Attachments — Slice 1 (text/markdown/code) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user drag-drop, paste, or browse **text/markdown/code** files into the chat composer; each file is written to the vault as an indexed note, and the current chat turn is grounded on those notes by reference.

**Architecture:** Renderer uploads each file (base64) to a new `POST /v1/chat/{conv}/attachments` endpoint via the existing `window.gb.api.request` bridge; the endpoint writes a markdown note under `20-contexts/chat-attachments/` and returns its vault-relative path. The renderer then calls `chat.send(convId, text, attachmentPaths)`; the sidecar persists the paths on the user message and augments the agent prompt with wikilinks plus a "read these first" instruction. The agent reads each via `poltergeist_get_note` (pure reference — content is never inlined). The existing periodic `semantic refresh` (which scans `20-contexts`) makes the notes searchable on its next cycle — no new indexing code.

**Tech Stack:** Python 3 / FastAPI / pydantic / pyyaml / pytest (sidecar); TypeScript / React / Electron / Zustand / Vitest + React Testing Library (desktop).

## Global Constraints

- Attachment notes live under `20-contexts/chat-attachments/` — MUST be under `20-contexts/` because `ghostbrain/semantic/refresh.py:63` (`contexts_root = vault_path() / "20-contexts"`) and search only walk that tree.
- In-turn grounding is **reference-by-path only**: augment the prompt with `[[vault-relative-path]]` wikilinks; never inline file content into the prompt.
- Slice 1 accepts **text-like files only** (see `TEXT_EXTENSIONS` / `text/` MIME in Task 1). Non-text files are rejected with HTTP 415. PDFs and images are later slices.
- Per-file size cap: **1_000_000 bytes**. Over cap → HTTP 413.
- Per-message file cap: **10** files (enforced in the endpoint and the composer).
- Filenames follow the connector convention `YYYYMMDDTHHMMSS-<slug>.md`.
- Frontmatter uses `yaml.safe_dump(front, sort_keys=False, allow_unicode=True)` then `---\n{yaml}\n---\n\n{body}\n`, mirroring `ghostbrain/worker/note_generator.py:131-132`.
- Vault path root is `ghostbrain.paths.vault_path()`. Tests point it at a temp dir via the `tmp_vault` fixture (sets `VAULT_PATH`).
- Run sidecar tests with `pytest`; desktop tests with `npm test` (Vitest) from `desktop/`.

---

### Task 1: `chat_attachments` repo — write a text attachment note to the vault

**Files:**
- Create: `ghostbrain/api/repo/chat_attachments.py`
- Test: `ghostbrain/api/tests/test_chat_attachments.py`

**Interfaces:**
- Consumes: `ghostbrain.paths.vault_path`.
- Produces:
  - `save_attachment(conv_id: str, filename: str, mime: str, content: bytes) -> dict` returning `{"path": str, "title": str, "kind": str}` where `path` is vault-relative (e.g. `20-contexts/chat-attachments/20260701T120000-notes.md`) and `kind == "text"`.
  - Exceptions `UnsupportedAttachment(RuntimeError)`, `AttachmentTooLarge(RuntimeError)`.
  - Constants `ATTACHMENTS_DIR_REL = "20-contexts/chat-attachments"`, `MAX_TEXT_BYTES = 1_000_000`, `TEXT_EXTENSIONS: set[str]`.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_chat_attachments.py`:

```python
from pathlib import Path

import pytest

from ghostbrain.api.repo import chat_attachments as repo


def test_saves_text_note_under_contexts(tmp_vault: Path):
    result = repo.save_attachment(
        "conv1", "notes.txt", "text/plain", b"hello world"
    )
    assert result["kind"] == "text"
    assert result["title"] == "notes.txt"
    assert result["path"].startswith("20-contexts/chat-attachments/")
    note = tmp_vault / result["path"]
    assert note.exists()
    text = note.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "source: chat-attachment" in text
    assert "conversation_id: conv1" in text
    assert "hello world" in text


def test_markdown_body_inlined_verbatim(tmp_vault: Path):
    result = repo.save_attachment("c", "a.md", "text/markdown", b"# Title\n\nBody")
    body = (tmp_vault / result["path"]).read_text(encoding="utf-8")
    assert "# Title\n\nBody" in body
    assert "```" not in body  # markdown is not fenced


def test_code_body_is_fenced_by_extension(tmp_vault: Path):
    result = repo.save_attachment("c", "s.py", "text/x-python", b"print(1)")
    body = (tmp_vault / result["path"]).read_text(encoding="utf-8")
    assert "```py\nprint(1)\n```" in body


def test_rejects_unsupported_type(tmp_vault: Path):
    with pytest.raises(repo.UnsupportedAttachment):
        repo.save_attachment("c", "x.png", "image/png", b"\x89PNG")


def test_rejects_oversize(tmp_vault: Path):
    big = b"a" * (repo.MAX_TEXT_BYTES + 1)
    with pytest.raises(repo.AttachmentTooLarge):
        repo.save_attachment("c", "big.txt", "text/plain", big)


def test_identical_content_reuses_note(tmp_vault: Path):
    a = repo.save_attachment("c", "d.txt", "text/plain", b"same")
    b = repo.save_attachment("c", "d.txt", "text/plain", b"same")
    assert a["path"] == b["path"]
    notes = list((tmp_vault / "20-contexts" / "chat-attachments").glob("*.md"))
    assert len(notes) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest ghostbrain/api/tests/test_chat_attachments.py -v`
Expected: FAIL — `ModuleNotFoundError: ghostbrain.api.repo.chat_attachments`.

- [ ] **Step 3: Write the implementation**

Create `ghostbrain/api/repo/chat_attachments.py`:

```python
"""Persist chat-attached files as indexed vault notes.

Attachments land under ``20-contexts/chat-attachments/`` (must be under
20-contexts so ``semantic/refresh.py`` and search pick them up). The current
chat turn references them by path; the periodic semantic refresh embeds them
later. Slice 1 handles text/markdown/code only.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ghostbrain.paths import vault_path

ATTACHMENTS_DIR_REL = "20-contexts/chat-attachments"
MAX_TEXT_BYTES = 1_000_000

# Extension → fenced-code language. Markdown extensions map to "" (inline as-is).
_LANG_BY_EXT = {
    ".md": "", ".markdown": "",
    ".txt": "", ".text": "", ".log": "",
    ".py": "py", ".js": "js", ".ts": "ts", ".tsx": "tsx", ".jsx": "jsx",
    ".go": "go", ".rs": "rs", ".java": "java", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".sh": "sh", ".rb": "rb", ".sql": "sql", ".html": "html",
    ".css": "css", ".xml": "xml", ".toml": "toml", ".ini": "ini",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".csv": "", ".tsv": "",
}
TEXT_EXTENSIONS = set(_LANG_BY_EXT)


class UnsupportedAttachment(RuntimeError):
    """File type not accepted in this slice (→ HTTP 415)."""


class AttachmentTooLarge(RuntimeError):
    """File exceeds the per-file byte cap (→ HTTP 413)."""


def _slug(name: str) -> str:
    stem = Path(name).stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return slug or "attachment"


def _is_text(filename: str, mime: str) -> bool:
    return Path(filename).suffix.lower() in TEXT_EXTENSIONS or mime.startswith("text/")


def _render(front: dict, body: str) -> str:
    yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{yaml_block}\n---\n\n{body.rstrip()}\n"


def save_attachment(conv_id: str, filename: str, mime: str, content: bytes) -> dict:
    if not _is_text(filename, mime):
        raise UnsupportedAttachment(f"unsupported attachment type: {filename} ({mime})")
    if len(content) > MAX_TEXT_BYTES:
        raise AttachmentTooLarge(f"{filename} exceeds {MAX_TEXT_BYTES} bytes")

    text = content.decode("utf-8", errors="replace")
    note_id = hashlib.sha256(content).hexdigest()[:12]

    target_dir = vault_path() / ATTACHMENTS_DIR_REL
    target_dir.mkdir(parents=True, exist_ok=True)

    # Content-addressed reuse: a note whose frontmatter id matches is identical.
    for existing in sorted(target_dir.glob("*.md")):
        if _frontmatter_id(existing) == note_id:
            return _result(existing, filename)

    ext = Path(filename).suffix.lower()
    lang = _LANG_BY_EXT.get(ext, "")
    body = text if lang == "" and ext in (".md", ".markdown") else (
        f"```{lang}\n{text}\n```" if lang else text
    )

    front = {
        "id": note_id,
        "source": "chat-attachment",
        "title": filename,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "conversation_id": conv_id,
        "original_filename": filename,
        "kind": "text",
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    note_path = target_dir / f"{stamp}-{_slug(filename)}.md"
    note_path.write_text(_render(front, body), encoding="utf-8")
    return _result(note_path, filename)


def _result(note_path: Path, filename: str) -> dict:
    rel = note_path.resolve().relative_to(vault_path().resolve())
    return {"path": str(rel), "title": filename, "kind": "text"}


def _frontmatter_id(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return fm.get("id") if isinstance(fm, dict) else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest ghostbrain/api/tests/test_chat_attachments.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/chat_attachments.py ghostbrain/api/tests/test_chat_attachments.py
git commit -m "feat(chat): write text chat-attachments as indexed vault notes"
```

---

### Task 2: Attachments upload endpoint

**Files:**
- Modify: `ghostbrain/api/models/chat.py` (add upload models)
- Modify: `ghostbrain/api/routes/chat.py` (add `POST /{conv_id}/attachments`)
- Test: `ghostbrain/api/tests/test_chat_attachments.py` (append endpoint tests)

**Interfaces:**
- Consumes: `chat_attachments.save_attachment` + its exceptions (Task 1); `chat_store.get` (existing).
- Produces: `POST /v1/chat/{conv_id}/attachments` accepting `{"files": [{"name": str, "mime": str, "content_b64": str}]}`, returning `{"attachments": [{"path": str, "title": str, "kind": str}]}`. 404 unknown conv, 415 unsupported, 413 oversize, 400 too many files.

- [ ] **Step 1: Write the failing tests**

Append to `ghostbrain/api/tests/test_chat_attachments.py`:

```python
import base64


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_upload_endpoint_writes_and_returns_paths(client, auth_headers):
    conv = client.post("/v1/chat", headers=auth_headers).json()
    res = client.post(
        f"/v1/chat/{conv['id']}/attachments",
        json={"files": [{"name": "n.txt", "mime": "text/plain",
                         "content_b64": _b64(b"hello")}]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    atts = res.json()["attachments"]
    assert len(atts) == 1
    assert atts[0]["path"].startswith("20-contexts/chat-attachments/")


def test_upload_unknown_conversation_404(client, auth_headers):
    res = client.post(
        "/v1/chat/nope/attachments",
        json={"files": [{"name": "n.txt", "mime": "text/plain",
                         "content_b64": _b64(b"x")}]},
        headers=auth_headers,
    )
    assert res.status_code == 404


def test_upload_unsupported_type_415(client, auth_headers):
    conv = client.post("/v1/chat", headers=auth_headers).json()
    res = client.post(
        f"/v1/chat/{conv['id']}/attachments",
        json={"files": [{"name": "x.png", "mime": "image/png",
                         "content_b64": _b64(b"\x89PNG")}]},
        headers=auth_headers,
    )
    assert res.status_code == 415


def test_upload_too_many_files_400(client, auth_headers):
    conv = client.post("/v1/chat", headers=auth_headers).json()
    files = [{"name": f"f{i}.txt", "mime": "text/plain",
              "content_b64": _b64(b"x")} for i in range(11)]
    res = client.post(
        f"/v1/chat/{conv['id']}/attachments",
        json={"files": files}, headers=auth_headers,
    )
    assert res.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest ghostbrain/api/tests/test_chat_attachments.py -v -k upload`
Expected: FAIL — 404/405 (route missing).

- [ ] **Step 3: Add the models**

In `ghostbrain/api/models/chat.py`, add near the other request models:

```python
class AttachmentFile(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    mime: str = Field("", max_length=255)
    content_b64: str = Field(..., min_length=1)


class AttachmentUploadRequest(BaseModel):
    files: list[AttachmentFile] = Field(..., min_length=1)


class Attachment(BaseModel):
    path: str
    title: str
    kind: str


class AttachmentUploadResponse(BaseModel):
    attachments: list[Attachment]
```

- [ ] **Step 4: Add the route**

In `ghostbrain/api/routes/chat.py`, extend the imports:

```python
from ghostbrain.api.models.chat import (
    AttachmentUploadRequest,
    AttachmentUploadResponse,
    ChatMessageRequest,
    Conversation,
    ConversationSummary,
    RenameRequest,
)
from ghostbrain.api.repo import chat_attachments
```

Add, above `send_message`:

```python
MAX_ATTACHMENTS_PER_MESSAGE = 10


@router.post("/{conv_id}/attachments", response_model=AttachmentUploadResponse)
def upload_attachments(conv_id: str, payload: AttachmentUploadRequest) -> dict:
    import base64
    import binascii

    if chat_store.get(conv_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    if len(payload.files) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise HTTPException(
            status_code=400,
            detail=f"at most {MAX_ATTACHMENTS_PER_MESSAGE} files per message",
        )
    out: list[dict] = []
    for f in payload.files:
        try:
            content = base64.b64decode(f.content_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail=f"invalid base64: {f.name}")
        try:
            out.append(chat_attachments.save_attachment(conv_id, f.name, f.mime, content))
        except chat_attachments.UnsupportedAttachment as e:
            raise HTTPException(status_code=415, detail=str(e))
        except chat_attachments.AttachmentTooLarge as e:
            raise HTTPException(status_code=413, detail=str(e))
    return {"attachments": out}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest ghostbrain/api/tests/test_chat_attachments.py -v`
Expected: PASS (all, including the 4 new upload tests).

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/models/chat.py ghostbrain/api/routes/chat.py ghostbrain/api/tests/test_chat_attachments.py
git commit -m "feat(chat): add POST /v1/chat/{id}/attachments upload endpoint"
```

---

### Task 3: Persist attachments on the user message

**Files:**
- Modify: `ghostbrain/api/models/chat.py` (`ChatMessage.attachments`, `ChatMessageRequest.attachment_paths`)
- Modify: `ghostbrain/api/repo/chat_store.py` (`append_user_message` accepts attachments)
- Test: `ghostbrain/api/tests/test_chat_store.py` (or `test_chat_repo.py`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `chat_store.append_user_message(conv, text, attachments=None)` — when `attachments` is a non-empty list of `{"path","title","kind"}` dicts, it is stored on the message as `attachments`. `ChatMessage` model gains `attachments: list[Attachment] = []`. `ChatMessageRequest` gains `attachment_paths: list[str] = []`.

- [ ] **Step 1: Write the failing test**

Append to `ghostbrain/api/tests/test_chat_store.py`:

```python
def test_append_user_message_stores_attachments(tmp_chats_dir):
    from ghostbrain.api.repo import chat_store

    conv = chat_store.create()
    atts = [{"path": "20-contexts/chat-attachments/a.md", "title": "a.md", "kind": "text"}]
    chat_store.append_user_message(conv, "see attached", attachments=atts)
    reloaded = chat_store.get(conv["id"])
    msg = reloaded["messages"][-1]
    assert msg["attachments"] == atts


def test_append_user_message_omits_empty_attachments(tmp_chats_dir):
    from ghostbrain.api.repo import chat_store

    conv = chat_store.create()
    chat_store.append_user_message(conv, "plain")
    assert "attachments" not in chat_store.get(conv["id"])["messages"][-1]
```

Note: `test_chat_store.py` already uses the `tmp_chats_dir` fixture (conftest line 81). Match its existing import style if it imports `chat_store` at module top.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest ghostbrain/api/tests/test_chat_store.py -v -k attachments`
Expected: FAIL — `append_user_message()` got an unexpected keyword argument `attachments`.

- [ ] **Step 3: Update the store + models**

In `ghostbrain/api/repo/chat_store.py`, replace `append_user_message`:

```python
def append_user_message(
    conv: dict, text: str, *, attachments: list[dict] | None = None
) -> dict:
    msg: dict = {"role": "user", "text": text}
    if attachments:
        msg["attachments"] = attachments
    conv["messages"].append(msg)
    if len(conv["messages"]) == 1:
        conv["title"] = derive_title(text)
    conv["updated_at"] = time.time()
    _write(conv)
    return conv
```

In `ghostbrain/api/models/chat.py`, add `attachments` to `ChatMessage` and `attachment_paths` to `ChatMessageRequest` (the `Attachment` model was added in Task 2):

```python
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    tools: list[ChatToolUse] = []
    interrupted: bool = False
    attachments: list[Attachment] = []
```

```python
class ChatMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    attachment_paths: list[str] = Field(default_factory=list, max_length=10)
```

Move the `Attachment` class definition above `ChatMessage` so it is defined before use (place the Task-2 attachment models block directly under `ChatToolUse`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest ghostbrain/api/tests/test_chat_store.py -v -k attachments`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/chat_store.py ghostbrain/api/models/chat.py ghostbrain/api/tests/test_chat_store.py
git commit -m "feat(chat): persist attachment refs on the user message"
```

---

### Task 4: Prompt augmentation — reference attachments by path

**Files:**
- Modify: `ghostbrain/api/repo/chat.py` (`send_message` signature + augmentation)
- Modify: `ghostbrain/api/routes/chat.py` (pass `attachment_paths` through)
- Test: `ghostbrain/api/tests/test_chat_repo.py`

**Interfaces:**
- Consumes: `chat_store.append_user_message(..., attachments=...)` (Task 3).
- Produces: `repo_chat.send_message(conv_id, text, attachment_paths=None)` — persists the user message with attachment refs (title derived from the path stem) and augments the agent prompt. `build_attachment_prompt(text, paths) -> str` (new, exported for unit test).

- [ ] **Step 1: Write the failing test**

Append to `ghostbrain/api/tests/test_chat_repo.py`:

```python
def test_build_attachment_prompt_references_paths():
    from ghostbrain.api.repo.chat import build_attachment_prompt

    prompt = build_attachment_prompt(
        "summarize these",
        ["20-contexts/chat-attachments/a.md", "20-contexts/chat-attachments/b.md"],
    )
    assert "[[20-contexts/chat-attachments/a.md]]" in prompt
    assert "[[20-contexts/chat-attachments/b.md]]" in prompt
    assert "poltergeist_get_note" in prompt
    assert prompt.endswith("summarize these")


def test_build_attachment_prompt_no_paths_returns_text_unchanged():
    from ghostbrain.api.repo.chat import build_attachment_prompt

    assert build_attachment_prompt("hi", []) == "hi"
    assert build_attachment_prompt("hi", None) == "hi"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest ghostbrain/api/tests/test_chat_repo.py -v -k attachment_prompt`
Expected: FAIL — `ImportError: cannot import name 'build_attachment_prompt'`.

- [ ] **Step 3: Implement augmentation**

In `ghostbrain/api/repo/chat.py`, add:

```python
def build_attachment_prompt(text: str, paths: list[str] | None) -> str:
    """Prepend attachment wikilinks + a read-first instruction to the turn.

    Reference-by-path only: the agent fetches each note via
    poltergeist_get_note. Content is never inlined here.
    """
    if not paths:
        return text
    links = "\n".join(f"- [[{p}]]" for p in paths)
    return (
        "The user attached the following notes to this message. Read each with "
        "poltergeist_get_note before answering:\n"
        f"{links}\n\n{text}"
    )
```

Change `send_message` to accept and thread the paths:

```python
def send_message(
    conv_id: str, text: str, attachment_paths: list[str] | None = None
) -> Iterator[dict]:
```

Inside, replace the `append_user_message` call so attachments are persisted, and augment the prompt used for the turn:

```python
        conv = chat_store.get(conv_id)
        if conv is None:
            yield {"type": "error", "message": "conversation not found"}
            return
        attachments = [
            {"path": p, "title": p.rsplit("/", 1)[-1], "kind": "text"}
            for p in (attachment_paths or [])
        ]
        chat_store.append_user_message(conv, text, attachments=attachments or None)
        prompt = build_attachment_prompt(text, attachment_paths)
        session_id = conv.get("claude_session_id")
        try:
            yield from _stream_turn(conv, prompt, session_id)
        except agent.ResumeFailed as e:
            log.warning(
                "resume failed for %s (%s); retrying without session", conv_id, e
            )
            yield from _stream_turn(conv, _with_history(conv, prompt), None)
```

(Note: `_stream_turn`'s second positional arg is already named `prompt`; we now pass the augmented prompt. `_with_history` wraps whatever prompt it's given, so attachment refs survive a session reset.)

In `ghostbrain/api/routes/chat.py`, thread the paths from the request:

```python
    def gen():
        for event in repo_chat.send_message(
            conv_id, payload.text, payload.attachment_paths
        ):
            yield f"data: {json.dumps(event)}\n\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest ghostbrain/api/tests/test_chat_repo.py -v`
Expected: PASS (new tests + existing ones unaffected).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/chat.py ghostbrain/api/routes/chat.py ghostbrain/api/tests/test_chat_repo.py
git commit -m "feat(chat): reference attached notes by path in the turn prompt"
```

---

### Task 5: IPC plumbing — carry attachment paths through send

**Files:**
- Modify: `desktop/src/shared/types.ts` (`chat.send` signature)
- Modify: `desktop/src/preload/index.ts` (`chat.send` forward)
- Modify: `desktop/src/main/index.ts:295-319` (`gb:chat:send` handler)
- Modify: `desktop/src/main/chat-stream.ts` (`startChatStream` body)
- Test: `desktop/src/main/__tests__/chat-stream.test.ts`

**Interfaces:**
- Consumes: sidecar `POST /v1/chat/{conv}/messages` now accepts `attachment_paths` (Task 4).
- Produces: `window.gb.chat.send(convId, text, attachmentPaths?)`; `startChatStream(sidecar, convId, text, send, attachmentPaths?)` posts `{ text, attachment_paths }`; `buildMessageBody(text, attachmentPaths) -> string` (new, exported for unit test).

- [ ] **Step 1: Write the failing test**

Append to `desktop/src/main/__tests__/chat-stream.test.ts`:

```typescript
import { buildMessageBody } from '../chat-stream';

describe('buildMessageBody', () => {
  it('includes attachment_paths when provided', () => {
    expect(JSON.parse(buildMessageBody('hi', ['a.md', 'b.md']))).toEqual({
      text: 'hi',
      attachment_paths: ['a.md', 'b.md'],
    });
  });

  it('sends an empty array when no attachments', () => {
    expect(JSON.parse(buildMessageBody('hi', undefined))).toEqual({
      text: 'hi',
      attachment_paths: [],
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `desktop/`): `npm test -- chat-stream`
Expected: FAIL — `buildMessageBody` is not exported.

- [ ] **Step 3: Update `chat-stream.ts`**

In `desktop/src/main/chat-stream.ts`, add the helper and use it. Replace the `startChatStream` signature and body construction:

```typescript
export function buildMessageBody(
  text: string,
  attachmentPaths?: string[],
): string {
  return JSON.stringify({ text, attachment_paths: attachmentPaths ?? [] });
}

export async function startChatStream(
  sidecar: Sidecar,
  convId: string,
  text: string,
  send: (event: ChatStreamEvent) => void,
  attachmentPaths?: string[],
): Promise<{ ok: true } | { ok: false; error: string }> {
```

and change the `fetch` `body:` line from `body: JSON.stringify({ text }),` to:

```typescript
        body: buildMessageBody(text, attachmentPaths),
```

- [ ] **Step 4: Update the shared type, preload, and main handler**

In `desktop/src/shared/types.ts`, change the `chat.send` signature:

```typescript
  chat: {
    send(
      convId: string,
      text: string,
      attachmentPaths?: string[],
    ): Promise<{ ok: true } | { ok: false; error: string }>;
    stop(convId: string): Promise<{ ok: true } | { ok: false; error: string }>;
  };
```

In `desktop/src/preload/index.ts`, change the `chat.send` line:

```typescript
    send: (convId, text, attachmentPaths) =>
      ipcRenderer.invoke('gb:chat:send', convId, text, attachmentPaths),
```

In `desktop/src/main/index.ts`, update the `gb:chat:send` handler (line 295) to read and forward the paths:

```typescript
ipcMain.handle(
  'gb:chat:send',
  async (e, convId: unknown, text: unknown, attachmentPaths: unknown) => {
    if (typeof convId !== 'string' || typeof text !== 'string') {
      return { ok: false, error: 'Invalid request shape' };
    }
    const paths = Array.isArray(attachmentPaths)
      ? attachmentPaths.filter((p): p is string => typeof p === 'string')
      : [];
    const wc = e.sender;
    const send = (event: ChatStreamEvent) => {
      if (!wc.isDestroyed()) wc.send('gb:chat:event', { convId, event });
    };
    if (DEMO) {
      const onDestroyed = () => stopDemoChat(convId);
      wc.once('destroyed', onDestroyed);
      try {
        return await runDemoChatStream(convId, text, send);
      } finally {
        wc.removeListener('destroyed', onDestroyed);
      }
    }
    const onDestroyed = () => stopTurn(convId);
    wc.once('destroyed', onDestroyed);
    try {
      return await startChatStream(sidecar, convId, text, send, paths);
    } finally {
      wc.removeListener('destroyed', onDestroyed);
    }
  },
);
```

- [ ] **Step 5: Run tests + typecheck**

Run (from `desktop/`): `npm test -- chat-stream` then `npm run typecheck` (or `npx tsc --noEmit` if that's the project's check).
Expected: chat-stream tests PASS; typecheck clean.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/shared/types.ts desktop/src/preload/index.ts desktop/src/main/index.ts desktop/src/main/chat-stream.ts desktop/src/main/__tests__/chat-stream.test.ts
git commit -m "feat(chat): thread attachment paths through the send IPC path"
```

---

### Task 6: Renderer types + upload helper

**Files:**
- Modify: `desktop/src/shared/api-types.ts` (`ChatAttachment` + `ChatMessage.attachments`)
- Create: `desktop/src/renderer/lib/chat-attachments.ts`
- Test: `desktop/src/renderer/__tests__/chat-attachments.test.ts`

**Interfaces:**
- Consumes: `post` from `../lib/api/client`; the `POST /v1/chat/{id}/attachments` endpoint (Task 2).
- Produces:
  - `ChatAttachment { path: string; title: string; kind: string }` in `api-types.ts`; `ChatMessage.attachments?: ChatAttachment[]`.
  - `fileToBase64(file: File): Promise<string>`.
  - `uploadAttachments(convId: string, files: File[]): Promise<ChatAttachment[]>` — POSTs `{files:[{name,mime,content_b64}]}`, returns `attachments`.
  - `ACCEPTED_EXTENSIONS: string[]`, `MAX_FILE_BYTES = 1_000_000`, `MAX_FILES = 10`, `isAccepted(file: File): boolean`.

- [ ] **Step 1: Write the failing test**

Create `desktop/src/renderer/__tests__/chat-attachments.test.ts`:

```typescript
import { describe, expect, it, vi, beforeEach } from 'vitest';

import * as client from '../lib/api/client';
import { isAccepted, uploadAttachments } from '../lib/chat-attachments';

describe('isAccepted', () => {
  it('accepts .md and .txt', () => {
    expect(isAccepted(new File(['x'], 'a.md', { type: 'text/markdown' }))).toBe(true);
    expect(isAccepted(new File(['x'], 'a.txt', { type: 'text/plain' }))).toBe(true);
  });
  it('rejects .png', () => {
    expect(isAccepted(new File(['x'], 'a.png', { type: 'image/png' }))).toBe(false);
  });
});

describe('uploadAttachments', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('posts files as base64 and returns attachments', async () => {
    const spy = vi.spyOn(client, 'post').mockResolvedValue({
      attachments: [{ path: '20-contexts/chat-attachments/a.md', title: 'a.md', kind: 'text' }],
    });
    const out = await uploadAttachments('conv1', [
      new File(['hello'], 'a.md', { type: 'text/markdown' }),
    ]);
    expect(out).toHaveLength(1);
    expect(spy).toHaveBeenCalledWith('/v1/chat/conv1/attachments', {
      files: [{ name: 'a.md', mime: 'text/markdown', content_b64: expect.any(String) }],
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `desktop/`): `npm test -- chat-attachments`
Expected: FAIL — module `../lib/chat-attachments` not found.

- [ ] **Step 3: Add the shared type**

In `desktop/src/shared/api-types.ts`, add above `ChatMessage` and extend it:

```typescript
export interface ChatAttachment {
  path: string;
  title: string;
  kind: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  tools?: ChatToolUse[];
  interrupted?: boolean;
  attachments?: ChatAttachment[];
}
```

- [ ] **Step 4: Implement the helper**

Create `desktop/src/renderer/lib/chat-attachments.ts`:

```typescript
import { post } from './api/client';
import type { ChatAttachment } from '../../shared/api-types';

export const MAX_FILE_BYTES = 1_000_000;
export const MAX_FILES = 10;

// Mirror the sidecar's TEXT_EXTENSIONS (chat_attachments.py) for this slice.
export const ACCEPTED_EXTENSIONS = [
  'md', 'markdown', 'txt', 'text', 'log', 'csv', 'tsv', 'json', 'yaml', 'yml',
  'py', 'js', 'ts', 'tsx', 'jsx', 'go', 'rs', 'java', 'c', 'h', 'cpp', 'sh',
  'rb', 'sql', 'html', 'css', 'xml', 'toml', 'ini',
];

export function isAccepted(file: File): boolean {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
  return ACCEPTED_EXTENSIONS.includes(ext) || file.type.startsWith('text/');
}

export async function fileToBase64(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

export async function uploadAttachments(
  convId: string,
  files: File[],
): Promise<ChatAttachment[]> {
  const payload = {
    files: await Promise.all(
      files.map(async (f) => ({
        name: f.name,
        mime: f.type,
        content_b64: await fileToBase64(f),
      })),
    ),
  };
  const res = await post<{ attachments: ChatAttachment[] }>(
    `/v1/chat/${convId}/attachments`,
    payload,
  );
  return res.attachments;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run (from `desktop/`): `npm test -- chat-attachments`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/shared/api-types.ts desktop/src/renderer/lib/chat-attachments.ts desktop/src/renderer/__tests__/chat-attachments.test.ts
git commit -m "feat(chat): renderer upload helper + attachment types"
```

---

### Task 7: Composer — drop / paste / browse + chips + upload-then-send

**Files:**
- Modify: `desktop/src/renderer/stores/chat.ts` (`StreamState.attachments`, `beginStream` arg)
- Modify: `desktop/src/renderer/screens/chat.tsx` (`Composer`, `ChatScreen.sendMessage`)
- Test: `desktop/src/renderer/__tests__/chat-store.test.ts`, `desktop/src/renderer/__tests__/ChatScreen.test.tsx`

**Interfaces:**
- Consumes: `uploadAttachments`, `isAccepted`, `MAX_FILE_BYTES`, `MAX_FILES` (Task 6); `ChatAttachment` (Task 6); `toast` (`../stores/toast`).
- Produces: `beginStream(id, userText, attachments?: ChatAttachment[])`; `StreamState.attachments: ChatAttachment[]`; `Composer` accepts `onSend(text: string, files: File[])`; internally holds a `File[]` queue with add/remove; renders removable chips; supports drag-drop, paste, and a paperclip file picker. `ChatScreen.sendMessage(text, files)` uploads then sends.

- [ ] **Step 1: Extend the stream store (test first)**

Append to `desktop/src/renderer/__tests__/chat-store.test.ts`:

```typescript
it('beginStream stores attachments on the stream', () => {
  const { beginStream } = useChat.getState();
  beginStream('c1', 'hi', [
    { path: '20-contexts/chat-attachments/a.md', title: 'a.md', kind: 'text' },
  ]);
  expect(useChat.getState().streams['c1'].attachments).toEqual([
    { path: '20-contexts/chat-attachments/a.md', title: 'a.md', kind: 'text' },
  ]);
});
```

Run (from `desktop/`): `npm test -- chat-store` → expect FAIL (`attachments` undefined / arity).

Then in `desktop/src/renderer/stores/chat.ts`, import the type and extend `StreamState` + `beginStream`:

```typescript
import type { ChatStreamEvent, ChatToolUse, ChatAttachment } from '../../shared/api-types';
```

```typescript
export interface StreamState {
  userText: string;
  text: string;
  tools: ChatToolUse[];
  attachments: ChatAttachment[];
}
```

```typescript
  beginStream: (id: string, userText: string, attachments?: ChatAttachment[]) => void;
```

```typescript
  beginStream: (id, userText, attachments = []) =>
    set((s) => {
      const errors = { ...s.errors };
      delete errors[id];
      return {
        streams: {
          ...s.streams,
          [id]: { userText, text: '', tools: [], attachments },
        },
        errors,
      };
    }),
```

Run: `npm test -- chat-store` → expect PASS.

- [ ] **Step 2: Write the failing composer test**

Add to `desktop/src/renderer/__tests__/ChatScreen.test.tsx` (follow the file's existing render/setup helpers; this shows the new assertions):

```typescript
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// ... within the existing describe block, with an active conversation rendered:

it('queues a dropped text file as a chip and clears it on remove', async () => {
  renderChat(); // existing helper that renders ChatScreen with a conversation
  const file = new File(['hello'], 'notes.md', { type: 'text/markdown' });
  const composer = screen.getByPlaceholderText(/message poltergeist/i);
  fireEvent.drop(composer, { dataTransfer: { files: [file] } });
  expect(await screen.findByText('notes.md')).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText('remove notes.md'));
  expect(screen.queryByText('notes.md')).not.toBeInTheDocument();
});

it('rejects an unsupported dropped file with a toast and no chip', async () => {
  renderChat();
  const file = new File(['x'], 'pic.png', { type: 'image/png' });
  const composer = screen.getByPlaceholderText(/message poltergeist/i);
  fireEvent.drop(composer, { dataTransfer: { files: [file] } });
  expect(screen.queryByText('pic.png')).not.toBeInTheDocument();
});
```

If `ChatScreen.test.tsx` has no `renderChat` helper, add a minimal one that mocks `useConversation` to return one conversation with an `activeId`, matching how the existing tests set up state. Reuse the file's current mocking approach rather than introducing a new one.

- [ ] **Step 3: Run test to verify it fails**

Run (from `desktop/`): `npm test -- ChatScreen`
Expected: FAIL — no chip renders on drop.

- [ ] **Step 4: Update `ChatScreen.sendMessage` and the `Composer` call site**

In `desktop/src/renderer/screens/chat.tsx`, change `sendMessage` to upload first, then send:

```typescript
  const sendMessage = (text: string, files: File[] = []) => {
    if (!activeId) return;
    void (async () => {
      let attachments: ChatAttachment[] = [];
      if (files.length > 0) {
        try {
          attachments = await uploadAttachments(activeId, files);
        } catch (err) {
          toast.error(err instanceof Error ? err.message : 'attachment upload failed');
          return;
        }
      }
      beginStream(activeId, text, attachments);
      const paths = attachments.map((a) => a.path);
      void window.gb.chat.send(activeId, text, paths).then((res) => {
        if (!res.ok) applyEvent(activeId, { type: 'error', message: res.error });
        endStream(activeId);
        qc.invalidateQueries({ queryKey: ['chat'] });
      });
    })();
  };
```

Add imports at the top of the file:

```typescript
import { toast } from '../stores/toast';
import { uploadAttachments, isAccepted, MAX_FILE_BYTES, MAX_FILES } from '../lib/chat-attachments';
import type { ChatAttachment } from '../../shared/api-types';
```

Update the `onRetry` prop passed to `Thread` — retry has no files: change `onRetry={sendMessage}` to `onRetry={(t) => sendMessage(t, [])}`.

- [ ] **Step 4: Update the `Composer` component**

Replace the `Composer` function in `desktop/src/renderer/screens/chat.tsx` with a version that owns a file queue and renders chips. Keep the existing textarea/autosize/submit logic; add the file handling:

```typescript
function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (text: string, files: File[]) => void;
}) {
  const [text, setText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const autosize = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
    el.style.overflowY = el.scrollHeight > 132 ? 'auto' : 'hidden';
  };

  const addFiles = (incoming: File[]) => {
    const accepted: File[] = [];
    for (const f of incoming) {
      if (!isAccepted(f)) {
        toast.error(`${f.name}: unsupported file type`);
        continue;
      }
      if (f.size > MAX_FILE_BYTES) {
        toast.error(`${f.name}: too large (max 1 MB)`);
        continue;
      }
      accepted.push(f);
    }
    setFiles((prev) => {
      const next = [...prev, ...accepted];
      if (next.length > MAX_FILES) {
        toast.error(`at most ${MAX_FILES} files per message`);
        return next.slice(0, MAX_FILES);
      }
      return next;
    });
  };

  const removeFile = (idx: number) =>
    setFiles((prev) => prev.filter((_, i) => i !== idx));

  const submit = () => {
    const trimmed = text.trim();
    if ((!trimmed && files.length === 0) || disabled) return;
    onSend(trimmed, files);
    setText('');
    setFiles([]);
    requestAnimationFrame(autosize);
  };

  return (
    <div
      className="flex-shrink-0 border-t border-hairline bg-paper px-6 py-4"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        addFiles(Array.from(e.dataTransfer.files));
      }}
    >
      <div className="mx-auto max-w-[760px]">
        {files.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-[6px]">
            {files.map((f, i) => (
              <span
                key={`${f.name}-${i}`}
                className="inline-flex items-center gap-1 rounded-xs bg-fog px-2 py-[3px] font-mono text-10 text-ink-2"
              >
                <Lucide name="paperclip" size={9} color="var(--ink-3)" />
                {f.name}
                <button
                  type="button"
                  aria-label={`remove ${f.name}`}
                  onClick={() => removeFile(i)}
                  className="ml-1 text-ink-3 hover:text-oxblood"
                >
                  <Lucide name="x" size={9} />
                </button>
              </span>
            ))}
          </div>
        )}

        <div
          className={`flex items-end gap-2 rounded-r10 border bg-vellum py-[6px] pl-[14px] pr-[6px] transition-colors duration-[120ms] ${
            dragging ? 'border-neon' : 'border-hairline-2 focus-within:border-ink-3'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []));
              e.target.value = '';
            }}
          />
          <button
            type="button"
            aria-label="attach files"
            disabled={disabled}
            onClick={() => fileInputRef.current?.click()}
            className="mb-[1px] flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-r6 text-ink-3 hover:bg-fog hover:text-ink-1 disabled:opacity-40"
          >
            <Lucide name="paperclip" size={15} />
          </button>
          <textarea
            ref={ref}
            value={text}
            rows={1}
            disabled={disabled}
            placeholder={
              disabled ? 'poltergeist is responding…' : 'message poltergeist…'
            }
            onChange={(e) => {
              setText(e.target.value);
              autosize();
            }}
            onPaste={(e) => {
              const pasted = Array.from(e.clipboardData.files);
              if (pasted.length > 0) {
                e.preventDefault();
                addFiles(pasted);
              }
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            className="flex-1 resize-none overflow-y-hidden border-none bg-transparent py-[7px] text-14 leading-[1.5] text-ink-0 placeholder:text-ink-3 focus:outline-none disabled:opacity-60"
          />
          <button
            type="button"
            aria-label="send"
            disabled={disabled || (text.trim().length === 0 && files.length === 0)}
            onClick={submit}
            className="mb-[1px] flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-r6 bg-neon transition-all duration-[120ms] hover:bg-neon-dark disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Lucide name="arrow-up" size={15} color="#0E0F12" />
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run (from `desktop/`): `npm test -- ChatScreen` then `npm run typecheck`.
Expected: PASS; typecheck clean.

- [ ] **Step 7: Commit**

```bash
git add desktop/src/renderer/stores/chat.ts desktop/src/renderer/screens/chat.tsx desktop/src/renderer/__tests__/chat-store.test.ts desktop/src/renderer/__tests__/ChatScreen.test.tsx
git commit -m "feat(chat): drop/paste/browse file attachments in the composer"
```

---

### Task 8: Render attachment chips on user messages (stream + history)

**Files:**
- Modify: `desktop/src/renderer/screens/chat.tsx` (`Message`, `StreamingTurn`, new `AttachmentChips`)
- Test: `desktop/src/renderer/__tests__/ChatScreen.test.tsx`

**Interfaces:**
- Consumes: `ChatAttachment` (Task 6); `StreamState.attachments` + `beginStream(…, attachments)` (Task 7).
- Produces: `AttachmentChips` component; `Message`/`StreamingTurn` render an attachment chip row on the user bubble (history + live stream).

- [ ] **Step 1: Render chips on the user bubble**

In `desktop/src/renderer/screens/chat.tsx`, add a small presentational component and use it in both `Message` (history) and `StreamingTurn` (live):

```typescript
function AttachmentChips({ attachments }: { attachments: ChatAttachment[] }) {
  if (attachments.length === 0) return null;
  return (
    <div className="mb-1 flex flex-wrap justify-end gap-[6px]">
      {attachments.map((a) => (
        <span
          key={a.path}
          className="inline-flex items-center gap-1 rounded-xs bg-fog px-2 py-[2px] font-mono text-10 text-ink-2"
          title={a.path}
        >
          <Lucide name="paperclip" size={9} color="var(--ink-3)" />
          {a.title}
        </span>
      ))}
    </div>
  );
}
```

In `Message`, render chips above the user bubble:

```typescript
  if (message.role === 'user') {
    return (
      <div className="flex flex-col items-end">
        <AttachmentChips attachments={message.attachments ?? []} />
        <div className="max-w-[80%] whitespace-pre-wrap rounded-r10 border border-hairline bg-vellum px-[14px] py-[10px] text-14 leading-[1.5] text-ink-0">
          {message.text}
        </div>
      </div>
    );
  }
```

In `StreamingTurn`, render chips above the optimistic user bubble:

```typescript
      <div className="flex flex-col items-end">
        <AttachmentChips attachments={stream.attachments} />
        <div className="max-w-[80%] whitespace-pre-wrap rounded-r10 border border-hairline bg-vellum px-[14px] py-[10px] text-14 leading-[1.5] text-ink-0">
          {stream.userText}
        </div>
      </div>
```

- [ ] **Step 2: Add a history-render assertion**

Append to `desktop/src/renderer/__tests__/ChatScreen.test.tsx` (using the file's conversation-mock helper, returning a user message that carries `attachments`):

```typescript
it('renders attachment chips on a historical user message', async () => {
  renderChatWithMessages([
    {
      role: 'user',
      text: 'see this',
      attachments: [
        { path: '20-contexts/chat-attachments/a.md', title: 'a.md', kind: 'text' },
      ],
    },
  ]);
  expect(await screen.findByText('a.md')).toBeInTheDocument();
});
```

If the test file lacks a `renderChatWithMessages` helper, extend its existing conversation mock to accept a `messages` array rather than adding a parallel harness.

- [ ] **Step 3: Run tests to verify they pass**

Run (from `desktop/`): `npm test -- ChatScreen` then `npm run typecheck`.
Expected: PASS; typecheck clean.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/screens/chat.tsx desktop/src/renderer/__tests__/ChatScreen.test.tsx
git commit -m "feat(chat): render attachment chips on user messages"
```

---

## Final verification

- [ ] Run the full sidecar suite: `pytest ghostbrain/api/tests/ -q` — expect green.
- [ ] Run the full desktop suite: from `desktop/`, `npm test` then `npm run typecheck` — expect green.
- [ ] Manual smoke (DEMO off, real sidecar): open Chat, drag a `.md` file onto the composer, confirm the chip appears, send a message, confirm the turn references `[[20-contexts/chat-attachments/…]]` and the note exists on disk under the vault.

## Follow-up (out of this plan)

- **Slice 2 (PDF/docx):** add a Python extraction step before `save_attachment`'s note write; extend `TEXT_EXTENSIONS`/`ACCEPTED_EXTENSIONS` and the `kind` values. Reuses Tasks 2–8 unchanged.
- **Slice 3 (images):** store the binary under `chat-attachments/assets/` + generate OCR/caption text for the note body. Resolve the open decision (dedicated `claude -p` vision call vs local OCR) when planning this slice.
