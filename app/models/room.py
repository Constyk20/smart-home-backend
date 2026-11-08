from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field


RoomType = Literal[
    "living_room",
    "bedroom",
    "kitchen",
    "bathroom",
    "entrance",
    "outdoor",
    "other",
]


class RoomCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    room_type: RoomType = "other"
    description: Optional[str] = Field(default=None, max_length=300)


class RoomUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    room_type: Optional[RoomType] = None
    description: Optional[str] = Field(default=None, max_length=300)


class RoomResponse(BaseModel):
    id: str
    house_id: str
    name: str
    room_type: RoomType
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
