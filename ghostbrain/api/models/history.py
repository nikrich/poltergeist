"""Page-history request schemas (spec A3)."""
from pydantic import BaseModel, Field

BLOB_PATTERN = r"^[0-9a-f]{64}$"


class RestoreRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)  # vault-relative
    blob: str = Field(pattern=BLOB_PATTERN)
