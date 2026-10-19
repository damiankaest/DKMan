from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

HealthStatus = Literal["healthy", "starting", "degraded", "unhealthy", "stopped", "unknown"]


class MeView(BaseModel):
    subject: str
    display_name: str
    roles: list[str]


class DefinitionView(BaseModel):
    id: str
    name: str
    version: str
    description: str
    source: str


class AppView(BaseModel):
    id: str
    definition_id: str
    name: str
    version: str
    description: str
    status: HealthStatus
    checked_at: datetime | None
    route: str | None


class ServiceView(BaseModel):
    id: str
    installation_id: str
    provider: str
    status: HealthStatus
    checked_at: datetime | None
    reason: str | None


class CapabilityView(BaseModel):
    id: str
    definition_id: str
    permission: str
    method: str
    path: str


class HealthView(BaseModel):
    status: Literal["healthy", "unhealthy"]
    checked_at: datetime
    database: Literal["ready", "unavailable"]
    schema_state: Literal["current", "unavailable"] = Field(serialization_alias="schema")
