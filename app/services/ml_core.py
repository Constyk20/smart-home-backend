"""Pure machine-learning logic for the virtual smart home.

Nothing in this file touches MongoDB or FastAPI. It takes plain Python / pandas inputs
and returns plain results, so it can be unit tested without a database.

Pipeline (each step is its own function):
    1. build_hourly_dataset  - turn logged on/off events into one row per device per hour
    2. make_features         - turn rows into numeric model inputs
    3. train_usage_model     - chronological split, train, evaluate against a baseline
    4. usage_probability     - predict how likely a device is to be ON at a given hour
    5. detect_anomalies      - flag unusual days of runtime with an Isolation Forest

What the usage model is: a "habit" estimate. It learns, from the house's own logged history,
how often each device type is ON at each hour of the day and day of the week. It is not a
deep model and it does not know *why* a device was on.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score

# Hours of the day are interpreted in this timezone (Nigeria has no daylight saving time).
LOCAL_TZ = "Africa/Lagos"

# Only devices with a simple on/off meaning take part in the habit model.
MODEL_DEVICE_TYPES = ("light", "fan", "air_conditioner", "television", "exhaust_fan")

HOUR = timedelta(hours=1)

# Minimum amounts of real history before we are willing to train or report anything.
MIN_EVENTS = 20
MIN_ROWS = 120
MIN_TEST_ROWS = 24
MIN_DAYS_PER_DEVICE = 14
TRAIN_FRACTION = 0.8

FEATURE_COLUMNS = ["hour_sin", "hour_cos", "dow", "is_weekend"] + [
    f"type_{t}" for t in MODEL_DEVICE_TYPES
]

MODEL_DIR = Path(__file__).resolve().parents[2] / "ml_models"
_HOUSE_ID_RE = re.compile(r"^[0-9a-f]{24}$")


class InsufficientDataError(Exception):
    """Raised when there is not enough real history to train or analyse honestly."""


# ---------------------------------------------------------------------------
# 1. Dataset building
# ---------------------------------------------------------------------------

def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


_DATASET_COLUMNS = [
    "device_id", "device_type", "bucket_start", "on_fraction", "label", "hour", "dow", "date",
]


def build_hourly_dataset(
    events: list[dict[str, Any]],
    device_types: dict[str, str],
    end: datetime,
) -> pd.DataFrame:
    """One row per device per fully elapsed hour.

    events: dicts with device_id (str), timestamp (tz-aware UTC datetime), is_on (bool).
    The device is assumed to keep its last logged state until the next logged change.
    A row starts at each device's first logged event, so no state is ever guessed before
    the device has any history.

    label = 1 when the device was ON for at least half of that hour.
    """
    end_hour = _floor_hour(end)
    by_device: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        dtype = device_types.get(ev["device_id"])
        if dtype in MODEL_DEVICE_TYPES:
            by_device.setdefault(ev["device_id"], []).append(ev)

    rows: list[dict[str, Any]] = []
    for device_id, evs in by_device.items():
        evs = sorted(evs, key=lambda e: e["timestamp"])
        start_hour = _floor_hour(evs[0]["timestamp"])
        if start_hour >= end_hour:
            continue
        n = int((end_hour - start_hour) / HOUR)
        on_seconds = np.zeros(n)
        for i, ev in enumerate(evs):
            if not ev["is_on"]:
                continue
            seg_start = ev["timestamp"]
            seg_end = min(evs[i + 1]["timestamp"], end_hour) if i + 1 < len(evs) else end_hour
            k = int((_floor_hour(seg_start) - start_hour) / HOUR)
            while k < n:
                bucket_start = start_hour + k * HOUR
                if bucket_start >= seg_end:
                    break
                overlap = (min(seg_end, bucket_start + HOUR) - max(seg_start, bucket_start)).total_seconds()
                if overlap > 0:
                    on_seconds[k] += overlap
                k += 1
        for k in range(n):
            fraction = float(on_seconds[k] / 3600.0)
            rows.append(
                {
                    "device_id": device_id,
                    "device_type": device_types[device_id],
                    "bucket_start": start_hour + k * HOUR,
                    "on_fraction": fraction,
                    "label": int(fraction >= 0.5),
                }
            )

    if not rows:
        return pd.DataFrame(columns=_DATASET_COLUMNS)

    df = pd.DataFrame(rows)
    local = pd.to_datetime(df["bucket_start"], utc=True).dt.tz_convert(LOCAL_TZ)
    df["hour"] = local.dt.hour
    df["dow"] = local.dt.dayofweek
    df["date"] = local.dt.date
    return df[_DATASET_COLUMNS]


# ---------------------------------------------------------------------------
# 2. Features
# ---------------------------------------------------------------------------

def make_features(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric inputs: hour as a circle (so 23:00 is next to 00:00), day of week, device type."""
    x = pd.DataFrame(index=df.index)
    x["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    x["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    x["dow"] = df["dow"]
    x["is_weekend"] = (df["dow"] >= 5).astype(int)
    for dtype in MODEL_DEVICE_TYPES:
        x[f"type_{dtype}"] = (df["device_type"] == dtype).astype(int)
    return x[FEATURE_COLUMNS]


# ---------------------------------------------------------------------------
# 3. Training and evaluation
# ---------------------------------------------------------------------------

def train_usage_model(df: pd.DataFrame) -> tuple[RandomForestClassifier, dict[str, Any]]:
    """Train on the earliest 80% of time, evaluate on the latest 20%.

    The split is by time, not random, so the model is never tested on hours that came before
    hours it learned from. Metrics describe a model fit on the early part only; the returned
    model is then refit on all the data so it is as informed as possible for real use.
    """
    if len(df) < MIN_ROWS:
        raise InsufficientDataError(
            f"Only {len(df)} device-hours of history; at least {MIN_ROWS} are needed to train."
        )

    times = sorted(df["bucket_start"].unique())
    cutoff = times[int(len(times) * TRAIN_FRACTION)]
    train = df[df["bucket_start"] < cutoff]
    test = df[df["bucket_start"] >= cutoff]

    if len(test) < MIN_TEST_ROWS:
        raise InsufficientDataError(
            f"Only {len(test)} device-hours are left for testing; at least {MIN_TEST_ROWS} are needed."
        )
    if train["label"].nunique() < 2:
        raise InsufficientDataError(
            "The earlier history contains only one outcome (devices always on or always off), "
            "so there is nothing to learn yet."
        )

    def new_model() -> RandomForestClassifier:
        return RandomForestClassifier(
            n_estimators=150, max_depth=8, min_samples_leaf=3, random_state=42
        )

    model = new_model().fit(make_features(train), train["label"])
    predicted = model.predict(make_features(test))

    majority = int(train["label"].mean() >= 0.5)
    baseline_accuracy = float((test["label"] == majority).mean())
    accuracy = float(accuracy_score(test["label"], predicted))

    metrics = {
        "accuracy": accuracy,
        "f1": float(f1_score(test["label"], predicted, zero_division=0)),
        "baseline_majority_accuracy": baseline_accuracy,
        "beats_majority_baseline": bool(accuracy > baseline_accuracy),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "positive_rate_test": float(test["label"].mean()),
    }

    final_model = new_model().fit(make_features(df), df["label"])
    return final_model, metrics


# ---------------------------------------------------------------------------
# 4. Prediction
# ---------------------------------------------------------------------------

def usage_probability(model: RandomForestClassifier, rows: pd.DataFrame) -> np.ndarray:
    """Probability that each row's device is ON. rows needs: hour, dow, device_type."""
    if rows.empty:
        return np.array([])
    proba = model.predict_proba(make_features(rows))
    classes = list(model.classes_)
    if 1 not in classes:
        return np.zeros(len(rows))
    return proba[:, classes.index(1)]


# ---------------------------------------------------------------------------
# 5. Anomaly detection
# ---------------------------------------------------------------------------

def _daily_features(df: pd.DataFrame) -> pd.DataFrame:
    records = []
    for (device_id, date), group in df.groupby(["device_id", "date"]):
        if len(group) != 24:  # skip partial days
            continue
        on_hours = group.loc[group["label"] == 1, "hour"]
        records.append(
            {
                "device_id": device_id,
                "date": date,
                "on_hours": float(group["on_fraction"].sum()),
                "first_on": int(on_hours.min()) if len(on_hours) else -1,
                "last_on": int(on_hours.max()) if len(on_hours) else -1,
            }
        )
    return pd.DataFrame(records, columns=["device_id", "date", "on_hours", "first_on", "last_on"])


def detect_anomalies(df: pd.DataFrame) -> tuple[list[dict[str, Any]], int, int]:
    """Flag days where a device ran unusually compared with its own history.

    One Isolation Forest per device, on three daily numbers: hours on, first hour on, last hour on.
    Returns (anomalies, devices_checked, devices_skipped). A device needs at least
    MIN_DAYS_PER_DEVICE complete days of history to be checked.
    """
    daily = _daily_features(df)
    anomalies: list[dict[str, Any]] = []
    checked = skipped = 0
    if daily.empty:
        return anomalies, checked, skipped

    for device_id, group in daily.groupby("device_id"):
        if len(group) < MIN_DAYS_PER_DEVICE:
            skipped += 1
            continue
        checked += 1
        features = group[["on_hours", "first_on", "last_on"]]
        forest = IsolationForest(n_estimators=100, contamination="auto", random_state=42)
        forest.fit(features)
        flags = forest.predict(features)
        scores = forest.decision_function(features)
        typical = float(group["on_hours"].median())
        for (_, row), flag, score in zip(group.iterrows(), flags, scores):
            if flag == -1:
                anomalies.append(
                    {
                        "device_id": device_id,
                        "date": row["date"],
                        "on_hours": float(row["on_hours"]),
                        "typical_on_hours": typical,
                        "anomaly_score": float(score),
                    }
                )
    anomalies.sort(key=lambda a: a["date"], reverse=True)
    return anomalies, checked, skipped


# ---------------------------------------------------------------------------
# Persistence (models live on disk, one folder per house)
# ---------------------------------------------------------------------------

def _house_dir(house_id: str, base_dir: Path | None) -> Path:
    if not _HOUSE_ID_RE.match(house_id):
        raise ValueError("Invalid house id")
    return (base_dir or MODEL_DIR) / house_id


def save_model(
    house_id: str,
    model: RandomForestClassifier,
    meta: dict[str, Any],
    base_dir: Path | None = None,
) -> None:
    folder = _house_dir(house_id, base_dir)
    folder.mkdir(parents=True, exist_ok=True)
    meta = {**meta, "sklearn_version": sklearn.__version__}
    joblib.dump(model, folder / "usage_model.joblib")
    (folder / "usage_model.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_model(
    house_id: str, base_dir: Path | None = None
) -> tuple[RandomForestClassifier, dict[str, Any]] | None:
    """Only ever load files this application wrote itself (joblib files can run code on load)."""
    folder = _house_dir(house_id, base_dir)
    model_path, meta_path = folder / "usage_model.joblib", folder / "usage_model.json"
    if not model_path.exists() or not meta_path.exists():
        return None
    return joblib.load(model_path), json.loads(meta_path.read_text(encoding="utf-8"))


def local_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(LOCAL_TZ))
