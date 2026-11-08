from typing import List

from fastapi import APIRouter, Depends, status

from app.models.device import (
    DeviceCreate,
    DeviceUpdate,
    DeviceStateUpdate,
    DeviceResponse,
)
from app.routers.auth import get_current_user
from app.services import device_service

router = APIRouter(tags=["Devices"])


@router.post(
    "/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_device(
    data: DeviceCreate,
    current_user: dict = Depends(get_current_user),
):
    return await device_service.create_device(str(current_user["_id"]), data)


@router.get("/houses/{house_id}/devices", response_model=List[DeviceResponse])
async def list_devices_in_house(
    house_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await device_service.get_devices_for_house(house_id, str(current_user["_id"]))


@router.get("/rooms/{room_id}/devices", response_model=List[DeviceResponse])
async def list_devices_in_room(
    room_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await device_service.get_devices_for_room(room_id, str(current_user["_id"]))


@router.get("/devices/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await device_service.get_device_by_id(device_id, str(current_user["_id"]))


@router.patch("/devices/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: str,
    data: DeviceUpdate,
    current_user: dict = Depends(get_current_user),
):
    return await device_service.update_device(device_id, str(current_user["_id"]), data)


@router.put("/devices/{device_id}/state", response_model=DeviceResponse)
async def update_device_state(
    device_id: str,
    data: DeviceStateUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update the live state of a device (on/off, brightness, temperature, etc.)."""
    return await device_service.update_device_state(
        device_id, str(current_user["_id"]), data
    )


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: str,
    current_user: dict = Depends(get_current_user),
):
    await device_service.delete_device(device_id, str(current_user["_id"]))
