from datetime import datetime, time, timezone
from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from app.core.realtime import manager
from app.db.mongodb import get_database
from app.models.automation import (
    AutomationRuleCreate,
    AutomationRuleResponse,
    AutomationRuleUpdate,
    EvaluationResponse,
    RuleCondition,
    RuleExecutionResult,
)
from app.services.activity_service import log_activity
from app.services.energy_service import record_power_transition
from app.services.house_service import get_house_by_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_rule(doc: dict) -> AutomationRuleResponse:
    return AutomationRuleResponse(
        id=str(doc["_id"]),
        house_id=str(doc["house_id"]),
        name=doc["name"],
        enabled=doc.get("enabled", True),
        priority=doc.get("priority", 0),
        cooldown_seconds=doc.get("cooldown_seconds", 60),
        conditions=doc.get("conditions", []),
        actions=doc.get("actions", []),
        last_triggered_at=doc.get("last_triggered_at"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    try:
        if operator == "eq":
            return actual == expected
        if operator == "neq":
            return actual != expected
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
    except TypeError:
        return False
    return False


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _in_time_window(cond: dict, now: datetime) -> bool:
    days = cond.get("days")
    if days is not None and now.weekday() not in days:
        return False
    start = cond.get("start_time")
    end = cond.get("end_time")
    if not start or not end:
        return True
    current = now.time()
    start_t = _parse_hhmm(start)
    end_t = _parse_hhmm(end)
    if start_t <= end_t:
        return start_t <= current <= end_t
    return current >= start_t or current <= end_t


def _condition_met(cond: dict, devices_by_id: dict, environment: dict, now: datetime) -> bool:
    ctype = cond.get("type")
    if ctype == "device_state":
        device = devices_by_id.get(cond.get("device_id"))
        if not device:
            return False
        actual = device.get("state", {}).get(cond.get("field"))
        return _compare(actual, cond.get("operator", "eq"), cond.get("value"))
    if ctype == "environment":
        actual = environment.get(cond.get("field"))
        return _compare(actual, cond.get("operator", "eq"), cond.get("value"))
    if ctype == "time_window":
        return _in_time_window(cond, now)
    return False


async def create_rule(house_id: str, owner_id: str, data: AutomationRuleCreate) -> AutomationRuleResponse:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    now = _now()
    doc = {
        "house_id": ObjectId(house_id),
        "owner_id": ObjectId(owner_id),
        "name": data.name,
        "enabled": data.enabled,
        "priority": data.priority,
        "cooldown_seconds": data.cooldown_seconds,
        "conditions": [c.model_dump() for c in data.conditions],
        "actions": [a.model_dump() for a in data.actions],
        "last_triggered_at": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await db["automation_rules"].insert_one(doc)
    created = await db["automation_rules"].find_one({"_id": result.inserted_id})
    await log_activity(
        user_id=owner_id,
        house_id=house_id,
        action="other",
        message=f"Created automation rule '{data.name}'",
        payload={"rule_id": str(created["_id"])},
    )
    return _to_rule(created)


async def list_rules(house_id: str, owner_id: str) -> list[AutomationRuleResponse]:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    cursor = db["automation_rules"].find({"house_id": ObjectId(house_id)}).sort("priority", -1)
    return [_to_rule(doc) async for doc in cursor]


async def update_rule(rule_id: str, owner_id: str, data: AutomationRuleUpdate) -> AutomationRuleResponse:
    db = get_database()
    try:
        oid = ObjectId(rule_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid rule ID")
    existing = await db["automation_rules"].find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")
    await get_house_by_id(str(existing["house_id"]), owner_id)
    update_data = data.model_dump(exclude_unset=True)
    if update_data.get("conditions") is not None:
        update_data["conditions"] = [
            c.model_dump() if isinstance(c, RuleCondition) else c for c in update_data["conditions"]
        ]
    if update_data.get("actions") is not None:
        update_data["actions"] = [
            a.model_dump() if hasattr(a, "model_dump") else a for a in update_data["actions"]
        ]
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    update_data["updated_at"] = _now()
    result = await db["automation_rules"].find_one_and_update(
        {"_id": oid},
        {"$set": update_data},
        return_document=True,
    )
    return _to_rule(result)


async def delete_rule(rule_id: str, owner_id: str) -> None:
    db = get_database()
    try:
        oid = ObjectId(rule_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid rule ID")
    existing = await db["automation_rules"].find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")
    await get_house_by_id(str(existing["house_id"]), owner_id)
    await db["automation_rules"].delete_one({"_id": oid})


async def evaluate_rules(house_id: str, owner_id: str) -> EvaluationResponse:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    now = _now()
    devices = [d async for d in db["devices"].find({"house_id": ObjectId(house_id)})]
    devices_by_id = {str(d["_id"]): d for d in devices}
    sim = await db["simulations"].find_one({"house_id": ObjectId(house_id)})
    environment = (sim or {}).get("environment", {})
    rules = [
        r
        async for r in db["automation_rules"]
        .find({"house_id": ObjectId(house_id), "enabled": True})
        .sort("priority", -1)
    ]
    results: list[RuleExecutionResult] = []

    for rule in rules:
        last = rule.get("last_triggered_at")
        cooldown = rule.get("cooldown_seconds", 60)
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (now - last).total_seconds() < cooldown:
                results.append(
                    RuleExecutionResult(
                        rule_id=str(rule["_id"]),
                        rule_name=rule["name"],
                        triggered=False,
                        skipped_reason="cooldown",
                    )
                )
                continue

        conditions_ok = all(
            _condition_met(c, devices_by_id, environment, now) for c in rule.get("conditions", [])
        )
        if not conditions_ok:
            results.append(
                RuleExecutionResult(
                    rule_id=str(rule["_id"]),
                    rule_name=rule["name"],
                    triggered=False,
                    skipped_reason="conditions_not_met",
                )
            )
            continue

        applied = 0
        for action in rule.get("actions", []):
            if action.get("type") != "set_device_state":
                continue
            device = devices_by_id.get(action.get("device_id"))
            if not device:
                continue
            requested = action.get("state") or {}
            current = device.get("state", {})
            if all(current.get(k) == v for k, v in requested.items()):
                continue
            merged = {**current, **requested}
            on_since = await record_power_transition(device, merged)
            await db["devices"].update_one(
                {"_id": device["_id"]},
                {"$set": {"state": merged, "on_since": on_since, "updated_at": now}},
            )
            device["state"] = merged
            device["on_since"] = on_since
            applied += 1
            await log_activity(
                user_id=owner_id,
                house_id=house_id,
                room_id=str(device["room_id"]) if device.get("room_id") else None,
                device_id=str(device["_id"]),
                action="device_state_changed",
                message=f"Automation '{rule['name']}' updated '{device.get('name')}'",
                payload={"new_state": merged, "rule_id": str(rule["_id"])},
            )

        if applied > 0:
            await db["automation_rules"].update_one(
                {"_id": rule["_id"]},
                {"$set": {"last_triggered_at": now, "updated_at": now}},
            )
            await manager.broadcast(
                house_id,
                "automation_applied",
                {"rule_id": str(rule["_id"]), "rule_name": rule["name"], "actions_applied": applied},
            )

        results.append(
            RuleExecutionResult(
                rule_id=str(rule["_id"]),
                rule_name=rule["name"],
                triggered=applied > 0,
                skipped_reason=None if applied > 0 else "already_in_state",
                actions_applied=applied,
            )
        )

    return EvaluationResponse(house_id=house_id, results=results)