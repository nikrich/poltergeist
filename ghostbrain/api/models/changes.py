"""Change-log request schemas (spec B §5, slice B2)."""
from pydantic import BaseModel

STATUS_PATTERN = r"^(applied|pending|reverted|rejected|conflicted)$"


class ChangeActionRequest(BaseModel):
    force: bool = False
