# Übergabe · DKMan 0.1.0

## Aktueller Stand

Phase-0-Code ist implementiert. Backend, Frontend und vollständiger Compose-Smoke
sind in GitHub Actions erfolgreich geprüft. Die Windows-Zielhost-Abnahme und der
echte interaktive Login bleiben offen.
Zusätzlich sind zusammenhängende Teile von Phase 1 vorhanden: OIDC-Verifikation,
Registry-Registrierung, App-/Service-/Capabilitysichtbarkeit, Manifestprüfung,
Audit und die entsprechende ServiceHub-Oberfläche. Phase 1 insgesamt ist noch
nicht abgeschlossen. DeploymentService/Notes-Installation gehören zum nächsten
großen Durchstich, nicht zum behaupteten aktuellen Funktionsumfang.

P2-001 ist abgeschlossen: persistente Jobs/Events/Approvals mit Idempotenz,
gebundenen Freigaben und Recovery, in `main` über PR #8 integriert. Der erste
Executor validiert tatsächlich registrierte Manifeste. Nachweis und Grenzen unten;
nächste Entwicklung P2-002 (isolierter Deployment-Adapter).

Das private Repository ist `https://github.com/damiankaest/DKMan`.
Der geprüfte Phase-0-Stand wurde über die GitHub-API importiert. Der ursprüngliche
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
Zusätzliche lokale DDL-Abnahme deshalb in PostgreSQL/WASM. Der Netzwerk-/Zielversionstest
auf PostgreSQL 17 wurde anschließend in GitHub Actions erfolgreich ausgeführt. Browserdownload-Problem wurde mit einer lokalen Chromium-Binary
für Testzwecke gelöst. Details, Befehle und Grenzen: `acceptance-tests.md`.

## Nächster Einstieg

1. `AGENTS.md`, diese Datei und `acceptance-tests.md` lesen.
2. Repository klonen; `uv sync --frozen`, im Hub `npm ci`.
3. GitHub-Actions-Ergebnisse prüfen; frühere lokale Prüfergebnisse sind keine CI-Abnahme.
4. P0-007 am freigegebenen Testhost durchführen: Dockerstart und echten OIDC-Flow
   prüfen, eventuelle Integrationsfehler zuerst schließen.
5. P1-004 mit zwei echten OIDC-Nutzern abnehmen; API und Hub-Verwaltung sind implementiert.
6. P2-001 ist implementiert: `jobs.md`, ADR 0007 und CI-Nachweis unten lesen.
7. P2-002: Einen separaten Compose-Adapter umsetzen, kuratierte Notes-App bauen, Digest
   erfassen und erst nach Planfreigabe über dieselbe Deploymentgrenze starten.

Die nächste Sitzung braucht keinen Architektur-Neustart. Alle späteren Phasen und
Akzeptanzkriterien stehen bereits im priorisierten `backlog.md`.

## Lokaler Verlauf

- `dace9c9`: Architektur, Entscheidungen, Spezifikation und Implementierungsplan.
- `7d0fc71`: implementierte Plattformbasis, Registry, Auth, Hub, Installer und Tests.
- Abschließender Dokumentationscommit: Nachweis des frischen Checkouts und Übergabe.

Der genaue Paketstand steht zusätzlich in `SOURCE_REVISION` im Quellarchiv. Der
mitgelieferte Git-Bundle enthält den vollständigen lokalen Verlauf.

## CI-Reparatur · 19.10.2026

- PostgreSQL-Service: doppelte Anführungszeichen für `--health-cmd`, da der Runner
  die bisherigen einfachen Quotes nicht als Argumentgrenze behandelte.
- Keycloak: `/auth` und Managementpfad `/` bereits vor `kc.sh build` setzen;
  der optimierte Start verweigerte zuvor die abweichenden Build-Time-Werte.
- Fehlerprotokolle umfassen jetzt auch Keycloak und Hub.
- TypeScript bleibt 5.9.3. Dependabot ignoriert Versionen >=6, solange
  `openapi-typescript` und ESLint keine kompatible gemeinsame Migration erlauben.
  PR #7 wurde daraufhin geschlossen. Laufzeit-Upgrades #1/#2 sind nicht integriert.
- [Grüner Gesamtlauf](https://github.com/damiankaest/DKMan/actions/runs/39296486987) für `b78c7e5`: 40 Backendtests,
  vier Frontendtests, zwei Browsertests; alle drei Jobs erfolgreich.
- Container-Smoke: Images gebaut, vier Dienste healthy, Migration Exit 0,
  zwei Manifestverträge registriert; Doctor bestätigt DB-Schema, Proxy,
  OIDC-Discovery und 401 ohne Token. Keine Beispiel-App installiert.
- Der Browsercheck verwendet weiterhin Testantworten; echter Login/Passwortwechsel,
  Refresh/Logout, Windows/VM-Neustart und Restore bleiben offen.

## Haushalte und App-Freigaben · 19.10.2026

- P1-004: Profilabgleich ausschließlich aus geprüftem OIDC-Principal; nur Admins
  dürfen Benutzerverzeichnis, Mitgliedschaften und Installationsfreigaben verwalten.
- Haushaltslisten normaler Benutzer enthalten ausschließlich eigene Haushalte.
  Mitgliedschaft allein erteilt keinen App-Zugriff. Freigaben setzen Mitgliedschaft
  im Installationshaushalt voraus. Entfernen eines Mitglieds entzieht sämtliche
  App-Freigaben dieses Haushalts; erneutes Hinzufügen stellt sie nicht wieder her.
- PostgreSQL-Zeilensperre am Haushalt serialisiert Mitgliedschafts- und Grantänderungen.
  Idempotente PUT/DELETE und Audit-Einträge in derselben Transaktion.
- Hub: Profilabgleich beim Login, Haushaltsanlage, Mitgliederverwaltung mit
  Löschbestätigung und App-Freigaben; Fehler werden angezeigt. Konten/Rollen bleiben
  in Keycloak. Keine Beispielinstallation vorgetäuscht, kein Hostzugriff hinzugefügt.
- Bestehende Tabellen genügen; keine Migration erforderlich. OpenAPI und TS-Typen
  regeneriert. Neue Backendtests prüfen Rollen, Isolation, Idempotenz, Widerruf,
  Audit und fehlende Ressourcen; UI-Test prüft Anlage und Mitgliederänderungen.
- Lokal: Ruff, Format, mypy erfolgreich; pytest 45 bestanden / 1 PostgreSQL-Test
  mangels lokaler Testdatenbank übersprungen. npm ci, lint, build und 5 UI-Tests
  erfolgreich. Lokaler Playwright-Start durch fehlende Browserbinary blockiert;
  Browserdownload liefert beschädigtes Archiv. GitHub-CI-Nachweis siehe unten.
- Offen: echte OIDC-Mehrbenutzerabnahme und Windows-/Persistenz-/Restoretests.
  Nächster Entwicklungsschritt P2-001, ohne vorgezogenen Zielhost-Deploymentlauf.

## CI-Abnahme P1-004 · 19.10.2026

Commit `5c8e112`: [Actions-Lauf 39298429354](https://github.com/damiankaest/DKMan/actions/runs/39298429354)
vollständig erfolgreich: Backend 46 Tests einschließlich PostgreSQL-Migrationsprobe,
Ruff/Format/mypy, ASGI-Smoke, PowerShell-Syntax, Manifest- und Vertragsprüfung;
Frontend Produktionsbuild, 5 UI-Tests, 2 Browserchecks und Dependency-Audit.
Container-Smoke baut Images, führt Migration mit Exit 0 aus und meldet PostgreSQL,
Core, Keycloak und Hub healthy. Seed registriert zwei Manifestverträge; Doctor prüft
Schema, Proxy und OIDC-Discovery. Browsertests verwenden weiterhin Testantworten;
echte OIDC-Mehrbenutzerabnahme und Windows-/Restoretests bleiben offen.

## P2-001 · Persistente Jobs und Freigaben · 20.10.2026

- Ausgangspunkt: `main` `e021f57`; Actions `39298429354` für Featurestand `5c8e112`
  selbst geprüft, alle drei Jobs erfolgreich. Keine fremden Dependabot-Änderungen übernommen.
- Neue Migration `0002_durable_jobs`: Jobs, sequenzierte Events und Approvals.
  Initialmigration unverändert; Readiness verlangt neue Revision.
- Autorisierte Anlage/Liste/Details/Events/Entscheidung/Abbruch/Ausführung. Der echte
  erste Executor validiert ausschließlich registrierte Manifest-Snapshots erneut.
  Kein Deployment-/Hostzugriff und kein vorgetäuschter Containererfolg.
- Unique Constraint pro Subject/Idempotency-Key; Request-Fingerprint gegen Konflikte.
  Serverplan und Approval binden Aktion, Ressource, Identität, Hash und Ablauf.
- Transaktionale Events/Audit, exklusive Claims, private Leases und persistierter
  Ausführungsmarker. Startup/15-Sekunden-Recovery wiederholt keine Aktionen nach
  möglichem Ausführungsbeginn; dann `reconciliation_required`, alte Worker gesperrt.
- Lokal: `uv sync --frozen`, Ruff/Format/mypy, `uv build`, HTTP-Smoke erfolgreich;
  `uv run pytest -q`: 67 bestanden, 7 PostgreSQL-Tests ohne lokale Testdatenbank
  übersprungen. PostgreSQL-WASM: Upgrade/Downgrade/erneutes Upgrade, 15 Tabellen,
  Revision und FK-Negativtest erfolgreich. Hub: npm ci, Lint, Build, 5 UI-Tests.
- OpenAPI und Frontendtypen regeneriert. Sechs zusätzliche PostgreSQLtests prüfen
  echte parallele Requests, Claims, Gegenentscheidungen, Abbruch und Recovery.
  PR-CI `39382031613` vollständig erfolgreich: 74 Backendtests ohne Skip,
  5 UI- und 2 Browserchecks sowie Container-Smoke; Nachweis unten.
- Grenzen und Verträge: `jobs.md`, ADR 0007, `acceptance-tests.md`. Windows-Host,
  echte OIDC-Mehrbenutzer-, Volume-Persistenz- und Restoreabnahmen bleiben offen.
- Nächster Einstieg P2-002: isolierter Compose-Adapter, typisierter Runtimeplan,
  verbindliche Risikopolicy, Ressourcenserialisierung und dauerhafte Operation-ID
  mit Abgleich unbekannter Ergebnisse. Danach P2-003: echte kuratierte Notes-App.

## CI-Abnahme und Integration P2-001 · 20.10.2026

[PR #8](https://github.com/damiankaest/DKMan/pull/8) wurde nach eigenständiger
Prüfung aller drei CI-Jobs integriert. Featurecommit `4d06567`, Maincommit `f2f4b70`.
[PR-Lauf 39382031613](https://github.com/damiankaest/DKMan/actions/runs/39382031613)
und [Branch-Lauf 39382018865](https://github.com/damiankaest/DKMan/actions/runs/39382018865)
sind vollständig erfolgreich. Main enthält denselben geprüften Tree.

Auch [Main-Lauf 39382343544](https://github.com/damiankaest/DKMan/actions/runs/39382343544)
für `f2f4b70` wurde anschließend vollständig erfolgreich kontrolliert. Der
abschließende reine Dokumentationscommit ergänzt diese Nachweise mit `[skip ci]`.

74 Backendtests ohne Skip, einschließlich echter PostgreSQL-17-Konkurrenztests und
Migration/Drift/Downgrade. Ruff/Format/mypy, HTTP-Smoke, PowerShell-Parser,
Manifestprüfung und generierte Verträge erfolgreich. Hub: Produktionsbuild,
5 UI-Tests, 2 Browserchecks und Dependency-Audit erfolgreich. Container-Smoke:
Migration Exit 0, PostgreSQL/Core/Keycloak/Hub healthy, Seed registriert nur
Manifestverträge; Doctor bestätigt neues Schema, Proxy, OIDC-Discovery und 401.

Lokal blieb Playwright wegen fehlender Binary und beschädigtem Downloadarchiv
blockiert. Die Browserchecks wurden in CI erfolgreich ausgeführt und verwenden
weiterhin Testantworten. Echte OIDC-/Windows-/Volume-/Restoreabnahmen bleiben offen.
Kein DeploymentService, kein Beispiel-App-Image installiert, keine Zielhostdienste geändert.

## P2-002 · Isolierter Deployment-Adapter · 20.10.2026

- Ausgangspunkt `main` `360b984`; letzter Main-CI-Lauf `39382343544` erfolgreich.
- Separater Adapterprozess/Compose, Dockerzugriff ausschließlich dort. Standardstack
  und Bootstrap unverändert; eigener Katalog standardmäßig leer. Keine Notes-Kuration
  vorgetäuscht und kein Zielhostcontainer gestartet.
- Provider für Discover/Pull/Install/Deploy/Start/Stop/Restart/Status/Logs/Remove und
  separate Datenlöschung; serverseitige begrenzte Pläne, Image-Digests, Ressourcen-
  und Eigentumsprüfungen. Keine freien Befehle, Mounts, Ports oder Environments.
- Kurzlebige rollen-/aktions-/ressourcen-/hashgebundene Delegation mit Approval-ID
  und Ablauf für Mutationen. Typisierter Core-Client, noch kein Core-Runtime-Dispatch.
- Eigenes persistentes SQLite-Journal mit expliziter Migration, OS-Ressourcensperren
  und Operation-ID-Idempotenz. Unsichere Ausgänge bleiben auch nach Neustart gesperrt;
  Reconcile beobachtet tatsächlichen Zustand ohne unbewiesene Erfolgserklärung.
- Lokal bisher 110 Tests bestanden, 8 mangels PostgreSQL/Docker übersprungen;
  Ruff/Format/mypy, Paketbuild und Schemaexport erfolgreich. Core-OpenAPI und
  Frontendtypen bleiben unverändert; Adapter-OpenAPI/Planschema neu exportiert.
- Neue CI-Probe mit realen Dockerimages, Datenerhalt und absichtlichem Healthfehler;
  Nachweis nach eigenständiger Kontrolle ergänzen. Vertrag und Grenzen:
  `deployment-adapter.md`, ADR 0008. Nächster Einstieg P2-003 nach grünem CI.
