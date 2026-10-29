from datetime import datetime
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class JobCreate(BaseModel):
    url: AnyHttpUrl
    payload: dict[str, Any]

    model_config = ConfigDict(extra="forbid")


class JobCreated(BaseModel):
    id: str
    status: str


class JobDetails(BaseModel):
    id: str
    status: str
    attempts: int
    next_retry_at: datetime | None
