from fastapi import APIRouter, Depends, Query

from app.models.energy import HouseEnergySummary, TariffUpdate, DeviceWattageUpdate
from app.routers.auth import get_current_user
from app.services import energy_service

router = APIRouter(tags=["Energy"])


@router.get("/houses/{house_id}/energy", response_model=HouseEnergySummary)
async def get_energy_summary(
    house_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await energy_service.get_house_energy_summary(
        house_id, str(current_user["_id"])
    )


@router.put("/houses/{house_id}/energy/tariff")
async def set_tariff(
    house_id: str,
    data: TariffUpdate,
    current_user: dict = Depends(get_current_user),
):
    return await energy_service.update_tariff(
        house_id, str(current_user["_id"]), data
    )


@router.put("/devices/{device_id}/wattage")
async def set_device_wattage(
    device_id: str,
    data: DeviceWattageUpdate,
    current_user: dict = Depends(get_current_user),
):
    return await energy_service.update_device_wattage(
        device_id, str(current_user["_id"]), data
    )


@router.get("/houses/{house_id}/energy/history")
async def energy_history(
    house_id: str,
    days: int = Query(default=7, ge=1, le=31),
    current_user: dict = Depends(get_current_user),
):
    return await energy_service.get_energy_history(
        house_id, str(current_user["_id"]), days=days
    )