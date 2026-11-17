"""Create disposable CI-only Forge keys and staging; never run on a target host."""

import os
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def prepare(root: Path) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") != "1"
    ):
        raise ValueError("Disposable CI only")
    forge = root / ".local/forge"
    forge.mkdir(mode=0o700)
    for purpose in ("build", "preview"):
        key = Ed25519PrivateKey.generate()
        private = forge / f"forge-{purpose}-private.pem"
        private.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        private.chmod(0o600)
        public = forge / ("builder-public.pem" if purpose == "build" else "preview-public.pem")
        public.write_bytes(
            key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        public.chmod(0o444)
    (forge / "worker").mkdir(mode=0o700)
    (forge / "incoming").mkdir(mode=0o700)
    subprocess.run(
        [
            "sudo",
            "install",
            "-d",
            "-m",
            "0700",
            "-o",
            "10001",
            "-g",
            "10001",
            str(forge / "staged"),
        ],
        check=True,
    )


if __name__ == "__main__":
    prepare(Path(__file__).resolve().parents[1])
