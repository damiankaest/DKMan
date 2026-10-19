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
| P1-004 | P0 / 1 | P1-003 | Haushalts-/Mitglieder-/Grant-Verwaltung: zwei echte Nutzer und getrennte Freigaben; offen |
| P1-005 | P0 / 1 | P1-003,P2-003 | tatsächliches Healthpolling mit Historie, Zeitstempel, Fehlerursache; DB-Readiness vorhanden, App-Polling offen |
| P2-001 | P0 / 2 | P0-007,P1-003 | persistente Job-/Event-/Approvaltabellen, Idempotency-Key, Neustart-Recovery; Tests für Duplikat/Crash/Fehler |
| P2-002 | P0 / 2 | P2-001 | DeploymentProvider und isolierter Compose-Adapter; keine freien Befehle/Mounts/Ports; Negativtests |
| P2-003 | P0 / 2 | P2-002 | Notes-Quellapp bauen/testen, tatsächlichen Digest erfassen und kuratieren; keine Platzhalterimages |
| P2-004 | P0 / 2 | P2-003 | UI-Plan → hashgebundene Freigabe → Job → echte Installation mit Proxyroute/SSO |
| P2-005 | P0 / 2 | P2-004 | Start/Stop/Restart/Status/Logs autorisiert, Redaction; Daten nach Stop/Start identisch |
| P2-006 | P0 / 2 | P2-005,P1-004 | Journey B mit zwei Nutzern und echten Containern E2E, verbotene Images/Permissions/DB-Ausfall testen |
| P3-001 | P1 / 3 | P2-006 | AppRequest/Planrevisionen persistieren; Workflow/Jobvertrag wiederverwenden |
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

Nächste Sitzung: P0-007 und offener Live-OIDC-Test zuerst; anschließend P1-004
und P2-001. Phase 2 nicht auf eine ungeprüfte Docker-/Identitykonfiguration aufbauen.
