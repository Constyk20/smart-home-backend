from datetime import datetime, timezone
from typing import List

from bson import ObjectId
from fastapi import HTTPException, status

from app.db.mongodb import get_database
from app.models.house import HouseCreate, HouseUpdate, HouseResponse
from app.services.activity_service import log_activity


def _to_house_response(doc: dict) -> HouseResponse:
    return HouseResponse(
        id=str(doc["_id"]),
        owner_id=str(doc["owner_id"]),
        name=doc["name"],
        description=doc.get("description"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


async def create_house(owner_id: str, data: HouseCreate) -> HouseResponse:
    db = get_database()
    now = datetime.now(timezone.utc)
    doc = {
        "owner_id": ObjectId(owner_id),
        "name": data.name,
        "description": data.description,
        "created_at": now,
        "updated_at": now,
    }
    result = await db["houses"].insert_one(doc)
    created = await db["houses"].find_one({"_id": result.inserted_id})

    await log_activity(
        user_id=owner_id,
        house_id=str(created["_id"]),
        action="house_created",
        message=f"Created house '{data.name}'",
        payload={"name": data.name},
    )
    return _to_house_response(created)


async def get_houses_for_user(owner_id: str) -> List[HouseResponse]:
    db = get_database()
    cursor = db["houses"].find({"owner_id": ObjectId(owner_id)}).sort("created_at", -1)
    houses = []
    async for doc in cursor:
        houses.append(_to_house_response(doc))
    return houses


async def get_house_by_id(house_id: str, owner_id: str) -> HouseResponse:
    db = get_database()
    try:
        oid = ObjectId(house_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid house ID")

    doc = await db["houses"].find_one({"_id": oid, "owner_id": ObjectId(owner_id)})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="House not found")
    return _to_house_response(doc)


async def update_house(house_id: str, owner_id: str, data: HouseUpdate) -> HouseResponse:
    db = get_database()
    try:
        oid = ObjectId(house_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid house ID")

    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items()}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    update_data["updated_at"] = datetime.now(timezone.utc)

    result = await db["houses"].find_one_and_update(
        {"_id": oid, "owner_id": ObjectId(owner_id)},
        {"": update_data},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="House not found")

    await log_activity(
        user_id=owner_id,
        house_id=house_id,
        action="house_updated",
        message=f"Updated house '{result['name']}'",
        payload=update_data,
    )
    return _to_house_response(result)


async def delete_house(house_id: str, owner_id: str) -> None:
    db = get_database()
    try:
        oid = ObjectId(house_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid house ID")

    # Also delete related rooms and devices (cascade)
    await db["rooms"].delete_many({"house_id": oid})
    await db["devices"].delete_many({"house_id": oid})

    result = await db["houses"].delete_one({"_id": oid, "owner_id": ObjectId(owner_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="House not found")

    await log_activity(
        user_id=owner_id,
        house_id=house_id,
        action="house_deleted",
        message="Deleted a house",
    )
