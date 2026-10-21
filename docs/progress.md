# Übergabe · DKMan 0.1.0

## Aktueller Stand

Phase-0-Code ist implementiert. Backend, Frontend und vollständiger Compose-Smoke
sind in GitHub Actions erfolgreich geprüft. Die Windows-Zielhost-Abnahme und der
interaktive Login am Zielhost bleiben offen. Die neue echte CI-Journey prüft bereits
OIDC-Code/PKCE mit drei getrennten Keycloak-Benutzern.
Zusätzlich sind zusammenhängende Teile von Phase 1 vorhanden: OIDC-Verifikation,
Registry-Registrierung, App-/Service-/Capabilitysichtbarkeit, Manifestprüfung,
Audit und die entsprechende ServiceHub-Oberfläche. Phase 1 insgesamt ist noch
nicht abgeschlossen. P2-003/P2-004 ergänzen Notes mit eigener PostgreSQL-Datenbank,
explizitem Quellbuild, tatsächlichen kuratierten Image-IDs und genehmigter Installation
über den Hub einschließlich Proxyroute/SSO. Keine Zielhostaktivierung durchgeführt.

P2-001 ist abgeschlossen: persistente Jobs/Events/Approvals mit Idempotenz,
gebundenen Freigaben und Recovery, in `main` über PR #8 integriert. Der erste
Executor validiert tatsächlich registrierte Manifeste. P2-002 ist ebenfalls abgeschlossen:
separater Compose-Provider mit eigenem Operationsjournal und gebundenen Delegationen,
in `main` über PR #9 integriert. P2-003/P2-004 sind als `ef888e7` über PR #10 in `main` integriert;
die vollständige echte Journey und der ergänzende Kompatibilitätslauf sind erfolgreich.
P2-005 ist ebenfalls implementiert und in isolierter CI geprüft: autorisierter Runtime-
Lifecycle über Core/Hub, getrennte Operatorrechte, maskierte Logs und echter Datenerhalt.
P2-005 ist über PR #11 als `07e18c5` integriert; Main-CI `39431777779` vollständig
erfolgreich. P2-006 ist implementiert und über PR #12 geprüft: sichere Belegauflösung
und echte Fehlermatrix; CI 39566266737 grün. Main-Abnahme nach Integration folgt.
Nächster gemeinsamer Schritt P0-007 (Windows-/VM-Testinstallation), nächste Entwicklung
P3-001. Konkrete Nachweise stehen am Ende.

Das private Repository ist `https://github.com/damiankaest/DKMan`.
Der geprüfte Phase-0-Stand wurde über die GitHub-API importiert. Der ursprüngliche
lokale Verlauf bleibt verlustfrei in `docs/archive/DKMan-history.bundle` erhalten.
Die GitHub-Commits beginnen mit dem Import; ursprünglicher Quellstand:
`51c0f1fdb2b8da38d9f281608def57467c9344fb`.

## Implementiert

- Spezifikation übernommen; Architektur, neun ADRs, Threat Model, Backlog und
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
6. P2-001/P2-002: `jobs.md`, `deployment-adapter.md`, ADR 0007/0008 und CI-Nachweise lesen.
7. P2-003/P2-004: `notes.md`, ADR 0009 und die tatsächlichen CI-/Buildnachweise lesen.
   Kein Image-Tag aus dem Beispielmanifest ist eine Kuration. Der lokale Builder
   erfasst die tatsächlich auf seinem Engine gespeicherten Image-IDs.
8. P2-005 ist geprüft: `runtime_api.py`, `runtime_access.py`, ADR 0010, Jobsvertrag und
   `docs/evidence/p2-005-runtime.json` lesen. Keine neue Installation durch Lifecycle,
   keine unbewiesene Auflösung unsicherer Jobs. Core/Hub bleiben ohne Dockerzugriff.
9. P2-006: ADR 0011, runtime-failure-matrix.md und docs/evidence/p2-006-runtime.json lesen.
   Danach P0-007 am freigegebenen Windows-/VM-Testsystem; nächste Entwicklung P3-001.
   Zielhost-/Windows-/Restore- und echte Benutzerabnahmen bleiben eigene Gates.

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
- Lokal 116 Tests bestanden, 8 mangels PostgreSQL/Docker übersprungen;
  Ruff/Format/mypy, Paketbuild und Schemaexport erfolgreich. Core-OpenAPI und
  Frontendtypen bleiben unverändert; Adapter-OpenAPI/Planschema neu exportiert.
- Neue CI-Probe mit realen Dockerimages, Datenerhalt und absichtlichem Healthfehler
  erfolgreich; abschließender PR-Lauf `39388427751` für `bb4b49c` vollständig grün.
  Zusätzlich Ablaufprüfung innerhalb der Journaltransaktion und einmalige Bindung
  jeder Approval-ID an eine Operation. Vertrag und Grenzen:
  `deployment-adapter.md`, ADR 0008. Nächster Einstieg P2-003.

## CI-Abnahme und Integration P2-002 · 20.10.2026

[PR #9](https://github.com/damiankaest/DKMan/pull/9) wurde als `864f002` in `main`
integriert. [PR-Lauf 39388427751](https://github.com/damiankaest/DKMan/actions/runs/39388427751)
prüfte Featurecommit `bb4b49c` vollständig erfolgreich, alle vier Jobs selbst kontrolliert.

- Backend: 123 Tests bestanden; ein bewusst übersprungener Docker-Guardtest wird im
  separaten Adapterjob tatsächlich ausgeführt. PostgreSQL-17-Tests laufen ohne Skip.
- Adapter-Smoke: 1 echter Docker-Integrationstest bestanden, 95,53 Sekunden. Eigene
  Images gebaut, kuratierte Image-IDs verwendet, Health/Lifecycle/Volumenerhalt,
  separate Datenlöschung, fremdes Projekt und Healthfehler-/Neustart-Abgleich geprüft.
- Frontend: Produktionsbuild, 5 UI-Tests, 2 Browserchecks und Dependency-Audit grün.
- Regulärer Container-Smoke: PostgreSQL/Core/Keycloak/Hub healthy, Migration Exit 0,
  Seed/Doctor erfolgreich. Der bisherige Stack erhielt keinen Docker-Socket.

Core-OpenAPI/Frontendtypen und bestehende Alembic-Migrationen sind unverändert.
Neu: Adapter-OpenAPI, Planschema und unabhängige explizite Journalmigrationen 0001/0002.
Zielhostaktivierung, echte OIDC-Mehrbenutzer-, Windows-/VM- und koordinierte
Backup-/Restoreabnahmen bleiben offen. Keine kuratierte Notes-App installiert.

Auch [Main-Lauf 39388850554](https://github.com/damiankaest/DKMan/actions/runs/39388850554)
für `864f002` ist vollständig grün; alle vier Jobs eigenständig kontrolliert. Der
folgende reine Dokumentationscommit speichert den Abschluss mit `[skip ci]`.


## P2-003/P2-004 · Notes und genehmigte Hubinstallation · 20.10.2026

- Ausgangspunkt `main` `3cc27ff`; Main-CI `39388850554` und aktuelle Branches geprüft.
  Keine fremden Dependabot-Änderungen übernommen; bestehende Migrationen unverändert.
- Eigenständige Notes-App mit SQL-Parametern, Textausgabe und serverseitiger
  Autoridentität. Eigene PostgreSQL-17-Instanz, eingeschränkte Approlle und explizite
  transaktionale Migration; keine Appdaten in Core oder Identity.
- Bestätigter Build auf isoliertem Linux-Builder: gepinnte Basis/Lockfiles, tatsächliche
  App-/DB-Image-IDs und Quellhash, validierter Nutzer-/Healthvertrag. Kein Registry-Push,
  kein Platzhalterimage im ausführbaren Katalog. Kuration gilt auf dem jeweiligen Engine.
- Migration 0003 reserviert Pläne getrennt von realen Installationen. PostgreSQLlocks
  verhindern doppelte Instanzen auch bei verschiedenen Keys. Identität, Haushalt,
  Manifestrevision und gesamte Runtime sind an denselben Approval-/Plan-Hash gebunden.
- Core verbraucht die Freigabe und committet den Marker vor Dispatch; Job-ID =
  Adapteroperation. Verlorener Ausgang bleibt gesperrt; Reconcile liest nur das
  gespeicherte Ergebnis. Erst belegter Erfolg materialisiert Installation und Service.
- Hub zeigt Plan/Freigabe/Installation/Verlauf, nimmt gespeicherte Jobs nach Reload
  wieder auf und öffnet nur frisch gemessene gesunde Apps. Read-only-Polling, eigene
  OIDC-Notes-Clientkonfiguration, automatische SSO-Prüfung nach Hub-Reload.
- Getrennte Delegations-/Datenschlüssel; nur Adapter erhält Datenkey und Docker-Socket.
  Ein explizites Runtime-Overlay verknüpft die Dienste, der Basisbootstrap bleibt unverändert.
- Lokal: Ruff/Format/mypy, Paket- und beide Frontendbuilds erfolgreich; 142 Backendtests,
  9 PostgreSQLtests und 1 Docker-Guard mangels lokaler Dienste übersprungen. 7 UI-Tests,
  OpenAPI/Typgenerierung, Dependency-Audits und PostgreSQL/WASM-Migration mit 16 Tabellen
  erfolgreich. Core-, Adapter- und Notes-OpenAPI versioniert.
- Vollständiger PR-Lauf `39408325672` für `d633db6` erfolgreich: fünf Jobs,
  149 Backendtests, 7 UI-Tests, zwei bestehende Browserchecks, echte Adapterprobe und
  echte Notes-Journey (22,8 s) mit drei separaten Keycloak-Logins, UI-Plan/Freigabe,
  echter Installation, gemeinsamen Daten und entzogenem Direktzugriff.
  Zusätzliche echte Stop-/Start-Probe erhält beide Notizen und prüft DB-Least-Privilege.
- Bei der echten Integration behoben: eindeutig zugeordnete Auswahlfeldlabels,
  Unix-Socket-Vertrag des PostgreSQL-Entrypoints, SSO bei Rückkehr in den Hub und
  zu enger Proxyburst bei normaler Verwaltung. Kein Auth-Bypass oder Mutations-Retry.
- Abschließender Zusatz: alte generische v1-Planhashes und Journal-Replays bleiben
  beim Upgrade erhalten; zwei Regressionstests. Finaler PR-Lauf `39409123565` für `8ff5429` vollständig erfolgreich; Integration
  über PR #10 als `ef888e7`. Main-CI `39409720195` ebenfalls vollständig erfolgreich.

Grenzen: Die echte CI-Journey ist keine Windows-/VM-/Zielhostabnahme mit Damians
Benutzern. Passwortwechsel, Logout/Refresh-Matrix, Host-/VM-Neustart, vollständiger
koordinierter Backup/Restore und Runtimeaktionen im Hub bleiben offen. Die bisherigen
Backup-/Restore-/Upgrade-Skripte decken den erweiterten Runtimestack nicht vollständig ab.
Nächster Einstieg P2-005, danach verbleibende P2-006-Fehlermatrix und sichere Entsperrung.


## Abschließende PR-Abnahme P2-003/P2-004

[PR #10](https://github.com/damiankaest/DKMan/pull/10) wurde nach Kontrolle aller
fünf Jobs von [CI 39409123565](https://github.com/damiankaest/DKMan/actions/runs/39409123565)
integriert. Featurestand `8ff5429`, Mainstand `ef888e7`; identischer geprüfter Tree.
151 Backendtests, 7 UI-Tests, zwei bisherige Browserchecks, echter Adaptertest
(85,08 s), echte OIDC-/Notes-Journey (21,4 s) und nachfolgende reale Datenerhalt-/
DB-Rollenprobe erfolgreich. Alte v1-Hashes und gespeicherte Replays zusätzlich geprüft.
Der Basisstack-Smoke meldet Migration Exit 0 und vier gesunde Dienste; Doctor bestätigt
Schema 0003, OIDC-Discovery und anonymes 401. Die neue Journey startet die vollständige
opt-in Runtime mit echtem Adapter und separaten Notes-/PostgreSQL-Containern.


## Main-Abnahme und dauerhafter Buildnachweis P2-003/P2-004

[Main-Lauf 39409720195](https://github.com/damiankaest/DKMan/actions/runs/39409720195)
für `ef888e7` ist mit allen fünf Jobs vollständig erfolgreich; auch dieser Lauf wurde
eigenständig geprüft. 151 Backendtests, 7 UI-Tests, 2 bestehende Browserchecks,
echte Adapterprobe und echte Notes-/OIDC-Journey (21,2 s); anschließende reale
Datenerhalt-/Least-Privilege-Probe ebenfalls erfolgreich.

Die tatsächlichen App-/DB-Image-IDs und der Quellhash aus diesem Main-Build sind in
[build-evidence.json](../examples/demo-notes/build-evidence.json) dauerhaft versioniert;
[CI-Artefakt](https://github.com/damiankaest/DKMan/actions/runs/39409720195/artifacts/12259580381)
enthält den tatsächlich kuratierten Katalog und Buildbericht. Die IDs gelten auf
diesem Engine, nicht als Registry-Pullreferenzen auf einem anderen Host.
Der abschließende Dokumentations-/Nachweiscommit enthält keine Runtimeänderung und
überspringt CI ausdrücklich. P2-003/P2-004 abgeschlossen; nächstes Ticket P2-005.


## P2-005 · Implementierung und laufende Verifikation · 20.10.2026

Ausgangsstand `ebd606c`, Main-CI `39409720195` eigenständig bestätigt. Dependency-PRs
bleiben unberührt. Runtime-APIs, explizite Operatorrechte `app.operate`, vollständige
Lifecyclepläne/Approvalbindung und Hubsteuerung sind implementiert. Keine Änderung
bestehender Migrationen oder v1-Hashes/Journale. Details: ADR 0010 und `jobs.md`.

Lokal sind Ruff/Mypy, Paketbuild und HTTP-Smoke sowie Hub-Lint/Produktionsbuild,
11 UI-Tests und Produktionsaudit ausgeführt. Neue Coretests decken autorisierte
Lifecycleübergänge, Freigaben, Ablauf, Idempotenz, Ressourcenrechte, Redaction,
verlorene Antworten und Recovery ab. Reale PostgreSQL-Konkurrenz und Container-/
OIDC-Journey sind als CI-Gates erweitert; Abschlussnachweis folgt nach erfolgreicher
CI und Mainintegration. Kein lokaler Docker-Daemon, keine Zielhoständerung.


Erster vollständiger PR-Lauf [39427241600](https://github.com/damiankaest/DKMan/actions/runs/39427241600)
für `f0f5011` erfolgreich: 182 Backendtests (ein Docker-Guard im eigenen Job), 11 UI-Tests,
2 bestehende Browserchecks, echter Adaptertest (87,53 s), Plattform-Smoke und echte
Notes-/OIDC-Lifecycle-Journey (1,1 min). Engineprobe belegt Stop beider Container,
identische Container/Images/Volumes und tatsächlich neue Startzeitpunkte. Vollständige
Notes-Datensätze nach Start und Restart identisch; getrennte Betriebsfreigabe/Widerruf geprüft.

Im Log fiel eine kurzzeitige 429-Antwort beim Freigabeladen auf. Deshalb doppelte
Runtime-Detailabfragen entfernt und Benutzer-/Haushaltsverzeichnisse von Mitglieds-/
Grantänderungen getrennt geladen. Die bestehende Proxybegrenzung bleibt unverändert.
Die echte Journey verlangt jetzt zusätzlich das Ausbleiben von 429-Antworten.
Abschließender CI-/Mainnachweis folgt; keine externe Mutation wird automatisch wiederholt.


Der Folgelauf `39428416976` legte nach erfolgreichem Stop eine Read/Read-Kollision
zwischen Healthpolling und Logabruf offen (503). Die Sperre war bisher auch für
lesende Operationen exklusiv. Korrektur: gemeinsame Lesesperren, weiterhin exklusive
Mutationen und maximal zwei Sekunden Wartezeit allein für den Sperrerwerb. Keine
Wiederholung von Docker-/Provideraufrufen. Zwei deterministische Regressionstests
prüfen parallele Leser, ausgeschlossene Schreiber, erfolgreichen späteren Erwerb
und Wartezeitgrenze. Die echte Journey bleibt unverändert streng.


Folgelauf `39429546677`: 184 Backendtests, 11 UI-Tests, 2 Browserchecks und beide
Smoke-Jobs erfolgreich. Die echte Journey belegt nun Stop **und** Logzugriff trotz
parallelem Healthpolling. Danach wurde ein Frontendrennen sichtbar: die Checkbox
konnte während des noch laufenden Planladens angehakt und anschließend wieder
zurückgesetzt werden. Checkboxen bleiben jetzt bis zum Ladeabschluss gesperrt;
verspätete alte Detailantworten verdrängen keine neuere Auswahl. Ein Test mit bewusst
verzögerter Statusantwort reproduziert diese Grenze ohne echte Auth zu ersetzen.


## Abschließende PR-Abnahme P2-005 · 20.10.2026

[PR #11](https://github.com/damiankaest/DKMan/pull/11), geprüfter Runtime-/UI-Commit
`f408059d3b0163c94864f78e90826b33034c282e`:
[CI 39430552396](https://github.com/damiankaest/DKMan/actions/runs/39430552396) vollständig
erfolgreich, alle fünf Joblogs eigenständig kontrolliert. 184 Backendtests mit
PostgreSQL 17, 11 UI-Tests, 2 bestehende Browserchecks, echter Docker-Adaptertest
(92,13 s), echte OIDC-/Notes-Journey (58,7 s) und nachfolgende Persistenz-/DB-Rollenprobe
bestanden. Die letzte Journey enthält keine 429-/503-Antwort; erwartete fremde bzw.
entzogene Appzugriffe bleiben 404.

Die tatsächlichen Container-/Image-/Volume-IDs und Startzeitpunkte sowie die drei
Core-Jobs/Operationen sind dauerhaft in [p2-005-runtime.json](evidence/p2-005-runtime.json)
versioniert. Das [CI-Artefakt](https://github.com/damiankaest/DKMan/actions/runs/39430552396/artifacts/12268236404)
wurde heruntergeladen und seine SHA-256 geprüft. Image-IDs gelten ausschließlich auf
dem jeweiligen CI-Engine, nicht als Registry-Pullreferenzen. Keine Secrets im Nachweis.

Lokaler Endstand: 173 Backendtests bestanden, 11 PostgreSQLfälle und 1 Docker-Guard
mangels lokaler Dienste übersprungen; alle diese PostgreSQLfälle liefen in CI.
Ruff/Format/Mypy, Paketbuild, HTTP-Smoke, Manifest-/Vertragsprüfung, Hub-Lint/Build,
11 UI-Tests und Produktionsaudit erfolgreich. PostgreSQL/WASM-Roundtrip ebenfalls
bestanden. Lokaler Browserstart mangels Chromium blockiert; beide Browserchecks in
CI erfolgreich. Bestehende Migrationen, Requirements/Lockfiles und alte v1-Hashes
bleiben unverändert.

Der folgende reine Dokumentations-/Nachweiscommit enthält keine Runtimeänderung
und überspringt CI ausdrücklich. Nach Integration wird der Main-Lauf gesondert geprüft.
P2-006 bleibt nächster Einstieg; Zielhost-/Windows-/VM-/vollständige OIDC-Betriebsmatrix
und koordinierter Backup/Restore bleiben offen. Keine vorhandenen Hostdienste geändert.


## Mainintegration und abschließende Abnahme P2-005

[PR #11](https://github.com/damiankaest/DKMan/pull/11) ist als
[`07e18c5e0b9f6082b96a846e63455c90b0cef854`](https://github.com/damiankaest/DKMan/commit/07e18c5e0b9f6082b96a846e63455c90b0cef854)
in `main` integriert. Der integrierte Tree entspricht exakt dem geprüften Featurestand
plus reinem Dokumentations-/Nachweischeckpoint; dies wurde nach dem Merge verglichen.
Keine fremden Dependency-PRs integriert, keine bestehenden Migrationen/Lockfiles geändert.

Zusätzlich [Main-CI 39431777779](https://github.com/damiankaest/DKMan/actions/runs/39431777779)
für `07e18c5` vollständig erfolgreich. Logs aller fünf Jobs eigenständig geprüft:
184 Backendtests einschließlich PostgreSQL-17-Konkurrenz und Migrationen, 11 UI-Tests,
2 bestehende Browserchecks, echter Adaptertest (96,54 s), Plattform-Smoke und echte
Notes-/OIDC-Journey (1,0 min) erfolgreich. Die zusätzliche echte Daten-/DB-Rollenprobe
besteht ebenfalls. Kein 429/503 im Main-Journeylog; erwartete unberechtigte Notes-
Datenzugriffe liefern 404. Die zwei älteren Browserchecks bleiben Tests mit Testantworten.

Tatsächlicher separater Main-Nachweis mit Container-/Image-/Volumeidentität, Startzeiten,
Core-Job-/Operations-IDs und Planhashes:
[p2-005-main-runtime.json](evidence/p2-005-main-runtime.json).
[Artefakt 12268123279](https://github.com/damiankaest/DKMan/actions/runs/39431777779/artifacts/12268123279)
wurde heruntergeladen und SHA-256
`5cb0412cd2669197d5a842077c2a588ccb052d5783aa80de4db04bd34219a94d` bestätigt.
Engine-lokale Image-IDs sind weiterhin keine Registry-Pullreferenzen.

P2-005 ist abgeschlossen. Der folgende reine Dokumentations-/Nachweiscommit verändert
keine Runtime und verwendet ausdrücklich `[skip ci]`. Die dokumentierte Main-CI prüft
alle integrierten Runtime-/UIquellen. Windows-/VM-/Zielhostabnahmen, vollständige OIDC-
Betriebsmatrix und koordinierter Backup/Restore bleiben offen. Bestehende Backup-/
Restore-/Upgrade-Skripte decken den Runtimestack nicht vollständig ab.

Nächster Einstieg P2-006: `runtime_api.py`, `deployment_api.py`, `jobs.py`, Adapterjournal,
ADRs 0007–0010 und die echten Journey-/Sperrentests lesen. Die positive Journey B ist
bereits belegt. Die restliche Fehlermatrix (verbotene Images, Rechte, DB-Ausfälle) und
einen belastbaren Abschluss dauerhaft unsicherer Adapteroperationen ergänzen. Aktuelle
Health allein, insbesondere nach möglichem Restart, reicht weiterhin nicht. Keine
pauschale Entsperrung, keine Journallöschung und kein Blind-Retry als Wiederanlaufweg.

## P2-006 · Implementierung und lokale Vorprüfung · 21.10.2026

Ausgang `main` `29ce123`, letzter Runtimecommit `07e18c5`; Main-CI `39431777779`
und alle fünf Jobs eigenständig geprüft. Lokaler isolierter Checkout stimmt mit dem
Remote-Quellstand überein (historischer Bundle bleibt ausschließlich remote erhalten;
PowerShell-Zeilenenden lokal normalisiert). Keine fremden Dependencyänderungen übernommen.

Implementiert: explizite Adaptermigration 0003 für dauerhafte Enginebelege, bindungs- und
aktionsspezifischer Abgleich unter exklusiver Ressourcensperre, erneute Core-Belegprüfung,
gebundene Nichtausführungsnachweise, Hub-Nachweishash. Kein Docker-Retry, keine pauschale
Entsperrung. Gesunde Runtime ohne Beleg bleibt gesperrt. Bestehende Plan-/Journalverträge
und Coremigrationen bleiben kompatibel; Details ADR 0011.

Lokal bisher Ruff/Format/Mypy, Paketbuild und HTTP-Smoke bestanden; 199 Backendtests
bestanden, 12 explizite PostgreSQL-/Docker-Skips ohne lokale Dienste. Hub npm ci,
Typgenerierung, Lint, Produktionsbuild und zunächst 11 UI-Tests bestanden. Zusätzliche
UI-/Statusregression und Endprüfung folgen. Reale CI-Abnahme steht vor Push noch aus.

Neue echte CI-Fehlermatrix: unberechtigte Runtime-/Imageanfragen, Notes- und Core-DB-Ausfall,
Adapterprozessabbruch nach und vor Enginebeleg. Alle Logins/Engineaktionen bleiben echt;
Abbrüche stammen ausschließlich aus einem separat gemounteten Testentrypoint. Belegbare
Auflösung erlaubt Wiederanlauf, fehlender Beleg hält trotz gesunder Container die Sperre.
Windows-/VM-Abnahme, volle OIDC-Betriebsmatrix und koordinierter Runtime-Backup/Restore
bleiben offen. Windowsanleitung ergänzt den Weg vom Preflight bis zur Notes-Testinstallation.


## P2-006 · Abschließender PR-Nachweis

[PR #12](https://github.com/damiankaest/DKMan/pull/12), Runtimecommit `99aaeed`,
[CI 39566266737](https://github.com/damiankaest/DKMan/actions/runs/39566266737):
alle fünf Jobs erfolgreich; sämtliche Joblogs eigenständig kontrolliert. 214 Backendtests
mit PostgreSQL 17 (1 absichtlicher Docker-Guard im separaten Adapterjob ausgeführt),
12 UI-Tests, 2 bisherige Browserchecks, echter Adaptertest in 95,71 s, echte OIDC-/Notes-
Fehlerjourney in 1,9 min und nachfolgende echte Daten-/DB-Rollenprobe bestanden.
Die erwarteten DB-Ausfälle liefern 503; unberechtigte Zugriffe 403/404, freies Imagefeld
422 und neue Mutation bei fehlendem Beleg 409. Keine 429-Antwort im Journeylog.

Belegt: Notes/Core-DB-Ausfall und Wiederanlauf; realer Adapterabsturz nach dauerhafter
Enginebestätigung, persistierter Job nach Reload und erfolgreicher Nachweisabgleich;
zweiter echter Absturz vor Belegcommit bleibt trotz gesunder Runtime gesperrt. Die
zusätzliche Engineprobe bestätigt unveränderte Container/Volumes und keinen weiteren
Restart durch Reconcile. Nachweise enthalten vollständige begrenzte Enginebelege und
die gebundenen Corejobs, keine Secrets oder simulierten HTTP-Antworten.

Dauerhaft: [p2-006-runtime.json](evidence/p2-006-runtime.json), Artefakt `12330397133`,
ZIP-SHA-256 `fe9ca201c785cfeea00ddec541afa392d8366e03f4ae2e322c5c639b956d4a12`.
Heruntergeladen, Prüfsumme sowie Core-/Adapter-/Enginebindungen zusätzlich geprüft.
Image-IDs sind ausschließlich lokal auf dem jeweiligen CI-Engine verfügbar.

Lokaler Endstand tatsächlich: 203 Backendtests bestanden, 12 Dienst-/Docker-Skips;
Ruff/Format/Mypy, Wheel/Sdist und HTTP-Smoke erfolgreich. Wheel enthält Migration 0003,
keinen CI-Faultentrypoint. Hub npm ci, Vertragsgenerierung ohne Drift, Lint/Build und
12 UI-Tests erfolgreich. Lokaler Browserstart mangels Chromium-Binary blockiert;
beide Browserchecks sind in CI bestanden. Core-/Adapter-OpenAPI exportiert; Coretypen
unverändert regeneriert. Alte Migrationen/Lockfiles unverändert. Zusätzliche Regressionen:
Delegationsablauf nach Enginebeobachtung, Rechteentzug während Reconcile-I/O,
Rejection ohne Lösen einer fremden Sperre und einmalige Approval-ID auch bei Ablehnung.

Neue Adapterjournalrevision 3 ist explizit zu migrieren; Core bleibt auf 0003. Kein
Force-Success oder Runtime-Retry. Zielhost-/Windows-/VM-/OIDC-Betriebs- und koordinierte
Backup-/Restoregates bleiben offen. Windowsanleitung enthält den konkreten Teststart;
keine Windows- oder Hoständerung durchgeführt. Nach Integration Main-CI prüfen.
