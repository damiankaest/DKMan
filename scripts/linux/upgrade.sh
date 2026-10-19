#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
action="${1:---dry-run}"
[[ "$action" == --dry-run || "$action" == --apply ]] || exit 2
echo 'Plan: aktuellen Checkout bauen, Backup mit separater Bestaetigung, Core/Identity/Hub stoppen, Migration, Neustart und Doctor.'
echo 'Kein git pull, kein Image-Prune, kein Volume-Loeschen. Bei Fehlern manuelle Recovery aus docs/operations.md.'
[[ "$action" == --apply ]] || exit 0
require_docker
require_own_project
confirm_action UPGRADE
start_log upgrade
compose config --quiet
compose build
bash "$DKMAN_ROOT/scripts/linux/backup.sh" --apply
compose stop hub core keycloak
trap 'echo "Upgrade fehlgeschlagen. Dienste bleiben zur kontrollierten Recovery gestoppt. Siehe docs/operations.md." >&2' ERR
compose run --rm --no-deps migrate
compose up -d --wait --wait-timeout 300 core keycloak hub
bash "$DKMAN_ROOT/scripts/linux/doctor.sh"
