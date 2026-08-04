"""Agenda schemas."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgendaStatus = Literal["upcoming", "recorded"]


class AgendaItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    time: str
    duration: str
    title: str
    with_: list[str] = Field(alias="with")
    status: AgendaStatus
