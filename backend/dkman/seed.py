"""Explicit host-admin bootstrap of bundled metadata; never creates an installation."""

import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dkman.auth import Principal
from dkman.config import Settings
from dkman.manifest import parse_manifest
from dkman.models import AppDefinition
from dkman.registry import register_manifest


def seed(session: Session, examples: Path) -> int:
    count = 0
    actor = Principal("system:bootstrap", "Bootstrap", frozenset(["admin"]))
    for path in sorted(examples.glob("*/dkman.yaml")):
        manifest = parse_manifest(path.read_text())
        if session.get(AppDefinition, manifest.id) is not None:
            continue
        register_manifest(
            session, manifest, actor, str(uuid.uuid4()), source="bundled-contract-unbuilt"
        )
        count += 1
    return count


if __name__ == "__main__":
    engine = create_engine(Settings().sqlalchemy_url, hide_parameters=True)
    with Session(engine) as session:
        count = seed(session, Path(__file__).resolve().parents[2] / "examples")
    engine.dispose()
    print(f"Registered {count} bundled manifest contracts. No images installed.")
