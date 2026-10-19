#!/usr/bin/env bash
set -euo pipefail
DKMAN_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export DKMAN_ROOT
compose() {
  docker compose --project-name dkman --env-file "$DKMAN_ROOT/.env" \
    --file "$DKMAN_ROOT/infrastructure/compose/compose.yaml" "$@"
}
require_docker() {
  command -v docker >/dev/null || { echo 'Docker Engine/CLI fehlt. Siehe docs/windows10-setup.md.' >&2; return 1; }
  docker compose version >/dev/null
  [[ "$(docker info --format '{{.OSType}}')" == linux ]] || { echo 'Linux-Docker-Engine erforderlich.' >&2; return 1; }
}
require_own_project() {
  local container_id marker container_ids
  echo "Docker-Kontext: $(docker context show)"
  echo "Docker-Engine: $(docker info --format '{{.Name}} / {{.OSType}}')"
  container_ids="$(docker ps -aq --filter label=com.docker.compose.project=dkman)"
  while IFS= read -r container_id; do
    [[ -n "$container_id" ]] || continue
    marker="$(docker inspect --format '{{index .Config.Labels "io.dkman.managed"}}' "$container_id")"
    [[ "$marker" == true ]] || {
      echo 'Abbruch: vorhandenes Compose-Projekt dkman ohne DKMan-Ownerlabel. Nicht veraendern.' >&2
      return 1
    }
  done <<< "$container_ids"
}
confirm_action() {
  local expected="$1" reply
  read -r -p "Zur Bestätigung '$expected' eingeben: " reply
  [[ "$reply" == "$expected" ]] || { echo 'Abgebrochen.' >&2; return 1; }
}
start_log() {
  mkdir -p "$DKMAN_ROOT/.local/logs"
  local logfile="$DKMAN_ROOT/.local/logs/$(date -u +%Y%m%dT%H%M%SZ)-$1.log"
  touch "$logfile"
  chmod 600 "$logfile"
  exec > >(tee -a "$logfile") 2>&1
}
