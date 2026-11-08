from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Recommendation(BaseModel):
    id: str
    # "rule" = fixed if/then logic. "ml" = produced from a trained model's estimate.
    source: Literal["rule", "ml"] = "rule"
    house_id: str
    device_id: Optional[str] = None
    title: str
    reason: str
    suggested_state: Optional[dict[str, Any]] = None
    # Only set for source="ml": the model's estimated chance the device is normally ON at
    # this hour. An estimate from past habits, not a calibrated certainty.
    probability_on: Optional[float] = Field(default=None, ge=0, le=1)
    model_trained_at: Optional[datetime] = None


class FeedbackCreate(BaseModel):
    recommendation_id: str
    accepted: bool
    note: Optional[str] = Field(default=None, max_length=300)


class FeedbackResponse(BaseModel):
    id: str
    house_id: str
    recommendation_id: str
    accepted: bool
    note: Optional[str] = None
    created_at: datetime
