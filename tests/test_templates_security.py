"""Adversarial templates: the template language is a security boundary
(C4 lets the AI write templates). A template must not execute code, read
files outside the vault, recurse without bound, or produce a path that
escapes the vault."""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from ghostbrain.templates.lang import (
    MAX_PLACEHOLDERS,
    MAX_TEMPLATE_CHARS,
    Placeholder,
    TemplateLimitError,
    Text,
    tokenize,
)
from ghostbrain.templates.parse import parse_template

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
    extra = "\n".join(f"  extra{i}: 1" for i in range(2_500))
    start = time.monotonic()
    r = parse_template(f"---\ntemplate:\n  name: X\n{extra}\n---\n", "x")
    assert time.monotonic() - start < 2.0
    assert not r.ok and len(r.diagnostics) <= 21
    assert "more" in r.diagnostics[-1].message
