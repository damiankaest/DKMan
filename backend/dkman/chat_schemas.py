"""A closed intent vocabulary. Model text never supplies an executable tool or URL."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dkman.job_schemas import JobState
from dkman.planning_schemas import Requirements
from dkman.schemas import AppView

IntentKind = Literal[
    "help",
    "apps.search",
    "registry.search",
    "jobs.status",
    "app.draft",
    "runtime.start",
    "runtime.stop",
    "runtime.restart",
    "catalog.install",
]


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=4000)


class IntentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: IntentKind
    query: str | None = Field(default=None, min_length=1, max_length=120)
    target: str | None = Field(default=None, min_length=1, max_length=120)
    requirements: Requirements | None = None

    @model_validator(mode="after")
    def compatible_arguments(self) -> Self:
        fields = {"query", "target", "requirements"}
        allowed = {
            "apps.search": {"query"},
            "registry.search": {"query"},
            "jobs.status": {"target"},
            "app.draft": {"requirements"},
            "runtime.start": {"target"},
            "runtime.stop": {"target"},
            "runtime.restart": {"target"},
            "catalog.install": {"target"},
        }.get(self.kind, set())
        if any(getattr(self, field) is not None for field in fields - allowed):
            raise ValueError("Unexpected intent argument")
        if self.kind == "app.draft" and self.requirements is None:
            raise ValueError("Requirements missing")
        if self.kind.startswith("runtime.") or self.kind == "catalog.install":
            if not self.target:
                raise ValueError("Target missing")
        return self


class ProviderView(BaseModel):
    mode: Literal["rules", "external"]
    label: str
    notice: str


class RegistryMatch(BaseModel):
    id: str
    name: str
    version: str
    description: str
    capabilities: list[str]


class ChatEvent(BaseModel):
    sequence: int
    kind: str
    state: JobState
    created_at: datetime


class ChatJob(BaseModel):
    id: str
    action: str
    state: JobState
    updated_at: datetime
    events: list[ChatEvent]


class DraftProposal(BaseModel):
    kind: Literal["app.draft"] = "app.draft"
    requirements: Requirements


class RuntimeProposal(BaseModel):
    kind: Literal["runtime"] = "runtime"
    installation_id: str
    name: str
    action: Literal["start", "stop", "restart"]


class InstallProposal(BaseModel):
    kind: Literal["catalog.install"] = "catalog.install"
    definition_id: str
    name: str
    version: str


class ChatView(BaseModel):
    provider: ProviderView
    intent: IntentKind
    summary: str
    observed_at: datetime
    apps: list[AppView] = Field(default_factory=list)
    registry: list[RegistryMatch] = Field(default_factory=list)
    jobs: list[ChatJob] = Field(default_factory=list)
    proposal: DraftProposal | RuntimeProposal | InstallProposal | None = None
