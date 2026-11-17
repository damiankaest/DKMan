#!/usr/bin/env bash
# Stage a signed SPA archive through a short-lived, unprivileged helper container.
# Default is read-only planning. This script never accesses the Docker socket from inside the helper.
set -euo pipefail

usage() {
  printf '%s\n' 'Usage: stage_forge_archive.sh --artifact-dir DIR --root STAGING_DIR --builder-public-key FILE [--apply --confirm STAGE_FORGE_ARCHIVE]'
}

artifact=''
staging=''
key=''
apply=false
confirmation=''
while (($#)); do
  case "$1" in
    --artifact-dir) (($# >= 2)) || { usage; exit 2; }; artifact=$2; shift 2 ;;
    --root) (($# >= 2)) || { usage; exit 2; }; staging=$2; shift 2 ;;
    --builder-public-key) (($# >= 2)) || { usage; exit 2; }; key=$2; shift 2 ;;
    --apply) apply=true; shift ;;
    --confirm) (($# >= 2)) || { usage; exit 2; }; confirmation=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done
if [[ -z "$artifact" || -z "$staging" || -z "$key" ]]; then usage; exit 2; fi
if $apply && [[ "$confirmation" != STAGE_FORGE_ARCHIVE ]]; then
  printf '%s\n' 'Apply requires --confirm STAGE_FORGE_ARCHIVE.' >&2
  exit 2
fi
for input in "$artifact" "$staging" "$key"; do
  if [[ "$input" == *','* || "$input" == *$'\n'* || "$input" == *$'\r'* ]]; then
    printf '%s\n' 'Paths must not contain commas or line breaks.' >&2; exit 2
  fi
  if [[ "$(realpath -e -- "$input")" != "$(realpath -s -- "$input")" ]]; then
    printf '%s\n' 'Paths must exist and contain no symlinks.' >&2; exit 2
  fi
done
artifact=$(realpath -e -- "$artifact")
staging=$(realpath -e -- "$staging")
key=$(realpath -e -- "$key")
[[ -d "$artifact" && -d "$staging" && -f "$key" ]] || { printf '%s\n' 'Invalid paths.' >&2; exit 2; }
for directory in "$artifact" "$staging"; do
  if [[ "$(stat -c '%u:%a' -- "$directory")" != '10001:700' ]]; then
    printf '%s\n' 'Artifact and staging directories must be private and owned by UID 10001.' >&2
    exit 2
  fi
done
command -v docker >/dev/null || { printf '%s\n' 'Docker is unavailable.' >&2; exit 2; }

find_service() {
  local service=$1
  local -a ids
  mapfile -t ids < <(docker ps --filter 'label=com.docker.compose.project=dkman' --filter "label=com.docker.compose.service=$service" --format '{{.ID}}')
  if ((${#ids[@]} != 1)) || [[ ! "${ids[0]}" =~ ^[a-f0-9]{12,64}$ ]]; then
    printf '%s\n' "Expected one running DKMan $service container." >&2; return 1
  fi
  printf '%s' "${ids[0]}"
}
hub=$(find_service hub)
adapter=$(find_service deployment-adapter)
image=$(docker inspect --format '{{.Image}}' "$adapter")
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ ]] || { printf '%s\n' 'Invalid adapter image.' >&2; exit 2; }
mapfile -t mounts < <(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/dkman-forge-staged"}}{{.Source}}{{end}}{{end}}' "$adapter")
if ((${#mounts[@]} != 1)) || [[ "${mounts[0]}" != "$staging" ]]; then
  printf '%s\n' 'Staging directory is not the configured adapter mount.' >&2; exit 2
fi
printf '%s\n' 'Plan: verify the approved Forge SPA and stage its archive without loading an image or starting an app container.'
printf 'Artifact: %s\nStaging: %s\n' "$artifact" "$staging"
if ! $apply; then
  printf '%s\n' 'Dry-run only. Apply requires --apply --confirm STAGE_FORGE_ARCHIVE.'
  exit 0
fi
terminal=()
if [[ -t 0 ]]; then terminal=(-t); fi
exec docker run --rm -i "${terminal[@]}" --read-only --user 10001:10001 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --network "container:$hub" --mount "type=bind,src=$artifact,dst=/artifact,readonly" \
  --mount "type=bind,src=$staging,dst=/staged" \
  --mount "type=bind,src=$key,dst=/builder-public.pem,readonly" \
  "$image" python -m dkman.deployment_adapter.forge_staging \
  --root /staged --core http://127.0.0.1:8080 --artifact-dir /artifact \
  --builder-public-key /builder-public.pem --apply --confirm STAGE_FORGE_ARCHIVE
