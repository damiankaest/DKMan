from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, PyJWKClientConnectionError

from dkman.config import Settings

ROLE_NAMES = {"member", "developer", "operator", "admin"}
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    subject: str
    display_name: str
    roles: frozenset[str]


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.keys = PyJWKClient(settings.oidc_jwks_url, cache_jwk_set=True, timeout=3)

    def verify(self, token: str) -> Principal:
        try:
            key = self.keys.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
                leeway=5,
            )
            roles = claims.get("realm_access", {}).get("roles", [])
            if not isinstance(roles, list) or not isinstance(claims["sub"], str):
                raise jwt.InvalidTokenError()
            if not claims["sub"]:
                raise jwt.InvalidTokenError()
            return Principal(
                subject=claims["sub"],
                display_name=str(claims.get("preferred_username", claims["sub"])),
                roles=frozenset(role for role in roles if role in ROLE_NAMES),
            )
        except PyJWKClientConnectionError as exc:
            raise HTTPException(503, "Identity provider unavailable") from exc
        except (jwt.PyJWTError, ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(
                401, "Invalid access token", headers={"WWW-Authenticate": "Bearer"}
            ) from exc


def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    verifier: TokenVerifier = request.app.state.verifier
    return verifier.verify(credentials.credentials)


def require_admin(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if "admin" not in principal.roles:
        raise HTTPException(403, "Admin role required")
    return principal
