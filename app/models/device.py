from datetime import datetime
from typing import Any, Optional, Literal

from pydantic import BaseModel, Field


DeviceType = Literal[
    "light",
    "fan",
    "air_conditioner",
    "television",
    "curtain",
    "window",
    "door",
    "exhaust_fan",
    "security_camera",
    "other",
]


class DeviceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    device_type: DeviceType
    room_id: str
    # Initial state – can be empty; we will set sensible defaults in the service
    initial_state: Optional[dict[str, Any]] = None


class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    # Used for normal property updates (name only for now)
    # State changes go through a dedicated endpoint


class DeviceStateUpdate(BaseModel):
    state: dict[str, Any]


class DeviceResponse(BaseModel):
    id: str
    house_id: str
    room_id: str
    name: str
    device_type: DeviceType
    state: dict[str, Any]
    created_at: datetime
    updated_at: datetime
