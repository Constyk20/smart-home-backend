from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException

from app.core.realtime import manager
from app.db.mongodb import get_database
from app.models.simulation import (
    EnvironmentState,
    HouseSimulationState,
    SimulationControl,
    SimulationStatus,
)
from app.services.activity_service import log_activity
from app.services.automation_service import evaluate_rules
from app.services.house_service import get_house_by_id

DEFAULT_ENVIRONMENT = {
    "temperature": 30.0,
    "humidity": 65.0,
    "light_level": 25.0,
    "occupancy": False,
    "smoke_detected": False,
}

# Abuja-like idle outdoor target used when cooling is off.
IDLE_TEMPERATURE = 31.0
IDLE_HUMIDITY = 60.0
IDLE_LIGHT = 20.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _approach(current: float, target: float, rate_per_hour: float, hours: float) -> float:
    """Move current toward target by at most rate_per_hour * hours."""
    if hours <= 0 or rate_per_hour <= 0:
        return current
    delta = target - current
    step = rate_per_hour * hours
    if abs(delta) <= step:
        return target
    return current + step if delta > 0 else current - step


def _to_state(doc: dict) -> HouseSimulationState:
    env = doc.get("environment", {})
    sim = doc.get("simulation", {})
    return HouseSimulationState(
        house_id=str(doc["house_id"]),
        environment=EnvironmentState(
            temperature=env.get("temperature", 30.0),
            humidity=env.get("humidity", 65.0),
            light_level=env.get("light_level", 25.0),
            occupancy=env.get("occupancy", False),
            smoke_detected=env.get("smoke_detected", False),
            last_updated=env.get("last_updated", _now()),
        ),
        simulation=SimulationStatus(
            is_running=sim.get("is_running", False),
            speed=sim.get("speed", 1.0),
            started_at=sim.get("started_at"),
            paused_at=sim.get("paused_at"),
            simulated_seconds=sim.get("simulated_seconds", 0.0),
            last_tick_at=sim.get("last_tick_at"),
        ),
    )


async def _get_or_create_sim_doc(house_id: str) -> dict:
    db = get_database()
    doc = await db["simulations"].find_one({"house_id": ObjectId(house_id)})
    if doc:
        return doc
    now = _now()
    new_doc = {
        "house_id": ObjectId(house_id),
        "environment": {**DEFAULT_ENVIRONMENT, "last_updated": now},
        "simulation": {
            "is_running": False,
            "speed": 1.0,
            "started_at": None,
            "paused_at": None,
            "simulated_seconds": 0.0,
            "last_tick_at": None,
        },
        "created_at": now,
        "updated_at": now,
    }
    await db["simulations"].insert_one(new_doc)
    return await db["simulations"].find_one({"house_id": ObjectId(house_id)})


def apply_device_effects(env: dict, devices: list[dict], seconds: float) -> dict:
    """Deterministic environment step. seconds is simulated time, not a random draw."""
    hours = max(0.0, seconds) / 3600.0
    temperature = float(env.get("temperature", 30.0))
    humidity = float(env.get("humidity", 65.0))
    light_level = float(env.get("light_level", 25.0))

    ac_target = None
    fan_speed_sum = 0.0
    exhaust_on = False
    light_target = IDLE_LIGHT

    for device in devices:
        dtype = device.get("device_type")
        state = device.get("state", {})
        if dtype == "air_conditioner" and state.get("is_on"):
            ac_target = float(state.get("target_temp", 24))
        elif dtype == "fan" and state.get("is_on"):
            fan_speed_sum += float(state.get("speed", 1))
        elif dtype == "exhaust_fan" and state.get("is_on"):
            exhaust_on = True
        elif dtype == "light" and state.get("is_on"):
            light_target = min(100.0, light_target + float(state.get("brightness", 100)) * 0.5)

    if ac_target is not None:
        # About 4°C per simulated hour toward the setpoint.
        temperature = _approach(temperature, ac_target, 4.0, hours)
    else:
        temperature = _approach(temperature, IDLE_TEMPERATURE, 0.5, hours)

    if fan_speed_sum > 0:
        temperature = _approach(temperature, temperature - 1.5, 0.4 * fan_speed_sum, hours)
        humidity = _approach(humidity, humidity - 5, 1.0 * fan_speed_sum, hours)
    if exhaust_on:
        humidity = _approach(humidity, humidity - 8, 2.0, hours)

    humidity = _approach(humidity, IDLE_HUMIDITY, 0.8, hours)
    light_level = _approach(light_level, light_target, 40.0, hours)

    env["temperature"] = round(max(16.0, min(40.0, temperature)), 2)
    env["humidity"] = round(max(20.0, min(95.0, humidity)), 2)
    env["light_level"] = round(max(0.0, min(100.0, light_level)), 2)
    env["last_updated"] = _now()
    return env


async def _advance(house_id: str, owner_id: str, seconds: float) -> dict:
    db = get_database()
    doc = await _get_or_create_sim_doc(house_id)
    now = _now()
    sim = doc.get("simulation", {})
    env = dict(doc.get("environment", {**DEFAULT_ENVIRONMENT}))
    devices = [d async for d in db["devices"].find({"house_id": ObjectId(house_id)})]

    env = apply_device_effects(env, devices, seconds)
    sim["simulated_seconds"] = float(sim.get("simulated_seconds", 0.0)) + seconds
    sim["last_tick_at"] = now

    await db["simulations"].update_one(
        {"house_id": ObjectId(house_id)},
        {"$set": {"environment": env, "simulation": sim, "updated_at": now}},
    )
    await db["environment_history"].insert_one(
        {
            "house_id": ObjectId(house_id),
            "temperature": env["temperature"],
            "humidity": env["humidity"],
            "light_level": env["light_level"],
            "occupancy": env.get("occupancy", False),
            "simulated_seconds": sim["simulated_seconds"],
            "step_seconds": seconds,
            "created_at": now,
        }
    )

    await evaluate_rules(house_id, owner_id)
    updated = await db["simulations"].find_one({"house_id": ObjectId(house_id)})
    await manager.broadcast(
        house_id,
        "simulation_ticked",
        {
            "temperature": updated["environment"].get("temperature"),
            "humidity": updated["environment"].get("humidity"),
            "light_level": updated["environment"].get("light_level"),
            "simulated_seconds": updated["simulation"].get("simulated_seconds"),
        },
    )
    return updated


async def get_simulation_state(house_id: str, owner_id: str) -> HouseSimulationState:
    await get_house_by_id(house_id, owner_id)
    return _to_state(await _get_or_create_sim_doc(house_id))


async def control_simulation(house_id: str, owner_id: str, control: SimulationControl) -> HouseSimulationState:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    doc = await _get_or_create_sim_doc(house_id)
    now = _now()
    sim = doc.get("simulation", {})

    if control.action == "reset":
        sim = {
            "is_running": False,
            "speed": control.speed if control.speed is not None else 1.0,
            "started_at": None,
            "paused_at": None,
            "simulated_seconds": 0.0,
            "last_tick_at": None,
        }
        await db["simulations"].update_one(
            {"house_id": ObjectId(house_id)},
            {"$set": {"environment": {**DEFAULT_ENVIRONMENT, "last_updated": now}, "simulation": sim, "updated_at": now}},
        )
        await log_activity(user_id=owner_id, house_id=house_id, action="other", message="Simulation reset")
        return _to_state(await db["simulations"].find_one({"house_id": ObjectId(house_id)}))

    if control.action == "start":
        sim["is_running"] = True
        sim["started_at"] = now
        sim["paused_at"] = None
        sim["last_tick_at"] = now
        message = "Simulation started"
    elif control.action == "pause":
        sim["is_running"] = False
        sim["paused_at"] = now
        message = "Simulation paused"
    elif control.action == "resume":
        sim["is_running"] = True
        sim["paused_at"] = None
        sim["last_tick_at"] = now
        message = "Simulation resumed"
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    if control.speed is not None and control.action != "pause":
        sim["speed"] = control.speed

    await db["simulations"].update_one(
        {"house_id": ObjectId(house_id)},
        {"$set": {"simulation": sim, "updated_at": now}},
    )
    await log_activity(
        user_id=owner_id,
        house_id=house_id,
        action="other",
        message=message,
        payload={"action": control.action, "speed": sim.get("speed")},
    )
    return _to_state(await db["simulations"].find_one({"house_id": ObjectId(house_id)}))


async def tick_simulation(house_id: str, owner_id: str, seconds: float = 60.0) -> HouseSimulationState:
    await get_house_by_id(house_id, owner_id)
    updated = await _advance(house_id, owner_id, seconds)
    return _to_state(updated)


async def advance_running_simulations() -> None:
    """Called by the single background worker. No request user: owner comes from the house."""
    db = get_database()
    now = _now()
    cursor = db["simulations"].find({"simulation.is_running": True})
    async for doc in cursor:
        sim = doc.get("simulation", {})
        last = sim.get("last_tick_at")
        speed = float(sim.get("speed", 1.0))
        if not last:
            await db["simulations"].update_one({"_id": doc["_id"]}, {"$set": {"simulation.last_tick_at": now}})
            continue
        wall = (now - _as_utc(last)).total_seconds()
        simulated = wall * speed
        if simulated < 1:
            continue
        house = await db["houses"].find_one({"_id": doc["house_id"]})
        if not house:
            continue
        await _advance(str(doc["house_id"]), str(house["owner_id"]), simulated)
