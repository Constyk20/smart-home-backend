from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ModelMetrics(BaseModel):
    """Measured on the latest 20% of the house's own history, which the model never saw in training."""

    accuracy: float
    f1: float
    baseline_majority_accuracy: float
    beats_majority_baseline: bool
    train_rows: int
    test_rows: int
    positive_rate_test: float


class ModelInfo(BaseModel):
    house_id: str
    trained: bool
    trained_at: Optional[datetime] = None
    model_type: Optional[str] = None
    metrics: Optional[ModelMetrics] = None
    n_events: Optional[int] = None
    automation_event_share: Optional[float] = None
    history_start: Optional[datetime] = None
    history_end: Optional[datetime] = None
    timezone: Optional[str] = None
    data_origin: Literal["logged_events"] = "logged_events"
    synthetic: bool = False
    notes: list[str] = Field(default_factory=list)


class HourPrediction(BaseModel):
    hour_start: datetime
    probability_on: float


class DevicePrediction(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    hours: list[HourPrediction]


class PredictionResponse(BaseModel):
    house_id: str
    source: Literal["ml"] = "ml"
    generated_at: datetime
    model_trained_at: Optional[datetime] = None
    model_beats_baseline: bool
    note: str
    predictions: list[DevicePrediction]


class AnomalyItem(BaseModel):
    device_id: str
    device_name: str
    date: date
    on_hours: float
    typical_on_hours: float
    anomaly_score: float


class AnomalyResponse(BaseModel):
    house_id: str
    source: Literal["ml"] = "ml"
    generated_at: datetime
    devices_checked: int
    devices_skipped: int
    note: str
    anomalies: list[AnomalyItem]
