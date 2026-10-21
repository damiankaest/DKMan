"""Pure, action-specific checks. A current healthy workload is never execution proof."""

from datetime import datetime
from uuid import UUID

from dkman.deployments.contracts import (
    CompletionEvidence,
    DeploymentCommand,
    EngineReceipt,
    RuntimeView,
    WorkloadEvidence,
)


def prove_completion(
    command: DeploymentCommand,
    operation_id: UUID,
    created_at: datetime,
    receipt: EngineReceipt,
    after: WorkloadEvidence,
) -> tuple[CompletionEvidence, RuntimeView]:
    plan = command.plan
    if (
        receipt.operation_id != operation_id
        or receipt.installation_id != plan.installation_id
        or receipt.action != command.action
        or receipt.plan_hash != command.plan_hash
        or not created_at
        <= receipt.before.observed_at
        <= receipt.acknowledged_at
        <= after.observed_at
    ):
        raise ValueError("Receipt binding or execution interval mismatch")
    expected = {"app", "database"} if plan.profile == "notes-postgres-v1" else {"app"}
    before = {c.service: c for c in receipt.before.containers}
    current = {c.service: c for c in after.containers}
    if len(current) != len(after.containers) or set(current) != expected:
        raise ValueError("Incomplete current workload")
    if command.action == "install":
        if before:
            raise ValueError("Installation was not absent")
    elif set(before) != expected or len(before) != len(receipt.before.containers):
        raise ValueError("Incomplete original workload")
    for name, item in current.items():
        volumes = (
            [f"{plan.project}-data"]
            if (name == "database" or (name == "app" and plan.data_path is not None))
            else []
        )
        reference = plan.database_image if name == "database" else plan.image
        if (
            item.runtime_plan_hash != plan.plan_hash
            or item.volumes != volumes
            or (reference and reference.startswith("sha256:") and item.image_id != reference)
        ):
            raise ValueError("Runtime definition changed")
        previous = before.get(name)
        if previous and (
            previous.container_id != item.container_id
            or previous.image_id != item.image_id
            or previous.volumes != item.volumes
            or previous.runtime_plan_hash != item.runtime_plan_hash
        ):
            raise ValueError("Container identity changed")
        if command.action == "stop":
            if item.status != "exited":
                raise ValueError("Workload is not cleanly stopped")
            if previous and previous.status == "exited":
                if (item.started_at, item.finished_at) != (
                    previous.started_at,
                    previous.finished_at,
                ):
                    raise ValueError("Stopped workload changed after acknowledgement")
            elif not receipt.before.observed_at <= item.finished_at <= receipt.acknowledged_at:
                raise ValueError("Stop transition is not attributable to the acknowledged command")
        else:
            if item.status != "running" or item.health != "healthy":
                raise ValueError("Workload is not healthy")
            if not item.started_at <= receipt.acknowledged_at:
                raise ValueError("Workload started after acknowledgement")
            if command.action in {"restart", "install"} or (
                previous and previous.status != "running"
            ):
                if item.started_at < receipt.before.observed_at:
                    raise ValueError("No start transition in execution interval")
                if previous and item.started_at <= previous.started_at:
                    raise ValueError("Restart was not observed")
            elif previous and item.started_at != previous.started_at:
                raise ValueError("Unexpected start transition")
    evidence = CompletionEvidence(receipt=receipt, after=after)
    return evidence, RuntimeView(
        installation_id=plan.installation_id,
        state="stopped" if command.action == "stop" else "running",
        observed_at=after.observed_at,
        container_id=current["app"].container_id,
    )
