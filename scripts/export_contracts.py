"""Export versioned contracts without connecting to PostgreSQL or an identity provider."""

import json
from pathlib import Path

from sqlalchemy import create_engine

from dkman.config import Settings
from dkman.main import create_app
from dkman.manifest import Manifest

root = Path(__file__).resolve().parents[1]
app = create_app(Settings(), engine=create_engine("sqlite://"))
for path, content in [
    (root / "contracts/openapi/core.v1.json", app.openapi()),
    (
        root / "contracts/manifests/dkman.v1alpha1.schema.json",
        Manifest.model_json_schema(by_alias=True),
    ),
]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n")
