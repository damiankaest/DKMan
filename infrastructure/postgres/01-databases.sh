#!/usr/bin/env bash
set -euo pipefail
export CORE_PASSWORD KEYCLOAK_PASSWORD
CORE_PASSWORD="$(cat /run/secrets/core-db-password)"
KEYCLOAK_PASSWORD="$(cat /run/secrets/keycloak-db-password)"
psql --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<'SQL'
\getenv core_password CORE_PASSWORD
\getenv keycloak_password KEYCLOAK_PASSWORD
CREATE ROLE dkman_core LOGIN PASSWORD :'core_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE dkman_identity LOGIN PASSWORD :'keycloak_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE DATABASE dkman OWNER dkman_core;
CREATE DATABASE keycloak OWNER dkman_identity;
REVOKE ALL ON DATABASE dkman FROM PUBLIC;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
SQL
