from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


ConditionType = Literal["device_state", "environment", "time_window"]
Operator = Literal["eq", "neq", "gt", "gte", "lt", "lte"]


class RuleCondition(BaseModel):
    type: ConditionType
    # device_state
    device_id: Optional[str] = None
    field: Optional[str] = None
    operator: Operator = "eq"
    value: Optional[Any] = None
    # time_window — 24h "HH:MM", days 0=Monday ... 6=Sunday
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    days: Optional[list[int]] = None


class RuleAction(BaseModel):
    type: Literal["set_device_state"] = "set_device_state"
    device_id: str
    state: dict[str, Any]


class AutomationRuleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    enabled: bool = True
    priority: int = Field(default=0, ge=0, le=100)
    cooldown_seconds: int = Field(default=60, ge=0, le=86400)
    conditions: list[RuleCondition] = Field(min_length=1)
    actions: list[RuleAction] = Field(min_length=1)


class AutomationRuleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    enabled: Optional[bool] = None
    priority: Optional[int] = Field(default=None, ge=0, le=100)
    cooldown_seconds: Optional[int] = Field(default=None, ge=0, le=86400)
    conditions: Optional[list[RuleCondition]] = None
    actions: Optional[list[RuleAction]] = None


class AutomationRuleResponse(BaseModel):
    id: str
    house_id: str
    name: str
    enabled: bool
    priority: int
    cooldown_seconds: int
    conditions: list[RuleCondition]
    actions: list[RuleAction]
    last_triggered_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class RuleExecutionResult(BaseModel):
    rule_id: str
    rule_name: str
    triggered: bool
    skipped_reason: Optional[str] = None
    actions_applied: int = 0


class EvaluationResponse(BaseModel):
    house_id: str
    results: list[RuleExecutionResult]
