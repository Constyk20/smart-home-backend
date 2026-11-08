"""Execution history for automation rules.

Only firings that changed a device are stored. Evaluations skipped for cooldown or unmet
conditions happen on every tick and are not recorded, to keep the collection meaningful.
"""
import logging
from datetime import datetime
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException

from app.db.mongodb import get_database
from app.models.automation_history import AutomationHistoryEntry
from app.services.house_service import get_house_by_id

logger = logging.getLogger(__name__)

COLLECTION = "automation_history"


async def record_rule_execution(
    house_id: str, rule: dict[str, Any], executed_at: datetime, changes: list[dict[str, Any]]
) -> None:
    """Called by evaluate_rules. A failure here must never stop rule evaluation."""
    try:
        await get_database()[COLLECTION].insert_one(
            {
                "house_id": ObjectId(house_id),
                "rule_id": rule["_id"],
                "rule_name": rule["name"],
                "executed_at": executed_at,
                "actions_applied": len(changes),
                "changes": changes,
            }
        )
    except Exception:
        logger.exception("Could not record automation history for rule %s", rule.get("_id"))


async def list_history(
    house_id: str, owner_id: str, limit: int = 50, rule_id: Optional[str] = None
) -> list[AutomationHistoryEntry]:
    await get_house_by_id(house_id, owner_id)
    query: dict[str, Any] = {"house_id": ObjectId(house_id)}
    if rule_id is not None:
        try:
            query["rule_id"] = ObjectId(rule_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid rule ID")

    cursor = get_database()[COLLECTION].find(query).sort("executed_at", -1).limit(limit)
    return [
        AutomationHistoryEntry(
            id=str(doc["_id"]),
            house_id=str(doc["house_id"]),
            rule_id=str(doc["rule_id"]),
            rule_name=doc["rule_name"],
            executed_at=doc["executed_at"],
            actions_applied=doc.get("actions_applied", 0),
            changes=doc.get("changes", []),
        )
        async for doc in cursor
    ]
