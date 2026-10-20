"""Core-side typed HTTP transport. Does not import adapter execution code."""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from uuid import UUID

from dkman.deployments.contracts import (
    DeploymentCommand,
    DeploymentPlan,
    OperationView,
    PlanRequest,
)


class AdapterUnavailable(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class HttpDeploymentClient:
    def __init__(self, endpoint: str = "http://deployment-adapter:8010"):
        parsed = urllib.parse.urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"deployment-adapter", "localhost", "127.0.0.1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Deployment endpoint must be the configured internal adapter")
        self.endpoint = endpoint.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path: str, token: str, body: dict[str, Any] | None = None) -> bytes:
        request = urllib.request.Request(
            self.endpoint + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=120) as response:
                result = bytes(response.read(65537))
                if len(result) > 65536:
                    raise AdapterUnavailable("Adapter response exceeds limit")
                return result
        except (OSError, urllib.error.HTTPError) as error:
            raise AdapterUnavailable(
                "Adapter request unavailable; query the existing operation ID"
            ) from error

    def plan(self, request: PlanRequest, token: str) -> DeploymentPlan:
        return DeploymentPlan.model_validate_json(
            self.request("/v1/plans", token, request.model_dump(mode="json"))
        )

    def execute(self, operation_id: UUID, command: DeploymentCommand, token: str) -> OperationView:
        return OperationView.model_validate_json(
            self.request(f"/v1/operations/{operation_id}", token, command.model_dump(mode="json"))
        )

    def operation(
        self, operation_id: UUID, token: str, *, reconcile: bool = False
    ) -> OperationView:
        suffix = "/reconcile" if reconcile else ""
        return OperationView.model_validate_json(
            self.request(f"/v1/operations/{operation_id}{suffix}", token)
        )
