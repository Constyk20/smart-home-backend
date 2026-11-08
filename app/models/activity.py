from datetime import datetime
from typing import Any, Optional, Literal

from pydantic import BaseModel, Field


ActionType = Literal[
    "house_created",
    "house_updated",
    "house_deleted",
    "room_created",
    "room_updated",
    "room_deleted",
    "device_created",
    "device_updated",
    "device_state_changed",
    "device_deleted",
    "user_login",
    "other",
]


class ActivityLogResponse(BaseModel):
    id: str
    user_id: str
    house_id: Optional[str] = None
    room_id: Optional[str] = None
    device_id: Optional[str] = None
    action: ActionType
    message: str
    payload: Optional[dict[str, Any]] = None
    created_at: datetime
