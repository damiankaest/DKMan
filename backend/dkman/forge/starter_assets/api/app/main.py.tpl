"""Minimal authenticated API. Database migrations are always explicit."""
import os
from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from app.access import Access, current_access

app = FastAPI(title="DKMan application starter", version="0.1.0", docs_url=None, redoc_url=None)


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/health/ready")
def ready() -> dict[str, str]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(503, "Database is not configured")
    engine = None
    try:
        engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
        with engine.connect() as connection:
            if connection.scalar(text("SELECT version_num FROM alembic_version")) != "0001_initial":
                raise HTTPException(503, "Database migration required")
    except SQLAlchemyError:
        raise HTTPException(503, "Database unavailable") from None
    finally:
        if engine is not None:
            engine.dispose()
    return {"status": "healthy"}


@app.get("/api/me")
def me(response: Response, actor: Annotated[Access, Depends(current_access)]) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    return {"subject": actor.subject}


# Only fullstack images configure this path; mount after the API and health routes.
static_root = os.environ.get("DKMAN_STATIC_ROOT")
if static_root:
    app.mount("/", StaticFiles(directory=static_root, html=True, check_dir=False), name="web")
