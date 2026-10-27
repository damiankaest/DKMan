"""Generate deterministic reviewed templates without treating requirements as code."""

import hashlib
import json
from pathlib import Path

from dkman.forge.workspace import GenerationRequest, SourceBundle

ASSET_ROOT = Path(__file__).with_name("starter_assets")


def assets(group: str, prefix: str = "") -> dict[str, str]:
    """Load only repository-owned template files; no path originates from user input."""
    root = ASSET_ROOT / group
    if not root.is_dir():
        raise RuntimeError("Forge starter assets are missing from the installation")
    result = {}
    for source in sorted(root.rglob("*")):
        if source.is_symlink():
            raise RuntimeError("Forge starter assets must not contain symlinks")
        if not source.is_file():
            continue
        path = source.relative_to(root).as_posix()
        if path.endswith(".tpl"):
            path = path[:-4]
        result[f"{prefix}{path}"] = source.read_text(encoding="utf-8")
    if not result:
        raise RuntimeError("Forge starter assets are empty")
    return result


class TemplateProvider:
    """Produce a deterministic workspace, without building or deploying it."""

    def generate(self, request: GenerationRequest) -> SourceBundle:
        metadata = (
            json.dumps(
                {
                    "plan_id": request.plan_id,
                    "content_hash": request.content_hash,
                    "template": request.template,
                    "requirements": request.requirements.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        files = assets("common")
        files["plan.json"] = metadata
        is_api = request.template in {"python-api", "fullstack-fastapi-react"}
        is_web = request.template in {"react-spa", "fullstack-fastapi-react"}
        if is_api:
            files.update(assets("api", "backend/"))
        if is_web:
            files.update(assets("web", "web/"))
        if request.template == "fullstack-fastapi-react":
            files.update(assets("fullstack"))
        app_id = "app-" + hashlib.sha256(request.plan_id.encode("utf-8")).hexdigest()[:12]
        kind = "api" if request.template == "python-api" else "web-app"
        # An actual image reference must come from the isolated build worker in P4-002.
        # The placeholder deliberately fails the runtime manifest validator.
        files["dkman.yaml.template"] = (
            "schemaVersion: dkman.io/v1alpha1\n"
            f"id: {app_id}\nname: DKMan starter\nversion: 0.1.0\ntype: {kind}\n"
            "description: Generated starter; replace image only after verified build\n"
            f"ui:\n  displayName: DKMan starter\n  icon: grid\n  route: /run/{app_id}/\n"
            "runtime:\n  deploymentProvider: docker-compose\n"
            "  image: BUILD_ARTIFACT_REQUIRED\n  internalPort: 8080\n"
            "health:\n  livePath: /health/live\n  readyPath: /health/ready\n"
            "capabilities: []\ndependencies: []\n"
        )
        return SourceBundle(request=request, files=files)
