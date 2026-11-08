import asyncio
import sys

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from app.db.mongodb import close_mongo_connection, connect_to_mongo, get_database
from app.services.house_service import get_house_by_id

MIN_DAYS = 14


async def main(house_id: str, owner_id: str) -> None:
    await connect_to_mongo()
    try:
        await get_house_by_id(house_id, owner_id)
        db = get_database()
        from bson import ObjectId

        rows = [
            r
            async for r in db["energy_daily"].find({"house_id": ObjectId(house_id)})
        ]
        by_day: dict[str, float] = {}
        for row in rows:
            by_day[row["date"]] = by_day.get(row["date"], 0.0) + float(row.get("seconds_on", 0))
        print(f"Real daily buckets: {len(by_day)}")
        if len(by_day) < MIN_DAYS:
            print(f"Need at least {MIN_DAYS} distinct days of energy_daily. No anomaly model was written.")
            return
        values = np.array(list(by_day.values()), dtype=float).reshape(-1, 1)
        model = IsolationForest(contamination=0.1, random_state=42)
        model.fit(values)
        joblib.dump({"model": model, "days": len(by_day)}, "anomaly_model.joblib")
        print(f"Saved anomaly_model.joblib using {len(by_day)} real days. No accuracy figure is claimed.")
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m app.ml.train_anomaly <house_id> <owner_user_id>")
        raise SystemExit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))