"""Bounded source preparation for an operator-owned workspace root."""

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dkman.planning_schemas import PlanningHash, Requirements


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(min_length=1, max_length=64)
    content_hash: PlanningHash
    template: Literal["python-api", "react-spa", "fullstack-fastapi-react"]
    requirements: Requirements


class SourceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: GenerationRequest
    files: dict[str, str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_files(self) -> "SourceBundle":
        total = 0
        for name, content in self.files.items():
            path = PurePosixPath(name)
            if (
                len(name) > 240
                or "\\" in name
                or ":" in name
                or "\x00" in name
                or path.is_absolute()
                or path.as_posix() != name
                or any(part in {".", "..", ".git", ".local", ".env"} for part in path.parts)
                or not path.parts
            ):
                raise ValueError("unsafe_source_path")
            total += len(content.encode("utf-8"))
        if total > 1_000_000:
            raise ValueError("source_bundle_too_large")
        if any(
            str(parent) in self.files
            for name in self.files
            for parent in PurePosixPath(name).parents
        ):
            raise ValueError("conflicting_source_paths")
        return self


class CodingProvider(Protocol):
    def generate(self, request: GenerationRequest) -> SourceBundle:
        """Return source data; no workspace or execution authority."""
        ...


@dataclass(frozen=True)
class WorkspaceSnapshot:
    id: str
    path: Path
    source_hash: str
    file_count: int


def prepare_workspace(root: Path, bundle: SourceBundle) -> WorkspaceSnapshot:
    """Write inert files under a trusted root. This is not an execution sandbox."""
    root = root.absolute()
    if root.is_symlink() or root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("workspace_root_must_be_a_real_directory")
    bundle = SourceBundle.model_validate(bundle.model_dump())
    payload = json.dumps(
        bundle.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    identifier = str(uuid4())
    workspace = root / identifier
    workspace.mkdir(mode=0o700)
    try:
        for name, content in sorted(bundle.files.items()):
            destination = workspace / name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(
                destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
                target.write(content)
    except BaseException:
        shutil.rmtree(workspace)
        raise
    return WorkspaceSnapshot(
        identifier, workspace, hashlib.sha256(payload).hexdigest(), len(bundle.files)
    )
