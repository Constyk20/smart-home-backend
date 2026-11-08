from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    device_id: str
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    state: dict[str, Any]
    enabled: bool = True


class ScheduleResponse(BaseModel):
    id: str
    house_id: str
    device_id: str
    name: str
    time: str
    days: list[int]
    state: dict[str, Any]
    enabled: bool
    last_fired_key: Optional[str] = None
    created_at: datetime