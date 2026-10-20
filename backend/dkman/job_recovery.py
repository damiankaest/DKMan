"""Startup/periodic metadata recovery. This module never executes job actions."""

import asyncio
import logging

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from dkman.jobs import recover

logger = logging.getLogger("dkman.recovery")


def recover_once(engine: Engine) -> int:
    try:
        with Session(engine) as db:
            return recover(db)
    except SQLAlchemyError:
        # DB unavailable or migration not yet applied: readiness stays unhealthy;
        # next tick retries metadata recovery, never the action itself.
        logger.warning("Job metadata recovery unavailable")
        return 0


async def recovery_loop(engine: Engine) -> None:
    while True:
        await asyncio.sleep(15)
        await asyncio.to_thread(recover_once, engine)
