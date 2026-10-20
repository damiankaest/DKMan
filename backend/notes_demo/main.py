"""Notes data API. Every data request is authorized by Core using the real OIDC token."""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from notes_demo.database import database_engine


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
    installation = UUID(os.environ["NOTES_INSTALLATION_ID"])
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


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=4000)


class NoteView(NoteInput):
    id: UUID
    author_subject: str
    created_at: datetime


def create_app(engine: Engine | None = None, static_root: Path | None = None) -> FastAPI:
    engine = engine or database_engine()
    assets = static_root or Path("/app/web")
    app = FastAPI(title="DKMan Notes", version="0.1.0", docs_url=None, redoc_url=None)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_: Any, error: SQLAlchemyError) -> JSONResponse:
        return JSONResponse({"detail": "Notes database unavailable"}, status_code=503)

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/health/ready")
    def ready() -> dict[str, str]:
        with engine.connect() as connection:
            if connection.scalar(text("SELECT version FROM notes_schema")) != 1:
                raise HTTPException(503, "Notes migration required")
        return {"status": "healthy"}

    @app.get("/api/notes", response_model=list[NoteView])
    def notes(actor: Annotated[Access, Depends(current_access)], response: Response) -> Any:
        response.headers["Cache-Control"] = "no-store"
        with engine.connect() as connection:
            return list(
                connection.execute(
                    text(
                        "SELECT id, author_subject, text, created_at FROM notes "
                        "ORDER BY created_at DESC, id DESC LIMIT 100"
                    )
                ).mappings()
            )

    @app.post("/api/notes", response_model=NoteView, status_code=201)
    def create_note(body: NoteInput, actor: Annotated[Access, Depends(current_access)]) -> Any:
        with engine.begin() as connection:
            return (
                connection.execute(
                    text(
                        "INSERT INTO notes (id, author_subject, text) VALUES (:id, :author, :text) "
                        "RETURNING id, author_subject, text, created_at"
                    ),
                    {"id": str(uuid4()), "author": actor.subject, "text": body.text},
                )
                .mappings()
                .one()
            )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(assets / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/assets/{name}")
    def asset(name: str) -> FileResponse:
        if not name or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for char in name
        ):
            raise HTTPException(404)
        path = assets / "assets" / name
        if not path.is_file() or path.is_symlink():
            raise HTTPException(404)
        return FileResponse(path)

    return app
