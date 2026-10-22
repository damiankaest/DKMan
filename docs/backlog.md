# Priorisierter Implementierungsplan

Status gilt für Code/prüfbare Teilabnahmen. Hostabhängige Abnahmen bleiben offen,
auch wenn die zugehörigen Dateien implementiert sind. Nachweise: `acceptance-tests.md`.

| Ticket | Prio / Phase | Abhängigkeit | Akzeptanz / Stand |
| --- | --- | --- | --- |
| P0-001 | P0 / 0 | – | Spezifikation, Monorepo, Konventionen, sechs ADRs, Lizenzentscheidung; implementiert |
| P0-002 | P0 / 0 | 001 | Windows-Preflight liest Edition/Virtualisierung/RAM/Disk/Ports/Dienste/Netz; Setup nur nach Bestätigung; implementiert, Hosttest offen |
| P0-003 | P0 / 0 | 001 | FastAPI-Live/Ready, echte Alembic-Migration, keine Auto-DDL im Start; implementiert |
| P0-004 | P0 / 0 | 001 | React-Shell, responsiv, Tests/Lint/Build, generierte API-Typen; implementiert |
| P0-005 | P0 / 0 | 002–004 | Compose, idempotenter Bootstrap, zufällige Secrets, Loopback, Doctor; implementiert, Compose-Smoke in GitHub CI bestanden; Zielhost offen |
| P0-006 | P0 / 0 | 003–005 | CI mit PostgreSQL, Backend/Frontendprüfungen, Vertragsdrift und Container-Smoke; GitHub-CI vollständig bestanden (Lauf 39296486987) |
| P0-007 | P0 / 0 | 005 | Frischer Windows-/VM-Checkout: Bootstrap, Neustart, Doctor, Login; noch am Zielhost auszuführen |
| P1-001 | P0 / 1 | 003,005 | OIDC Code/PKCE, RS256-/Issuer-/Audienceprüfung, Rollen 401/403; implementiert, Live-Flow offen |
| P1-002 | P0 / 1 | 003 | Manifest-Schema, zwei Beispiele, kaputte/gefährliche Manifeste ablehnen; implementiert |
| P1-003 | P0 / 1 | 001,002 | Registry-Registrierung, Katalogliste, App-/Service-/Capabilitysichtbarkeit und Audit; implementiert; revisionssicheres Update/Unregister offen |
| P1-004 | P0 / 1 | P1-003 | Haushalts-/Mitglieder-/Grant-Verwaltung: API, Hub-UI und Isolationstests implementiert; Abnahme mit zwei echten OIDC-Nutzern offen |
| P1-005 | P0 / 1 | P1-003,P2-003 | tatsächliches Healthpolling mit Historie, Zeitstempel, Fehlerursache; DB-Readiness und App-Polling/45-s-Frischegrenze/Historie implementiert; Zielhost-/Betriebsabnahme offen |
| P2-001 | P0 / 2 | P0-007,P1-003 | abgeschlossen und geprüft: Migration 0002, Job/Event/Approval, Idempotenz, gebundene Freigabe, Lease/Recovery, autorisierte APIs und echte Manifestvalidierung; PR #8 in main integriert; CI 39382031613: 74 Backendtests inkl. PostgreSQL-Konkurrenz/Migration, 5 UI-, 2 Browserchecks, Container-Smoke erfolgreich; Hostabnahmen bleiben offen |
| P2-002 | P0 / 2 | P2-001 | abgeschlossen und geprüft: PR #9 in main; isolierter Compose-Provider, kuratierte Pläne, gebundene/einmalige Freigaben, Operationsjournal und Ressourcensperren; CI 39388427751: 123 Backendtests, 1 echter Docker-Integrationstest, 5 UI-/2 Browserchecks und Stack-Smoke erfolgreich; kein Zielhoststart |
| P2-003 | P0 / 2 | P2-002 | abgeschlossen und geprüft: PR #10 in main (`ef888e7`), PR-CI 39409123565 und Main-CI 39409720195 mit Notes-Quellbuild, eigener PostgreSQL-Instanz/Migration, tatsächlichen Image-IDs/Quellhash, echter Daten-/Rollen-/Neustartprobe bestanden |
| P2-004 | P0 / 2 | P2-003 | abgeschlossen und geprüft: PR #10 in main, Main-CI 39409720195: UI-Plan → gebundene Freigabe → dauerhafter Job → echte Installation/Proxy/SSO; drei echte OIDC-Nutzer, gemeinsame Daten und Widerruf. 151 Backend-/7 UI-Tests; Zielhost bleibt offen |
| P2-005 | P0 / 2 | P2-004 | abgeschlossen und geprüft: PR #11 in main (07e18c5); PR-CI 39430552396 und Main-CI 39431777779 vollständig erfolgreich: 184 Backendtests, 11 UI-Tests, 2 Browserchecks, echter Adaptertest und echte OIDC-/Notes-Lifecycle-Journey mit identischen Daten/Containern/Volumes; konkreter dauerhafter Mainnachweis unter docs/evidence/p2-005-main-runtime.json |
| P2-006 | P0 / 2 | P2-005,P1-004 | abgeschlossen und geprüft: PR #12 als 6c749e2 in main; PR-CI 39566266737 und Main-CI 39567571003 vollständig erfolgreich; dauerhafte Enginebelege, gebundene Nichtausführungsnachweise, reale Image-/Rechte-/DB-/Crashmatrix; 214 Backend-/12 UI-Tests, echte OIDC-/Dockerprobe; dauerhafter Mainnachweis docs/evidence/p2-006-main-runtime.json |
| P3-001 | P1 / 3 | P2-006 | implementiert: AppRequest als Workflowanker, unveränderliche Requirements-/Planrevisionen, manuelle Hub-Planung und konkrete Planfreigabe über Job/Event/Approval; lokale Prüfungen bestanden, vollständiger CI-Abschluss noch ausstehend; keine App-Erzeugung |
| P3-002 | P1 / 3 | P3-001 | Intent-/Tool-Dispatcher + austauschbarer Modellprovider; regelbasierter Modus offen gekennzeichnet |
| P3-003 | P1 / 3 | P3-002 | Garten-Wizard sammelt Requirements und schlägt berechtigte vorhandene Dienste vor; genehmigbarer Plan |
| P4-001 | P1 / 4 | P3-003 | CodingProvider, deterministischer Generator, drei getestete Vorlagen; isolierte Workspaces |
| P4-002 | P1 / 4 | P4-001 | echte Checks und Image-Build im isolierten Worker; BuildArtifact mit Digest, Fehlerlogs |
| P4-003 | P1 / 4 | P4-002,P2-006 | isolierte Preview → Freigabe → gleicher DeploymentService → Hub; Updates als neue Revision |
| P4-004 | P2 / 4 | P4-003 | OpenHands-SDK-Vertrag anhand offizieller Version in isolierter Probe evaluieren; keine vorgezogene Produktionsintegration |
| P5-001 | P2 / 5 | P4-003 | DB-Provider/Wizard, eigene Approllen/Secrets, Migration und Rechte-Negativtests |
| P5-002 | P2 / 5 | P5-001 | File-/Notification-Capabilities, zwei Apps ohne direkte Fremd-DB-Schreibrechte |
| P5-003 | P2 / 5 | P2-006 | Backups/Restore erweitern auf Apps; Restoreprobe und Upgrade-/Rollback im Live-Stack; Phase-0-Skripte liegen vor |
| P5-004 | P2 / 5 | P4-003 | Minecraft-Vertrag zunächst Mock: Status/Start/Stop/Backup/Restore; reale Integration nur ausdrücklich freigegeben |
| P5-005 | P3 / 5 | P2-006 | CoolifyProvider, Workspace-IDE und Quotas bei konkretem Bedarf evaluieren |

Nächster Entwicklungseinstieg nach Abnahme von P3-001: P3-002 (Intent-/Tool-Dispatcher
und austauschbarer Modellprovider). Damian hat am 22.10.2026 den erfolgreichen lokalen
DKMan-Start bestätigt. Die weiteren Zielhostprüfungen aus P0-007 bleiben separat offen;
Basisstack aktualisieren gemäß planning.md, Notes gemäß windows10-setup.md/notes.md.
Windows-/VM-/Zielhostabnahme, vollständige OIDC-Betriebsmatrix und koordinierter
Backup/Restore bleiben eigene offene Gates. Bestehende Backups decken den Runtimestack
nicht vollständig ab. Fehlender Enginebeleg bleibt bewusst gesperrt; kein Force-Retry.
