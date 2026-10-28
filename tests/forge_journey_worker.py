"""CI-only worker: real build, preview and staging for an approved Core workspace."""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from uuid import UUID, uuid4

from dkman.deployment_adapter.compose import ComposeProvider
from dkman.deployment_adapter.forge_preview import fetch_artifact, start_preview
from dkman.deployment_adapter.forge_staging import stage_archive
from dkman.forge.attestation import SignedBuildEvidence, SignedPreviewEvidence, read_private_key
from dkman.forge.build_worker import execute_build, fetch_input


def main(workspace_id: str) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") != "1"
    ):
        raise ValueError("Disposable CI only")
    workspace = str(UUID(workspace_id))
    token = sys.stdin.read().strip()
    root = Path(__file__).resolve().parents[1] / ".local/forge"
    worker = root / "worker"
    builder = read_private_key(root / "forge-build-private.pem")
    preview_key = read_private_key(root / "forge-preview-private.pem")
    buildctl, docker = shutil.which("buildctl"), shutil.which("docker")
    assert buildctl and docker
    origin = "http://127.0.0.1:8080"

    def source():
        return fetch_input(origin, workspace, token)

    result = execute_build(
        source, worker, os.environ["DKMAN_TEST_BUILDKIT_SOCKET"], buildctl, builder
    )
    if result["state"] != "succeeded":
        raise ValueError("Real CI build did not succeed")
    artifact_dir = worker / result["build_id"]
    archive = artifact_dir / "image.oci.tar"
    signed = SignedBuildEvidence.model_validate_json(
        (artifact_dir / "build-attestation.json").read_text()
    )

    def post(path: str, payload: dict):
        request = urllib.request.Request(
            origin + path,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    registered_data = post(
        f"/api/v1/forge/workspaces/{workspace}/build-artifacts", signed.model_dump(mode="json")
    )
    registered = fetch_artifact(origin, signed.evidence.build_id, token)
    assert registered_data["id"] == registered.id

    def authorize():
        return source(), fetch_artifact(origin, signed.evidence.build_id, token)

    seen = []

    def ready(url, proof):
        with urllib.request.urlopen(url + "/", timeout=5) as response:
            assert b"<html" in response.read(4096).lower()
        seen.append(proof)

    preview = start_preview(
        signed,
        authorize,
        builder.public_key(),
        preview_key,
        archive,
        worker,
        ComposeProvider(worker, uuid4(), docker),
        ttl_seconds=900,
        on_ready=ready,
        hold=lambda _: None,
    )
    assert preview["state"] == "stopped" and len(seen) == 1
    proof = SignedPreviewEvidence.model_validate_json(Path(seen[0]).read_text())
    observed = post(
        f"/api/v1/forge/build-artifacts/{registered.id}/previews", proof.model_dump(mode="json")
    )
    private_stage = worker / f"stage-{uuid4()}"
    private_stage.mkdir(mode=0o700)
    staged = stage_archive(signed, authorize, builder.public_key(), archive, private_stage)
    target = root / "staged" / str(signed.evidence.build_id)
    subprocess.run(["sudo", "cp", "-a", "--", str(staged), str(target)], check=True)
    subprocess.run(["sudo", "chown", "-R", "10001:10001", "--", str(target)], check=True)
    print(json.dumps({"preview_id": observed["id"], "build_id": registered.id}))


if __name__ == "__main__":
    main(sys.argv[1])
