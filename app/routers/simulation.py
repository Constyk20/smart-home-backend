from fastapi import APIRouter, Depends

from app.models.simulation import (
    HouseSimulationState,
    SimulationControl,
    TickRequest,
)
from app.routers.auth import get_current_user
from app.services import simulation_service

router = APIRouter(prefix="/houses/{house_id}/simulation", tags=["Simulation"])


@router.get("", response_model=HouseSimulationState)
async def get_simulation(
    house_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await simulation_service.get_simulation_state(
        house_id, str(current_user["_id"])
    )


@router.post("/control", response_model=HouseSimulationState)
async def control_simulation(
    house_id: str,
    control: SimulationControl,
    current_user: dict = Depends(get_current_user),
):
    return await simulation_service.control_simulation(
        house_id, str(current_user["_id"]), control
    )


@router.post("/tick", response_model=HouseSimulationState)
async def tick_simulation(
    house_id: str,
    body: TickRequest,
    current_user: dict = Depends(get_current_user),
):
    """Manually advance the simulation (useful for testing and for the future background worker)."""
    return await simulation_service.tick_simulation(
        house_id, str(current_user["_id"]), seconds=body.seconds
    )
