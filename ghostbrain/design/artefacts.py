"""Design artefacts: what a live design session leaves in the vault.

Every session folder (``20-contexts/<ctx>/[projects/<slug>/](prototypes|artefacts)/<name>``)
holds ``artefact.json`` (the machine-readable record the session keeps
current) and ``README.md`` (the note a human reads, ``type: artefact``). An
artefact is a scratch prototype, a git worktree of an existing frontend, or
an event-storming board.

Once the recording's meeting note exists, :func:`link_meeting` (a recorder
``on_transcribed`` hook) links the two both ways: the artefact names its
meeting, and the meeting note lists its artefacts.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from ghostbrain.recorder import hooks
from ghostbrain.vault_index.parse import split_frontmatter

log = logging.getLogger("ghostbrain.design.artefacts")

VERSION = 1
DATA_FILE = "artefact.json"
NOTE_FILE = "README.md"
KINDS = ("prototype", "worktree", "board")
FOLDER_KINDS = ("prototypes", "artefacts")
PLACEHOLDER_TITLES = ("", "meeting", "prototype")

# Frontmatter keys in note order; None values are left out.
_FRONT_KEYS = ("type", "kind", "title", "date", "context", "project", "design_system",
               "meeting", "meeting_path", "ui_rev", "board_rev", "repo", "worktree", "branch")
_CODEBASE_KEYS = ("repo", "name", "app_dir", "worktree", "branch", "base")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PLAIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_REV_LINE_RE = re.compile(r"^\s*- rev (\d+): (.*)$", re.MULTILINE)
_BOARD_LINE_RE = re.compile(r"`board\.json` \(rev (\d+)\)")
_FRONT_OPEN_RE = re.compile(r"\A---[ \t]*\r?\n")
_FRONT_CLOSE_RE = re.compile(r"^---[ \t]*\r?$", re.MULTILINE)
_SECTION_RE = re.compile(r"^## Artefacts[ \t]*\r?$", re.MULTILINE)
_HEADING_RE = re.compile(r"^#{1,2} ", re.MULTILINE)


class ArtefactError(Exception):
    """An action this artefact does not support (routes answer 409)."""


def _vault() -> Path:
    from ghostbrain.paths import vault_path

    return vault_path()


def _worktree() -> ModuleType:
    # Looked up at call time: the worktree module is optional at import.
    return importlib.import_module("ghostbrain.design.worktree")


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


# -- artefact.json + README ------------------------------------------------------------


def _read_json(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / DATA_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _note_stem(path: str) -> str:
    return path.removesuffix(".md")


def _meeting_link(data: dict) -> str | None:
    title, path = data.get("meeting"), data.get("meeting_path")
    if path:
        return f"[[{_note_stem(path)}|{title or Path(_note_stem(path)).name}]]"
    return title or None


def _yaml_scalar(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    s = str(value)
    if key == "date" and _DATE_RE.match(s):
        return s
    try:
        plain_ok = _PLAIN_RE.match(s) is not None and yaml.safe_load(s) == s
    except yaml.YAMLError:
        plain_ok = False
    return s if plain_ok else json.dumps(s, ensure_ascii=False)


def _render_note(data: dict) -> str:
    codebase = data.get("codebase") if isinstance(data.get("codebase"), dict) else None
    fields: dict[str, Any] = {
        "type": "artefact", "kind": data["kind"], "title": data["title"], "date": data["date"],
        "context": data["context"], "project": data.get("project"),
        "design_system": data.get("design_system"), "meeting": _meeting_link(data),
        "meeting_path": data.get("meeting_path"), "ui_rev": int(data.get("ui_rev") or 0),
        "board_rev": int(data.get("board_rev") or 0),
    }
    if data["kind"] == "worktree" and codebase:
        fields.update(repo=codebase.get("repo"), worktree=codebase.get("worktree"),
                      branch=codebase.get("branch"))
    front = ["---"]
    front += [f"{k}: {_yaml_scalar(k, fields[k])}" for k in _FRONT_KEYS if fields.get(k) is not None]
    front.append("---")

    link = fields["meeting"]
    during = f"**{link}**" if link else "a meeting"
    body = ["", f"# {data['title']}", "", f"Built live during {during} on {data['date']}.", ""]
    ui_rev, board_rev = fields["ui_rev"], fields["board_rev"]
    if data["kind"] == "worktree" and codebase:
        body.append(f"- Code: `{codebase.get('worktree')}` on branch `{codebase.get('branch')}` "
                    f"(from {codebase.get('repo')})")
    elif ui_rev:
        design = f", design system `{data['design_system']}`" if data.get("design_system") else ""
        body.append(f"- Prototype: `src/` (rev {ui_rev}{design})")
    if ui_rev or data["kind"] == "worktree":
        body += [f"  - rev {r.get('rev')}: {r.get('summary')}" for r in data.get("revs") or []]
    if board_rev:
        body.append(f"- Event-storming board: `board.json` (rev {board_rev})")
    if not ui_rev and not board_rev and data["kind"] != "worktree":
        body.append("- Nothing was generated in this meeting.")
    return "\n".join(front + body) + "\n"


def write(folder: Path, data: dict) -> None:
    """Write ``artefact.json`` and the ``README.md`` note, both atomically.

    A meeting link already recorded on disk survives a rewrite that does not
    carry one (the live session writes after every revision and knows
    nothing of :func:`link_meeting`)."""
    folder = Path(folder)
    data = _normalized(dict(data), folder)
    existing = _read_json(folder) or {}
    for key in ("meeting", "meeting_path"):
        if not data.get(key) and existing.get(key):
            data[key] = existing[key]
    _write_atomic(folder / DATA_FILE, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    _write_atomic(folder / NOTE_FILE, _render_note(data))


def _context_from(folder: Path) -> str:
    try:
        parts = folder.relative_to(_vault()).parts
    except ValueError:
        return ""
    return parts[1] if len(parts) > 1 and parts[0] == "20-contexts" else ""


def _normalized(data: dict, folder: Path) -> dict:
    kind = data.get("kind") if data.get("kind") in KINDS else "prototype"
    revs = [r for r in data.get("revs") or [] if isinstance(r, dict)]
    codebase = data.get("codebase") if isinstance(data.get("codebase"), dict) else None
    return {
        **data,
        "version": VERSION,
        "title": str(data.get("title") or "Meeting"),
        "kind": kind,
        "board": bool(data.get("board")),
        "date": str(data.get("date") or folder.name[:10]),
        "context": str(data.get("context") or _context_from(folder)),
        "project": data.get("project") or None,
        "design_system": data.get("design_system") or None,
        "meeting": data.get("meeting") or None,
        "meeting_path": data.get("meeting_path") or None,
        "ui_rev": int(data.get("ui_rev") or 0),
        "board_rev": int(data.get("board_rev") or 0),
        "revs": revs,
        "codebase": codebase,
    }


def _legacy(folder: Path) -> dict | None:
    """A prototype folder from before artefact.json: rebuild from its README."""
    try:
        text = (folder / NOTE_FILE).read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = split_frontmatter(text)
    if meta.get("type") not in ("prototype", "artefact"):
        return None
    revs = [{"rev": int(n), "at": None, "summary": s.strip()} for n, s in _REV_LINE_RE.findall(body)]
    ui_rev = max((r["rev"] for r in revs), default=0)
    board = _BOARD_LINE_RE.search(body)
    board_rev = int(board.group(1)) if board else 0
    if meta.get("type") == "artefact":
        ui_rev = int(meta.get("ui_rev") or ui_rev)
        board_rev = int(meta.get("board_rev") or board_rev)
    kind = meta.get("kind") if meta.get("kind") in KINDS else (
        "board" if board_rev and not ui_rev else "prototype")
    title = meta.get("title") if meta.get("type") == "artefact" else meta.get("meeting")
    day = meta.get("date")
    return {
        "version": VERSION, "title": str(title or folder.name), "kind": kind,
        "board": board_rev > 0, "date": day.isoformat() if hasattr(day, "isoformat") else str(day or ""),
        "context": meta.get("context"), "project": meta.get("project"),
        "design_system": meta.get("design_system"), "meeting": None, "meeting_path": None,
        "ui_rev": ui_rev, "board_rev": board_rev, "revs": revs, "codebase": None,
    }


def load(folder: Path) -> dict | None:
    """The artefact record (``artefact.json``, else a legacy README), or None."""
    folder = Path(folder)
    data = _read_json(folder)
    if data is None:
        data = _legacy(folder)
    return _normalized(data, folder) if data is not None else None


# -- listing + detail ----------------------------------------------------------------------


def folder_for(artefact_id: str) -> Path:
    """The artefact folder for a vault-relative id. ValueError unless it is an
    existing ``20-contexts/<ctx>/[projects/<slug>/](prototypes|artefacts)/<name>``
    folder reached without ``..`` or symlinks."""
    if not isinstance(artefact_id, str) or "\\" in artefact_id or "\0" in artefact_id:
        raise ValueError("invalid artefact id")
    parts = artefact_id.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("invalid artefact id")
    shaped = (
        (len(parts) == 4 and parts[0] == "20-contexts" and parts[2] in FOLDER_KINDS)
        or (len(parts) == 6 and parts[0] == "20-contexts" and parts[2] == "projects"
            and parts[4] in FOLDER_KINDS)
    )
    if not shaped:
        raise ValueError(f"not an artefact folder: {artefact_id}")
    root = _vault()
    folder = root.joinpath(*parts)
    if not folder.is_dir() or folder.resolve() != folder:
        raise ValueError(f"artefact not found: {artefact_id}")
    return folder


def _codebase_summary(codebase: Any) -> dict | None:
    if not isinstance(codebase, dict):
        return None
    out = {k: str(codebase.get(k) or "") for k in _CODEBASE_KEYS}
    out["missing"] = not (out["worktree"] and Path(out["worktree"]).is_dir())
    return out


def _summary(folder: Path, data: dict) -> dict:
    return {
        "id": folder.relative_to(_vault()).as_posix(),
        "title": data["title"],
        "kind": data["kind"],
        "board": data["board"] or data["board_rev"] > 0,
        "date": data["date"],
        "context": data["context"],
        "project": data["project"],
        "meeting": data["meeting"],
        "meeting_path": data["meeting_path"],
        "ui_rev": data["ui_rev"],
        "board_rev": data["board_rev"],
        "codebase": _codebase_summary(data["codebase"]),
    }


def _candidate_folders() -> list[Path]:
    contexts = _vault() / "20-contexts"
    found: list[Path] = []
    for kinds in FOLDER_KINDS:
        found += contexts.glob(f"*/{kinds}/*")
        found += contexts.glob(f"*/projects/*/{kinds}/*")
    return [p for p in found if p.is_dir() and not p.is_symlink()]


def _mtime(folder: Path) -> float:
    for name in (DATA_FILE, NOTE_FILE):
        try:
            return (folder / name).stat().st_mtime
        except OSError:
            continue
    return 0.0


def list_artefacts() -> list[dict]:
    """Every artefact in the vault as an ArtefactSummary dict, newest first."""
    rows: list[tuple[str, float, dict]] = []
    for folder in _candidate_folders():
        try:
            data = load(folder)
            if data is not None:
                rows.append((data["date"], _mtime(folder), _summary(folder, data)))
        except Exception:
            log.exception("could not read artefact %s", folder)
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [r[2] for r in rows]


def _revs(folder: Path, data: dict, codebase: dict | None) -> list[dict]:
    if data["kind"] == "worktree":
        if codebase and not codebase["missing"]:
            try:
                wt = _worktree()
                return list(wt.revisions(wt.Worktree.from_dict(data["codebase"])))
            except Exception:
                log.exception("could not read the revisions of %s", codebase["worktree"])
        return data["revs"]
    if data["revs"]:
        return data["revs"]
    from ghostbrain.design import scaffold

    try:
        return [r for r in scaffold.revisions(folder) if r["rev"] > 0]
    except Exception:
        log.exception("could not read the revisions of %s", folder)
        return []


def detail(artefact_id: str) -> dict | None:
    """One artefact as an ArtefactDetail dict, or None (unknown or invalid id)."""
    try:
        folder = folder_for(artefact_id)
    except ValueError:
        return None
    data = load(folder)
    if data is None:
        return None
    summary = _summary(folder, data)
    board_model = None
    try:
        model = json.loads((folder / "board.json").read_text(encoding="utf-8"))
        board_model = model if isinstance(model, dict) else None
    except (OSError, ValueError):
        pass
    return {
        **summary,
        "folder": str(folder),
        "revs": _revs(folder, data, summary["codebase"]),
        "board_model": board_model,
        "design_system": data["design_system"],
    }


# -- actions ---------------------------------------------------------------------------------


def remove_worktree(artefact_id: str) -> dict:
    """``git worktree remove`` the artefact's worktree; the branch is deleted
    only when merged. A worktree already deleted by hand is a success."""
    folder = folder_for(artefact_id)
    data = load(folder)
    if data is None or data["kind"] != "worktree" or data["codebase"] is None:
        raise ArtefactError("This artefact has no worktree")
    codebase = _codebase_summary(data["codebase"])
    assert codebase is not None
    try:
        wt = _worktree()
        return dict(wt.remove(wt.Worktree.from_dict(data["codebase"])))
    except Exception as e:
        if codebase["missing"]:
            log.info("worktree %s was already gone: %s", codebase["worktree"], e)
            return {"removed": True, "branch_kept": False, "reason": "The worktree was already removed"}
        raise ArtefactError(f"Could not remove the worktree: {e}") from e


def eject(artefact_id: str) -> Path:
    """Turn a scratch prototype into a standalone Vite project."""
    folder = folder_for(artefact_id)
    data = load(folder)
    if data is None or data["kind"] != "prototype":
        raise ArtefactError("Only scratch prototypes can be ejected")
    from ghostbrain.design import scaffold

    return Path(scaffold.eject(folder))


# -- meeting link ------------------------------------------------------------------------------


def _is_placeholder(title: str | None) -> bool:
    t = (title or "").strip().lower()
    return t in PLACEHOLDER_TITLES or t.startswith("meeting-")


def _meeting_title(meta: dict, body: str, note_path: Path) -> str:
    title = str(meta.get("title") or "").strip().removeprefix("Transcript:").strip()
    if not title:
        heading = re.search(r"^# (.+)$", body, re.MULTILINE)
        title = heading.group(1).strip() if heading else ""
    return title or note_path.stem


def _drop_key(front: str, key: str) -> str:
    """Remove a top-level key (and its indented / list lines) from raw YAML."""
    out: list[str] = []
    skipping = False
    for line in front.splitlines(keepends=True):
        if skipping and (line.startswith((" ", "\t", "- ")) or line.strip() == "-"):
            continue
        skipping = line.startswith(f"{key}:")
        if not skipping:
            out.append(line)
    return "".join(out)


def _with_frontmatter_entry(text: str, entry: str) -> str:
    """Add ``entry`` to the note's ``artefacts:`` list, leaving every other
    frontmatter line byte-for-byte as it was."""
    opening = _FRONT_OPEN_RE.match(text)
    closing = _FRONT_CLOSE_RE.search(text, opening.end()) if opening else None
    if opening is None or closing is None:
        block = yaml.safe_dump({"artefacts": [entry]}, sort_keys=False, allow_unicode=True)
        return f"---\n{block}---\n\n{text}"
    meta, _ = split_frontmatter(text)
    current = meta.get("artefacts")
    entries = [str(x) for x in current] if isinstance(current, list) else ([str(current)] if current else [])
    if entry in entries:
        return text
    raw = text[opening.end():closing.start()]
    if raw and not raw.endswith("\n"):
        raw += "\n"
    block = yaml.safe_dump({"artefacts": entries + [entry]}, sort_keys=False, allow_unicode=True)
    return text[:opening.end()] + _drop_key(raw, "artefacts") + block + text[closing.start():]


def _with_section_line(text: str, entry: str, line: str) -> str:
    if f"[[{entry}|" in text or f"[[{entry}]]" in text:
        return text
    section = _SECTION_RE.search(text)
    if section is None:
        return text.rstrip("\n") + f"\n\n## Artefacts\n\n{line}\n"
    nxt = _HEADING_RE.search(text, section.end())
    end = nxt.start() if nxt else len(text)
    kept = text[section.end():end].rstrip()
    chunk = (kept + "\n" if kept.strip() else "\n\n") + line + "\n" + ("\n" if nxt else "")
    return text[:section.end()] + chunk + text[end:]


def _link_meeting(wav: Path, note_path: Path) -> bool:
    from ghostbrain.design import session as design_session

    try:
        pointer = json.loads(design_session.pointer_path(wav).read_text(encoding="utf-8"))
        folder = Path(pointer["prototype_dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    data = load(folder)
    if data is None:
        return False
    root = _vault()
    try:
        artefact_id = folder.resolve().relative_to(root).as_posix()
        meeting_path = note_path.resolve().relative_to(root).as_posix()
    except ValueError:
        log.warning("artefact %s or meeting note %s is outside the vault", folder, note_path)
        return False
    text = note_path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(text)
    title = _meeting_title(meta, body, note_path)

    data["meeting"], data["meeting_path"] = title, meeting_path
    if _is_placeholder(data["title"]):
        data["title"] = title
    write(folder, data)

    live = design_session.get(wav)
    if live is not None and _is_placeholder(live.recording_title):
        live.recording_title = title

    entry = f"{artefact_id}/README"
    rev = data["board_rev"] if data["kind"] == "board" else data["ui_rev"]
    line = f"- [[{entry}|{data['title']}]] — {data['kind']}, rev {rev}"
    updated = _with_section_line(_with_frontmatter_entry(text, entry), entry, line)
    if updated != text:
        _write_atomic(note_path, updated)
    return True


def link_meeting(wav: Path, note_path: Path) -> bool:
    """Link the design artefact of recording ``wav`` and its meeting note both
    ways. False when the recording had no design session. Idempotent; never
    raises (it runs inside transcription)."""
    try:
        return _link_meeting(Path(wav), Path(note_path))
    except Exception:
        log.exception("could not link the design artefact of %s to its meeting", Path(wav).name)
        return False


hooks.on_transcribed(link_meeting)
