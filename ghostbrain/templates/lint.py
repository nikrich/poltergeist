"""Template linter (spec C3): parse diagnostics, then a registry check of
every ``{{ placeholder }}`` and every ```query``` block.

The placeholder checks mirror ``render.evaluate`` exactly: anything this
module flags renders as its literal text, and anything it passes renders
(pinned by a parity test). Nothing here evaluates template text.
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterable

import yaml

from ghostbrain.templates.functions import FIELDS, FILTERS, PROMPT_VALUE_TYPES, VARIABLES, find_spec
from ghostbrain.templates.lang import Placeholder, TemplateLimitError, tokenize
from ghostbrain.templates.parse import Diagnostic, Template, _compose, parse_template
from ghostbrain.vault_write.text import parse_note

MAX_LINT_DIAGNOSTICS = 100
_FENCE_OPEN_RE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*).*")
_FENCE_CLOSE_RE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*")
# The query parser's own complaint about {{ }} in a value: in a template the
# placeholder is filled in at creation, so it is expected there.
_TEMPLATE_ONLY_QUERY_CODES = frozenset({"unresolved-placeholder"})

# render() fills file.name and file.folder before `title` exists (title is
# made from file.name), so there it stays literal.
_TITLE_FREE_KEYS = ("name", "folder")
_TITLE_UNAVAILABLE = ("`title` is the note's title, made from file.name; "
                      "it isn't available in file.name or file.folder")

QueryParser = Callable[[str], "tuple[object, list[Diagnostic]]"]


def query_parser() -> QueryParser | None:
    """C2's ``parse_query_block`` when the branch has it, else None (query
    blocks are then not linted)."""
    try:
        from ghostbrain.templates.query import parse_query_block
    except ImportError:
        return None
    return parse_query_block


def _warn(ph: Placeholder, message: str, code: str) -> Diagnostic:
    return Diagnostic(ph.line, ph.col, "warning", message, code)


def _suggest(name: str, known: Iterable[str]) -> str:
    close = difflib.get_close_matches(name, sorted(set(known)), n=1, cutoff=0.6)
    return f" — did you mean `{close[0]}`?" if close else ""


def _root_type(name: str, prompt_types: dict[str, str]) -> str | None:
    if name in prompt_types:
        return prompt_types[name]
    spec = find_spec("variable", name)
    return spec.type if spec is not None else None


def _child(node: yaml.Node | None, key: str) -> yaml.Node | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    # The last duplicate key wins, as when the frontmatter is loaded.
    found = [v for k, v in node.value if isinstance(k, yaml.ScalarNode) and k.value == key]
    return found[-1] if found else None


def _title_free_spans(source: str) -> list[tuple[int, int]]:
    """Source offsets of the template's file.name and file.folder values."""
    parsed = parse_note(source)
    root = _compose(parsed.fm_inner)
    base = len(parsed.bom) + len(parsed.fm_head)
    spans = []
    file_node = _child(_child(root, "template"), "file")
    for key in _TITLE_FREE_KEYS:
        node = _child(file_node, key)
        if node is not None:
            spans.append((base + node.start_mark.index, base + node.end_mark.index))
    return spans


def _check(ph: Placeholder, prompt_types: dict[str, str], title_free: bool = False) -> Diagnostic | None:
    if ph.path is None:
        return _warn(ph, f"`{ph.raw}` is not a placeholder (a name, optional .fields and "
                         "| filters); it renders as literal text", "malformed")
    root = ph.path[0]
    if title_free and root == "title":
        return _warn(ph, _TITLE_UNAVAILABLE, "unknown-name")
    current = _root_type(root, prompt_types)
    if current is None:
        known = [*prompt_types, *(s.name for s in VARIABLES)]
        return _warn(ph, f"unknown name `{root}`; it renders as literal text{_suggest(root, known)}",
                     "unknown-name")
    owner = root
    for name in ph.path[1:]:
        spec = find_spec("field", name, current)
        if spec is None:
            fields = sorted(s.name for s in FIELDS if s.owner == current)
            if not fields:
                return _warn(ph, f"`{owner}` has no fields", "unknown-field")
            return _warn(ph, f"`{owner}` has no field `{name}`; fields: {', '.join(fields)}"
                             f"{_suggest(name, fields)}", "unknown-field")
        current, owner = spec.type, f"{owner}.{name}"
    for call in ph.filters:
        spec = find_spec("filter", call.name)
        if spec is None:
            known = [s.name for s in FILTERS]
            return _warn(ph, f"unknown filter `{call.name}`{_suggest(call.name, known)}",
                         "unknown-filter")
        if spec.arg_required and call.arg is None:
            return _warn(ph, f"`{call.name}` needs an argument, e.g. {spec.example}", "filter-arg")
        if spec.arg is None and call.arg is not None:
            return _warn(ph, f"`{call.name}` takes no argument", "filter-arg")
    return None


def _placeholder_diagnostics(source: str, template: Template) -> list[Diagnostic]:
    prompt_types = {p.id: PROMPT_VALUE_TYPES[p.type] for p in template.prompts}
    try:
        segments = tokenize(source)
    except TemplateLimitError:
        return []  # parse_template already reported the limit
    spans = _title_free_spans(source)
    out = []
    for seg in segments:
        if isinstance(seg, Placeholder):
            title_free = any(start <= seg.start and seg.end <= end for start, end in spans)
            diag = _check(seg, prompt_types, title_free)
            if diag is not None:
                out.append(diag)
    return out


def _query_diagnostics(template: Template, parser: QueryParser) -> list[Diagnostic]:
    lines = template.body.split("\n")
    out: list[Diagnostic] = []
    i = 0
    while i < len(lines):
        m = _FENCE_OPEN_RE.fullmatch(lines[i])
        if m is None:
            i += 1
            continue
        fence, is_query = m.group(1), m.group(2).lower() == "query"
        end = i + 1
        while end < len(lines):
            close = _FENCE_CLOSE_RE.fullmatch(lines[end])
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= len(fence):
                break
            end += 1
        fence_line = template.body_line + i
        if is_query:
            if end >= len(lines):
                out.append(Diagnostic(fence_line, 1, "warning",
                                      "this ```query block is never closed", "unclosed-query"))
            else:
                _query, diags = parser("\n".join(lines[i + 1:end]))
                out.extend(
                    Diagnostic(fence_line + d.line, d.col, d.severity, d.message, d.code)
                    for d in diags if d.code not in _TEMPLATE_ONLY_QUERY_CODES
                )
        i = end + 1
    return out


def lint(source: str, template_id: str = "draft") -> list[Diagnostic]:
    """Every problem in ``source``, ordered by position, at most
    MAX_LINT_DIAGNOSTICS (+1 summary). Lines and columns are 1-based, whole file."""
    result = parse_template(source, template_id)
    diags = list(result.diagnostics)
    if result.template is not None:
        diags += _placeholder_diagnostics(source.replace("\r\n", "\n"), result.template)
        parser = query_parser()
        if parser is not None:
            diags += _query_diagnostics(result.template, parser)
    diags.sort(key=lambda d: (d.line, d.col))
    if len(diags) > MAX_LINT_DIAGNOSTICS:
        rest = len(diags) - MAX_LINT_DIAGNOSTICS
        last = diags[MAX_LINT_DIAGNOSTICS]
        diags = [*diags[:MAX_LINT_DIAGNOSTICS],
                 Diagnostic(last.line, last.col, "info", f"…and {rest} more problems", "truncated")]
    return diags
