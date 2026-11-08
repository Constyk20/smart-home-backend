from typing import List

from fastapi import APIRouter, Depends, status

from app.models.room import RoomCreate, RoomUpdate, RoomResponse
from app.routers.auth import get_current_user
from app.services import room_service

router = APIRouter(tags=["Rooms"])


@router.post(
    "/houses/{house_id}/rooms",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_room(
    house_id: str,
    data: RoomCreate,
    current_user: dict = Depends(get_current_user),
):
    return await room_service.create_room(house_id, str(current_user["_id"]), data)


@router.get("/houses/{house_id}/rooms", response_model=List[RoomResponse])
async def list_rooms(
    house_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await room_service.get_rooms_for_house(house_id, str(current_user["_id"]))


@router.get("/rooms/{room_id}", response_model=RoomResponse)
async def get_room(
    room_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await room_service.get_room_by_id(room_id, str(current_user["_id"]))


@router.patch("/rooms/{room_id}", response_model=RoomResponse)
async def update_room(
    room_id: str,
    data: RoomUpdate,
    current_user: dict = Depends(get_current_user),
):
    return await room_service.update_room(room_id, str(current_user["_id"]), data)


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    room_id: str,
    current_user: dict = Depends(get_current_user),
):
    await room_service.delete_room(room_id, str(current_user["_id"]))
