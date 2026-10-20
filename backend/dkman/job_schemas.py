"""Only implemented actions are accepted; new actions need a typed server-side planner."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from dkman.deployments.contracts import DeploymentPlan, LifecyclePlan

JobState = Literal[
    "waiting_approval",
    "queued",
    "claimed",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "expired",
    "reconciliation_required",
]
ApprovalState = Literal["pending", "approved", "rejected", "expired", "consumed", "cancelled"]
Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class JobSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["registry.validate"]
    resource_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9-]{1,62}$")
    require_approval: bool = True
    approval_ttl_seconds: int = Field(default=900, ge=60, le=3600)


class ApprovalBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    subject: str = Field(min_length=1, max_length=255)
    action: str = Field(min_length=1, max_length=80)
    resource_type: str = Field(min_length=1, max_length=40)
    resource_id: str = Field(min_length=1, max_length=120)
    plan_hash: Hash
    expires_at: datetime


class ApprovalDecision(ApprovalBinding):
    decision: Literal["approve", "reject"]


class ApprovalView(ApprovalBinding):
    id: str
    job_id: str
    state: ApprovalState
    decided_by: str | None
    decided_at: datetime | None
    consumed_at: datetime | None


class ValidationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    action: Literal["registry.validate"]
    resource_type: Literal["app_definition"]
    resource_id: str
    subject: str
    manifest_id: str
    manifest_hash: Hash


class JobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    requested_by: str
    action: str
    resource_type: str
    resource_id: str
    risk: Literal["read_only", "reversible", "sensitive", "destructive"]
    state: JobState
    plan: ValidationPlan | DeploymentPlan | LifecyclePlan
    plan_hash: Hash
    requires_approval: bool
    attempt: int
    created_at: datetime
    updated_at: datetime
    execution_started_at: datetime | None
    finished_at: datetime | None
    failure_code: str | None
    result: dict[str, Any] | None


class JobEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sequence: int
    kind: str
    state: JobState
    actor_subject: str
    created_at: datetime
