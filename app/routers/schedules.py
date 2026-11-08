from fastapi import APIRouter, Depends, status

from app.models.schedule import ScheduleCreate, ScheduleResponse
from app.routers.auth import get_current_user
from app.services import schedule_service

router = APIRouter(tags=["Schedules"])


@router.post("/houses/{house_id}/schedules", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(house_id: str, data: ScheduleCreate, current_user: dict = Depends(get_current_user)):
    return await schedule_service.create_schedule(house_id, str(current_user["_id"]), data)


@router.get("/houses/{house_id}/schedules", response_model=list[ScheduleResponse])
async def list_schedules(house_id: str, current_user: dict = Depends(get_current_user)):
    return await schedule_service.list_schedules(house_id, str(current_user["_id"]))


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(schedule_id: str, current_user: dict = Depends(get_current_user)):
    await schedule_service.delete_schedule(schedule_id, str(current_user["_id"]))