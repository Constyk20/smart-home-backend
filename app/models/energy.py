from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DeviceEnergyInfo(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    wattage: float = Field(description="Watts")
    is_on: bool
    estimated_kwh_today: float
    estimated_cost_today: float  # in Naira


class HouseEnergySummary(BaseModel):
    house_id: str
    tariff_per_kwh: float = Field(description="₦ per kWh")
    total_kwh_today: float
    total_cost_today: float
    devices: list[DeviceEnergyInfo]
    last_calculated_at: datetime


class TariffUpdate(BaseModel):
    tariff_per_kwh: float = Field(gt=0, description="Electricity tariff in Nigerian Naira per kWh")


class DeviceWattageUpdate(BaseModel):
    wattage: float = Field(gt=0, description="Power rating in Watts")
