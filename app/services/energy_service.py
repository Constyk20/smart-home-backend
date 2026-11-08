from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict

from bson import ObjectId
from fastapi import HTTPException, status

from app.db.mongodb import get_database
from app.models.energy import (
    HouseEnergySummary,
    DeviceEnergyInfo,
    TariffUpdate,
    DeviceWattageUpdate,
)
from app.services.house_service import get_house_by_id

LAGOS = ZoneInfo("Africa/Lagos")

DEFAULT_WATTAGE: Dict[str, float] = {
    "light": 12.0,
    "fan": 70.0,
    "air_conditioner": 1500.0,
    "television": 100.0,
    "curtain": 50.0,
    "window": 0.0,
    "door": 0.0,
    "exhaust_fan": 40.0,
    "security_camera": 8.0,
    "other": 50.0,
}

DEFAULT_TARIFF = 70.0
NON_CONSUMING = {"window", "door"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lagos_date(value: datetime) -> str:
    return _as_utc(value).astimezone(LAGOS).date().isoformat()


def is_consuming(device: dict) -> bool:
    if device.get("device_type") in NON_CONSUMING:
        return False
    return bool(device.get("state", {}).get("is_on"))


async def _get_or_create_energy_settings(house_id: str) -> dict:
    db = get_database()
    doc = await db["energy_settings"].find_one({"house_id": ObjectId(house_id)})
    if doc:
        return doc
    new_doc = {
        "house_id": ObjectId(house_id),
        "tariff_per_kwh": DEFAULT_TARIFF,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db["energy_settings"].insert_one(new_doc)
    return await db["energy_settings"].find_one({"house_id": ObjectId(house_id)})


async def _add_seconds(device: dict, start: datetime, end: datetime) -> None:
    """Split one on-interval across Lagos midnights and increment daily buckets."""
    if end <= start:
        return
    db = get_database()
    cursor = _as_utc(start)
    end = _as_utc(end)
    while cursor < end:
        local_date = cursor.astimezone(LAGOS).date()
        next_midnight_local = datetime.combine(
            local_date + timedelta(days=1), time.min, tzinfo=LAGOS
        )
        slice_end = min(end, next_midnight_local.astimezone(timezone.utc))
        seconds = (slice_end - cursor).total_seconds()
        if seconds > 0:
            await db["energy_daily"].update_one(
                {"device_id": device["_id"], "date": local_date.isoformat()},
                {
                    "$inc": {"seconds_on": seconds},
                    "$set": {
                        "house_id": device["house_id"],
                        "device_name": device.get("name"),
                        "device_type": device.get("device_type"),
                        "updated_at": _now(),
                    },
                    "$setOnInsert": {"created_at": _now()},
                },
                upsert=True,
            )
        cursor = slice_end


async def record_power_transition(device_before: dict, new_state: dict) -> datetime | None:
    """Call this whenever a device state is replaced. Returns the new on_since value to store."""
    before = {**device_before, "state": device_before.get("state", {})}
    after = {**device_before, "state": new_state}
    was_on = is_consuming(before)
    now_on = is_consuming(after)
    previous_since = device_before.get("on_since")
    now = _now()

    if was_on and not now_on and previous_since:
        await _add_seconds(device_before, _as_utc(previous_since), now)
        return None
    if not was_on and now_on:
        return now
    if was_on and previous_since:
        return _as_utc(previous_since)
    return None


async def _seconds_on_for_date(device: dict, date_key: str, now: datetime) -> float:
    db = get_database()
    row = await db["energy_daily"].find_one({"device_id": device["_id"], "date": date_key})
    seconds = float(row["seconds_on"]) if row else 0.0

    on_since = device.get("on_since")
    if is_consuming(device) and on_since:
        start = _as_utc(on_since)
        # Only the part of the open session that falls on this Lagos date.
        day = datetime.fromisoformat(date_key).date()
        day_start = datetime.combine(day, time.min, tzinfo=LAGOS).astimezone(timezone.utc)
        day_end = day_start + timedelta(days=1)
        slice_start = max(start, day_start)
        slice_end = min(now, day_end)
        if slice_end > slice_start:
            seconds += (slice_end - slice_start).total_seconds()
    return seconds


async def get_house_energy_summary(house_id: str, owner_id: str) -> HouseEnergySummary:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    settings = await _get_or_create_energy_settings(house_id)
    tariff = float(settings.get("tariff_per_kwh", DEFAULT_TARIFF))
    now = _now()
    today = _lagos_date(now)

    devices = [d async for d in db["devices"].find({"house_id": ObjectId(house_id)})]
    infos: list[DeviceEnergyInfo] = []
    total_kwh = 0.0

    for device in devices:
        dtype = device.get("device_type", "other")
        wattage = float(device.get("wattage") or DEFAULT_WATTAGE.get(dtype, 50.0))
        seconds = await _seconds_on_for_date(device, today, now)
        kwh = (wattage * seconds) / 3_600_000.0
        cost = kwh * tariff
        total_kwh += kwh
        infos.append(
            DeviceEnergyInfo(
                device_id=str(device["_id"]),
                device_name=device.get("name", "Unknown"),
                device_type=dtype,
                wattage=wattage,
                is_on=is_consuming(device),
                estimated_kwh_today=round(kwh, 4),
                estimated_cost_today=round(cost, 2),
            )
        )

    return HouseEnergySummary(
        house_id=house_id,
        tariff_per_kwh=tariff,
        total_kwh_today=round(total_kwh, 4),
        total_cost_today=round(total_kwh * tariff, 2),
        devices=infos,
        last_calculated_at=now,
    )


async def get_energy_history(house_id: str, owner_id: str, days: int = 7) -> dict:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    settings = await _get_or_create_energy_settings(house_id)
    tariff = float(settings.get("tariff_per_kwh", DEFAULT_TARIFF))
    today = datetime.now(LAGOS).date()
    dates = [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]

    devices = [d async for d in db["devices"].find({"house_id": ObjectId(house_id)})]
    by_date = {d: 0.0 for d in dates}
    now = _now()

    for device in devices:
        wattage = float(device.get("wattage") or DEFAULT_WATTAGE.get(device.get("device_type", "other"), 50.0))
        for date_key in dates:
            seconds = await _seconds_on_for_date(device, date_key, now)
            by_date[date_key] += (wattage * seconds) / 3_600_000.0

    return {
        "house_id": house_id,
        "tariff_per_kwh": tariff,
        "timezone": "Africa/Lagos",
        "days": [
            {
                "date": date_key,
                "kwh": round(kwh, 4),
                "cost_naira": round(kwh * tariff, 2),
            }
            for date_key, kwh in by_date.items()
        ],
    }


async def update_tariff(house_id: str, owner_id: str, data: TariffUpdate) -> dict:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    await _get_or_create_energy_settings(house_id)
    await db["energy_settings"].update_one(
        {"house_id": ObjectId(house_id)},
        {"": {"tariff_per_kwh": data.tariff_per_kwh, "updated_at": _now()}},
    )
    return {"house_id": house_id, "tariff_per_kwh": data.tariff_per_kwh}


async def update_device_wattage(device_id: str, owner_id: str, data: DeviceWattageUpdate) -> dict:
    db = get_database()
    try:
        oid = ObjectId(device_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid device ID")
    device = await db["devices"].find_one({"_id": oid})
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    await get_house_by_id(str(device["house_id"]), owner_id)
    await db["devices"].update_one(
        {"_id": oid},
        {"": {"wattage": data.wattage, "updated_at": _now()}},
    )
    return {"device_id": device_id, "wattage": data.wattage}
