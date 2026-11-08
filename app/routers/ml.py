from fastapi import APIRouter, Depends, Query

from app.models.ml import AnomalyResponse, ModelInfo, PredictionResponse
from app.routers.auth import get_current_user
from app.services import ml_service

router = APIRouter(tags=["ML"])


@router.get("/houses/{house_id}/ml/status", response_model=ModelInfo)
async def model_status(house_id: str, current_user: dict = Depends(get_current_user)):
    """Whether a usage model exists for this house, and how well it did on held-out history."""
    return await ml_service.get_model_info(house_id, str(current_user["_id"]))


@router.post("/houses/{house_id}/ml/train", response_model=ModelInfo)
async def train_model(house_id: str, current_user: dict = Depends(get_current_user)):
    """Train (or retrain) this house's usage model from its logged device history."""
    return await ml_service.train_for_house(house_id, str(current_user["_id"]))


@router.get("/houses/{house_id}/ml/predictions", response_model=PredictionResponse)
async def predictions(
    house_id: str,
    hours: int = Query(default=12, ge=1, le=24),
    current_user: dict = Depends(get_current_user),
):
    """Estimated chance each device is normally ON in each of the next `hours` hours."""
    return await ml_service.predict_usage(house_id, str(current_user["_id"]), hours)


@router.get("/houses/{house_id}/ml/anomalies", response_model=AnomalyResponse)
async def anomalies(house_id: str, current_user: dict = Depends(get_current_user)):
    """Days when a device's runtime pattern was unusual compared with its own history."""
    return await ml_service.find_anomalies(house_id, str(current_user["_id"]))