# Architektur und Schnittstellen · 0.1

React/TypeScript wird statisch durch einen unprivilegierten Nginx ausgeliefert.
Der gleiche Origin routet `/api/v1/*` und `/health/*` zum FastAPI-Core sowie
`/auth/*` zu Keycloak. Nur der Proxy-Port wird auf `127.0.0.1` veröffentlicht.
Core und Keycloak erreichen PostgreSQL über ein internes Docker-Netzwerk.

Core ist ein modularer Monolith: `api.py` für REST, `auth.py` für OIDC/Rollen,
`registry.py` für Registrierung/Sichtbarkeit, `manifest.py` für den Vertrag,
`health.py` für tatsächliche DB-/Schema-Readiness. SQLAlchemy-Modelle und Alembic
liegen im Backend. `jobs.py` und `job_api.py` implementieren persistente Jobs und
Freigaben; `job_recovery.py` führt ausschließlich Metadaten-Recovery aus.
Es gibt keinen Deploymentworker und keinen Dockerzugriff.

## Daten und Rechte

`AppDefinition` beschreibt ein Paket, `ServiceManifest` dessen versionierten Vertrag,
`AppInstallation` die Haushaltsinstallation, `ServiceInstance` deren Runtime.
`Capability` beschreibt einzelne Aktionen. Eine `PermissionGrant` mit `app.use`
erteilt einem verifizierten OIDC-Subject Zugriff auf genau eine Installation.
Haushaltsmitgliedschaft allein gewährt noch keinen Appzugriff. Admins sehen die
Plattform zur Verwaltung. Nichtberechtigte Detailabfragen liefern 404.

Das Schema umfasst außerdem Nutzer, Haushalte, Mitgliedschaften, Healthbeobachtungen
und Auditereignisse. Registrierung und Audit werden zusammen committed. Keine
Appfachdaten im Core. Job-/Event-/Approvaltabellen folgen mit Migration 0002 und
echten Manifestvalidierungsaufträgen. Workflow-/Forge-/Datenprovider-Tabellen kommen
mit den dazugehörigen Tickets. Vertrag: [Jobs](jobs.md), [ADR 0007](architecture-decisions/0007-durable-jobs.md).

## Implementierte API

| Route | Zugriff | Verhalten |
| --- | --- | --- |
| `GET /health/live` | öffentlich, loopback | Prozess lebt, unabhängig von DB |
| `GET /health/ready` | öffentlich, loopback | SELECT 1 und exakte Alembic-Revision; sonst 503 |
| `GET /api/v1/me` | angemeldet | verifiziertes Subject, Name und Plattformrollen |
| `GET /api/v1/apps[/{id}]` | angemeldet | nur freigegebene Installationen bzw. Admin |
| `GET /api/v1/services[/{id}]` | angemeldet | gleiche Installationssichtbarkeit |
| `GET /api/v1/capabilities` | angemeldet | sichtbare Apps und passende Capability-Rolle |
| `GET /api/v1/catalog` | Admin | registrierte Definitionen; noch keine installierbaren Artefakte |
| `POST /api/v1/registry/manifests` | Admin | strenge JSON-Validierung, Registrierung, Audit; kein Start |
| `GET /api/v1/platform` | angemeldet | Versions-/Ausbaustand |

OpenAPI ist in `contracts/openapi/core.v1.json` versioniert. Der Hub verwendet daraus
generierte TypeScript-Typen. Mutationserweiterungen erhalten typisierte Requests,
Idempotency-Keys und persistente Jobs. Fehlende Installations-/Chat-/Forge-Routen
existieren bewusst noch nicht und melden keinen simulierten Erfolg.

## Nächste Trust Boundary

Phase 2 trennt einen internen Compose-Deployment-Adapter vom Core. Nur dieser Adapter
bekommt Dockersteuerung. Er erhält keine freien Compose-Dateien oder Shellbefehle,
sondern geprüfte strukturierte Pläne mit erlaubtem Image-Digest, Ressourcen,
Volume-IDs und an einen Hash gebundener Genehmigung. Die Core-API bleibt unabhängig
vom Provider. Forge wird eine eigene, davon getrennte Workspace-/Build-Domäne.

## Manifest v1alpha1

JSON-Schema und Pydantic prüfen denselben statischen Vertrag. Zusätzliche Regeln
(Route passend zur App-ID, eindeutige Capabilities, keine doppelten Schrägstriche)
prüft Pydantic serverseitig. YAML wird nur mit SafeLoader und 64-KiB-Grenze geladen.
Unbekannte Felder, Shell, Volumes und Privilegien sind verboten. Keine aus dem
Manifest abgeleiteten URL-Requests. Zulässiges Format ersetzt keine Image-Allowlist.
Beispiele enthalten lokale versionierte Image-Namen, die noch nicht gebaut sind.
Sie werden nicht als installierbare Laufzeitpakete behandelt.

Breaking Changes benötigen neue Schema-/API-Version; `v1alpha1`-Dokumente werden
streng validiert, nicht still interpretiert. Bestehende Manifestrevisionen bleiben
unverändert. Ein Upgrade-Workflow für Definitionen folgt in Phase 2.

## Ressourcen und Betrieb

Empfehlung für erste Ubuntu-VM: 4 vCPU, 6 GB RAM, 40 GB Disk; Kapazität am Host
prüfen. Compose begrenzt Core, DB, Identity und Proxy; Logs rotieren. DB- und
Keycloak-Readiness steuern den Start. Liveness des Core behauptet keine OIDC- oder
Appverfügbarkeit. Die Core-Readiness misst DB und Schema, der Doctor zusätzlich
OIDC-Discovery und die anonyme Zugriffssperre. App-Health-Polling folgt mit dem
Deployment-Adapter; nicht gemessene Runtimezustände bleiben `unknown`.
