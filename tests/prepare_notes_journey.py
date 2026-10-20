"""Disposable CI identities imported by a real Keycloak, never a production auth bypass."""

import json
import os
import secrets
from pathlib import Path


def prepare(root: Path) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") != "1"
    ):
        raise ValueError("Disposable GitHub runner required")
    path = root / ".local/keycloak/dkman-realm.json"
    realm = json.loads(path.read_text())
    credentials = {}
    for name, roles in [
        ("ci-admin", ["admin", "member"]),
        ("ci-member", ["member", "operator"]),
        ("ci-outsider", ["member"]),
    ]:
        password = secrets.token_urlsafe(36)
        credentials[name] = password
        realm["users"].append(
            {
                "username": name,
                "enabled": True,
                "firstName": "CI",
                "lastName": name,
                "email": f"{name}@localhost.invalid",
                "emailVerified": True,
                "realmRoles": roles,
                "requiredActions": [],
                "credentials": [{"type": "password", "value": password, "temporary": False}],
            }
        )
    path.chmod(0o600)
    path.write_text(json.dumps(realm))
    path.chmod(0o444)
    output = root / ".local/ci-users.json"
    with output.open("x") as stream:
        stream.write(json.dumps(credentials))
    output.chmod(0o600)


if __name__ == "__main__":
    prepare(Path(__file__).resolve().parents[1])
