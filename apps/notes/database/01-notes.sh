#!/usr/bin/env bash
set -euo pipefail
# Entrypoint sources this file as the database OS user. Do not echo passwords.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres --set=app_password="$NOTES_DB_PASSWORD" <<'SQL'
CREATE ROLE notes_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
CREATE DATABASE notes OWNER notes_app;
REVOKE ALL ON DATABASE notes FROM PUBLIC;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;
SQL
