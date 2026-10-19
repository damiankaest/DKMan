# ADR 0005 · PostgreSQL mit getrennten Rollen

Status: angenommen. Eine PostgreSQL-Instanz enthält getrennte Core- und Keycloak-DBs
mit eigenen nicht privilegierten Loginrollen. Der Core bekommt keinen Superuser und
keinen Zugriff auf Identitydaten. PUBLIC verliert CONNECT auf beide Datenbanken.

Appdaten liegen künftig in separaten DBs/Schemas mit eigenen eingeschränkten Rollen.
Provisionierung erhält einen eigenen privilegierten Vertrag, nicht die Core-API.
Appübergreifende Nutzung erfolgt über Capabilities/APIs. Alembic ist alleiniger
Schema-Migrationsweg; initiale DB-/Rollenerstellung ist nur bei leerem Postgresvolume
aktiv. Fehlende Secrets bestehender Installationen werden nicht automatisch rotiert.
