from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException

from app.db.mongodb import get_database
from app.models.schedule import ScheduleCreate, ScheduleResponse
from app.services.activity_service import log_activity
from app.services.energy_service import LAGOS, record_power_transition
from app.services.house_service import get_house_by_id
from app.core.realtime import manager


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_schedule(doc: dict) -> ScheduleResponse:
    return ScheduleResponse(
        id=str(doc["_id"]),
        house_id=str(doc["house_id"]),
        device_id=str(doc["device_id"]),
        name=doc["name"],
        time=doc["time"],
        days=doc.get("days", []),
        state=doc.get("state", {}),
        enabled=doc.get("enabled", True),
        last_fired_key=doc.get("last_fired_key"),
        created_at=doc["created_at"],
    )


async def create_schedule(house_id: str, owner_id: str, data: ScheduleCreate) -> ScheduleResponse:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    device = await db["devices"].find_one({"_id": ObjectId(data.device_id), "house_id": ObjectId(house_id)})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found in this house")
    now = _now()
    doc = {
        "house_id": ObjectId(house_id),
        "owner_id": ObjectId(owner_id),
        "device_id": ObjectId(data.device_id),
        "name": data.name,
        "time": data.time,
        "days": data.days,
        "state": data.state,
        "enabled": data.enabled,
        "last_fired_key": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await db["schedules"].insert_one(doc)
    created = await db["schedules"].find_one({"_id": result.inserted_id})
    return _to_schedule(created)


async def list_schedules(house_id: str, owner_id: str) -> list[ScheduleResponse]:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    cursor = db["schedules"].find({"house_id": ObjectId(house_id)}).sort("time", 1)
    return [_to_schedule(doc) async for doc in cursor]


async def delete_schedule(schedule_id: str, owner_id: str) -> None:
    db = get_database()
    try:
        oid = ObjectId(schedule_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid schedule ID")
    existing = await db["schedules"].find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await get_house_by_id(str(existing["house_id"]), owner_id)
    await db["schedules"].delete_one({"_id": oid})


async def run_due_schedules() -> None:
    db = get_database()
    local = datetime.now(LAGOS)
    minute_key = local.strftime("%Y-%m-%dT%H:%M")
    cursor = db["schedules"].find({"enabled": True, "time": local.strftime("%H:%M")})
    async for schedule in cursor:
        if schedule.get("last_fired_key") == minute_key:
            continue
        if local.weekday() not in schedule.get("days", []):
            continue
        device = await db["devices"].find_one({"_id": schedule["device_id"]})
        if not device:
            continue
        house = await db["houses"].find_one({"_id": schedule["house_id"]})
        if not house:
            continue
        merged = {**device.get("state", {}), **schedule.get("state", {})}
        if merged == device.get("state", {}):
            await db["schedules"].update_one({"_id": schedule["_id"]}, {"$set": {"last_fired_key": minute_key}})
            continue
        on_since = await record_power_transition(device, merged)
        now = _now()
        await db["devices"].update_one(
            {"_id": device["_id"]},
            {"$set": {"state": merged, "on_since": on_since, "updated_at": now}},
        )
        await db["schedules"].update_one(
            {"_id": schedule["_id"]},
            {"$set": {"last_fired_key": minute_key, "updated_at": now}},
        )
        owner_id = str(house["owner_id"])
        await log_activity(
            user_id=owner_id,
            house_id=str(house["_id"]),
            room_id=str(device.get("room_id")) if device.get("room_id") else None,
            device_id=str(device["_id"]),
            action="device_state_changed",
            message=f"Schedule '{schedule['name']}' updated '{device.get('name')}'",
            payload={"new_state": merged, "schedule_id": str(schedule["_id"])},
        )
        await manager.broadcast(
            str(house["_id"]),
            "device_state_changed",
            {"device_id": str(device["_id"]), "name": device.get("name"), "state": merged},
        )