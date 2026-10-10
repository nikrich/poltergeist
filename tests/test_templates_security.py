"""Adversarial templates: the template language is a security boundary
(C4 lets the AI write templates). A template must not execute code, read
files outside the vault, recurse without bound, or produce a path that
escapes the vault."""
from __future__ import annotations

import os
import re
import time
from datetime import datetime as _dt
from datetime import timedelta as _td
from datetime import timezone as _tz
from pathlib import Path

import pytest
import yaml as _yaml

from ghostbrain.templates.lang import (
    MAX_PLACEHOLDERS,
    MAX_TEMPLATE_CHARS,
    Placeholder,
    TemplateLimitError,
    Text,
    tokenize,
)
from ghostbrain.templates.parse import parse_template
from ghostbrain.templates.registry import (
    TemplateNotFound,
    list_templates,
    load_template,
    read_template_source,
)
from ghostbrain.templates.render import (
    MAX_OUTPUT_CHARS,
    AnswerError,
    RenderEnv,
    RenderError,
    render,
    validate_folder,
)

PKG = Path(__file__).resolve().parents[1] / "ghostbrain" / "templates"
FORBIDDEN = [
    re.compile(r"\beval\("),
    re.compile(r"\bexec\("),
    re.compile(r"(?<![.\w])compile\("),
    re.compile(r"__import__"),
    re.compile(r"\bgetattr\("),
    re.compile(r"\bsetattr\("),
    re.compile(r"\bimportlib\b"),
    re.compile(r"\bsubprocess\b"),
    re.compile(r"\bpickle\b"),
    re.compile(r"\bjinja2\b"),
    re.compile(r"yaml\.(?:load|unsafe_load|full_load)\("),
    re.compile(r"Loader=yaml\.(?:Loader|FullLoader|UnsafeLoader)\b"),
]


def test_sec_engine_source_has_no_dynamic_execution():
    assert PKG.is_dir()
    offenders = []
    for f in sorted(PKG.glob("*.py")):
        text = f.read_text(encoding="utf-8")
        for pat in FORBIDDEN:
            if pat.search(text):
                offenders.append(f"{f.name}: {pat.pattern}")
    assert offenders == []


@pytest.mark.parametrize(
    "src",
    [
        "{{ __import__('os').system('touch pwned') }}",
        "{{ person.__class__ }}",
        "{{ person.__class__.__mro__ }}",
        "{{ ''.join }}",
        "{{ date() }}",
        "{{ items[0] }}",
        "{{ a + b }}",
        "{{ open('/etc/passwd') }}",
    ],
)
def test_sec_code_like_expressions_never_parse(src):
    segs = tokenize(src)
    assert all(isinstance(s, Text) or s.path is None for s in segs)


def test_sec_placeholder_count_is_capped():
    with pytest.raises(TemplateLimitError):
        tokenize("{{x}}" * (MAX_PLACEHOLDERS + 1))


def test_sec_source_size_is_capped():
    with pytest.raises(TemplateLimitError):
        tokenize("a" * (MAX_TEMPLATE_CHARS + 1))


def test_sec_pathological_braces_finish_fast():
    start = time.monotonic()
    segs = tokenize("{" * 200_000)
    assert time.monotonic() - start < 2.0
    assert segs == [Text("{" * 200_000)]


def test_sec_many_placeholders_on_one_line_finish_fast():
    src = "x" * 100_000 + "{{a}}" * MAX_PLACEHOLDERS
    start = time.monotonic()
    segs = tokenize(src)
    assert time.monotonic() - start < 2.0
    assert sum(isinstance(s, Placeholder) for s in segs) == MAX_PLACEHOLDERS



BOMB = """---
a: &a ["x","x","x","x","x","x","x","x","x"]
b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]
c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]
d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]
e: &e [*d,*d,*d,*d,*d,*d,*d,*d,*d]
f: &f [*e,*e,*e,*e,*e,*e,*e,*e,*e]
g: &g [*f,*f,*f,*f,*f,*f,*f,*f,*f]
template:
  name: Bomb
  frontmatter:
    boom: *g
---
"""


def test_sec_yaml_python_tags_do_not_execute(monkeypatch):
    import os

    monkeypatch.setattr(os, "system", lambda *_a, **_k: pytest.fail("os.system ran"))
    r = parse_template("---\ntemplate: !!python/object/apply:os.system ['echo pwned']\n---\n", "x")
    assert not r.ok and r.diagnostics[0].code == "yaml"


def test_sec_yaml_alias_bomb_is_rejected_fast():
    start = time.monotonic()
    r = parse_template(BOMB, "bomb")
    assert time.monotonic() - start < 2.0
    assert not r.ok and r.diagnostics[0].code == "limit"


def test_sec_recursive_yaml_is_rejected():
    src = "---\ntemplate:\n  name: Loop\n  frontmatter:\n    me: &me [*me]\n---\n"
    r = parse_template(src, "loop")
    assert not r.ok and r.diagnostics[0].code == "limit"


def test_sec_deeply_nested_yaml_does_not_crash():
    src = "---\ntemplate:\n  name: Deep\n  frontmatter:\n    x: " + "[" * 3000 + "]" * 3000 + "\n---\n"
    start = time.monotonic()
    r = parse_template(src, "deep")
    assert time.monotonic() - start < 1.0
    assert not r.ok and r.diagnostics[0].code in ("yaml", "limit")


def test_sec_oversized_source_is_a_diagnostic_not_a_crash():
    r = parse_template("---\ntemplate:\n  name: Big\n---\n" + "a" * MAX_TEMPLATE_CHARS, "big")
    assert not r.ok and r.diagnostics[0].code == "limit"


def test_sec_yaml_merge_key_bomb_is_rejected_fast():
    lines = ["a0: &a0 {" + ", ".join(f"k{i}: {i}" for i in range(9)) + "}"]
    for n in range(1, 8):
        lines.append(f"a{n}: &a{n} {{<<: [" + ", ".join([f"*a{n - 1}"] * 9) + "]}")
    src = "---\n" + "\n".join(lines) + "\ntemplate:\n  name: Merge\n---\n"
    start = time.monotonic()
    r = parse_template(src, "merge")
    assert time.monotonic() - start < 1.0
    assert not r.ok and r.diagnostics[0].code == "limit"
    assert r.diagnostics[0].line == 2


def test_sec_aliased_strings_finish_fast():
    blob = "{{x}} " * 4_000
    refs = "\n".join(f"    k{i}: *s" for i in range(800))
    src = f"---\ns: &s \"{blob}\"\ntemplate:\n  name: Blob\n  frontmatter:\n{refs}\n---\n"
    start = time.monotonic()
    r = parse_template(src, "blob")
    assert time.monotonic() - start < 2.0
    assert not r.ok and r.diagnostics[0].code == "limit"


def test_sec_many_schema_errors_finish_fast():
    extra = "\n".join(f"  extra{i}: 1" for i in range(2_000))
    start = time.monotonic()
    r = parse_template(f"---\ntemplate:\n  name: X\n{extra}\n---\n", "x")
    assert time.monotonic() - start < 2.0
    assert not r.ok and len(r.diagnostics) <= 21
    assert "more" in r.diagnostics[-1].message


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-30",
        "2026-13-45",
        "9" * 5_000,
        "1" + ":59" * 5_000,
        "1" + ":59" * 2_000 + ".5",
        "!!bool maybe",
        "!!timestamp foo",
        "!!int ''",
    ],
    ids=[
        "bad-date", "month-13", "5000-digit-int", "long-sexagesimal", "sexagesimal-float",
        "bool-tag", "timestamp-tag", "empty-int-tag",
    ],
)
def test_sec_unconstructable_scalars_are_a_diagnostic(value):
    src = f"---\ntemplate:\n  name: X\n  frontmatter:\n    v: {value}\n---\n"
    start = time.monotonic()
    r = parse_template(src, "x")
    assert time.monotonic() - start < 1.0
    assert not r.ok and r.diagnostics[0].code in ("yaml", "limit")
    assert r.diagnostics[0].line == 2


def test_sec_huge_flow_list_is_rejected_fast():
    src = "---\ntemplate:\n  name: X\n  frontmatter:\n    v: [" + "1," * 120_000 + "1]\n---\n"
    assert len(src) < MAX_TEMPLATE_CHARS
    start = time.monotonic()
    r = parse_template(src, "x")
    assert time.monotonic() - start < 0.5
    assert not r.ok and r.diagnostics[0].code == "limit"


@pytest.mark.parametrize(
    "value",
    ["!!set {a: null}", "!!binary aGVsbG8=", ".nan", "-.inf", "!!omap [{a: 1}]"],
    ids=["set", "binary", "nan", "inf", "omap"],
)
def test_sec_non_json_frontmatter_values_are_rejected(value):
    src = f"---\ntemplate:\n  name: X\n  frontmatter:\n    v: {value}\n---\n"
    r = parse_template(src, "x")
    assert not r.ok and r.diagnostics[0].code == "limit"


def test_sec_early_limit_reports_the_column():
    r = parse_template("---\ntemplate:\n  name: X\n  frontmatter:\n    v: &a 1\n---\n", "x")
    d = r.diagnostics[0]
    assert d.code == "limit" and (d.line, d.col) == (5, 8)


@pytest.mark.parametrize("value", ["!!bool maybe", "!!timestamp foo", "!!int ''", "2026-02-30"])
def test_sec_unconstructable_prompt_defaults_are_a_diagnostic(value):
    src = (
        "---\ntemplate:\n  name: X\n  prompts:\n    - id: s\n      ask: S\n"
        f"      type: choice\n      options: [{value}]\n      default: {value}\n---\n"
    )
    r = parse_template(src, "x")
    assert not r.ok and r.diagnostics[0].code == "yaml"


_ENV = RenderEnv(now=_dt(2026, 10, 9, 14, 30, tzinfo=_tz(_td(hours=2))),
                 default_context="work", contexts=("work",))


def _t(folder: str, body: str = "x", name: str = "n"):
    src = (
        "---\ntemplate:\n  name: Evil\n  prompts:\n    - id: focus\n      ask: F\n      type: text\n"
        f"      optional: true\n  file:\n    folder: {_yaml.safe_dump(folder).splitlines()[0]}\n"
        f"    name: {_yaml.safe_dump(name).splitlines()[0]}\n---\n{body}"
    )
    r = parse_template(src, "evil")
    assert r.ok, r.diagnostics
    return r.template


@pytest.mark.parametrize(
    "folder, answer",
    [
        ("../../etc", ""),
        ("/etc", ""),
        ("20-contexts/../../..", ""),
        ("20-contexts/{{focus}}", "../../outside"),
        ("20-contexts/{{focus}}", "a\\..\\..\\b"),
        ("C:/Windows", ""),
        ("20-contexts/x:stream", ""),
        ("90-meta/templates", ""),
        ("90-META/prompts", ""),
        ("80-profile", ""),
        ("80-Profile/about", ""),
        ("{{focus}}/x", "80-PROFILE"),
        ("20-contexts/.git", ""),
        ("20-contexts/CON", ""),
        ("20-contexts/{{nope}}", ""),
        ("20-contexts/{{focus}}", "line\nbreak"),
        ("{{focus}}", "   "),
        ("a/b/c/d/e/f/g/h/i/j/k", ""),
        # URL-encoded traversal and separators are rejected, not filed literally.
        ("20-contexts/%2e%2e/%2e%2e", ""),
        ("20-contexts/{{focus}}", "%2E%2E%2Fetc"),
        ("20-contexts/a%2Fb", ""),
        ("20-contexts/a%5cb", ""),
        # Absolute, backslash, drive letter, dot segments, NUL, leading dots.
        ("{{focus}}", "/etc/passwd"),
        ("{{focus}}", "\\\\server\\share"),
        ("{{focus}}", "D:relative"),
        ("20-contexts/./x", ""),
        ("20-contexts/{{focus}}", ".."),
        ("20-contexts/{{focus}}", "a\x00b"),
        ("20-contexts/.hidden", ""),
        (".obsidian/plugins", ""),
        # Windows 8.3 short names resolve to protected or hidden folders.
        ("80-PRO~1/x", ""),
        ("{{focus}}", "OBSIDI~1"),
        # Trailing dots / spaces are dropped by Windows, so 90-meta. == 90-meta.
        ("90-meta.", ""),
        ("90-meta ", ""),
        ("90-meta./x", ""),
        ("90-meta /x", ""),
        ("20-contexts/COM\u00b9", ""),
        ("20-contexts/{{focus}}", "lpt\u00b2.txt"),
        ("20-contexts/{{focus}}", "a\u2028b"),
    ],
)
def test_sec_rendered_folder_cannot_escape_or_hit_system_areas(folder, answer):
    with pytest.raises(RenderError):
        render(_t(folder), {"focus": answer} if answer else {}, _ENV)


def test_sec_validate_folder_keeps_safe_paths_and_a_lone_percent():
    assert validate_folder("20-contexts/work/one-on-ones") == "20-contexts/work/one-on-ones"
    assert validate_folder("20-contexts/work/100% done/") == "20-contexts/work/100% done"
    assert validate_folder("30-cross-context/80-profile") == "30-cross-context/80-profile"


def test_sec_file_name_cannot_carry_a_path():
    note = render(_t("20-contexts/work", name="../../evil/{{focus}}"), {"focus": "../x"}, _ENV)
    assert note.path == "20-contexts/work/evil-x.md"


def test_sec_answers_are_never_re_expanded():
    note = render(_t("20-contexts/work", body="{{focus}}"), {"focus": "{{user.name}} {{date}}"}, _ENV)
    assert note.body == "{{user.name}} {{date}}"


def test_sec_answers_cannot_inject_frontmatter_keys():
    src = (
        "---\ntemplate:\n  name: Inj\n  prompts:\n    - id: focus\n      ask: F\n      type: text\n"
        "  frontmatter:\n    summary: \"{{focus}}\"\n---\nbody\n"
    )
    t = parse_template(src, "inj").template
    from ghostbrain.vault_write.text import parse_note

    note = render(t, {"focus": "x\nevil: true\n---\ninjected"}, _ENV)
    parsed = parse_note(note.markdown())  # the same fence finder the write path uses
    data = _yaml.safe_load(parsed.fm_inner)
    assert "evil" not in data and data["summary"] == "x\nevil: true\n---\ninjected"
    assert parsed.body == "body\n"


def test_sec_output_size_is_capped():
    body = "{{focus}}" * 200
    with pytest.raises(RenderError):
        render(_t("20-contexts/work", body=body), {"focus": "x" * 10_000}, _ENV)
    assert 200 * 10_000 > MAX_OUTPUT_CHARS


def test_sec_person_path_answers_cannot_traverse():
    src = "---\ntemplate:\n  name: P\n  prompts:\n    - id: person\n      ask: W\n      type: person\n---\n{{person.link}}"
    t = parse_template(src, "p").template
    for bad in ("../../etc/passwd", "/etc/passwd", "30-cross-context/../../x", "C:/x", ".hidden/x", "a\\b",
                "30-cross-context/people/a\x00b.md"):
        with pytest.raises(AnswerError):
            render(t, {"person": bad}, _ENV)


@pytest.mark.parametrize(
    "bad",
    [
        "30-cross-context/people/alex]] [[evil",
        "30-cross-context/people/[[x",
        "30-cross-context/people/a|b",
        "30-cross-context/people/a#heading",
        "30-cross-context/people/a\nb",
        "30-cross-context/people/a\rb.md",
        "alex]]evil.md",
        "30-cross-context/people/a\tb",
        "30-cross-context/people/a\x85b",
        "30-cross-context/people/a\u2028b",
        "Al\u2029ex",
        "Al\x00ex",
    ],
)
def test_sec_person_path_answers_cannot_inject_markup(bad):
    src = "---\ntemplate:\n  name: P\n  prompts:\n    - id: person\n      ask: W\n      type: person\n---\n{{person.link}}"
    t = parse_template(src, "p").template
    with pytest.raises(AnswerError) as e:
        render(t, {"person": bad}, _ENV)
    assert e.value.field == "person"


def test_sec_person_lookup_uses_the_env_lookup():
    """Person names come from the in-memory link index only."""
    seen: list[str] = []
    env = RenderEnv(now=_ENV.now, default_context="work", contexts=("work",),
                    person_title=lambda p: seen.append(p) or None)
    src = "---\ntemplate:\n  name: P\n  prompts:\n    - id: person\n      ask: W\n      type: person\n---\n{{person.name}}"
    t = parse_template(src, "p").template
    assert render(t, {"person": "30-cross-context/people/alex"}, env).body == "Alex"
    assert seen == ["30-cross-context/people/alex.md"]


def test_sec_person_path_into_system_area_is_only_a_link(monkeypatch):
    """A person answer naming 90-meta/config yields a link; no file is opened."""
    import builtins
    import pathlib

    def no_io(*_a, **_k):
        raise AssertionError("render must not touch the filesystem")

    monkeypatch.setattr(builtins, "open", no_io)
    monkeypatch.setattr(pathlib.Path, "open", no_io)
    monkeypatch.setattr(pathlib.Path, "read_text", no_io)
    monkeypatch.setattr(pathlib.Path, "read_bytes", no_io)
    seen: list[str] = []
    env = RenderEnv(now=_ENV.now, default_context="work", contexts=("work",),
                    person_title=lambda p: seen.append(p) or None)
    t = parse_template(
        "---\ntemplate:\n  name: P\n  prompts:\n    - id: person\n      ask: W\n      type: person\n"
        "---\n{{person.link}} {{person.name}}", "p").template
    assert render(t, {"person": "90-meta/config"}, env).body == "[[90-meta/config]] Config"
    assert seen == ["90-meta/config.md"]


@pytest.mark.parametrize("title", ["con", "NUL", "Aux", "com1", "LPT9", "prn"])
def test_sec_filename_is_never_a_windows_device_name(title):
    note = render(_t("20-contexts/work", name="{{focus}}"), {"focus": title}, _ENV)
    assert note.filename == f"{title.lower()}-note.md"
    assert note.title == title


def test_sec_device_like_titles_that_are_not_devices_keep_their_slug():
    for title, filename in (("console", "console.md"), ("com10", "com10.md"), ("con x", "con-x.md")):
        assert render(_t("20-contexts/work", name="{{focus}}"), {"focus": title}, _ENV).filename == filename


_OK_TPL = "---\ntemplate:\n  name: Outside\n---\nsecret body\n"


def _symlink(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")


@pytest.mark.parametrize("bad_id", ["../secret", "..", "a/b", "A", ".hidden", "x" * 65, "", "secret.md"])
def test_sec_template_ids_cannot_traverse(tmp_path, bad_id):
    vault = tmp_path / "vault"
    (vault / "90-meta/templates").mkdir(parents=True)
    (vault / "90-meta/secret.md").write_text(_OK_TPL, encoding="utf-8")
    with pytest.raises(TemplateNotFound):
        load_template(bad_id, vault)
    with pytest.raises(TemplateNotFound):
        read_template_source(bad_id, vault)


def test_sec_symlinked_template_file_is_never_read(tmp_path):
    vault = tmp_path / "vault"
    (vault / "90-meta/templates").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text(_OK_TPL, encoding="utf-8")
    _symlink(outside, vault / "90-meta/templates/outside.md")
    assert [i.id for i in list_templates(vault)] == []
    with pytest.raises(TemplateNotFound):
        read_template_source("outside", vault)


def test_sec_symlinked_templates_folder_outside_vault_is_ignored(tmp_path):
    vault = tmp_path / "vault"
    (vault / "90-meta").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "outside.md").write_text(_OK_TPL, encoding="utf-8")
    _symlink(elsewhere, vault / "90-meta/templates")
    assert list_templates(vault) == []
    with pytest.raises(TemplateNotFound):
        load_template("outside", vault)
