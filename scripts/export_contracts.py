"""Export versioned contracts without connecting to PostgreSQL or an identity provider."""

import json
from pathlib import Path

from sqlalchemy import create_engine

from dkman.config import Settings
from dkman.deployment_adapter.main import create_app as create_adapter_app
from dkman.deployments.contracts import DeploymentPlan
from dkman.main import create_app
from dkman.manifest import Manifest
from notes_demo.main import create_app as create_notes_app

root = Path(__file__).resolve().parents[1]
app = create_app(Settings(), engine=create_engine("sqlite://"))
for path, content in [
    (root / "contracts/openapi/core.v1.json", app.openapi()),
    (root / "contracts/openapi/deployment-adapter.v1.json", create_adapter_app().openapi()),
    (
        root / "contracts/openapi/notes.v1.json",
        create_notes_app(create_engine("sqlite://")).openapi(),
    ),
    (root / "contracts/deployments/plan.v1.schema.json", DeploymentPlan.model_json_schema()),
    (
        root / "contracts/manifests/dkman.v1alpha1.schema.json",
        Manifest.model_json_schema(by_alias=True),
    ),
]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n")
