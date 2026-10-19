#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
target="${1:?Usage: restore.sh BACKUP_DIRECTORY [--dry-run|--apply]}"
action="${2:---dry-run}"
[[ "$action" == --dry-run || "$action" == --apply ]] || exit 2
target="$(realpath "$target")"
[[ -f "$target/SHA256SUMS" && -f "$target/core.dump" && -f "$target/keycloak.dump" ]] || { echo 'Unvollstaendiges Backup.' >&2; exit 1; }
echo 'Plan: Core/Identity/Hub stoppen; beide DKMan-Datenbanken ersetzen. Bestehende Daten gehen verloren.'
echo 'Vorher neues Backup erstellen. Config/Secrets werden nicht automatisch ersetzt. Siehe docs/operations.md.'
[[ "$action" == --apply ]] || exit 0
require_docker
require_own_project
(cd "$target" && sha256sum --check SHA256SUMS)
confirm_action RESTORE
start_log restore
compose stop hub core keycloak
compose exec -T postgres pg_restore -U postgres --clean --if-exists --exit-on-error -d dkman < "$target/core.dump"
compose exec -T postgres pg_restore -U postgres --clean --if-exists --exit-on-error -d keycloak < "$target/keycloak.dump"
compose up -d --wait --wait-timeout 300 core keycloak hub
bash "$DKMAN_ROOT/scripts/linux/doctor.sh"
