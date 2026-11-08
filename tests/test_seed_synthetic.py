"""Tests for the synthetic seeding script. The data is SYNTHETIC by design; these tests only check
that the generator is sane and that the pipeline can learn from it and say so honestly."""
import asyncio
from datetime import datetime, timezone

from app.services import ml_core
from scripts.seed_synthetic_history import generate_events

NOW = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)
DEVICES = [
    {"id": "light1", "device_type": "light", "name": "Lamp", "room_id": None},
    {"id": "fan1", "device_type": "fan", "name": "Fan", "room_id": None},
    {"id": "ac1", "device_type": "air_conditioner", "name": "AC", "room_id": None},
    {"id": "door1", "device_type": "door", "name": "Door", "room_id": None},
]
TYPES = {d["id"]: d["device_type"] for d in DEVICES}


def test_generator_is_repeatable_and_ignores_unsupported_devices():
    first = generate_events(DEVICES, 30, NOW, seed=7)
    assert first == generate_events(DEVICES, 30, NOW, seed=7)
    assert first != generate_events(DEVICES, 30, NOW, seed=8)
    assert {e["device_id"] for e in first} == {"light1", "fan1", "ac1"}


def test_generator_never_creates_future_events():
    events = generate_events(DEVICES, 30, NOW)
    assert all(e["timestamp"] <= NOW for e in events)
    assert [e["timestamp"] for e in events] == sorted(e["timestamp"] for e in events)


def test_pipeline_can_train_and_find_anomalies_on_generated_history():
    events = [
        {"device_id": e["device_id"], "timestamp": e["timestamp"], "is_on": e["is_on"]}
        for e in generate_events(DEVICES, 30, NOW)
    ]
    df = ml_core.build_hourly_dataset(events, TYPES, NOW)
    model, metrics = ml_core.train_usage_model(df)
    assert metrics["beats_majority_baseline"] is True

    anomalies, checked, _ = ml_core.detect_anomalies(df)
    assert checked == 3
    assert len(anomalies) >= 1  # the injected "left on all day" days
