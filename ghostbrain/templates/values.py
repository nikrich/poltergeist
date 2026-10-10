"""Typed values the template language works with, and their text forms."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

SLUG_MAX = 32  # notes_manual.make_slug parity (tests/test_templates_functions.py)
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_FORMAT_RE = re.compile(r"\[([^\]]*)\]|YYYY|YY|MMMM|MMM|MM|M|DD|D|dddd|ddd|HH|H|mm|ss")


@dataclass(frozen=True)
class DateValue:
    value: date


@dataclass(frozen=True)
class DateTimeValue:
    value: datetime


@dataclass(frozen=True)
class PersonValue:
    name: str
    path: str  # vault-relative .md path, or "" for a typed name with no page

    @property
    def link(self) -> str:
        target = self.path.removesuffix(".md")
        return f"[[{target or self.name}]]"


@dataclass(frozen=True)
class ProjectValue:
    id: str
    name: str
    slug: str
    context: str

    @property
    def path(self) -> str:
        return f"20-contexts/{self.context}/projects/{self.slug}"


@dataclass(frozen=True)
class UserValue:
    name: str


class EmptyValue:
    """An unanswered optional prompt: renders "", and so does every field of it."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "EMPTY"

    def __bool__(self) -> bool:
        return False


EMPTY = EmptyValue()
Value = str | DateValue | DateTimeValue | PersonValue | ProjectValue | UserValue | EmptyValue


def value_type(value: Value) -> str:
    if isinstance(value, str):
        return "text"
    if isinstance(value, DateValue):
        return "date"
    if isinstance(value, DateTimeValue):
        return "datetime"
    if isinstance(value, PersonValue):
        return "person"
    if isinstance(value, ProjectValue):
        return "project"
    if isinstance(value, UserValue):
        return "user"
    return "empty"


def to_text(value: Value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, DateValue):
        return value.value.isoformat()
    if isinstance(value, DateTimeValue):
        return value.value.isoformat(timespec="minutes")
    if isinstance(value, (PersonValue, ProjectValue, UserValue)):
        return value.name
    return ""


def format_date(value: date, pattern: str) -> str:
    """Moment-style tokens, English names; ``[text]`` is literal."""
    if isinstance(value, datetime):
        hour, minute, second = value.hour, value.minute, value.second
    else:
        hour = minute = second = 0
    month, day = _MONTHS[value.month - 1], _DAYS[value.weekday()]
    table = {
        "YYYY": f"{value.year:04d}", "YY": f"{value.year % 100:02d}",
        "MMMM": month, "MMM": month[:3], "MM": f"{value.month:02d}", "M": str(value.month),
        "DD": f"{value.day:02d}", "D": str(value.day), "dddd": day, "ddd": day[:3],
        "HH": f"{hour:02d}", "H": str(hour), "mm": f"{minute:02d}", "ss": f"{second:02d}",
    }

    def sub(m: re.Match[str]) -> str:
        if m.group(1) is not None:
            return m.group(1)
        return table[m.group(0)]

    return _FORMAT_RE.sub(sub, pattern)


def slugify(text: str, max_len: int = SLUG_MAX) -> str:
    """make_slug's rules: lower-case, non-alnum runs → '-', 'untitled' when empty."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not s:
        return "untitled"
    return s[:max_len].rstrip("-") or "untitled"
