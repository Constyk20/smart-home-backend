from fastapi import APIRouter, Depends, status

from app.models.recommendation import FeedbackCreate, FeedbackResponse, Recommendation
from app.routers.auth import get_current_user
from app.services.recommendation_service import build_recommendations, save_feedback

router = APIRouter(prefix="/houses/{house_id}/recommendations", tags=["Recommendations"])


@router.get("", response_model=list[Recommendation])
async def list_recommendations(house_id: str, current_user: dict = Depends(get_current_user)):
    return await build_recommendations(house_id, str(current_user["_id"]))


@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def give_feedback(
    house_id: str,
    data: FeedbackCreate,
    current_user: dict = Depends(get_current_user),
):
    return await save_feedback(house_id, str(current_user["_id"]), data)