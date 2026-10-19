# Übergabe · DKMan 0.1.0

## Aktueller Stand

Phase-0-Code ist implementiert. Die Host-/Docker-Abnahme ist noch offen.
Zusätzlich sind zusammenhängende Teile von Phase 1 vorhanden: OIDC-Verifikation,
Registry-Registrierung, App-/Service-/Capabilitysichtbarkeit, Manifestprüfung,
Audit und die entsprechende ServiceHub-Oberfläche. Phase 1 insgesamt ist noch
nicht abgeschlossen. DeploymentService/Notes-Installation gehören zum nächsten
großen Durchstich, nicht zum behaupteten aktuellen Funktionsumfang.

Das private Repository ist `https://github.com/damiankaest/DKMan`.
Der geprüfte Phase-0-Stand wird über die GitHub-API importiert. Der ursprüngliche
lokale Verlauf bleibt verlustfrei in `docs/archive/DKMan-history.bundle` erhalten.
Die GitHub-Commits beginnen mit dem Import; ursprünglicher Quellstand:
`51c0f1fdb2b8da38d9f281608def57467c9344fb`.

## Implementiert

- Spezifikation übernommen; Architektur, sechs ADRs, Threat Model, Backlog und
  Arbeitskonventionen angelegt. Lizenzentscheidung beim Eigentümer belassen.
- FastAPI, SQLAlchemy/Alembic, OIDC-Rollenprüfung und strenges v1alpha1-Manifest.
- Initialmigration mit elf Domänentabellen; Registry-Mutationen mit Audit.
- Getrennte Definition/Installation/Runtime; keine frei erfundenen laufenden Apps.
- React/TypeScript-Hub mit API-generierten Typen, Suche, Status und Admin-Registry.
- Compose mit PostgreSQL, Migration, Core, Keycloak und unprivilegiertem Hub-Proxy;
  Loopback-Binding, getrennte Secrets, eingeschränkte DB-Rollen, Ressourcenlimits.
- Bootstrap mit Dry-run/Bestätigung, Prüfung des Dockerkontexts und Schutz vor
  fremden gleichnamigen Compose-Projekten; Windows-Preflight/-Vorbereitung,
  Doctor und erste Backup-/Restore-/Upgradeskripte.
- Python-/Frontend-/Browserprüfungen, zusätzlicher PostgreSQL-WASM-Migrationstest,
  CI mit PostgreSQL-17-Integration und Container-Smoke.

## Entscheidungen während der Umsetzung

Aktuelle auflösbare Paketversionen wurden überprüft und kompatibel gepinnt.
TypeScript 7 kollidierte mit TypeScript-ESLint; TypeScript 6 kollidierte mit
openapi-typescript. Gewählt wurde die kompatible Version 5.9.3 ohne erzwungene
Peer-Dependency-Ausnahmen. Starlettes aktueller Testclient benötigt `httpx2`;
die Tests verwenden dessen gepinnte Version. Python 3.12 und Node 24 sind die Basis.

Keycloak 26.8.1 wird auf offiziellem Image aufgebaut; öffentliche/interne OIDC-URLs
sind getrennt konfiguriert, die Tokenprüfung bleibt strikt. Dockerbasisimages sind
mit Registry-Digests gepinnt; der Keycloak-Basistag ist versionsgepinnt.

Kein nativer PostgreSQL-Prozess wegen Einschränkungen des Workspace-Benutzerwechsels.
Zusätzliche DDL-Abnahme deshalb in PostgreSQL/WASM; Netzwerk-/Zielversionstest bleibt
im CI/Host offen. Browserdownload-Problem wurde mit einer lokalen Chromium-Binary
für Testzwecke gelöst. Details, Befehle und Grenzen: `acceptance-tests.md`.

## Nächster Einstieg

1. `AGENTS.md`, diese Datei und `acceptance-tests.md` lesen.
2. Repository klonen; `uv sync --frozen`, im Hub `npm ci`.
3. GitHub-Actions-Ergebnisse prüfen; frühere lokale Prüfergebnisse sind keine CI-Abnahme.
4. P0-007 am freigegebenen Testhost durchführen: Dockerstart und echten OIDC-Flow
   prüfen, eventuelle Integrationsfehler zuerst schließen.
5. P1-004 Haushalts-/Benutzer-/Grant-Verwaltung ergänzen.
6. P2-001 persistente Jobs/Events/Approvals mit Idempotenz und Crash-Recovery.
7. Einen separaten Compose-Adapter umsetzen, kuratierte Notes-App bauen, Digest
   erfassen und erst nach Planfreigabe über dieselbe Deploymentgrenze starten.

Die nächste Sitzung braucht keinen Architektur-Neustart. Alle späteren Phasen und
Akzeptanzkriterien stehen bereits im priorisierten `backlog.md`.

## Lokaler Verlauf

- `dace9c9`: Architektur, Entscheidungen, Spezifikation und Implementierungsplan.
- `7d0fc71`: implementierte Plattformbasis, Registry, Auth, Hub, Installer und Tests.
- Abschließender Dokumentationscommit: Nachweis des frischen Checkouts und Übergabe.

Der genaue Paketstand steht zusätzlich in `SOURCE_REVISION` im Quellarchiv. Der
mitgelieferte Git-Bundle enthält den vollständigen lokalen Verlauf.
