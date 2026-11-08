from typing import List

from fastapi import APIRouter, Depends, status

from app.models.house import HouseCreate, HouseUpdate, HouseResponse
from app.routers.auth import get_current_user
from app.services import house_service

router = APIRouter(prefix="/houses", tags=["Houses"])


@router.post("", response_model=HouseResponse, status_code=status.HTTP_201_CREATED)
async def create_house(
    data: HouseCreate,
    current_user: dict = Depends(get_current_user),
):
    return await house_service.create_house(str(current_user["_id"]), data)


@router.get("", response_model=List[HouseResponse])
async def list_my_houses(current_user: dict = Depends(get_current_user)):
    return await house_service.get_houses_for_user(str(current_user["_id"]))


@router.get("/{house_id}", response_model=HouseResponse)
async def get_house(
    house_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await house_service.get_house_by_id(house_id, str(current_user["_id"]))


@router.patch("/{house_id}", response_model=HouseResponse)
async def update_house(
    house_id: str,
    data: HouseUpdate,
    current_user: dict = Depends(get_current_user),
):
    return await house_service.update_house(house_id, str(current_user["_id"]), data)


@router.delete("/{house_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_house(
    house_id: str,
    current_user: dict = Depends(get_current_user),
):
    await house_service.delete_house(house_id, str(current_user["_id"]))
