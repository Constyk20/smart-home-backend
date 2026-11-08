from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AutomationHistoryEntry(BaseModel):
    """One time an automation rule fired and changed at least one device."""

    id: str
    house_id: str
    rule_id: str
    rule_name: str
    executed_at: datetime
    actions_applied: int
    changes: list[dict[str, Any]] = Field(default_factory=list)
