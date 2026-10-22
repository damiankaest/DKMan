"""Versioned planning data. Free text is never an executable tool or deployment plan."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

PlanningText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
PlanningHash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class Requirements(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=4000)
    features: list[PlanningText] = Field(min_length=1, max_length=30)
    entities: list[PlanningText] = Field(default_factory=list, max_length=30)
    screens: list[PlanningText] = Field(default_factory=list, max_length=30)
    acceptance_checks: list[PlanningText] = Field(default_factory=list, max_length=30)
    deployment_requirements: list[PlanningText] = Field(default_factory=list, max_length=30)


class RequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    household_id: str | None = Field(default=None, min_length=1, max_length=64)
    requirements: Requirements


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    requirements: Requirements


class PlanDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    planning_mode: Literal["manual"] = "manual"
    household_id: str | None
    requirements: Requirements


class RequestView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    requested_by: str
    household_id: str | None
    current_revision: int
    created_at: datetime
    updated_at: datetime


class PlanView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    request_id: str
    revision: int
    document: PlanDocument
    content_hash: PlanningHash
    created_by: str
    created_at: datetime
    approved_job_id: str | None


class PlanApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_hash: PlanningHash


class PlanApprovalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    action: Literal["app_plan.approve"] = "app_plan.approve"
    resource_type: Literal["app_plan"] = "app_plan"
    resource_id: str
    subject: str
    request_id: str
    revision: int
    content_hash: PlanningHash
