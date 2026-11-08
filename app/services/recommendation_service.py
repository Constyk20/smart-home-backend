import logging
from datetime import datetime, timezone
from uuid import uuid4

from bson import ObjectId

from app.db.mongodb import get_database
from app.models.recommendation import FeedbackCreate, FeedbackResponse, Recommendation
from app.services import ml_service
from app.services.house_service import get_house_by_id

logger = logging.getLogger(__name__)

# Only energy-saving suggestions for ordinary appliances. Doors, windows, curtains and
# cameras are never switched by a recommendation.
ML_RECOMMENDABLE_TYPES = {"light", "fan", "air_conditioner", "television", "exhaust_fan"}
ML_LOW_PROBABILITY = 0.15


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _ml_recommendations(
    house_id: str, devices: list[dict], already_advised: set[str]
) -> list[Recommendation]:
    """Suggestions from the trained usage model. Returns [] if the model is missing, did not
    beat its baseline, or anything goes wrong, so rule-based advice always still works."""
    try:
        result = await ml_service.current_hour_probabilities(house_id)
    except Exception:
        logger.exception("ML recommendations unavailable for house %s", house_id)
        return []
    if result is None:
        return []
    probabilities, meta, local_hour = result
    metrics = meta["metrics"]
    trained_at = datetime.fromisoformat(meta["trained_at"])

    advice: list[Recommendation] = []
    for device in devices:
        device_id = str(device["_id"])
        if device_id in already_advised or device.get("device_type") not in ML_RECOMMENDABLE_TYPES:
            continue
        if not device.get("state", {}).get("is_on"):
            continue
        probability = probabilities.get(device_id)
        if probability is None or probability >= ML_LOW_PROBABILITY:
            continue
        advice.append(
            Recommendation(
                id=str(uuid4()),
                source="ml",
                house_id=house_id,
                device_id=device_id,
                title=f"{device.get('name', 'Device')} is usually off at this hour",
                reason=(
                    f"In this house's history the model estimates a {probability:.0%} chance a "
                    f"{device['device_type'].replace('_', ' ')} is on around {local_hour:02d}:00. "
                    f"Learned from {meta['n_events']} logged changes; on held-out history the model "
                    f"scored {metrics['accuracy']:.0%} accuracy versus {metrics['baseline_majority_accuracy']:.0%} "
                    "for always guessing the majority. This is a habit estimate, not a certainty."
                    + (
                        " The model was trained on synthetic (generated) history, so this is a demonstration."
                        if meta.get("synthetic_event_share", 0) > 0
                        else ""
                    )
                ),
                suggested_state={"is_on": False},
                probability_on=round(probability, 3),
                model_trained_at=trained_at,
            )
        )
    return advice


async def build_recommendations(house_id: str, owner_id: str) -> list[Recommendation]:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    sim = await db["simulations"].find_one({"house_id": ObjectId(house_id)})
    temperature = (sim or {}).get("environment", {}).get("temperature")
    devices = [d async for d in db["devices"].find({"house_id": ObjectId(house_id)})]
    advice: list[Recommendation] = []

    for device in devices:
        state = device.get("state", {})
        dtype = device.get("device_type")
        if dtype == "air_conditioner" and state.get("is_on") and temperature is not None:
            target = float(state.get("target_temp", 24))
            if float(temperature) <= target:
                advice.append(
                    Recommendation(
                        id=str(uuid4()),
                        house_id=house_id,
                        device_id=str(device["_id"]),
                        title="Air conditioner can be turned off",
                        reason=(
                            f"Simulated temperature is {temperature}°C, which is already "
                            f"at or below the {target}°C setpoint. This is a rule, not a trained model."
                        ),
                        suggested_state={"is_on": False},
                    )
                )
        if dtype == "light" and state.get("is_on") and float(state.get("brightness", 100)) > 80:
            advice.append(
                Recommendation(
                    id=str(uuid4()),
                    house_id=house_id,
                    device_id=str(device["_id"]),
                    title="Lower the light brightness",
                    reason="This light is above 80% brightness. Reducing it lowers estimated wattage use. Rule, not a model.",
                    suggested_state={"is_on": True, "brightness": 60},
                )
            )

    # A device that already has a rule-based suggestion does not also get an ML one.
    advised_devices = {a.device_id for a in advice if a.device_id}
    advice.extend(await _ml_recommendations(house_id, devices, advised_devices))
    return advice


async def save_feedback(house_id: str, owner_id: str, data: FeedbackCreate) -> FeedbackResponse:
    await get_house_by_id(house_id, owner_id)
    db = get_database()
    doc = {
        "house_id": ObjectId(house_id),
        "user_id": ObjectId(owner_id),
        "recommendation_id": data.recommendation_id,
        "accepted": data.accepted,
        "note": data.note,
        "created_at": _now(),
    }
    result = await db["recommendation_feedback"].insert_one(doc)
    return FeedbackResponse(
        id=str(result.inserted_id),
        house_id=house_id,
        recommendation_id=data.recommendation_id,
        accepted=data.accepted,
        note=data.note,
        created_at=doc["created_at"],
    )
