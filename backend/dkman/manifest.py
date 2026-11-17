from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,62}$")]
ApiPath = Annotated[str, StringConstraints(pattern=r"^/[a-zA-Z0-9/_-]*$")]
Version = Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
Image = Annotated[
    str,
    StringConstraints(
        pattern=r"^(sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9./:_-]*(@sha256:[a-f0-9]{64}|:[0-9]+\.[0-9]+\.[0-9]+))$"
    ),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class UI(StrictModel):
    display_name: str = Field(alias="displayName", min_length=1, max_length=120)
    icon: Literal["notebook", "activity", "grid"] = "grid"
    route: ApiPath


class Runtime(StrictModel):
    deployment_provider: Literal["docker-compose"] = Field(alias="deploymentProvider")
    image: Image
    internal_port: int = Field(alias="internalPort", ge=1024, le=65535)
    memory_mb: int = Field(default=128, alias="memoryMb", ge=32, le=1024)
    cpus: float = Field(default=0.5, ge=0.1, le=2)


class Health(StrictModel):
    live_path: ApiPath = Field(alias="livePath")
    ready_path: ApiPath = Field(alias="readyPath")


class ManifestCapability(StrictModel):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$")]
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: ApiPath
    permission: Literal["member", "developer", "operator", "admin"]


class Dependency(StrictModel):
    type: Literal["database", "service"]
    capability: Identifier
    required: bool = True


class Manifest(StrictModel):
    schema_version: Literal["dkman.io/v1alpha1"] = Field(alias="schemaVersion")
    id: Identifier
    name: str = Field(min_length=1, max_length=120)
    version: Version
    type: Literal["web-app", "api"]
    description: str = Field(default="", max_length=2000)
    ui: UI
    runtime: Runtime
    health: Health
    capabilities: list[ManifestCapability] = Field(default_factory=list, max_length=40)
    dependencies: list[Dependency] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def consistent_paths(self) -> "Manifest":
        if self.ui.route != f"/run/{self.id}/":
            raise ValueError("UI route must match /run/{id}/")
        for path in [self.health.live_path, self.health.ready_path] + [
            item.path for item in self.capabilities
        ]:
            if "//" in path:
                raise ValueError("Paths may not contain double slashes")
        keys = [item.id for item in self.capabilities]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate capability ID")
        return self


def parse_manifest(text: str) -> Manifest:
    if len(text.encode()) > 65536:
        raise ValueError("Manifest exceeds 64 KiB")
    return Manifest.model_validate(yaml.safe_load(text))
