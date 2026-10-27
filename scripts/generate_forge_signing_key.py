"""Create an isolated builder signing key; dry-run unless explicitly confirmed."""

import argparse
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dkman.forge.attestation import key_id
from dkman.forge.build_worker import private_root


def generate(
    root: Path, *, purpose: str = "build", apply: bool = False, confirmation: str = ""
) -> None:
    root = private_root(root)
    if purpose not in {"build", "preview"}:
        raise ValueError("Unsupported signing key purpose")
    private_file = root / f"forge-{purpose}-private.pem"
    public_file = root / f"forge-{purpose}-public.pem"
    if not apply:
        print("Dry-run: create a builder-only Ed25519 key and its public verification key.")
        print("Apply requires --apply --confirm CREATE_FORGE_SIGNING_KEY on the isolated builder.")
        return
    if confirmation != "CREATE_FORGE_SIGNING_KEY":
        raise ValueError("Explicit CREATE_FORGE_SIGNING_KEY confirmation required")
    if private_file.exists() or public_file.exists():
        raise ValueError("Key files already exist; key rotation requires an explicit procedure")
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    payloads = [
        (
            private_file,
            private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        ),
        (
            public_file,
            public.public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            ),
        ),
    ]
    created: list[Path] = []
    try:
        for path, value in payloads:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            created.append(path)
            with os.fdopen(fd, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    print(f"{purpose.capitalize()} key fingerprint: {key_id(public)}")
    print("Copy only the public key to the configured Core verification path.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--purpose", choices=["build", "preview"], default="build")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    generate(args.root, purpose=args.purpose, apply=args.apply, confirmation=args.confirm)
