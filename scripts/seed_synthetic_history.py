"""Fill a house with SYNTHETIC device history so the ML pipeline can be demonstrated.

Every row this script writes is marked payload.synthetic = True. The trained model reports
that it saw synthetic data, and recommendations built from it say so. A model trained this way
has learned the made-up routine below, NOT real household behaviour. When real history has
accumulated, retrain with the same /ml/train endpoint after clearing the synthetic rows.

Run from the backend folder with the venv active:
    python -m scripts.seed_synthetic_history HOUSE_ID --days 30 --train
    python -m scripts.seed_synthetic_history HOUSE_ID --clear

It only writes activity log entries. It does not change device states, energy records or
simulation data, and --clear only deletes rows marked synthetic.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

LOCAL_TZ = "Africa/Lagos"

# (which days, start hour, end hour) in local time. Hours may have a .5 for half past.
ROUTINES: dict[str, list[tuple[str, float, float]]] = {
    "light": [("weekday", 6.5, 7.5), ("all", 18.0, 23.0)],
    "fan": [("all", 13.0, 17.0)],
    "air_conditioner": [("weekday", 21.0, 23.5), ("weekend", 12.0, 17.0)],
    "television": [("weekday", 19.0, 22.0), ("weekend", 15.0, 23.0)],
    "exhaust_fan": [("all", 7.0, 7.5)],
}

SKIP_PROBABILITY = 0.1  # the occupant sometimes just doesn't use the device
JITTER_MINUTES = 20  # start and stop times vary a little
MIN_DAYS_FOR_ANOMALY = 14


def _applies(rule_days: str, weekday: int) -> bool:
    return rule_days == "all" or (rule_days == "weekday") == (weekday < 5)


def generate_events(
    devices: list[dict[str, Any]], days: int, now: datetime, seed: int = 42
) -> list[dict[str, Any]]:
    """Return on/off events: dicts with device_id, room_id, device_name, timestamp (UTC), is_on.

    devices: dicts with id, device_type, name, room_id. Unsupported device types are ignored.
    One day per device is turned into an 'anomaly day' where the device is left on almost
    all day, so anomaly detection has something to find.
    """
    rng = random.Random(seed)
    tz = ZoneInfo(LOCAL_TZ)
    now_local = now.astimezone(tz)
    today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    events: list[dict[str, Any]] = []

    for device in devices:
        routines = ROUTINES.get(device["device_type"])
        if not routines:
            continue
        anomaly_offset = rng.randint(2, days - 1) if days >= MIN_DAYS_FOR_ANOMALY else None

        for offset in range(days, -1, -1):
            midnight = today - timedelta(days=offset)
            if offset == anomaly_offset:
                spans = [(0.5, 23.5)]
            else:
                spans = [
                    (start, end)
                    for rule_days, start, end in routines
                    if _applies(rule_days, midnight.weekday())
                    and rng.random() >= SKIP_PROBABILITY
                ]
            for start, end in spans:
                jitter = lambda: timedelta(minutes=rng.uniform(-JITTER_MINUTES, JITTER_MINUTES))  # noqa: E731
                on_at = midnight + timedelta(hours=start) + (timedelta(0) if offset == anomaly_offset else jitter())
                off_at = midnight + timedelta(hours=end) + (timedelta(0) if offset == anomaly_offset else jitter())
                if on_at.astimezone(timezone.utc) > now:
                    continue
                base = {
                    "device_id": device["id"],
                    "device_name": device["name"],
                    "room_id": device.get("room_id"),
                }
                events.append({**base, "timestamp": on_at.astimezone(timezone.utc), "is_on": True})
                if off_at.astimezone(timezone.utc) <= now:  # still on if "now" is mid-session
                    events.append({**base, "timestamp": off_at.astimezone(timezone.utc), "is_on": False})

    events.sort(key=lambda e: e["timestamp"])
    return events


async def _run(args: argparse.Namespace) -> int:
    # Imported here so generate_events can be imported (and tested) without a database.
    from bson import ObjectId

    from app.db.mongodb import close_mongo_connection, connect_to_mongo, get_database
    from app.services import ml_service

    if not ObjectId.is_valid(args.house_id):
        print("HOUSE_ID is not a valid id.")
        return 1

    await connect_to_mongo()
    try:
        db = get_database()
        house_oid = ObjectId(args.house_id)
        house = await db["houses"].find_one({"_id": house_oid})
        if not house:
            print("No house with that id.")
            return 1
        user_id = args.user_id or str(house.get("owner_id") or house.get("user_id") or "")
        if not ObjectId.is_valid(user_id):
            print("Could not work out the owner's user id from the house; pass --user-id.")
            return 1

        deleted = await db["activity_logs"].delete_many(
            {"house_id": house_oid, "payload.synthetic": True}
        )
        print(f"Removed {deleted.deleted_count} earlier synthetic log entries.")
        if args.clear:
            return 0

        devices = [
            {
                "id": str(d["_id"]),
                "device_type": d.get("device_type"),
                "name": d.get("name", "Device"),
                "room_id": str(d["room_id"]) if d.get("room_id") else None,
            }
            async for d in db["devices"].find({"house_id": house_oid})
        ]
        events = generate_events(devices, args.days, datetime.now(timezone.utc), seed=args.seed)
        if not events:
            print("This house has no supported devices (light, fan, air conditioner, television, exhaust fan).")
            return 1

        docs = [
            {
                "user_id": ObjectId(user_id),
                "house_id": house_oid,
                "room_id": ObjectId(e["room_id"]) if e["room_id"] else None,
                "device_id": ObjectId(e["device_id"]),
                "action": "device_state_changed",
                "message": f"[synthetic] {'On' if e['is_on'] else 'Off'}: {e['device_name']}",
                "payload": {"new_state": {"is_on": e["is_on"]}, "synthetic": True},
                "created_at": e["timestamp"],
            }
            for e in events
        ]
        await db["activity_logs"].insert_many(docs)
        print(f"Inserted {len(docs)} SYNTHETIC log entries covering {args.days} days.")

        if args.train:
            info = await ml_service.train_for_house(args.house_id, user_id)
            m = info.metrics
            print(f"Trained. synthetic={info.synthetic}")
            print(f"  accuracy {m.accuracy:.1%} vs majority baseline {m.baseline_majority_accuracy:.1%}")
            print(f"  beats baseline: {m.beats_majority_baseline}; f1 {m.f1:.2f}")
            for note in info.notes:
                print(f"  note: {note}")
        return 0
    finally:
        await close_mongo_connection()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("house_id")
    parser.add_argument("--days", type=int, default=30, help="days of history to generate (7-90)")
    parser.add_argument("--seed", type=int, default=42, help="random seed, for repeatable data")
    parser.add_argument("--user-id", help="owner's user id, if it cannot be read from the house")
    parser.add_argument("--train", action="store_true", help="train the model straight after seeding")
    parser.add_argument("--clear", action="store_true", help="only delete earlier synthetic rows")
    args = parser.parse_args()
    if not 7 <= args.days <= 90:
        parser.error("--days must be between 7 and 90")
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
