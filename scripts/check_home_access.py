"""Read-only client-side checks for a proposed DKMan HTTPS origin."""

import argparse
import json
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(origin: str) -> list[str]:
    url = urlsplit(origin)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise ValueError("Eine HTTPS-Origin ohne Pfad, Zugangsdaten oder Parameter angeben.")
    try:
        _ = url.port
    except ValueError as exc:
        raise ValueError("Ungültiger Port.") from exc
    base = origin.rstrip("/")
    opener = build_opener(NoRedirect())
    failures: list[str] = []
    paths = [
        ("Hub", "/", 200),
        ("Live", "/health/live", 200),
        ("Ready", "/health/ready", 200),
        ("OIDC", "/auth/realms/dkman/.well-known/openid-configuration", 200),
        ("Anonymer API-Zugriff", "/api/v1/me", 401),
    ]
    for label, path, expected in paths:
        try:
            try:
                response = opener.open(Request(base + path, method="GET"), timeout=10)
            except HTTPError as exc:
                response = exc
            with response:
                if response.status != expected:
                    raise ValueError(f"HTTP {response.status}, erwartet {expected}")
                if label == "OIDC":
                    data = json.loads(response.read(65537))
                    if (
                        not isinstance(data, dict)
                        or data.get("issuer") != base + "/auth/realms/dkman"
                    ):
                        raise ValueError("Issuer stimmt nicht mit der Origin überein")
            print(f"OK: {label}")
        except (URLError, OSError, ValueError, json.JSONDecodeError, ssl.SSLError) as exc:
            print(f"FEHLER: {label}: {exc}", file=sys.stderr)
            failures.append(label)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="HTTPS-Origin, z. B. https://dkman.example")
    args = parser.parse_args()
    try:
        failures = check(args.origin)
    except ValueError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    if failures:
        print("Nicht bestanden; siehe Fehler. Keine Konfiguration wurde verändert.")
        return 1
    print("Technische Basis geprüft. Login, Berechtigungen und Firewall separat abnehmen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
