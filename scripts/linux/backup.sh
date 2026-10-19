#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
action="${1:---dry-run}"
[[ "$action" == --dry-run || "$action" == --apply ]] || exit 2
echo 'Plan: transaktionskonsistente pg_dump-Dateien fuer Core und Keycloak; lokale Config/Secrets sichern. Nur Phase-0-Plattform, keine App-Volumes.'
echo 'Backup enthaelt Zugangsdaten. Ziel: .local/backups, Berechtigungen 0700/0600. Kein externer Upload.'
[[ "$action" == --apply ]] || exit 0
require_docker
require_own_project
confirm_action BACKUP
umask 077
mkdir -p "$DKMAN_ROOT/.local/backups"
target="$(mktemp -d "$DKMAN_ROOT/.local/backups/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX.partial")"
compose exec -T postgres pg_dump -U postgres -Fc dkman > "$target/core.dump"
compose exec -T postgres pg_dump -U postgres -Fc keycloak > "$target/keycloak.dump"
tar -C "$DKMAN_ROOT" -czf "$target/config.tar.gz" .env .local/secrets .local/keycloak
if git -C "$DKMAN_ROOT" rev-parse HEAD > "$target/revision.txt" 2>/dev/null; then
  :
elif [[ -f "$DKMAN_ROOT/SOURCE_REVISION" ]]; then
  cp "$DKMAN_ROOT/SOURCE_REVISION" "$target/revision.txt"
else
  echo 'unversioned-source-export: preserve the matching source manually' > "$target/revision.txt"
fi
(cd "$target" && sha256sum core.dump keycloak.dump config.tar.gz > SHA256SUMS)
mv "$target" "${target%.partial}"
echo "Backup erstellt: ${target%.partial}"
