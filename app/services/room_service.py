from datetime import datetime, timezone
from typing import List

from bson import ObjectId
from fastapi import HTTPException, status

from app.db.mongodb import get_database
from app.models.room import RoomCreate, RoomUpdate, RoomResponse
from app.services.house_service import get_house_by_id


def _to_room_response(doc: dict) -> RoomResponse:
    return RoomResponse(
        id=str(doc["_id"]),
        house_id=str(doc["house_id"]),
        name=doc["name"],
        room_type=doc["room_type"],
        description=doc.get("description"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


async def create_room(house_id: str, owner_id: str, data: RoomCreate) -> RoomResponse:
    # Verify ownership first
    await get_house_by_id(house_id, owner_id)

    db = get_database()
    now = datetime.now(timezone.utc)
    doc = {
        "house_id": ObjectId(house_id),
        "name": data.name,
        "room_type": data.room_type,
        "description": data.description,
        "created_at": now,
        "updated_at": now,
    }
    result = await db["rooms"].insert_one(doc)
    created = await db["rooms"].find_one({"_id": result.inserted_id})
    return _to_room_response(created)


async def get_rooms_for_house(house_id: str, owner_id: str) -> List[RoomResponse]:
    await get_house_by_id(house_id, owner_id)

    db = get_database()
    cursor = db["rooms"].find({"house_id": ObjectId(house_id)}).sort("name", 1)
    rooms = []
    async for doc in cursor:
        rooms.append(_to_room_response(doc))
    return rooms


async def get_room_by_id(room_id: str, owner_id: str) -> RoomResponse:
    db = get_database()
    try:
        oid = ObjectId(room_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid room ID")

    doc = await db["rooms"].find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

    # Ownership check via the house
    await get_house_by_id(str(doc["house_id"]), owner_id)
    return _to_room_response(doc)


async def update_room(room_id: str, owner_id: str, data: RoomUpdate) -> RoomResponse:
    db = get_database()
    try:
        oid = ObjectId(room_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid room ID")

    existing = await db["rooms"].find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

    await get_house_by_id(str(existing["house_id"]), owner_id)

    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items()}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    update_data["updated_at"] = datetime.now(timezone.utc)

    result = await db["rooms"].find_one_and_update(
        {"_id": oid},
        {"": update_data},
        return_document=True,
    )
    return _to_room_response(result)


async def delete_room(room_id: str, owner_id: str) -> None:
    db = get_database()
    try:
        oid = ObjectId(room_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid room ID")

    existing = await db["rooms"].find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

    await get_house_by_id(str(existing["house_id"]), owner_id)

    # Also delete devices that belong to this room
    await db["devices"].delete_many({"room_id": oid})
    await db["rooms"].delete_one({"_id": oid})
