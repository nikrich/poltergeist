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
