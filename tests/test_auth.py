import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt import PyJWK, PyJWKClientConnectionError

from dkman.auth import TokenVerifier
from dkman.config import Settings


@pytest.fixture
def signer(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = TokenVerifier(Settings())
    key = PyJWK.from_dict(
        jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    )
    monkeypatch.setattr(verifier.keys, "get_signing_key_from_jwt", lambda _: key)

    def sign(**overrides):
        claims = {
            "sub": "alice",
            "preferred_username": "Alice",
            "iat": int(time.time()),
            "exp": int(time.time()) + 120,
            "iss": verifier.settings.oidc_issuer,
            "aud": "dkman-api",
            "realm_access": {"roles": ["member", "unrelated"]},
        }
        claims.update(overrides)
        return jwt.encode(claims, private_key, algorithm="RS256")

    return verifier, sign


def test_real_signature_and_role_filter(signer):
    verifier, sign = signer
    principal = verifier.verify(sign())
    assert principal.subject == "alice"
    assert principal.roles == frozenset(["member"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": 1},
        {"aud": "other"},
        {"iss": "https://attacker.invalid"},
        {"sub": ""},
        {"realm_access": {"roles": "admin"}},
        {"realm_access": {"roles": [{}]}},
    ],
)
def test_invalid_tokens(signer, overrides):
    verifier, sign = signer
    with pytest.raises(HTTPException) as error:
        verifier.verify(sign(**overrides))
    assert error.value.status_code == 401


def test_forged_signature_and_algorithm(signer):
    verifier, sign = signer
    foreign = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = jwt.decode(sign(), options={"verify_signature": False})
    for token in [
        jwt.encode(claims, foreign, algorithm="RS256"),
        jwt.encode(claims, "test-secret-only-do-not-use-for-production", algorithm="HS256"),
        "not.a.token",
    ]:
        with pytest.raises(HTTPException) as error:
            verifier.verify(token)
        assert error.value.status_code == 401


def test_identity_outage_fails_closed(signer, monkeypatch):
    verifier, sign = signer

    def down(_):
        raise PyJWKClientConnectionError("private internal message")

    monkeypatch.setattr(verifier.keys, "get_signing_key_from_jwt", down)
    with pytest.raises(HTTPException) as error:
        verifier.verify(sign())
    assert error.value.status_code == 503
    assert "private" not in error.value.detail
