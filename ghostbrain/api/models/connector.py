"""Connector schema."""
from typing import Literal

from pydantic import BaseModel, ConfigDict

ConnectorState = Literal["on", "off", "err"]


class Connector(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    displayName: str
    state: ConnectorState
    count: int
    lastSyncAt: str | None
    account: str | None
    throughput: str | None
    error: str | None


class ConnectorDetail(Connector):
    scopes: list[str]
    pulls: list[str]
    vaultDestination: str
