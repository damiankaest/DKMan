#!/usr/bin/env bash
set -euo pipefail
export KC_DB_PASSWORD
KC_DB_PASSWORD="$(cat /run/secrets/keycloak-db-password)"
export KC_BOOTSTRAP_ADMIN_PASSWORD
KC_BOOTSTRAP_ADMIN_PASSWORD="$(cat /run/secrets/keycloak-admin-password)"
exec /opt/keycloak/bin/kc.sh start --optimized --import-realm
