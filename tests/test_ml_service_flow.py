"""End-to-end check of ml_service, recommendation_service and automation history against a
tiny in-memory fake of MongoDB.

The household routine used here is SYNTHETIC and exists only to exercise the code paths.
The fake database checks our parsing and orchestration, not the real query behaviour of MongoDB.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.services import automation_history_service, ml_core, ml_service, recommendation_service

UTC = timezone.utc


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, key, direction=1):
        self.docs.sort(key=lambda d: d[key], reverse=direction == -1)
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    def __aiter__(self):
        self._it = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _match(doc, query):
        for key, value in (query or {}).items():
            if isinstance(value, dict) and "$in" in value:
                if doc.get(key) not in value["$in"]:
                    return False
            elif doc.get(key) != value:
                return False
        return True

    def find(self, query=None):
        return FakeCursor(d for d in self.docs if self._match(d, query))

    async def find_one(self, query=None):
        return next((d for d in self.docs if self._match(d, query)), None)

    async def insert_one(self, doc):
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)


class FakeDB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


HOUSE_ID = str(ObjectId())
OWNER_ID = str(ObjectId())


@pytest.fixture
def world(monkeypatch, tmp_path):
    db = FakeDB()
    house_oid = ObjectId(HOUSE_ID)
    light_id, ac_id, door_id = ObjectId(), ObjectId(), ObjectId()
    db["devices"].docs += [
        {"_id": light_id, "house_id": house_oid, "name": "Lamp", "device_type": "light",
         "state": {"is_on": True, "brightness": 50}},
        {"_id": ac_id, "house_id": house_oid, "name": "AC", "device_type": "air_conditioner",
         "state": {"is_on": False}},
        {"_id": door_id, "house_id": house_oid, "name": "Door", "device_type": "door",
         "state": {"is_open": False}},
    ]

    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
    # A weekday (local time) near the end of the history, whatever day the tests run on.
    anomaly_day = next(d for d in range(18, 30) if (start + timedelta(days=d, hours=1)).weekday() < 5)

    def log(device_id, ts, is_on, extra=None):
        payload = {"new_state": {"is_on": is_on}, **(extra or {})}
        db["activity_logs"].docs.append(
            {
                "house_id": house_oid,
                "device_id": device_id,
                "action": "device_state_changed",
                "payload": payload,
                "created_at": ts.replace(tzinfo=None),  # MongoDB hands back naive UTC datetimes
            }
        )

    for d in range(30):
        day = start + timedelta(days=d)
        if (day + timedelta(hours=1)).weekday() < 5:
            on, off = day + timedelta(hours=17), day + timedelta(hours=22)
            if d == anomaly_day:
                on, off = day, day + timedelta(hours=20)
            log(light_id, on, True)
            log(light_id, off, False)
        else:
            log(ac_id, day + timedelta(hours=12), True)
            log(ac_id, day + timedelta(hours=16), False)
    log(door_id, start, True)  # unsupported type; must be ignored

    async def no_check(house_id, owner_id):
        return None

    for module in (ml_service, recommendation_service, automation_history_service):
        monkeypatch.setattr(module, "get_database", lambda: db)
        monkeypatch.setattr(module, "get_house_by_id", no_check)
    monkeypatch.setattr(ml_core, "MODEL_DIR", tmp_path)
    return {"db": db, "start": start, "light_id": light_id, "anomaly_day": anomaly_day}


def run(coro):
    return asyncio.run(coro)


def test_untrained_house_reports_not_trained(world):
    info = run(ml_service.get_model_info(HOUSE_ID, OWNER_ID))
    assert info.trained is False


def test_training_and_status(world):
    info = run(ml_service.train_for_house(HOUSE_ID, OWNER_ID))
    assert info.trained is True and info.synthetic is False
    assert info.metrics.beats_majority_baseline is True
    assert info.automation_event_share == 0.0
    assert run(ml_service.get_model_info(HOUSE_ID, OWNER_ID)).trained is True


def test_model_trained_on_synthetic_rows_says_so(world):
    for doc in world["db"]["activity_logs"].docs:
        doc["payload"]["synthetic"] = True
    info = run(ml_service.train_for_house(HOUSE_ID, OWNER_ID))
    assert info.synthetic is True
    assert any("SYNTHETIC DATA" in note for note in info.notes)


def test_training_refused_with_too_little_history(world):
    world["db"]["activity_logs"].docs = world["db"]["activity_logs"].docs[:5]
    with pytest.raises(HTTPException) as excinfo:
        run(ml_service.train_for_house(HOUSE_ID, OWNER_ID))
    assert excinfo.value.status_code == 422


def test_predictions_cover_supported_devices_only(world):
    run(ml_service.train_for_house(HOUSE_ID, OWNER_ID))
    response = run(ml_service.predict_usage(HOUSE_ID, OWNER_ID, 12))
    names = {p.device_name for p in response.predictions}
    assert names == {"Lamp", "AC"}
    assert all(len(p.hours) == 12 for p in response.predictions)
    assert all(0.0 <= h.probability_on <= 1.0 for p in response.predictions for h in p.hours)


def test_predictions_need_a_trained_model(world):
    with pytest.raises(HTTPException) as excinfo:
        run(ml_service.predict_usage(HOUSE_ID, OWNER_ID, 12))
    assert excinfo.value.status_code == 404


def test_anomaly_endpoint_flags_planted_day(world):
    response = run(ml_service.find_anomalies(HOUSE_ID, OWNER_ID))
    assert response.devices_checked >= 1
    expected = (world["start"] + timedelta(days=world["anomaly_day"], hours=1)).date()
    assert any(a.device_name == "Lamp" and a.date == expected for a in response.anomalies)


def test_ml_recommendation_when_lamp_is_on_on_a_saturday_morning(world, monkeypatch):
    # In the synthetic routine the lamp is never used at weekends.
    run(ml_service.train_for_house(HOUSE_ID, OWNER_ID))
    saturday_3am = datetime(2026, 9, 5, 3, 0, tzinfo=ml_core.ZoneInfo(ml_core.LOCAL_TZ))
    monkeypatch.setattr(ml_core, "local_now", lambda: saturday_3am)

    advice = run(recommendation_service.build_recommendations(HOUSE_ID, OWNER_ID))
    ml_advice = [a for a in advice if a.source == "ml"]
    assert len(ml_advice) == 1
    assert ml_advice[0].device_id == str(world["light_id"])
    assert ml_advice[0].probability_on < recommendation_service.ML_LOW_PROBABILITY
    assert ml_advice[0].suggested_state == {"is_on": False}


def test_no_ml_recommendation_when_lamp_is_normally_on(world, monkeypatch):
    run(ml_service.train_for_house(HOUSE_ID, OWNER_ID))
    wednesday_8pm = datetime(2026, 9, 2, 20, 0, tzinfo=ml_core.ZoneInfo(ml_core.LOCAL_TZ))
    monkeypatch.setattr(ml_core, "local_now", lambda: wednesday_8pm)
    advice = run(recommendation_service.build_recommendations(HOUSE_ID, OWNER_ID))
    assert [a for a in advice if a.source == "ml"] == []


def test_recommendations_still_work_without_a_model(world):
    advice = run(recommendation_service.build_recommendations(HOUSE_ID, OWNER_ID))
    assert [a for a in advice if a.source == "ml"] == []


def test_automation_history_round_trip(world):
    rule = {"_id": ObjectId(), "name": "Night light"}
    now = datetime.now(UTC)
    run(automation_history_service.record_rule_execution(
        HOUSE_ID, rule, now, [{"device_id": "d1", "device_name": "Lamp", "new_state": {"is_on": True}}]
    ))
    run(automation_history_service.record_rule_execution(
        HOUSE_ID, {"_id": ObjectId(), "name": "Other"}, now - timedelta(minutes=1), []
    ))
    entries = run(automation_history_service.list_history(HOUSE_ID, OWNER_ID))
    assert [e.rule_name for e in entries] == ["Night light", "Other"]  # newest first
    only_one = run(automation_history_service.list_history(HOUSE_ID, OWNER_ID, rule_id=str(rule["_id"])))
    assert len(only_one) == 1 and only_one[0].actions_applied == 1
    with pytest.raises(HTTPException):
        run(automation_history_service.list_history(HOUSE_ID, OWNER_ID, rule_id="not-an-id"))
