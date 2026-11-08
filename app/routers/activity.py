from typing import List

from fastapi import APIRouter, Depends, Query

from app.models.activity import ActivityLogResponse
from app.routers.auth import get_current_user
from app.services import activity_service
from app.services.house_service import get_house_by_id

router = APIRouter(tags=["Activity"])


@router.get("/houses/{house_id}/activity", response_model=List[ActivityLogResponse])
async def get_house_activity(
    house_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    # Ownership check
    await get_house_by_id(house_id, str(current_user["_id"]))
    return await activity_service.get_activity_for_house(
        house_id, str(current_user["_id"]), limit=limit
    )


@router.get("/activity/me", response_model=List[ActivityLogResponse])
async def get_my_recent_activity(
    limit: int = Query(default=30, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    return await activity_service.get_recent_activity_for_user(
        str(current_user["_id"]), limit=limit
    )
