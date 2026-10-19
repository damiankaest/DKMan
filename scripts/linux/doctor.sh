#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_docker
[[ -f "$DKMAN_ROOT/.env" ]] || { echo '.env fehlt: zuerst bootstrap.sh --apply.' >&2; exit 1; }
command -v python3 >/dev/null
command -v curl >/dev/null
compose config --quiet
compose ps --all
base="$(python3 - "$DKMAN_ROOT/.env" <<'PY'
from pathlib import Path
import sys
values = dict(line.split('=', 1) for line in Path(sys.argv[1]).read_text().splitlines() if line and not line.startswith('#'))
print(values['DKMAN_PUBLIC_URL'])
PY
)"
curl --fail --silent --show-error --max-time 10 "$base/health/live"
curl --fail --silent --show-error --max-time 10 "$base/health/ready"
curl --fail --silent --show-error --max-time 10 "$base/auth/realms/dkman/.well-known/openid-configuration" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["issuer"].endswith("/auth/realms/dkman"); print("OIDC discovery erreichbar")'
code="$(curl --silent --show-error --max-time 10 --output /dev/null --write-out '%{http_code}' "$base/api/v1/me")"
[[ "$code" == 401 ]] || { echo "Erwartet 401 ohne Token, erhalten: $code" >&2; exit 1; }
echo 'Doctor: DB-Schema, Proxy, Identity-Discovery und anonyme Zugriffssperre geprüft.'
