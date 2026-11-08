from datetime import timedelta

from bson import ObjectId
from fastapi import HTTPException

from app.db.mongodb import get_database
from app.services.energy_service import LAGOS, _as_utc
from app.services.house_service import get_house_by_id

DEVICE_TYPES = [
    "light",
    "fan",
    "air_conditioner",
    "television",
    "curtain",
    "exhaust_fan",
    "security_camera",
    "other",
]


def _on_label(payload: dict | None) -> int | None:
    if not payload:
        return None
    state = payload.get("new_state") or payload.get("state") or {}
    if "is_on" not in state:
        return None
    return 1 if state.get("is_on") else 0


async def build_usage_dataset(house_id: str, owner_id: str) -> dict:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    house_oid = ObjectId(house_id)

    devices = {
        str(d["_id"]): d
        async for d in db["devices"].find({"house_id": house_oid})
    }
    history = [
        h
        async for h in db["environment_history"]
        .find({"house_id": house_oid})
        .sort("created_at", 1)
    ]
    logs = [
        log
        async for log in db["activity_logs"]
        .find({"house_id": house_oid, "action": "device_state_changed"})
        .sort("created_at", 1)
    ]

    rows: list[dict] = []
    hist_index = 0
    for log in logs:
        label = _on_label(log.get("payload"))
        device = devices.get(str(log.get("device_id"))) if log.get("device_id") else None
        if label is None or device is None:
            continue
        created = _as_utc(log["created_at"])
        while (
            hist_index + 1 < len(history)
            and _as_utc(history[hist_index + 1]["created_at"]) <= created
        ):
            hist_index += 1
        if not history:
            continue
        snap = history[hist_index]
        if abs((_as_utc(snap["created_at"]) - created).total_seconds()) > 600:
            continue
        local = created.astimezone(LAGOS)
        rows.append(
            {
                "created_at": created.isoformat(),
                "hour": local.hour,
                "day_of_week": local.weekday(),
                "device_type": device.get("device_type", "other"),
                "temperature": snap.get("temperature"),
                "humidity": snap.get("humidity"),
                "light_level": snap.get("light_level"),
                "occupancy": 1 if snap.get("occupancy") else 0,
                "turned_on": label,
            }
        )

    return {
        "house_id": house_id,
        "source": "activity_logs+environment_history",
        "synthetic": False,
        "row_count": len(rows),
        "minimum_rows_to_train": 30,
        "ready_to_train": len(rows) >= 30,
        "rows": rows,
    }