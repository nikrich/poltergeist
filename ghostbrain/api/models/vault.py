"""Vault statistics."""
from pydantic import BaseModel, ConfigDict


class VaultStats(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totalNotes: int
    queuePending: int
    vaultSizeBytes: int
    lastSyncAt: str | None
    indexedCount: int
