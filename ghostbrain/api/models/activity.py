"""Activity row schema."""
from pydantic import BaseModel, ConfigDict


class ActivityRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    verb: str
    subject: str
    atRelative: str
    at: str
