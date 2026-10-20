"""Short-lived delegation from the trusted Core; never accepts user OIDC tokens."""

import time
from datetime import datetime
from typing import Literal
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from dkman.deployments.contracts import READ_ACTIONS, Action

ISSUER = "dkman-core"
AUDIENCE = "dkman-deployment-adapter"


class Delegation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    iss: Literal["dkman-core"]
    aud: Literal["dkman-deployment-adapter"]
    sub: str = Field(min_length=1, max_length=255)
    roles: list[Literal["admin", "operator", "developer", "member"]]
    jti: UUID
    action: Action | Literal["plan", "operation.read", "reconcile"]
    resource_id: UUID
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    iat: StrictInt
    exp: StrictInt
    approval_id: UUID | None = None
    approval_expires_at: StrictInt | None = None


def sign_delegation(
    *,
    secret: bytes,
    subject: str,
    roles: list[str],
    operation_id: UUID,
    action: str,
    resource_id: UUID,
    plan_hash: str,
    approval_id: UUID | None = None,
    approval_expires_at: datetime | None = None,
) -> str:
    """Internal transport helper. Caller must first authorize and consume the Core approval.

    There is no HTTP endpoint issuing these tokens. P2-004 wires the Core state machine.
    """
    if len(secret) < 32:
        raise ValueError("Delegation secret must contain at least 32 bytes")
    now = int(time.time())
    expiry = int(approval_expires_at.timestamp()) if approval_expires_at else None
    claims = Delegation.model_validate(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": subject,
            "roles": roles,
            "jti": operation_id,
            "action": action,
            "resource_id": resource_id,
            "plan_hash": plan_hash,
            "iat": now,
            "exp": min(now + 60, expiry) if expiry else now + 60,
            "approval_id": approval_id,
            "approval_expires_at": expiry,
        }
    )
    return jwt.encode(claims.model_dump(mode="json"), secret, algorithm="HS256")


def verify_delegation(token: str, secret: bytes) -> Delegation:
    if len(secret) < 32:
        raise ValueError("Invalid delegation configuration")
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
    )
    grant = Delegation.model_validate(claims)
    now = int(time.time())
    if grant.exp > grant.iat + 60 or grant.exp <= now or grant.iat > now:
        raise ValueError("Invalid delegation lifetime")
    operator_actions = READ_ACTIONS | {"start", "stop", "restart", "operation.read", "reconcile"}
    required = {"admin", "operator"} if grant.action in operator_actions else {"admin"}
    if not required.intersection(grant.roles):
        raise PermissionError("Delegated role is not sufficient")
    if grant.action not in READ_ACTIONS | {"plan", "operation.read", "reconcile"}:
        if (
            grant.approval_id is None
            or grant.approval_expires_at is None
            or grant.approval_expires_at <= now
            or grant.exp > grant.approval_expires_at
        ):
            raise PermissionError("Mutation requires an unexpired bound approval")
    return grant
