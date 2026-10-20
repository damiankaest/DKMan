"""Generate first-run local configuration. No network calls, no credential output."""

import argparse
import json
import os
import secrets
from pathlib import Path


def write_exclusive(path: Path, content: str, mode: int = 0o600) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode), "w") as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(content)


def generate(root: Path, port: int) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("Port must be between 1024 and 65535")
    local = root / ".local"
    if local.is_symlink():
        raise ValueError(".local may not be a symlink")
    local.mkdir(exist_ok=True, mode=0o700)
    local.chmod(0o700)
    config = root / ".env"
    expected = f"DKMAN_HTTP_PORT={port}\nDKMAN_PUBLIC_URL=http://localhost:{port}\n"
    if config.is_symlink():
        raise ValueError(".env may not be a symlink")
    if config.exists() and config.read_text() != expected:
        raise ValueError("Existing .env differs. Review manually; no overwrite performed.")
    secret_names = [
        "postgres-password",
        "core-db-password",
        "keycloak-db-password",
        "keycloak-admin-password",
    ]
    marker = local / "config-complete"
    if marker.exists():
        required = [config, local / "keycloak/dkman-realm.json"] + [
            local / "secrets" / name for name in secret_names
        ]
        if any(not path.is_file() or path.is_symlink() for path in required):
            raise ValueError(
                "Incomplete existing installation. Restore configuration; do not rotate secrets."
            )
    for name in ["secrets", "keycloak", "logs", "backups"]:
        folder = local / name
        if folder.is_symlink():
            raise ValueError("Local configuration directories may not be symlinks")
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.chmod(0o700)
    for name in secret_names:
        path = local / "secrets" / name
        if path.is_symlink():
            raise ValueError("Secret files may not be symlinks")
        if not path.exists():
            # Compose mounts file-backed secrets without remapping host UID/mode.
            # Parent directories are 0700; only the mounted file is container-readable.
            write_exclusive(path, secrets.token_urlsafe(36) + "\n", 0o444)
    realm_path = local / "keycloak/dkman-realm.json"
    if realm_path.is_symlink():
        raise ValueError("Realm file may not be a symlink")
    if not realm_path.exists():
        password = secrets.token_urlsafe(24)
        realm = json.loads((root / "infrastructure/keycloak/dkman-realm.template.json").read_text())
        client = realm["clients"][0]
        origin = f"http://localhost:{port}"
        client["rootUrl"] = origin
        client["redirectUris"] = [origin + "/"]
        client["webOrigins"] = [origin]
        client["attributes"]["post.logout.redirect.uris"] = origin + "/"
        for app_client in realm["clients"][1:]:
            app_client["rootUrl"] = origin
            app_client["redirectUris"] = [origin + "/run/*"]
            app_client["webOrigins"] = [origin]
            app_client["attributes"]["post.logout.redirect.uris"] = origin + "/"
        realm["users"] = [
            {
                "username": "platform-admin",
                "enabled": True,
                "firstName": "Platform",
                "lastName": "Admin",
                "email": "admin@localhost.invalid",
                "emailVerified": True,
                "realmRoles": ["admin", "member"],
                "requiredActions": ["UPDATE_PASSWORD"],
                "credentials": [{"type": "password", "value": password, "temporary": True}],
            }
        ]
        write_exclusive(realm_path, json.dumps(realm, indent=2) + "\n", 0o444)
        credentials_path = local / "initial-credentials.txt"
        if not credentials_path.exists():
            write_exclusive(
                credentials_path,
                f"ServiceHub user: platform-admin\nTemporary password: {password}\n\n"
                "Keycloak user: bootstrap-admin\n"
                "Password: see .local/secrets/keycloak-admin-password\n",
            )
    if not config.exists():
        write_exclusive(config, expected)
    if not marker.exists():
        write_exclusive(marker, "v1\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    generate(args.root.resolve(), args.port)
    print(
        "Local configuration ready. Credentials are stored only in .local/initial-credentials.txt."
    )
