from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field


class EnvironmentState(BaseModel):
    temperature: float = Field(default=28.0, description="°C")
    humidity: float = Field(default=65.0, description="%")
    light_level: float = Field(default=30.0, description="0-100")
    occupancy: bool = False
    smoke_detected: bool = False
    last_updated: datetime


class SimulationStatus(BaseModel):
    is_running: bool = False
    speed: float = Field(default=1.0, ge=0.1, le=60.0)  # 1.0 = real time
    started_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    simulated_seconds: float = 0.0  # total simulated time advanced
    last_tick_at: Optional[datetime] = None


class HouseSimulationState(BaseModel):
    house_id: str
    environment: EnvironmentState
    simulation: SimulationStatus


class SimulationControl(BaseModel):
    action: Literal["start", "pause", "resume", "reset"]
    speed: Optional[float] = Field(default=None, ge=0.1, le=60.0)


class TickRequest(BaseModel):
    """Manually advance the simulation by a number of simulated seconds."""
    seconds: float = Field(default=60.0, gt=0, le=3600)
