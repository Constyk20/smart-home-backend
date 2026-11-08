from datetime import datetime, timezone
from typing import Any, List, Optional

from bson import ObjectId

from app.db.mongodb import get_database
from app.models.activity import ActivityLogResponse


def _to_response(doc: dict) -> ActivityLogResponse:
    return ActivityLogResponse(
        id=str(doc["_id"]),
        user_id=str(doc["user_id"]),
        house_id=str(doc["house_id"]) if doc.get("house_id") else None,
        room_id=str(doc["room_id"]) if doc.get("room_id") else None,
        device_id=str(doc["device_id"]) if doc.get("device_id") else None,
        action=doc["action"],
        message=doc["message"],
        payload=doc.get("payload"),
        created_at=doc["created_at"],
    )


async def log_activity(
    *,
    user_id: str,
    action: str,
    message: str,
    house_id: Optional[str] = None,
    room_id: Optional[str] = None,
    device_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """Write one activity log entry. This function never raises – logging must not break main operations."""
    try:
        db = get_database()
        doc = {
            "user_id": ObjectId(user_id),
            "house_id": ObjectId(house_id) if house_id else None,
            "room_id": ObjectId(room_id) if room_id else None,
            "device_id": ObjectId(device_id) if device_id else None,
            "action": action,
            "message": message,
            "payload": payload,
            "created_at": datetime.now(timezone.utc),
        }
        await db["activity_logs"].insert_one(doc)
    except Exception as e:
        # In development we print; later we can add proper logging
        print(f"[ActivityLog] Failed to write log: {e}")


async def get_activity_for_house(
    house_id: str, owner_id: str, limit: int = 50
) -> List[ActivityLogResponse]:
    # Ownership is verified by the caller (or we can call get_house_by_id here)
    db = get_database()
    cursor = (
        db["activity_logs"]
        .find({"house_id": ObjectId(house_id), "user_id": ObjectId(owner_id)})
        .sort("created_at", -1)
        .limit(limit)
    )
    logs = []
    async for doc in cursor:
        logs.append(_to_response(doc))
    return logs


async def get_recent_activity_for_user(
    user_id: str, limit: int = 30
) -> List[ActivityLogResponse]:
    db = get_database()
    cursor = (
        db["activity_logs"]
        .find({"user_id": ObjectId(user_id)})
        .sort("created_at", -1)
        .limit(limit)
    )
    logs = []
    async for doc in cursor:
        logs.append(_to_response(doc))
    return logs
