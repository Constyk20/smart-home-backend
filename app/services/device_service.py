from datetime import datetime, timezone
from typing import Any, List

from bson import ObjectId
from fastapi import HTTPException, status

from app.core.realtime import manager
from app.db.mongodb import get_database
from app.models.device import DeviceCreate, DeviceResponse, DeviceStateUpdate, DeviceUpdate
from app.services.activity_service import log_activity
from app.services.energy_service import record_power_transition
from app.services.house_service import get_house_by_id
from app.services.room_service import get_room_by_id


DEFAULT_STATES: dict[str, dict[str, Any]] = {
    "light": {"is_on": False, "brightness": 100},
    "fan": {"is_on": False, "speed": 1},
    "air_conditioner": {"is_on": False, "target_temp": 24, "mode": "cool"},
    "television": {"is_on": False, "volume": 20, "channel": 1},
    "curtain": {"is_open": False, "position": 0},
    "window": {"is_open": False},
    "door": {"is_open": False, "is_locked": True},
    "exhaust_fan": {"is_on": False, "speed": 1},
    "security_camera": {"is_on": True, "recording": False},
    "other": {"is_on": False},
}


def _to_device_response(doc: dict) -> DeviceResponse:
    return DeviceResponse(
        id=str(doc["_id"]),
        house_id=str(doc["house_id"]),
        room_id=str(doc["room_id"]),
        name=doc["name"],
        device_type=doc["device_type"],
        state=doc.get("state", {}),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


async def create_device(owner_id: str, data: DeviceCreate) -> DeviceResponse:
    room = await get_room_by_id(data.room_id, owner_id)
    db = get_database()
    now = datetime.now(timezone.utc)
    state = data.initial_state if data.initial_state is not None else DEFAULT_STATES.get(
        data.device_type, {"is_on": False}
    )
    on_since = now if state.get("is_on") else None
    doc = {
        "house_id": ObjectId(room.house_id),
        "room_id": ObjectId(data.room_id),
        "name": data.name,
        "device_type": data.device_type,
        "state": state,
        "on_since": on_since,
        "created_at": now,
        "updated_at": now,
    }
    result = await db["devices"].insert_one(doc)
    created = await db["devices"].find_one({"_id": result.inserted_id})
    await log_activity(
        user_id=owner_id,
        house_id=str(created["house_id"]),
        room_id=str(created["room_id"]),
        device_id=str(created["_id"]),
        action="device_created",
        message=f"Created device '{data.name}' ({data.device_type})",
        payload={"device_type": data.device_type, "state": state},
    )
    return _to_device_response(created)


async def get_devices_for_house(house_id: str, owner_id: str) -> List[DeviceResponse]:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    cursor = db["devices"].find({"house_id": ObjectId(house_id)}).sort("name", 1)
    return [_to_device_response(doc) async for doc in cursor]


async def get_devices_for_room(room_id: str, owner_id: str) -> List[DeviceResponse]:
    await get_room_by_id(room_id, owner_id)
    db = get_database()
    cursor = db["devices"].find({"room_id": ObjectId(room_id)}).sort("name", 1)
    return [_to_device_response(doc) async for doc in cursor]


async def get_device_by_id(device_id: str, owner_id: str) -> DeviceResponse:
    db = get_database()
    try:
        oid = ObjectId(device_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid device ID")
    doc = await db["devices"].find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    await get_house_by_id(str(doc["house_id"]), owner_id)
    return _to_device_response(doc)


async def update_device(device_id: str, owner_id: str, data: DeviceUpdate) -> DeviceResponse:
    db = get_database()
    try:
        oid = ObjectId(device_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid device ID")
    existing = await db["devices"].find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    await get_house_by_id(str(existing["house_id"]), owner_id)
    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items()}
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    update_data["updated_at"] = datetime.now(timezone.utc)
    result = await db["devices"].find_one_and_update(
        {"_id": oid},
        {"$set": update_data},
        return_document=True,
    )
    return _to_device_response(result)


async def update_device_state(device_id: str, owner_id: str, data: DeviceStateUpdate) -> DeviceResponse:
    db = get_database()
    try:
        oid = ObjectId(device_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid device ID")
    existing = await db["devices"].find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    await get_house_by_id(str(existing["house_id"]), owner_id)
    on_since = await record_power_transition(existing, data.state)
    now = datetime.now(timezone.utc)
    result = await db["devices"].find_one_and_update(
        {"_id": oid},
        {"$set": {"state": data.state, "on_since": on_since, "updated_at": now}},
        return_document=True,
    )
    await log_activity(
        user_id=owner_id,
        house_id=str(result["house_id"]),
        room_id=str(result["room_id"]),
        device_id=str(result["_id"]),
        action="device_state_changed",
        message=f"Changed state of '{result['name']}'",
        payload={"new_state": data.state},
    )
    await manager.broadcast(
        str(result["house_id"]),
        "device_state_changed",
        {
            "device_id": str(result["_id"]),
            "name": result.get("name"),
            "state": result.get("state", {}),
        },
    )
    return _to_device_response(result)


async def delete_device(device_id: str, owner_id: str) -> None:
    db = get_database()
    try:
        oid = ObjectId(device_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid device ID")
    existing = await db["devices"].find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    await get_house_by_id(str(existing["house_id"]), owner_id)
    await db["devices"].delete_one({"_id": oid})