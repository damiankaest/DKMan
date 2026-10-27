import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class Access:
    subject: str


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def current_access(authorization: Annotated[str | None, Header()] = None) -> Access:
    if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 16384:
        raise HTTPException(401, "OIDC access token required")
    try:
        installation = UUID(os.environ["DKMAN_INSTALLATION_ID"])
    except (KeyError, ValueError):
        raise HTTPException(503, "App identity is not configured") from None
    # Fixed destination, no redirects/proxies, no user-provided URLs or forwarded identities.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(
        f"http://core:8000/api/v1/apps/{installation}/access",
        headers={"Authorization": authorization},
    )
    try:
        with opener.open(request, timeout=3) as response:
            body = response.read(4097)
            if len(body) > 4096:
                raise ValueError()
            result = json.loads(body)
            if result["installation_id"] != str(installation) or not result["subject"]:
                raise ValueError()
            return Access(subject=str(result["subject"]))
    except urllib.error.HTTPError as error:
        status = error.code if error.code in {401, 403, 404} else 503
        raise HTTPException(
            status, "App access denied" if status != 503 else "Identity unavailable"
        ) from None
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Authorization unavailable") from None

