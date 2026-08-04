"""Recorder control schemas."""
from typing import Literal

from pydantic import BaseModel, Field

# Phase progression for a manual recording session:
#   idle → recording → transcribing → done → (UI clears, back to idle)
# A calendar-driven recording reports phase=recording, owner=daemon and
# bypasses the manual flow entirely.
RecorderPhase = Literal["idle", "recording", "transcribing", "done"]
RecorderOwner = Literal["manual", "daemon"]


class StartRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    context: str | None = Field(default=None, max_length=80)


class RecorderStatus(BaseModel):
    phase: RecorderPhase
    owner: RecorderOwner | None = None
    title: str | None = None
    startedAt: str | None = None
    wavPath: str | None = None
    transcriptPath: str | None = None  # vault-relative once transcribed
    error: str | None = None
