from typing import List

from fastapi import APIRouter, Depends, status

from app.models.automation import (
    AutomationRuleCreate,
    AutomationRuleUpdate,
    AutomationRuleResponse,
    EvaluationResponse,
)
from app.routers.auth import get_current_user
from app.services import automation_service

router = APIRouter(tags=["Automation"])


@router.post(
    "/houses/{house_id}/automation/rules",
    response_model=AutomationRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule(
    house_id: str,
    data: AutomationRuleCreate,
    current_user: dict = Depends(get_current_user),
):
    return await automation_service.create_rule(house_id, str(current_user["_id"]), data)


@router.get("/houses/{house_id}/automation/rules", response_model=List[AutomationRuleResponse])
async def list_rules(house_id: str, current_user: dict = Depends(get_current_user)):
    return await automation_service.list_rules(house_id, str(current_user["_id"]))


@router.patch("/automation/rules/{rule_id}", response_model=AutomationRuleResponse)
async def update_rule(
    rule_id: str,
    data: AutomationRuleUpdate,
    current_user: dict = Depends(get_current_user),
):
    return await automation_service.update_rule(rule_id, str(current_user["_id"]), data)


@router.delete("/automation/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: str, current_user: dict = Depends(get_current_user)):
    await automation_service.delete_rule(rule_id, str(current_user["_id"]))


@router.post("/houses/{house_id}/automation/evaluate", response_model=EvaluationResponse)
async def evaluate(house_id: str, current_user: dict = Depends(get_current_user)):
    return await automation_service.evaluate_rules(house_id, str(current_user["_id"]))
