"""Build the reviewed source app and curate actual local image IDs, never placeholder tags.

This is a workstation/CI build tool, not a Core or Hub execution capability.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from dkman.deployments.contracts import Catalog, CuratedImage


def source_hash(root: Path) -> str:
    paths = [root / "requirements.lock"]
    for folder in [root / "backend/notes_demo", root / "apps/notes"]:
        paths.extend(
            p
            for p in folder.rglob("*")
            if p.is_file() and not {"node_modules", "dist", "__pycache__"}.intersection(p.parts)
        )
    digest = hashlib.sha256()
    for path in sorted(paths):
        if path.is_symlink():
            raise ValueError("Reviewed source may not use symlinks")
        name = path.relative_to(root).as_posix().encode()
        data = path.read_bytes()
        digest.update(len(name).to_bytes(8) + name + len(data).to_bytes(8) + data)
    return digest.hexdigest()


def build(root: Path, *, apply: bool = False, confirmation: str = "") -> None:
    if apply and confirmation != "BUILD_NOTES":
        raise ValueError("Explicit BUILD_NOTES confirmation required")
    reviewed = source_hash(root)
    print(f"Notes source SHA-256: {reviewed}")
    if not apply:
        print("Dry-run: build Notes and its private PostgreSQL image; inspect actual IDs;")
        print("curate only this source revision in .local/adapter/catalog.json. No app is started.")
        print("Apply requires --apply --confirm BUILD_NOTES on an isolated Linux Docker builder.")
        return
    catalog_path = root / ".local/adapter/catalog.json"
    for path in [root / ".local", catalog_path.parent, catalog_path]:
        if path.is_symlink():
            raise ValueError("Build configuration may not use symlinks")
    catalog = Catalog.model_validate_json(catalog_path.read_text())
    evidence_path = catalog_path.parent / "notes-build.json"
    if evidence_path.is_symlink():
        raise ValueError("Build evidence may not use symlinks")

    def docker(*args: str) -> str:
        command = ["docker", "--host", "unix:///var/run/docker.sock", *args]
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=600)
        if result.returncode:
            raise ValueError("Notes build failed; no catalog changed (builder output withheld)")
        return result.stdout.strip()

    if docker("info", "--format", "{{.OSType}}") != "linux":
        raise ValueError("An isolated Linux Docker builder is required")
    images = []
    for recipe in ["apps/notes/Dockerfile", "apps/notes/database/Dockerfile"]:
        identifier = docker(
            "build", "--quiet", "--label", f"io.dkman.source-sha256={reviewed}", "-f", recipe, "."
        )
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", identifier):
            raise ValueError("Builder did not return an immutable image ID")
        image = json.loads(docker("image", "inspect", identifier))[0]
        if (
            image["Id"] != identifier
            or image["Config"].get("User") != "10001:10001"
            or image["Config"].get("Healthcheck", {}).get("Test", [None])[0] != "CMD"
        ):
            raise ValueError("Built image does not meet the curated contract")
        images.append(identifier)
    if source_hash(root) != reviewed:
        raise ValueError("Source changed during build; catalog remains unchanged")
    curated = CuratedImage(
        definition_id="demo-notes",
        version="0.1.0",
        image=images[0],
        internal_port=8080,
        profile="notes-postgres-v1",
        database_image=images[1],
        source_hash=reviewed,
    )
    existing = [x for x in catalog.images if x.definition_id == "demo-notes"]
    if existing and existing != [curated]:
        raise ValueError(
            "Existing Notes curation differs; use an explicit reviewed revision workflow"
        )
    result = Catalog(
        images=[x for x in catalog.images if x.definition_id != "demo-notes"] + [curated]
    )
    evidence = {
        "schema_version": 1,
        "source_hash": reviewed,
        "app_image": images[0],
        "database_image": images[1],
        "scope": "local Linux engine; rebuild explicitly on another engine",
    }
    # Catalog contains no secrets; siblings are in the private local directory.
    for path, raw in [
        (evidence_path, json.dumps(evidence, indent=2)),
        (catalog_path, result.model_dump_json(indent=2)),
    ]:
        temporary = path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(raw + "\n")
        temporary.replace(path)
    print(json.dumps(evidence, sort_keys=True))
    print("Curated actual image IDs. No container installed or target host service changed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    build(args.root, apply=args.apply, confirmation=args.confirm)
