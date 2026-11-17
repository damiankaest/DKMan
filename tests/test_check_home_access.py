"""Checks for the read-only home network acceptance helper."""

import io
import json
from urllib.error import HTTPError
from urllib.parse import urlsplit

import pytest
from scripts import check_home_access


class Response(io.BytesIO):
    def __init__(self, status, body=b""):
        super().__init__(body)
        self.status = status


class FakeOpener:
    def __init__(self, issuer, override=None):
        self.issuer = issuer
        self.override = override or {}

    def open(self, request, timeout):
        assert request.method == "GET"
        assert timeout == 10
        path = urlsplit(request.full_url).path
        status = self.override.get(path, 401 if path == "/api/v1/me" else 200)
        if status != 200:
            raise HTTPError(request.full_url, status, "error", {}, io.BytesIO())
        body = json.dumps({"issuer": self.issuer}).encode()
        return Response(status, body)


def test_home_access_checks_actual_issuer_and_anonymous_api(monkeypatch):
    origin = "https://dkman.example"
    monkeypatch.setattr(
        check_home_access, "build_opener", lambda *_: FakeOpener(origin + "/auth/realms/dkman")
    )
    assert check_home_access.check(origin) == []


def test_home_access_rejects_wrong_issuer_redirect_and_public_api(monkeypatch):
    monkeypatch.setattr(
        check_home_access,
        "build_opener",
        lambda *_: FakeOpener("https://localhost/auth/realms/dkman", {"/": 302, "/api/v1/me": 200}),
    )
    assert check_home_access.check("https://dkman.example") == [
        "Hub",
        "OIDC",
        "Anonymer API-Zugriff",
    ]


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:8080",
        "https://a/b",
        "https://x:y@host",
        "https://host/?x=1",
        "https://host:999999",
    ],
)
def test_requires_https_origin(origin):
    with pytest.raises(ValueError):
        check_home_access.check(origin)
