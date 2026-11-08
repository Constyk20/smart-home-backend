"""Unit tests for app/services/ml_core.py.

All data in this file is SYNTHETIC: a made-up household routine used only to check that the
code behaves correctly. Passing these tests says nothing about how well the model will perform
on real logged history.
"""
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services import ml_core

UTC = timezone.utc
# Lagos is UTC+1 all year, so local 18:00 == 17:00 UTC.
START = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)  # a Tuesday


def _event(device_id, ts, is_on):
    return {"device_id": device_id, "timestamp": ts, "is_on": is_on}


def _routine_events(days=30, anomaly_day=None):
    """Light on 18:00-23:00 local on weekdays; AC on 13:00-17:00 local at weekends."""
    events = []
    for d in range(days):
        day = START + timedelta(days=d)
        local_weekday = (day + timedelta(hours=1)).weekday()
        if local_weekday < 5:
            on = day + timedelta(hours=17)
            off = day + timedelta(hours=22)
            if d == anomaly_day:
                on, off = day, day + timedelta(hours=20)  # light on almost all day
            events += [_event("light1", on, True), _event("light1", off, False)]
        else:
            events += [
                _event("ac1", day + timedelta(hours=12), True),
                _event("ac1", day + timedelta(hours=16), False),
            ]
    return events


DEVICE_TYPES = {"light1": "light", "ac1": "air_conditioner", "door1": "door"}


def test_hourly_dataset_fractions_and_local_hours():
    events = [
        _event("light1", START + timedelta(hours=17, minutes=30), True),
        _event("light1", START + timedelta(hours=18, minutes=30), False),
    ]
    df = ml_core.build_hourly_dataset(events, DEVICE_TYPES, START + timedelta(days=1))
    on_rows = df[df["on_fraction"] > 0].sort_values("bucket_start")
    assert list(on_rows["on_fraction"]) == [0.5, 0.5]
    assert list(on_rows["hour"]) == [18, 19]  # converted to Lagos time
    assert len(df) == 7  # first event 17:00 UTC until midnight UTC


def test_hourly_dataset_ignores_unsupported_device_types():
    events = [_event("door1", START, True)]
    df = ml_core.build_hourly_dataset(events, DEVICE_TYPES, START + timedelta(days=2))
    assert df.empty


def test_train_beats_baseline_on_synthetic_routine():
    events = _routine_events()
    df = ml_core.build_hourly_dataset(events, DEVICE_TYPES, START + timedelta(days=30))
    model, metrics = ml_core.train_usage_model(df)

    assert metrics["train_rows"] + metrics["test_rows"] == len(df)
    assert metrics["beats_majority_baseline"] is True
    assert 0.0 <= metrics["accuracy"] <= 1.0

    rows = pd.DataFrame(
        [
            {"hour": 20, "dow": 2, "device_type": "light"},  # Wednesday evening
            {"hour": 3, "dow": 2, "device_type": "light"},  # Wednesday 03:00
        ]
    )
    evening, night = ml_core.usage_probability(model, rows)
    assert evening > 0.8
    assert night < 0.2


def test_split_is_chronological():
    events = _routine_events()
    df = ml_core.build_hourly_dataset(events, DEVICE_TYPES, START + timedelta(days=30))
    times = sorted(df["bucket_start"].unique())
    cutoff = times[int(len(times) * ml_core.TRAIN_FRACTION)]
    train = df[df["bucket_start"] < cutoff]
    test = df[df["bucket_start"] >= cutoff]
    assert train["bucket_start"].max() < test["bucket_start"].min()


def test_too_little_history_is_refused_not_faked():
    events = _routine_events(days=2)
    df = ml_core.build_hourly_dataset(events, DEVICE_TYPES, START + timedelta(days=2))
    with pytest.raises(ml_core.InsufficientDataError):
        ml_core.train_usage_model(df)


def test_always_off_history_is_refused():
    events = [_event("light1", START, False), _event("light1", START + timedelta(hours=1), False)]
    df = ml_core.build_hourly_dataset(events, DEVICE_TYPES, START + timedelta(days=10))
    with pytest.raises(ml_core.InsufficientDataError):
        ml_core.train_usage_model(df)


def test_anomaly_detection_flags_planted_day():
    anomaly_day = 21  # a weekday, local date = START + 21 days
    events = _routine_events(days=30, anomaly_day=anomaly_day)
    df = ml_core.build_hourly_dataset(events, DEVICE_TYPES, START + timedelta(days=30))
    anomalies, checked, skipped = ml_core.detect_anomalies(df)
    assert checked >= 1
    flagged = {(a["device_id"], a["date"]) for a in anomalies}
    expected_date = (START + timedelta(days=anomaly_day, hours=1)).date()
    assert ("light1", expected_date) in flagged
    planted = next(a for a in anomalies if a["date"] == expected_date and a["device_id"] == "light1")
    assert planted["on_hours"] > planted["typical_on_hours"]


def test_anomaly_detection_skips_devices_with_short_history():
    events = _routine_events(days=6)
    df = ml_core.build_hourly_dataset(events, DEVICE_TYPES, START + timedelta(days=6))
    anomalies, checked, skipped = ml_core.detect_anomalies(df)
    assert anomalies == []
    assert checked == 0


def test_model_round_trip_and_house_id_validation(tmp_path):
    events = _routine_events()
    df = ml_core.build_hourly_dataset(events, DEVICE_TYPES, START + timedelta(days=30))
    model, metrics = ml_core.train_usage_model(df)
    house_id = "a" * 24

    assert ml_core.load_model(house_id, tmp_path) is None
    ml_core.save_model(house_id, model, {"metrics": metrics}, tmp_path)
    loaded_model, meta = ml_core.load_model(house_id, tmp_path)
    assert meta["metrics"]["accuracy"] == metrics["accuracy"]
    assert "sklearn_version" in meta

    rows = pd.DataFrame([{"hour": 20, "dow": 2, "device_type": "light"}])
    assert ml_core.usage_probability(loaded_model, rows)[0] == ml_core.usage_probability(model, rows)[0]

    with pytest.raises(ValueError):
        ml_core.load_model("../../etc", tmp_path)
