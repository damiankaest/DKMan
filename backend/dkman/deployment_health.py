"""Read-only runtime observations. Never restarts, installs or retries mutations."""

import asyncio
from uuid import UUID, uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from dkman.auth import Principal
from dkman.config import Settings
from dkman.deployment_api import credential, record_runtime
from dkman.deployments.client import HttpDeploymentClient
from dkman.deployments.contracts import DeploymentCommand, DeploymentPlan, RuntimeView
from dkman.models import AppInstallation, DeploymentTarget, Job, utcnow


def poll_once(engine: Engine, settings: Settings, client: HttpDeploymentClient) -> None:
    if not settings.deployment_enabled:
        return
    from dkman.runtime_api import installed_plan

    with Session(engine) as db:
        installations = list(
            db.scalars(
                select(AppInstallation)
                .join(DeploymentTarget, AppInstallation.id == DeploymentTarget.id)
                .order_by(DeploymentTarget.id)
                .limit(100)
            )
        )
        snapshots: list[tuple[str, DeploymentPlan | None]] = []
        for item in installations:
            try:
                snapshots.append((item.id, installed_plan(db, item)))
            except Exception:
                snapshots.append((item.id, None))
    actor = Principal("system:health", "Health poller", frozenset({"admin"}))
    for installation_id, snapshot in snapshots:
        try:
            if snapshot is None:
                raise ValueError("Installed runtime provenance unavailable")
            plan = snapshot
            read = Job(id=str(uuid4()), resource_id=installation_id, plan_hash=plan.plan_hash)
            token = credential(settings, actor, read, "status")
            result = client.execute(
                UUID(read.id), DeploymentCommand(action="status", plan=plan), token
            )
            if (
                result.state != "succeeded"
                or result.runtime is None
                or str(result.installation_id) != installation_id
                or result.runtime.installation_id != plan.installation_id
                or result.plan_hash != plan.plan_hash
                or result.operation_id != UUID(read.id)
                or result.action != "status"
            ):
                raise ValueError()
            runtime = result.runtime
        except Exception:
            runtime = RuntimeView(
                installation_id=UUID(installation_id), state="unknown", observed_at=utcnow()
            )
        with Session(engine) as db:
            record_runtime(db, installation_id, runtime)
            db.commit()


async def health_loop(engine: Engine, settings: Settings, client: HttpDeploymentClient) -> None:
    while True:
        await asyncio.sleep(15)
        try:
            await asyncio.to_thread(poll_once, engine, settings, client)
        except Exception:
            # The next request still treats expired observations as unknown.
            continue
