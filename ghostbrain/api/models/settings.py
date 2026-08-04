"""Vault-level user settings exposed to the desktop app."""
from pydantic import BaseModel, Field


class RecorderSettings(BaseModel):
    """Subset of `recorder:` in <vault>/90-meta/config.yaml that the
    meetings UI surfaces. Other recorder knobs (poll interval, audio
    devices) stay file-only for now."""

    enabled: bool = True
    excluded_titles: list[str] = Field(default_factory=lambda: ["Focus", "focus"])
    manual_context: str = "personal"


class UpdateRecorderSettings(BaseModel):
    """Partial update — any omitted field is left untouched in the file."""

    enabled: bool | None = None
    excluded_titles: list[str] | None = None
    manual_context: str | None = None
