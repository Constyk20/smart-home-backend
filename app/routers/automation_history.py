from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.models.automation_history import AutomationHistoryEntry
from app.routers.auth import get_current_user
from app.services import automation_history_service

router = APIRouter(tags=["Automation"])


@router.get("/houses/{house_id}/automation/history", response_model=List[AutomationHistoryEntry])
async def automation_history(
    house_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    rule_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Times automation rules fired and changed a device, newest first."""
    return await automation_history_service.list_history(
        house_id, str(current_user["_id"]), limit=limit, rule_id=rule_id
    )