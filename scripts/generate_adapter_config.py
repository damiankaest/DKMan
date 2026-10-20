"""Prepare opt-in adapter configuration. Default is a plan; never starts Docker."""

import argparse
import os
import secrets
from pathlib import Path

from dkman.deployments.contracts import Catalog


def generate(root: Path, *, apply: bool = False, confirmation: str = "") -> None:
    if not apply:
        print("Dry-run: prepare empty adapter catalog and a new delegation secret if missing.")
        print(
            "No files changed. No Docker action. Apply requires --apply --confirm ADAPTER_CONFIG."
        )
        return
    if confirmation != "ADAPTER_CONFIG":
        raise ValueError("Explicit ADAPTER_CONFIG confirmation required")
    for directory in [root / ".local", root / ".local/secrets", root / ".local/adapter"]:
        if directory.is_symlink():
            raise ValueError("Adapter configuration may not use symlinks")
        directory.mkdir(exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    catalog = root / ".local/adapter/catalog.json"
    key = root / ".local/secrets/adapter-delegation-key"
    marker = root / ".local/adapter/config-complete"
    for path in [catalog, key, marker]:
        if path.is_symlink():
            raise ValueError("Adapter configuration may not use symlinks")
    if marker.exists() and (not catalog.is_file() or not key.is_file()):
        raise ValueError("Incomplete adapter configuration; restore it without rotating secrets")
    for path, content in [
        (catalog, Catalog().model_dump_json() + "\n"),
        (key, secrets.token_urlsafe(48) + "\n"),
        (marker, "v1\n"),
    ]:
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(content)
    Catalog.model_validate_json(catalog.read_text())
    if len(key.read_bytes().strip()) < 32:
        raise ValueError("Invalid existing delegation secret; no replacement performed")
    print("Adapter configuration ready. Catalog remains explicit; no images installed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    generate(args.root, apply=args.apply, confirmation=args.confirm)
