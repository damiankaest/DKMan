#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
action="${1:---dry-run}"
[[ "$action" == --dry-run || "$action" == --apply ]] || { echo 'Usage: bootstrap.sh [--dry-run|--apply]' >&2; exit 2; }
cat <<'PLAN'
DKMan Bootstrap-Plan (nur eigener Compose-Stack):
1. Vorhandene Linux-Docker-Engine und Compose prüfen; keine Pakete installieren.
2. .env, zufällige Secrets und OIDC-Realm einmalig lokal erzeugen.
3. Compose validieren und eigene Images bauen.
4. Datenbank starten, Alembic-Migration ausführen, Core/Identity/Hub starten.
5. Health, Proxy und OIDC-Discovery prüfen.
Nur Loopback-Port 8080; keine Firewall-, VM- oder Windows-Änderungen.
Bei Fehlern bleibt der Stack zur Diagnose bestehen. Volumes werden nie gelöscht.
PLAN
if [[ "$action" == --dry-run ]]; then
  echo 'Dry-run: keine Dateien oder Dienste verändert. Ausführung: bash scripts/linux/bootstrap.sh --apply'
  exit 0
fi
require_docker
require_own_project
command -v python3 >/dev/null
command -v curl >/dev/null
confirm_action INSTALL
cd "$DKMAN_ROOT"
umask 077
python3 scripts/generate_local_config.py
start_log bootstrap
trap 'echo "Bootstrap fehlgeschlagen. Diagnose: bash scripts/linux/doctor.sh; keine Volumes löschen." >&2' ERR
compose config --quiet
compose build
compose up -d --wait postgres
compose run --rm --no-deps migrate
compose run --rm --no-deps core python -m dkman.seed
compose up -d --wait --wait-timeout 300 core keycloak hub
bash scripts/linux/doctor.sh
echo 'Öffnen: http://localhost:8080. Erste Zugangsdaten: .local/initial-credentials.txt (nicht teilen).'
