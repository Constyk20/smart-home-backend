import asyncio
import json
import sys

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.preprocessing import OneHotEncoder

from app.db.mongodb import close_mongo_connection, connect_to_mongo
from app.services.dataset_service import DEVICE_TYPES, build_usage_dataset

MIN_ROWS = 30


def encode(rows: list[dict]) -> np.ndarray:
    encoder = OneHotEncoder(categories=[DEVICE_TYPES], handle_unknown="ignore", sparse_output=False)
    types = encoder.fit_transform([[r["device_type"]] for r in rows])
    numbers = np.array(
        [
            [
                r["hour"],
                r["day_of_week"],
                r["temperature"],
                r["humidity"],
                r["light_level"],
                r["occupancy"],
            ]
            for r in rows
        ],
        dtype=float,
    )
    return np.hstack([numbers, types]), encoder


async def main(house_id: str, owner_id: str) -> None:
    await connect_to_mongo()
    try:
        dataset = await build_usage_dataset(house_id, owner_id)
        rows = dataset["rows"]
        print(f"Real rows: {len(rows)}")
        if len(rows) < MIN_ROWS:
            print("Not enough real history to train. Run the house simulation and use devices first.")
            print("No model file was written. No accuracy is reported.")
            return
        split = int(len(rows) * 0.8)
        train, test = rows[:split], rows[split:]
        if len(test) < 5:
            print("The chronological test split has fewer than 5 rows. No model file was written.")
            return
        x_train, encoder = encode(train)
        x_test = np.hstack(
            [
                np.array(
                    [[r["hour"], r["day_of_week"], r["temperature"], r["humidity"], r["light_level"], r["occupancy"]] for r in test],
                    dtype=float,
                ),
                encoder.transform([[r["device_type"]] for r in test]),
            ]
        )
        y_train = np.array([r["turned_on"] for r in train])
        y_test = np.array([r["turned_on"] for r in test])
        if len(set(y_train.tolist())) < 2:
            print("Training rows contain only one class. No model file was written.")
            return
        model = LogisticRegression(max_iter=500)
        model.fit(x_train, y_train)
        predicted = model.predict(x_test)
        metrics = {
            "train_rows": len(train),
            "test_rows": len(test),
            "accuracy": float(accuracy_score(y_test, predicted)),
            "f1": float(f1_score(y_test, predicted, zero_division=0)),
            "synthetic": False,
        }
        joblib.dump({"model": model, "encoder": encoder, "metrics": metrics}, "usage_model.joblib")
        print(json.dumps(metrics, indent=2))
        print("Saved usage_model.joblib")
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m app.ml.train_usage <house_id> <owner_user_id>")
        raise SystemExit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))