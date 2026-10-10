"""Load and validate a template file (spec: Template format, parse.py).

The frontmatter's ``template:`` mapping is validated with pydantic, and every
problem becomes a line/col ``Diagnostic`` so the C3 editor can mark it.
Only ``yaml.safe_load`` / ``yaml.compose`` with SafeLoader are used, so YAML
tags cannot construct Python objects. Anchors and aliases are rejected from
the event stream before anything is constructed (templates never need them,
and ``<<`` merge keys / aliased strings amplify work), and a node, depth and
total-text budget bounds whatever is left.
"""
from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ghostbrain.templates.lang import MAX_TEMPLATE_CHARS, Placeholder, TemplateLimitError, tokenize
from ghostbrain.vault_write.text import parse_note

PromptType = Literal["person", "text", "date", "choice", "context", "project"]
Severity = Literal["error", "warning", "info"]

PROMPT_ID_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
DEFAULT_FOLDER = "20-contexts/{{context}}/notes"
SHADOWABLE: Mapping[str, str] = {"date": "date", "context": "context", "project": "project"}
RESERVED_IDS = frozenset({"time", "now", "title", "user"})
MAX_PROMPTS = 20
MAX_TREE_NODES = 5_000
MAX_TREE_DEPTH = 12
MAX_DIAGNOSTICS = 20


@dataclass(frozen=True)
class Diagnostic:
    line: int
    col: int
    severity: Severity
    message: str
    code: str

    def to_json(self) -> dict[str, Any]:
        return {"line": self.line, "col": self.col, "severity": self.severity,
                "message": self.message, "code": self.code}


@dataclass(frozen=True)
class Prompt:
    id: str
    ask: str
    type: PromptType
    optional: bool = False
    default: str | None = None
    options: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "ask": self.ask, "type": self.type, "optional": self.optional,
                "default": self.default, "options": list(self.options)}


@dataclass(frozen=True)
class FileSpec:
    folder: str
    name: str


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    description: str
    prompts: tuple[Prompt, ...]
    file: FileSpec
    frontmatter: Mapping[str, Any]
    body: str
    body_line: int
    variables: tuple[str, ...]


@dataclass(frozen=True)
class ParseResult:
    template: Template | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return self.template is not None


def _scalar_text(value: Any) -> Any:
    """YAML turns ``2026-10-09`` into a date and ``2`` into an int; prompt
    defaults and options are text. Containers are left for pydantic to reject."""
    if value is None or isinstance(value, (str, dict, list)):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class _PromptModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=PROMPT_ID_PATTERN)
    ask: str = Field(min_length=1, max_length=200)
    type: PromptType
    optional: bool = False
    default: str | None = Field(default=None, max_length=2_000)
    options: list[str] | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("default", mode="before")
    @classmethod
    def _default_as_text(cls, value: Any) -> Any:
        return _scalar_text(value)

    @field_validator("options", mode="before")
    @classmethod
    def _options_as_text(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [_scalar_text(v) for v in value]
        return value

    @model_validator(mode="after")
    def _options_match_type(self) -> _PromptModel:
        if self.type == "choice":
            if not self.options:
                raise ValueError("a choice prompt needs `options`")
            if self.default is not None and self.default not in self.options:
                raise ValueError("`default` must be one of `options`")
        elif self.options is not None:
            raise ValueError("`options` is only allowed on choice prompts")
        return self


class _FileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder: str = Field(default=DEFAULT_FOLDER, min_length=1, max_length=300)
    name: str | None = Field(default=None, min_length=1, max_length=300)


class _TemplateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)
    prompts: list[_PromptModel] = Field(default_factory=list, max_length=MAX_PROMPTS)
    file: _FileModel = Field(default_factory=_FileModel)
    frontmatter: dict[str, Any] = Field(default_factory=dict)


def _event_problem(fm_inner: str) -> tuple[yaml.Mark, str] | None:
    """Scan the YAML event stream (nothing constructed yet) for anchors,
    aliases, too many nodes and runaway nesting, so neither alias
    amplification nor the constructor/composer ever runs on them. Returns
    the offending event's mark and a message, or None."""
    depth = nodes = 0
    for event in yaml.parse(fm_inner, Loader=yaml.SafeLoader):
        if isinstance(event, yaml.AliasEvent) or (
            isinstance(event, yaml.NodeEvent) and event.anchor is not None
        ):
            return (event.start_mark,
                    "YAML anchors and aliases (&name, *name, <<) are not allowed in templates")
        if isinstance(event, (yaml.ScalarEvent, yaml.CollectionStartEvent)):
            nodes += 1
            if nodes > MAX_TREE_NODES:
                return event.start_mark, "frontmatter is too large"
        if isinstance(event, yaml.CollectionStartEvent):
            depth += 1
            if depth > MAX_TREE_DEPTH + 1:  # the root mapping is depth 1
                return event.start_mark, "frontmatter is nested too deeply"
        elif isinstance(event, yaml.CollectionEndEvent):
            depth -= 1
    return None


def _tree_problem(value: Any) -> str | None:
    """Iterative walk with a node, depth and total-text budget (a second line
    of defence behind ``_event_problem``)."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = chars = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_TREE_NODES:
            return "frontmatter is too large"
        if depth > MAX_TREE_DEPTH:
            return "frontmatter is nested too deeply"
        if isinstance(item, float) and not math.isfinite(item):
            return "frontmatter numbers must be finite"
        if isinstance(item, int) and item.bit_length() > 63:
            return "frontmatter numbers must fit in 64 bits"
        if not isinstance(item, (str, int, float, date, list, dict)) and item is not None:
            return f"frontmatter values cannot be YAML {type(item).__name__} (use text, numbers, lists or mappings)"
        if isinstance(item, str):
            chars += len(item)
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    return "frontmatter keys must be text"
                chars += len(key)
                stack.append((child, depth + 1))
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        if chars > MAX_TEMPLATE_CHARS:
            return f"frontmatter text is larger than {MAX_TEMPLATE_CHARS} characters"
    return None


def _strings(value: Any) -> Iterator[str]:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _with_source_spelling(template: Any, root: yaml.Node | None) -> Any:
    """Copy of the ``template`` mapping whose prompt ``default``/``options``
    scalars carry their source text, so ``yes``/``On``/``2026-10-09`` stay as
    written instead of YAML 1.1's bool/date (``_scalar_text`` is the fallback)."""
    prompts = template.get("prompts")
    if root is None or not isinstance(prompts, list):
        return template

    def node_at(*loc: Any) -> yaml.Node | None:
        node: yaml.Node | None = root
        for part in loc:
            if isinstance(node, yaml.MappingNode):
                node = next((v for k, v in node.value
                             if isinstance(k, yaml.ScalarNode) and k.value == part), None)
            elif isinstance(node, yaml.SequenceNode) and isinstance(part, int) and part < len(node.value):
                node = node.value[part]
            else:
                return None
        return node

    def spelled(value: Any, node: yaml.Node | None) -> Any:
        if value is None or isinstance(value, (str, list, dict)) or not isinstance(node, yaml.ScalarNode):
            return value
        return node.value

    new_prompts = []
    for i, prompt in enumerate(prompts):
        if isinstance(prompt, dict):
            prompt = dict(prompt)
            if "default" in prompt:
                prompt["default"] = spelled(prompt["default"], node_at("template", "prompts", i, "default"))
            if isinstance(prompt.get("options"), list):
                prompt["options"] = [spelled(v, node_at("template", "prompts", i, "options", j))
                                     for j, v in enumerate(prompt["options"])]
        new_prompts.append(prompt)
    return {**template, "prompts": new_prompts}


def _compose(fm_inner: str) -> yaml.Node | None:
    try:
        return yaml.compose(fm_inner, Loader=yaml.SafeLoader)
    except (yaml.YAMLError, RecursionError):
        return None


def _locate(root: yaml.Node | None, loc: tuple[Any, ...], fm_line: int) -> tuple[int, int]:
    """Line/col (1-based, whole file) of the deepest YAML node on ``loc``.
    ``root`` is the frontmatter composed once per parse (None if it failed)."""
    node = root
    if node is None:
        return fm_line, 1
    mark = node.start_mark
    for part in loc:
        child = None
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode) and key_node.value == str(part):
                    child, mark = value_node, key_node.start_mark
                    break
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int) and 0 <= part < len(node.value):
            child = node.value[part]
            mark = child.start_mark
        if child is None:
            break
        node = child
    return fm_line + mark.line, mark.column + 1


def _capped(diags: list[Diagnostic]) -> tuple[Diagnostic, ...]:
    """The first MAX_DIAGNOSTICS diagnostics plus one summary for the rest."""
    if len(diags) <= MAX_DIAGNOSTICS:
        return tuple(diags)
    rest = diags[MAX_DIAGNOSTICS:]
    severity: Severity = "error" if any(d.severity == "error" for d in rest) else "warning"
    first = rest[0]
    summary = Diagnostic(first.line, first.col, severity,
                         f"…and {len(rest)} more problems", "truncated")
    return (*diags[:MAX_DIAGNOSTICS], summary)


def parse_template(source: str, template_id: str) -> ParseResult:
    diags: list[Diagnostic] = []

    def fail(line: int, col: int, message: str, code: str) -> ParseResult:
        return ParseResult(None, _capped([*diags, Diagnostic(line, col, "error", message, code)]))

    if len(source) > MAX_TEMPLATE_CHARS:
        return fail(1, 1, f"template is larger than {MAX_TEMPLATE_CHARS} characters", "limit")
    # CRLF -> LF keeps line numbers (one break either way) and stops a
    # Windows-saved template from producing mixed line endings.
    parsed = parse_note(source.replace("\r\n", "\n"))
    if not parsed.has_frontmatter:
        return fail(1, 1, "a template starts with a --- frontmatter block that has a `template:` key",
                    "no-frontmatter")
    fm_line = parsed.fm_head.count("\n") + 1
    body_line = (parsed.fm_head + parsed.fm_inner + parsed.fm_close + parsed.gap).count("\n") + 1
    try:
        early = _event_problem(parsed.fm_inner)
        if early is not None:
            return fail(fm_line + early[0].line, early[0].column + 1, early[1], "limit")
        meta = yaml.safe_load(parsed.fm_inner)
    except yaml.MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        line = fm_line + (mark.line if mark else 0)
        return fail(line, (mark.column + 1) if mark else 1,
                    f"frontmatter is not valid YAML: {e.problem or e}", "yaml")
    except yaml.YAMLError as e:
        return fail(fm_line, 1, f"frontmatter is not valid YAML: {e}", "yaml")
    except RecursionError:
        return fail(fm_line, 1, "frontmatter is nested too deeply", "limit")
    except (ValueError, OverflowError) as e:
        # SafeConstructor raises these for e.g. 2026-02-30, a >4300-digit int
        # or an overflowing sexagesimal float.
        return fail(fm_line, 1, f"frontmatter has a value YAML cannot read: {e}", "yaml")
    if not isinstance(meta, dict) or not isinstance(meta.get("template"), dict):
        return fail(fm_line, 1, "frontmatter needs a `template:` mapping", "no-template")
    problem = _tree_problem(meta)
    if problem is not None:
        return fail(fm_line, 1, problem, "limit")
    root = _compose(parsed.fm_inner)
    for key in meta:
        if key != "template":
            line, col = _locate(root, (key,), fm_line)
            diags.append(Diagnostic(line, col, "warning",
                                    f"top-level key `{key}` is ignored; note frontmatter goes "
                                    "under template.frontmatter", "ignored-key"))
    try:
        model = _TemplateModel.model_validate(_with_source_spelling(meta["template"], root))
    except ValidationError as e:
        errors = []
        for err in e.errors():
            loc = ("template", *err["loc"])
            line, col = _locate(root, loc, fm_line)
            where = ".".join(str(p) for p in loc)
            errors.append(Diagnostic(line, col, "error", f"{where}: {err['msg']}", "schema"))
        return ParseResult(None, _capped([*diags, *errors]))

    errors = []
    seen: set[str] = set()
    for i, p in enumerate(model.prompts):
        loc = ("template", "prompts", i, "id")
        message = None
        if p.id in seen:
            message = f"duplicate prompt id `{p.id}`"
        elif p.id in RESERVED_IDS:
            message = f"`{p.id}` is a built-in variable; pick another id"
        elif p.id in SHADOWABLE and SHADOWABLE[p.id] != p.type:
            message = f"a prompt with id `{p.id}` must have type {SHADOWABLE[p.id]}"
        seen.add(p.id)
        if message:
            line, col = _locate(root, loc, fm_line)
            errors.append(Diagnostic(line, col, "error", message, "prompt-id"))

    file_name = model.file.name or "{{date | format: YYYY-MM-DD}} " + model.name
    variables: set[str] = set()
    try:
        for text in (model.file.folder, file_name, parsed.body, *_strings(model.frontmatter)):
            for seg in tokenize(text):
                if isinstance(seg, Placeholder) and seg.path:
                    variables.add(seg.path[0])
    except TemplateLimitError as e:
        errors.append(Diagnostic(body_line, 1, "error", str(e), "limit"))
    if errors:
        return ParseResult(None, _capped([*diags, *errors]))

    prompts = tuple(
        Prompt(p.id, p.ask, p.type, p.optional, p.default, tuple(p.options or ()))
        for p in model.prompts
    )
    template = Template(
        id=template_id,
        name=model.name,
        description=model.description,
        prompts=prompts,
        file=FileSpec(model.file.folder, file_name),
        frontmatter=model.frontmatter,
        body=parsed.body,
        body_line=body_line,
        variables=tuple(sorted(variables)),
    )
    return ParseResult(template, _capped(diags))
