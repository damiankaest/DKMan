"""Signed build evidence. An attestation is not a preview or deployment approval."""

import base64
import binascii
import hashlib
import json
import os
import stat
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from dkman.forge.build_recipe import (
    CHECK_LOCK,
    checks_dockerfile,
    expected_checks,
    image_dockerfile,
)
from dkman.forge.oci import MAX_ARCHIVE, sha256_file
from dkman.forge.workspace import SourceBundle
from dkman.planning_schemas import PlanningHash

DOMAIN = b"dkman-forge-build-attestation-v1\x00"
PREVIEW_DOMAIN = b"dkman-forge-preview-attestation-v1\x00"
OciDigest = Annotated[str, StringConstraints(pattern=r"^sha256:[a-f0-9]{64}$")]


class BuildEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    build_id: UUID
    workspace_id: UUID
    source_hash: PlanningHash
    plan_hash: PlanningHash
    template: Literal["python-api", "react-spa", "fullstack-fastapi-react"]
    checks: list[Literal["api-passed", "web-passed"]] = Field(min_length=1, max_length=2)
    manifest_digest: OciDigest
    config_digest: OciDigest
    archive_sha256: PlanningHash
    archive_size: int = Field(gt=0, le=MAX_ARCHIVE, strict=True)
    check_recipe_sha256: PlanningHash
    check_requirements_sha256: PlanningHash
    image_recipe_sha256: PlanningHash
    finished_at: AwareDatetime

    @model_validator(mode="after")
    def checks_match_template(self) -> "BuildEvidence":
        if self.checks != expected_checks(self.template):
            raise ValueError("incomplete_checks")
        return self


class SignedBuildEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    algorithm: Literal["ed25519"] = "ed25519"
    key_id: PlanningHash
    evidence: BuildEvidence
    signature: str = Field(min_length=88, max_length=88, pattern=r"^[A-Za-z0-9+/]{86}==$")


class PreviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    preview_id: UUID
    artifact_id: UUID
    workspace_id: UUID
    artifact_evidence_hash: PlanningHash
    source_hash: PlanningHash
    plan_hash: PlanningHash
    manifest_digest: OciDigest
    config_digest: OciDigest
    container_id: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    state: Literal["healthy"] = "healthy"

    @model_validator(mode="after")
    def bounded_lifetime(self) -> "PreviewEvidence":
        if self.expires_at <= self.observed_at or self.expires_at > self.observed_at + timedelta(
            minutes=15
        ):
            raise ValueError("invalid_preview_lifetime")
        return self


class SignedPreviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    algorithm: Literal["ed25519"] = "ed25519"
    key_id: PlanningHash
    evidence: PreviewEvidence
    signature: str = Field(min_length=88, max_length=88, pattern=r"^[A-Za-z0-9+/]{86}==$")


def canonical_bytes(evidence: BuildEvidence | PreviewEvidence) -> bytes:
    domain = DOMAIN if isinstance(evidence, BuildEvidence) else PREVIEW_DOMAIN
    return domain + json.dumps(
        evidence.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def key_id(public: Ed25519PublicKey) -> str:
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()


def sign_evidence(evidence: BuildEvidence, private: Ed25519PrivateKey) -> SignedBuildEvidence:
    return SignedBuildEvidence(
        key_id=key_id(private.public_key()),
        evidence=evidence,
        signature=base64.b64encode(private.sign(canonical_bytes(evidence))).decode("ascii"),
    )


def verify_signature(signed: SignedBuildEvidence, public: Ed25519PublicKey) -> None:
    try:
        signature = base64.b64decode(signed.signature, validate=True)
        if len(signature) != 64 or signed.key_id != key_id(public):
            raise ValueError("untrusted_signing_key")
        public.verify(signature, canonical_bytes(signed.evidence))
    except (InvalidSignature, binascii.Error) as exc:
        raise ValueError("invalid_build_signature") from exc


def sign_preview(evidence: PreviewEvidence, private: Ed25519PrivateKey) -> SignedPreviewEvidence:
    return SignedPreviewEvidence(
        key_id=key_id(private.public_key()),
        evidence=evidence,
        signature=base64.b64encode(private.sign(canonical_bytes(evidence))).decode("ascii"),
    )


def verify_preview_signature(signed: SignedPreviewEvidence, public: Ed25519PublicKey) -> None:
    try:
        signature = base64.b64decode(signed.signature, validate=True)
        if len(signature) != 64 or signed.key_id != key_id(public):
            raise ValueError("untrusted_preview_key")
        public.verify(signature, canonical_bytes(signed.evidence))
    except (InvalidSignature, binascii.Error) as exc:
        raise ValueError("invalid_preview_signature") from exc


def read_public_key(path: Path) -> Ed25519PublicKey:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("invalid_public_key_file")
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("ed25519_public_key_required")
    return key


def read_private_key(path: Path) -> Ed25519PrivateKey:
    path = path.absolute()
    if path.resolve(strict=True) != path:
        raise ValueError("private_key_path_must_not_use_symlinks")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_size > 4096
        ):
            raise ValueError("private_key_must_be_owned_and_private")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(4097)
    finally:
        os.close(descriptor)
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("ed25519_private_key_required")
    return key


def verify_recipe(evidence: BuildEvidence, bundle: SourceBundle) -> None:
    if (
        evidence.plan_hash != bundle.request.content_hash
        or evidence.template != bundle.request.template
        or evidence.check_recipe_sha256
        != hashlib.sha256(checks_dockerfile(evidence.template).encode("utf-8")).hexdigest()
        or evidence.check_requirements_sha256 != sha256_file(CHECK_LOCK)
        or evidence.image_recipe_sha256
        != hashlib.sha256(image_dockerfile(bundle).encode("utf-8")).hexdigest()
    ):
        raise ValueError("build_recipe_or_plan_mismatch")
