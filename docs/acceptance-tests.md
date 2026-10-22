# Ausgeführte Prüfungen · Stand 22.10.2026

## P3-002 · Abschließende CI-Abnahme · 22.10.2026

Code `a27f8b18c81136a8bf40e3325d99d83ddca19bba` besteht
[PR-CI 39748544251](https://github.com/damiankaest/DKMan/actions/runs/39748544251)
und [Branch-CI 39748531267](https://github.com/damiankaest/DKMan/actions/runs/39748531267)
mit allen fünf Jobs. **299 Backendtests / 1 expliziter Docker-Guard-Skip**, 19 UI-Tests,
6 Browserchecks, 3 echte OIDC-Journeys, eine echte Docker-Adapterprobe und der
vollständige Basisstack-Smoke sind erfolgreich. PostgreSQL-/Migrations-/Konkurrenz-
prüfungen und Vertragsdrift bleiben grün. Der optionale Modell-Compose-Zusatz besteht
seine Konfigurationsprobe ohne Anbieteraufruf.

Die neue Chat-Journey verwendet drei echte Keycloak-Nutzer und den produktiven Core:
Entwurf erst prüfen/bearbeiten, dann persistent speichern und nach Reload lesen;
realen wartenden und danach abgebrochenen Job mit Ereignissen abfragen; fremden
Job/Request verbergen; nur berechtigte Registrydaten; kuratierte Installationsdefinition
korrekt vorwählen; keine neuen Jobs/Installationen durch Chatvorschläge. Notes-
Daten-/Rollen-/Lifecycle-/Fehlermatrix und die bestehende Planfreigabejourney bleiben grün.
Der HTTP-Modellvertrag ist kontrolliert getestet, kein bezahlter Modellaufruf.

Dauerhafter Nachweis: `docs/evidence/p3-002-chat.json`, inklusive gelesener Job-IDs und
Artefaktmetadaten. PR-Artefakt `12412528288` enthält `.local/chat-journey.json`;
ZIP-SHA-256 `7a5349ffc96e6b86b5d1751399a8d05add273346dbe45fd83e3ca5f0d653816f`.
Kein Zielhostupgrade. P3-003 und P4 bleiben offen.

PR #14 ist als `a671c643acad7d5a37afce3a2af4ac4d6902565f` in `main` integriert.
Der gelesene Main-Tree `9471b5e9c851b52e37a59155c8729ded2d9a3518` ist identisch
mit dem geprüften PR-Stand einschließlich der anschließenden vier reinen Nachweisdateien.
Main-CI `39749924394` läuft beim Schreiben noch; kein Ergebnis dafür behauptet.
Der folgende reine Integrationsnachweis verändert keinen Programmcode.

### Lokale Prüfungen

`uv sync --frozen`, Ruff/Format/mypy, `uv build` und HTTP-Smoke erfolgreich.
Pytest **285 bestanden / 15 Skips** (14 PostgreSQL, 1 Dockerguard); davon 67 neue
Dispatcher-/Providerprüfungen. Hub npm ci, Lint, Build und **19 UI-Tests** erfolgreich.
**6 Playwright-Prüfungen** erfolgreich: Hub, manuelle Planung und Chat→Entwurf→geprüftes
Speichern jeweils Desktop/Handy, kein horizontaler Überlauf; Screenshots visuell geprüft.
Lokaler Browser: separat bereitgestelltes Chromium 153, keine Produktionsabhängigkeit.

Geprüft: OIDC-Pflicht, serverbestimmte Identität/Provider, begrenzte Eingaben, gleiche
Sichtbarkeit wie Apps/Registry, keine erfundene Health, eigene Jobereignisse, keine
Mutation durch Runtime-/Installationsvorschläge, gespeicherte Anforderung erst nach
expliziter Formularprüfung, fremde/erfundene Ziele und Rechtewiderruf nach Modell-I/O.
HTTP-Vertrag: JSON-Modus, minimale berechtigte Kontextdaten, begrenzte Antwort,
Truncation/Refusal/Toolcalls abgewiesen, feste Fehlercodes, kein Retry, HTTPS ohne
Credentials/Redirects, reguläre begrenzte Secretdatei, maximal zwei parallele Calls.
Echte Anbieteraufrufe und Zielhostprüfungen nicht ausgeführt. Die zusätzliche reale
OIDC-Chat-Journey und optionale Compose-Konfigurationsprobe sind oben separat belegt.

Die folgenden P3-001-/P2-Abschnitte sind historische Nachweise.

## P3-001 · Abschließende CI-Abnahme · 22.10.2026

Korrigierter Code `a41bc151156a044b36a1e03529bec773d9313fa6`:
[PR-CI 39731623907](https://github.com/damiankaest/DKMan/actions/runs/39731623907)
und [Branch-CI 39731620032](https://github.com/damiankaest/DKMan/actions/runs/39731620032)
vollständig erfolgreich. Alle fünf PR-Jobs und ihre relevanten Logs selbst geprüft.

| Job | Tatsächlich abgenommen |
| --- | --- |
| backend | **232 bestanden, 1 Dockerguard-Skip**; PostgreSQL 17 einschließlich drei neuer Planungskonkurrenztests; Migration 0004 Upgrade/Drift/Downgrade/Reupgrade; Ruff/Format/mypy, HTTP-Smoke, PowerShell und Vertragsdrift |
| frontend | Lint/Build, **15 UI-Tests**, **4 Desktop-/Handy-Browserprüfungen** einschließlich Reload/Wiederöffnung; Vertragsgenerierung und Produktions-Audit erfolgreich |
| adapter-smoke | **1 echter Docker-Integrationstest** in 95,15 Sekunden; bestehende Runtime-/Datenerhalt-/Fehlerregression erfolgreich |
| container-smoke | Images gebaut, Migration Exit 0, PostgreSQL/Core/Keycloak/Hub healthy; Seed registriert zwei Verträge; Doctor bestätigt aktuelle Revision/Proxy/OIDC und anonyme Zugriffssperre |
| notes-journey | **2 echte Journeys bestanden** in 2,2 Minuten: bisherige OIDC-/Notes-/Lifecycle-/Fehlermatrix und neue persistente Planung mit drei echten Keycloak-Konten |

Die Planungsjourney legt per Member-UI eine Idee an, lädt den Browser neu und öffnet
dieselben gespeicherten Requirements. Adminfreigabe durchläuft die echte Jobgrenze;
danach unveränderte Appinstallationen. Revision 2 besitzt keine geerbte Freigabe,
Revision 1 behält Dokument/Hash/Nachweis; fremde Direktabfragen werden 404.
Keine Auth-Overrides oder HTTP-Testantworten in diesen beiden echten Journeys.

Der CI-Artefaktdownload `12406095247` wurde anhand seines gemeldeten SHA-256
`c722bebceb164ec911614d624301a583e0ff656c5487576d05124df22a513664` geprüft.
Der enthaltene echte Planungsnachweis mit Request-/Plan-/Job-IDs und Versionshashes
liegt dauerhaft unter [evidence/p3-001-planning.json](evidence/p3-001-planning.json).
Keine produktiven Schlüssel oder Benutzerdaten darin. Der anschließende reine
Nachweiscommit verändert keinen geprüften Programmcode und überspringt CI ausdrücklich.

Keine fernbediente Windowsaktualisierung, keine neue App generiert. Zielhost-
Neustart/Autostart/Mehrgeräte/Restore bleiben eigene Gates. Nächste Entwicklung P3-002.

Integration: [PR #13](https://github.com/damiankaest/DKMan/pull/13) als `efde76d`
in `main`. Main-Tree `5f33184f1f93a9c0b8f0d97bb519b98e6d22a086` ist mit dem
geprüften PR-Tree identisch. Zusätzlicher Main-CI-Lauf `39732646116` beim Schreiben
dieses Nachweises noch laufend; keine vorweggenommene Main-CI-Erfolgsaussage.

## P3-001 · Lokale Prüfung · 22.10.2026

Ausgangspunkt: Remote-`main` `b44afcd`; letzter ausführbarer Main-CI-Lauf
`39567571003` für `6c749e2` selbst erfolgreich kontrolliert. Neuer isolierter
Workspace, Quellstand mit 185 Repositorydateien gegen GitHub-Blobhashes geprüft.
Kein Docker-Daemon und kein Windows-Zielhostzugriff im Workspace.

| Prüfung | Tatsächliches Ergebnis |
| --- | --- |
| Dependencies | `uv sync --frozen`; im Hub `npm ci --ignore-scripts --no-audit --no-fund` erfolgreich; Lockfiles unverändert |
| Python | Ruff Check/Format und `uv run mypy` (38 Quelldateien) erfolgreich |
| Backend | `uv run pytest -q`: **218 bestanden, 15 übersprungen**; 14 PostgreSQL-Tests ohne lokale Testdatenbank und 1 ausschließlich auf wegwerfbarem Docker-Runner zulässige Probe |
| Planung | 15 neue API-/Persistenz-/Fehlertests bestanden; 3 neue echte PostgreSQL-Konkurrenztests lokal ausdrücklich übersprungen |
| Migration | PostgreSQL/WASM: Upgrade auf `0004_app_planning`, 18 Tabellen, FK-Negativprobe, Downgrade und erneutes Upgrade erfolgreich; ersetzt keinen PostgreSQL-17-Netzwerktest |
| Backendpaket/Prozess | `uv build` erfolgreich; echter Uvicorn-Smoke: Live 200, Ready ohne DB 503, anonymes Me 401 |
| Hub | Lint, TypeScript-/Produktionsbuild und **15 UI-Tests** erfolgreich |
| Browser | **4 Playwright-Prüfungen** erfolgreich: abgemeldeter Hub und neue Planung jeweils Desktop/Handy; gespeicherter Entwurf, kein horizontaler Überlauf; Screenshots visuell geprüft |
| Verträge | OpenAPI exportiert, TypeScript generiert; erneuter Export/Generierung ohne Hashdrift; `git diff --check` erfolgreich |

Planungstests prüfen Eigentümer-/Rollen-/Haushaltsisolation und Widerruf, strenge
Anforderungsdaten, Idempotenz/Schlüsselkonflikte, unveränderte historische Dokumente,
veraltete erwartete Revisionen, gebundene Freigabe, aktuelles Dokument beim Abschluss,
keinen Appinstallationsdatensatz durch Planfreigabe, atomaren Rollback bei Create/
Revision/Abschluss sowie Persistenz in neuem Appprozess und konservative Recovery.
Die UI-Tests prüfen zusätzlich denselben Requestschlüssel nach Transportfehler,
einen neuen Schlüssel für eine absichtlich weitere Idee und die genaue Approvalbindung.

Browserprüfungen verwenden ausdrücklich HTTP-/Auth-Testantworten. Der normale
Playwrightdownload liefert lokal weiterhin ein ungültiges Archiv. Stattdessen
Chromium 153.0.0 aus `@sparticuz/chromium` für Tests entpackt und über
`DKMAN_TEST_BROWSER=/tmp/chromium FONTCONFIG_PATH=/tmp/fonts npm run test:e2e`
verwendet. Browserartefakte und temporäre Pakete sind keine Projektabhängigkeiten.

Die neue `journey/planning.spec.ts` prüft dagegen im echten CI-Stack mit drei
Keycloak-Konten Plananlage/-wiederaufnahme, Adminfreigabe, separate neue Version,
fremden Direktzugriff und unveränderte Appinstallationen. Vollständige CI-Abnahme
einschließlich PostgreSQL-17-Konkurrenz/Migration, Notes- und Dockerregression ist
zum Zeitpunkt dieses lokalen Nachweises noch ausstehend.

Der erste PR-Lauf `39730755621` bestätigte Backend (232 bestanden / 1 Dockerguard),
Frontend, Adapter und Basisstack, fand aber im neuen Planungsjourney eine instabile
Labelauflösung nach Wiederöffnung vorbefüllter Textareas. Der gespeicherte Inhalt
war im Browser vorhanden. Labels und Controls sind nun über separate `htmlFor`/`id`
verbunden; der lokale Desktop-/Handytest reproduziert zusätzlich Reload und erneutes
Öffnen. Danach erneut 15 UI-Tests, vier Browserprüfungen, Lint und Build erfolgreich.
Ein neuer vollständiger CI-Lauf muss diesen korrigierten Stand abnehmen.

Damian bestätigt am 22.10.2026 den erfolgreichen lokalen DKMan-Start. Dies ist kein
von hier ausgeführter Windows-/Neustart-/Autostart-/Mehrgeräte-/Restoretest.
Die historischen Abnahmen und deren damalige Grenzen folgen unten.

Die ursprünglichen lokalen Prüfungen wurden im isolierten Work-Workspace ausgeführt,
**nicht auf Damians Windows-Rechner**. Ergänzende GitHub-CI-Prüfungen stehen unten.
Python 3.12.14, Node 24.19.0. Kein Docker-Daemon, kein Windows-Hostzugriff.

## Bestanden

| Prüfung | Tatsächlicher Befehl / Ergebnis |
| --- | --- |
| Python-Dependencies | `uv sync --frozen`; vollständiges `uv.lock`; gehashte Produktions-Requirements exportiert |
| Python-Lint/Format | `uv run ruff check backend scripts tests`; `uv run ruff format --check backend scripts tests` |
| Python-Typprüfung | `uv run mypy`; 12 Quelldateien ohne Fehler |
| Backend-/Skripttests | `uv run pytest -q`; 39 bestanden, 1 PostgreSQL-Netzwerktest explizit übersprungen |
| Backend-Build | `uv build`; Wheel und Source Distribution erfolgreich gebaut |
| Echter HTTP-Start | `uv run python scripts/smoke_core.py`; Uvicorn gestartet/beendet, `/health/live` 200, `/health/ready` bei nicht erreichbarer DB 503, `/api/v1/me` ohne Token 401 |
| PostgreSQL-DDL | `cd tests/postgres-wasm && npm ci && npm test`; PostgreSQL 18.6 / PGlite 0.5.10: Upgrade, Revision, 12 Tabellen inkl. Alembic, FK-Verletzung abgewiesen, Downgrade, erneutes Upgrade |
| Manifestbeispiele | `uv run python scripts/validate_manifests.py`; beide gültig; negative Schema-/Privileg-/Pfadtests in Pytest |
| API-/Schema-Verträge | Export und TypeScript-Generierung erneut ausgeführt; SHA-256 vor/nach identisch |
| Frontend-Lint/Build | `npm run lint`; `npm run build` inklusive TypeScript-Prüfung und Vite-Produktionsbuild |
| Frontend-Tests | `npm test`; 4 Vitest-Tests bestanden |
| Browserprüfungen | `npm run test:e2e`; 2 Playwright-Tests (Desktop und mobiles Viewport), kein horizontaler Überlauf; Screenshots visuell geprüft |
| Compose-Schema | offizielles Compose v5.6.0, Download-Checksumme verifiziert; `docker-compose --env-file .env.example -f infrastructure/compose/compose.yaml config --quiet` erfolgreich |
| Bash | `bash -n` für alle Linux-/Container-Shellskripte; Bootstrap ohne Parameter tatsächlich als Dry-run ausgeführt |
| PowerShell-Syntax | portables PowerShell 7.6.7, Download-Checksumme verifiziert; `pwsh -NoProfile -File scripts/check_powershell.ps1` für beide Windows-Skripte erfolgreich |
| Dependency-Audit | `npm audit --omit=dev --audit-level=high`: 0 gemeldete Schwachstellen; `uvx pip-audit -r requirements.lock --disable-pip --no-deps`: keine bekannten Schwachstellen gemeldet |
| Frischer Git-Checkout | lokalen Commit ohne Hardlinks in neues Verzeichnis geklont; dort `uv sync --frozen` + 39 bestandene Backendtests (1 Skip) und `npm ci` + Frontend-Produktionsbuild erneut erfolgreich |

Die API-Tests nutzen eine isolierte SQLite-Datenbank für schnelle Anwendungsfälle
und Test-Dependency-Overrides für Benutzer. Token-Tests prüfen zusätzlich echte
RSA-Signaturen, falschen Issuer/Audience/Ablauf/Algorithmus, fremde Signaturen und
Identity-Ausfall. Es gibt keine Laufzeit-Auth-Abschaltung im Produktivcode.

Die Browserprüfungen ersetzen Identity und Health ausdrücklich durch Testantworten.
Sie beweisen Darstellung/Bedienbarkeit, **nicht** den echten Login. Der reguläre
Playwright-Browserdownload lieferte hier kein gültiges ZIP. Stattdessen wurde lokal
Chromium 153.0.8010.0 aus `@sparticuz/chromium` 153.0.0 entpackt und über
`DKMAN_TEST_BROWSER` verwendet. Der normale CI-Weg bleibt `npx playwright install
--with-deps chromium`. Test-Binaries, Screenshots und Testzugangsdaten sind nicht
im Übergabepaket enthalten.

Der WASM-Test führt Alembics PostgreSQL-SQL auf einer echten PostgreSQL-WASM-Engine
aus. Er ersetzt weder den Zielversions-Test auf PostgreSQL 17 noch psycopg-Verbindung,
Rollenisolation, Volume-Persistenz oder Containerstart. Ein nativer PostgreSQL-Prozess
ließ sich hier wegen gesperrtem OS-Benutzerwechsel nicht starten. Kein Systembenutzer
wurde angelegt; der pytest-Netzwerktest wird daher transparent übersprungen.

## Noch nicht ausgeführt / nicht abgenommen

- Zielhostprüfungen zur Core-/Identity-DB-Isolation und Volume-Persistenz.
  Notes-Rolle und Notes-Datenerhalt sind inzwischen zusätzlich in echter CI geprüft.
- Benutzerabnahme am Zielhost einschließlich Passwortwechsel, Logout/Refresh-Matrix
  und CSP. Die neue echte CI-Journey prüft Code/PKCE/JWKS/SSO und Appfreigaben mit
  drei getrennten Keycloak-Konten; sie ersetzt die Zielhostabnahme nicht.
- Windows-10-Preflight auf echter Hardware, Featureaktivierung, Ubuntu-VM/WSL2,
  Netzwerk, Host-/VM-Neustart und Autostart. Syntaxprüfung ist keine Hostabnahme.
- Backup, Restore und Upgrade im laufenden Stack; Skripte existieren, aber kein
  behaupteter Recovery-Erfolg. Container-Securityscan mangels gebauter Images offen.
- Journey B am Zielhost bleibt offen. Notes-Build/Kuration, UI-Plan/Freigabe,
  echte Installation/SSO und Mehrbenutzerrechte sind seit P2-003/P2-004 in einer
  separaten echten CI-Journey geprüft; P2-005 ergänzt den kompletten autorisierten
  Runtime-Lifecycle über Core/Hub mit realem Daten-/Containeridentitätsnachweis.

## Zielhost-Abnahme P0-007

1. Windows-Preflight lesen/ausführen, vorhandene Dienste und Ports prüfen.
2. Dedizierte Linux-Laufzeit vorbereiten; Dockerkontext vor Apply kontrollieren.
3. Frisches Projekt: Bootstrap-Dry-run, dann bewusste `INSTALL`-Bestätigung.
4. Doctor muss DB-Schema, Identity-Discovery und 401 für anonymen Zugriff bestätigen.
5. Mit temporärem Plattformkonto anmelden, Passwort wechseln; zwei registrierte
   Manifestbeispiele in der Verwaltung sehen, keine angeblich laufenden Apps.
6. Zweiten Nutzer ohne Adminrolle anlegen: Registry-POST und Katalog bleiben 403.
7. Stack/VM/Host gezielt neu starten; Daten/Identity und Doctor erneut prüfen.
8. Erst danach die Runtime-Abnahme für Notes und DeploymentService aufbauen.

## GitHub Actions · ergänzende Abnahme

[CI-Lauf 39296486987](https://github.com/damiankaest/DKMan/actions/runs/39296486987), Commit `b78c7e506189ee942e1f583d5ba7f4138ca90b95`:

| Job | Ergebnis |
| --- | --- |
| backend | Erfolgreich: 40 Tests ohne Skip, PostgreSQL 17 über psycopg, Lint/Format/mypy, HTTP-Smoke, PowerShell-Parser, Manifest- und Vertragsprüfung |
| frontend | Erfolgreich: npm ci, generierte Typen ohne Drift, Lint/Build, vier Vitest- und zwei Playwright-Tests, Produktions-Audit |
| container-smoke | Erfolgreich: Core-/Hub-/Keycloak-Images gebaut, Compose-Start, Migration Exit 0, PostgreSQL/Core/Keycloak/Hub healthy, Seed und Doctor |

Doctor prüfte über den Proxy Live/Ready, OIDC-Discovery sowie HTTP 401 ohne Token.
Der Seed registrierte zwei Manifestverträge und installierte keine Images.
Die CI lief auf einem wegwerfbaren Ubuntu-Runner. Das ersetzt weder die
Windows-Zielhost-Abnahme noch den interaktiven OIDC-Login.

## P1-004: Haushalte und Freigaben

Automatisiert: `uv run pytest tests/test_access.py -q` und im Hub `npm test`.
API-Tests verwenden ausschließlich Test-Dependency-Overrides, keine echten OIDC-Logins.
Manuelle Abnahme (offen): zwei Benutzer in Keycloak erstellen und einmal im Hub
anmelden; als Admin Haushalt anlegen, nur Benutzer A hinzufügen. Beide sehen keine
Apps ohne Grant. Nach einer echten Installation A freigeben; B darf sie weder listen
noch direkt lesen. A aus Haushalt entfernen und wieder hinzufügen: App bleibt
unsichtbar, bis eine neue explizite Freigabe erfolgt. Andere Haushalte bleiben
unberührt. Rollenänderung und Tokenrefresh zusätzlich im echten Loginflow prüfen.

## CI-Abnahme P1-004 · 19.10.2026

Commit `5c8e112`: [Actions-Lauf 39298429354](https://github.com/damiankaest/DKMan/actions/runs/39298429354)
vollständig erfolgreich: Backend 46 Tests einschließlich PostgreSQL-Migrationsprobe,
Ruff/Format/mypy, ASGI-Smoke, PowerShell-Syntax, Manifest- und Vertragsprüfung;
Frontend Produktionsbuild, 5 UI-Tests, 2 Browserchecks und Dependency-Audit.
Container-Smoke baut Images, führt Migration mit Exit 0 aus und meldet PostgreSQL,
Core, Keycloak und Hub healthy. Seed registriert zwei Manifestverträge; Doctor prüft
Schema, Proxy und OIDC-Discovery. Browsertests verwenden weiterhin Testantworten;
echte OIDC-Mehrbenutzerabnahme und Windows-/Restoretests bleiben offen.

## P2-001 · Lokale Prüfung · 20.10.2026

| Prüfung | Befehl / tatsächlich beobachtetes Ergebnis |
| --- | --- |
| Reproduzierbare Dependencies | `uv sync --frozen`; im Hub `npm ci --ignore-scripts --no-audit --no-fund` |
| Pythonqualität | `uv run ruff check backend scripts tests`; `uv run ruff format --check backend scripts tests`; `uv run mypy` (17 Quelldateien) erfolgreich |
| Backend | `uv run pytest -q`: 67 bestanden, 7 mangels `DKMAN_TEST_DATABASE_URL` übersprungen |
| Paketbuild | `uv build`: Wheel und Source Distribution gebaut |
| HTTP-Prozess | `uv run python scripts/smoke_core.py`: Live 200, Ready bei DB-Ausfall 503, anonymes Me 401; Start/Stop erfolgreich |
| Migration PostgreSQL/WASM | `cd tests/postgres-wasm && npm ci --ignore-scripts --no-audit --no-fund && npm test`: Revision 0002, 15 Tabellen, FK-Abweisung, Downgrade und erneutes Upgrade erfolgreich |
| Hub | `npm run lint`, `npm run build`, `npm test`: erfolgreich; 5 UI-Tests |
| Lokaler Browserstart | `npm run test:e2e` mangels Binary blockiert; `npx playwright install chromium` liefert beschädigtes ZIP; Browserchecks anschließend in GitHub CI bestanden |
| Verträge | `uv run python scripts/export_contracts.py`, Hub `npm run generate:api`; OpenAPI und TypeScript eingecheckt |

Neue Tests: serverseitige Rollen und Jobisolation, Requestreplay/409 bei Konflikt,
alle sechs Approvalbindungsfelder, Ablauf vor Zustimmung und zwischen Claim/Start,
einmaliger Verbrauch, Gegenentscheidung/Abbruch, geänderte Ressourcen, bereinigte
Fehler, transaktionaler Rollback ohne verwaiste Datensätze, gültige/abgelaufene
Leases, alter Worker und Recovery im neuen App-Lifespan auf derselben Testdatei.

`tests/test_jobs_postgres.py` ergänzt sechs Tests mit echten konkurrierenden
PostgreSQL-Sessions; lokal ausdrücklich übersprungen. Zusammen mit dem Migrationstest
wurden sie in GitHub Actions auf PostgreSQL 17 erfolgreich ausgeführt. Nachweis unten.

Keine echte OIDC- oder Windows-Abnahme. Keine Runtime-App installiert. Tests von
Crashgrenzen/Lifespan belegen die Metadatenzustände, keinen Host-/Volume-Restore.

## P2-001 · GitHub-CI-Abnahme und Mainintegration

[PR-Lauf 39382031613](https://github.com/damiankaest/DKMan/actions/runs/39382031613),
Featurecommit `4d06567`; über [PR #8](https://github.com/damiankaest/DKMan/pull/8)
als `f2f4b70` in `main` integriert. Branch-Lauf `39382018865` ebenfalls grün.
Alle Schritte und die relevanten Backend-/Frontend-/Containerlogs selbst geprüft.

Nach Integration zusätzlich [Main-Lauf 39382343544](https://github.com/damiankaest/DKMan/actions/runs/39382343544)
für `f2f4b70`: alle drei Jobs vollständig erfolgreich. Der folgende reine
Dokumentationscommit verändert weder Code noch Verträge und überspringt CI ausdrücklich.

| Job | Ergebnis |
| --- | --- |
| backend | 74 Tests ohne Skip; PostgreSQL 17 mit psycopg; vier konkurrierende Duplikate konvergieren, widersprüchliche Requests/Entscheidungen und doppelte Claims abgewehrt, Abbruch serialisiert, Recovery überspringt fremde Locks und wiederholt laufende Aktionen nicht; Migration Upgrade/Drift/Downgrade/erneutes Upgrade; Lint/Format/mypy, HTTP-Smoke, PowerShell, Manifest-/Vertragsdrift erfolgreich |
| frontend | npm ci, generierte Typen ohne Drift, Lint, TypeScript-/Produktionsbuild, 5 UI-Tests, 2 Browserchecks und Produktions-Dependency-Audit erfolgreich |
| container-smoke | Images gebaut; Migration Exit 0; PostgreSQL/Core/Keycloak/Hub healthy; Seed: zwei Manifestverträge, keine Images installiert; Doctor: neues Schema current, Proxy, OIDC-Discovery, anonymes Me 401 |

Abgeschlossen ist die isolierte Implementierung P2-001. Echte OIDC-Mehrbenutzer-,
Windows-/VM-Neustart-, Volume-Persistenz- und Restoreabnahmen bleiben separat offen.
Die reale Manifestvalidierung ist keine Deployment- oder Appinstallationsabnahme.

## P2-002 · Lokale Prüfung · 20.10.2026

| Prüfung | Tatsächliches Ergebnis |
| --- | --- |
| Pythonqualität | Ruff Check/Format und Mypy erfolgreich; 25 Quelldateien |
| Backend/Sicherheit | `uv run pytest -q`: 116 bestanden; 7 PostgreSQLtests ohne lokale Testdatenbank und 1 Dockerprobe ohne wegwerfbaren Runner ausdrücklich übersprungen |
| Paket | `uv build` erfolgreich; explizite Adaptermigrationen sind Teil des Wheels |
| HTTP-Smoke | Uvicorn tatsächlich gestartet/beendet; Live 200, Ready bei DB-Ausfall 503, Me anonym 401 |
| Hub | Lint, Produktionsbuild und 5 UI-Tests erfolgreich; Core-API-/Frontendtypen unverändert |
| Verträge | Export von Core-/Adapter-OpenAPI und Planschema sowie Frontendgenerierung erneut ohne Drift |

Adaptertests prüfen kuratierte Pläne, schädliche Felder, Rollen/Signatur/Issuer/Audience,
Operation-/Aktions-/Ressourcen-/Hashbindung, Approvalablauf auch nach Erwerb des
Journal-Schreiblocks, einmaligen Approvalverbrauch, Duplikate/Konflikte, SQLite-
Transaktionsrollback, konkurrierende IDs und Dateisperren, verwaiste Ausführungsmarker,
persistente Ressourcensperre nach Fehler und beobachtenden Reconcile ohne Blind-Retry.
Zusätzlich Konfigurations-Dry-run/Secreterhalt, exklusiver Socketempfänger,
bereinigtes CLI-Environment/Timeout-Prozessgruppe und Logredaktion.

Die erste echte Dockerprobe in CI `39387390163` war erfolgreich: ein Integrationstest
in 82,18 Sekunden, eigene tatsächlich gebaute Fixture-Images, komplette Lifecycle-
und Persistenzprüfung sowie absichtlich ungesunder Container. Das ist keine
Notes-/OIDC-/Zielhostabnahme. Abschließender CI-Nachweis unten.

## P2-002 · Abschließende CI-Abnahme

[PR-Lauf 39388427751](https://github.com/damiankaest/DKMan/actions/runs/39388427751)
für `bb4b49c`, über [PR #9](https://github.com/damiankaest/DKMan/pull/9) als
`864f002` in `main` integriert. Alle vier Jobs erfolgreich; relevante Logs geprüft.

| Job | Tatsächliches Ergebnis |
| --- | --- |
| backend | 123 bestanden; 1 expliziter Docker-Guard-Skip, der im eigenen Job ausgeführt wird; PostgreSQL 17, Lint/Format/mypy, HTTP-Smoke, PowerShell, Manifest- und Vertragsdrift erfolgreich |
| adapter-smoke | 1 bestanden in 95,53 Sekunden: eigene Images gebaut, echten Adaptercontainer gestartet, exakte kuratierte Image-IDs; echte Health, Install/Stop/Start/Restart, persistenter Zähler über Remove/erneutes Install, separate Datenlöschung, fremdes Projekt unangetastet; ungesundes Image führt zu gesperrtem unsicherem Ergebnis, Duplikat/neue Operation/Adapterneustart wiederholen die Aktion nicht |
| frontend | Produktionsbuild, 5 UI-Tests, 2 Browserchecks, generierte Typen ohne Drift, Dependency-Audit erfolgreich |
| container-smoke | bestehender Plattformstack gebaut/gestartet, Migration Exit 0, PostgreSQL/Core/Keycloak/Hub healthy, Seed und Doctor erfolgreich |

Docker-Smoke läuft nur auf ausdrücklich wegwerfbaren GitHub-Runnern. Keine Änderung
an bestehenden Zielhostdiensten. Notes-Kuration, UI-/OIDC-Installationsjourney und
Windows-/VM-/Restoreabnahmen bleiben offen. Der alte Backupprozess deckt das neue
Adapterjournal und den Adapterkatalog noch nicht ab; vor Livebetrieb gesondert ergänzen.

Zusätzlich nach Integration [Main-Lauf 39388850554](https://github.com/damiankaest/DKMan/actions/runs/39388850554)
für `864f002` geprüft: backend, frontend, adapter-smoke und container-smoke erfolgreich.
Der folgende Dokumentationscommit enthält keine Code-/Vertragsänderung und überspringt CI.


## P2-003/P2-004 · Lokale und echte CI-Prüfung

Lokal tatsächlich ausgeführt: `uv sync --frozen`, Ruff Check/Format, `uv run mypy`
(31 Quelldateien), `uv run pytest -q` (142 bestanden / 9 PostgreSQL- und 1 Docker-Guard
ohne lokale Dienste übersprungen), `uv build`, HTTP-Smoke und Build-Dry-run ohne Docker.
Im Hub npm ci, Vertragsgenerierung, Lint, TypeScript-/Produktionsbuild, 7 UI-Tests
und Produktions-Audit; Notes-Web npm ci/TypeScript-/Produktionsbuild/Audit erfolgreich.
PostgreSQL/WASM: Upgrade auf 0003, 16 Tabellen, FK-Abweisung, Downgrade und Reupgrade.
Bestehende Core-/Adaptermigrationen anhand ihrer Blob-Hashes unverändert bestätigt;
das Wheel enthält die explizite Notes-Migration.

[PR-Lauf 39408325672](https://github.com/damiankaest/DKMan/actions/runs/39408325672)
für `d633db6` ist mit allen fünf Jobs erfolgreich. Zusätzlich zum vorhandenen
Container-/Adapter-Smoke baut und kuratiert `notes-journey` zwei echte lokale Images,
startet Core/PostgreSQL/Keycloak/Hub/Adapter und führt folgende Probe ohne Testantworten
oder Auth-Dependency-Override aus:

1. Drei getrennte Browserkontexte melden sich an echtem Keycloak mit Code/PKCE an.
2. Admin legt Haushalt an, prüft im Hub Plan und Hash, stimmt explizit zu und installiert.
3. Beide echten Container sind gesund; zweite Person erhält Mitgliedschaft und App-Grant.
4. Notes öffnet per SSO. Zwei Nutzer sehen/erstellen denselben Notizdatensatz;
   HTML-Sonderzeichen bleiben Text. Nicht freigegebener dritter Nutzer bekommt keine Daten.
5. Rückkehr in den Hub erhält die SSO-Sitzung. Entfernen des Mitglieds entzieht
   Appzugriff auch unter bekanntem Direktlink beim nächsten Datenrequest.
6. Echte Containerprobe stoppt/startet ausschließlich diese App/DB; dieselben IDs und
   Notiztexte bleiben erhalten. UID, read-only, Capabilities, keine Hostports/Socketmounts
   und Datenbankrolle ohne Superuser/CreateDB/CreateRole geprüft; fremde DB gesperrt.

Echte Journey: 1 bestanden in 22,8 Sekunden; nachfolgende Persistenz-/Rollenprobe
erfolgreich. Der separate Adaptertest prüft weiterhin echte Lifecycle-/Datenlösch-/
Kollisions- und ungesunde/unsichere Neustartfälle. Die zwei älteren Browserchecks
verwenden weiterhin Testantworten und werden ausdrücklich getrennt gezählt.

Neue Backendtests decken Job-/Appisolation, Pflichtfreigabe, sämtliche Bindungen,
Ablauf, geänderte Pläne/Quellen, doppelte Keys, konkurrierende Haushaltsreservierungen
in PostgreSQL, verloren gegangene erfolgreiche Adapterantwort, Recovery mit neuer
Session und ausschließlich lesenden Abgleich ab. Gesunder Container bei unbewiesenem
Operationsabschluss reicht nicht aus. Alte generische v1-Hashes/Fingerprints erhalten
eigene Regressionstests. Finaler CI-Nachweis mit diesem Zusatz: Lauf `39409123565` für `8ff5429`,
alle fünf Jobs erfolgreich. Integration als `ef888e7` über PR #10.

Grenzen bleiben: Zielhost-/Windows-/VM-Neustart, Damians echte Benutzer, vollständige
Logout-/Refresh-/Passwortwechselmatrix, koordinierter Backup/Restore und sichere
Auflösung verbleibender Adapterunsicherheit. Kein Zielhostdienst geändert.


Abschließender [PR-Lauf 39409123565](https://github.com/damiankaest/DKMan/actions/runs/39409123565):
151 Backendtests und 1 expliziter Docker-Guard-Skip (im Adapterjob tatsächlich ausgeführt),
7 UI-Tests, 2 bisherige Browserchecks, echter Docker-Adaptertest (85,08 s), echte
OIDC-/Notes-Journey (21,4 s) und nachfolgende echte Persistenz-/Rollenprobe erfolgreich.
Alle Logs der fünf Jobs eigenständig kontrolliert. Main enthält denselben geprüften Tree.
Buildmetadaten: [Artefakt 12258471841](https://github.com/damiankaest/DKMan/actions/runs/39409123565/artifacts/12258471841).


Zusätzlich [Main-Lauf 39409720195](https://github.com/damiankaest/DKMan/actions/runs/39409720195)
für `ef888e7` kontrolliert: alle fünf Jobs erfolgreich, 151 Backendtests, 7 UI-Tests,
2 bestehende Browserchecks und beide echten Dockerproben. Echte Notes-/OIDC-Journey
21,2 Sekunden; tatsächliche Datenerhalt-/Rollenprobe anschließend bestanden.
Die vollständigen tatsächlichen Image-IDs/Quellhash/Artefaktchecksumme stehen dauerhaft
in [build-evidence.json](../examples/demo-notes/build-evidence.json). Das Artefakt ist
zeitlich befristet; der versionierte Nachweis bleibt erhalten. Der folgende reine
Dokumentations-/Buildnachweiscommit verändert keine Runtime und überspringt CI.


## P2-005 · Lokale Prüfung und CI-Vertrag

Ausgang: `ebd606c`; vorhandene Main-CI `39409720195` selbst geprüft. Lokal tatsächlich:
`uv sync --frozen`, Ruff Check/Format, Mypy (34 Quelldateien), `uv run pytest -q`
(171 bestanden; 11 PostgreSQLfälle und 1 Docker-Guard ohne lokale Dienste übersprungen),
`uv build`, `scripts/smoke_core.py` (Live 200 / Ready bei fehlender DB 503 / anonym 401),
Manifestprüfung und Vertrags-/Typgenerierung erfolgreich. Hub: npm ci, Lint, TypeScript-
und Produktionsbuild, 11 UI-Tests, Produktionsaudit ohne Befund. PostgreSQL/WASM:
Revision 0003, 16 Tabellen, FK-Abweisung, Downgrade und Reupgrade erfolgreich.
Der lokale Playwrightstart scheiterte an fehlender Chromium-Binary; die zwei
bestehenden Browserchecks laufen zusätzlich in GitHub CI, weiterhin mit Testantworten.

Neue Tests prüfen autorisierte Stop-/Start-/Restartübergänge, unveränderte Installationszahl,
Operator + getrenntes `app.operate`, verweigerte App-use-Eskalation, fremde Ressourcen/Jobs,
Rollen-/Grant-/Mitgliedschaftsentzug vor Ausführung, alle sechs Approvalbindungen,
Ablauf, geänderte Ressource, Key-Konflikte und Reservierung über unterschiedliche Keys,
Redaction/UTF-8-/Zeilengrenzen, maskierte Fehler, read-only Status/Logs, fehlende oder
unpassende Operationsnachweise, verlorene erfolgreiche Antwort und Recovery in neuer
DB-Session. Eine verspätete gesunde Messung kann den neueren Stopstatus nicht überschreiben.
Alte generische Plan-/Journalreplays bleiben durch bestehende Regressionstests geprüft.

Zwei neue echte PostgreSQL-Tests prüfen konkurrierende Lifecycleplanung über unabhängige
Sessions: gleiche Keys konvergieren, andere Keys werden bis zum Abschluss blockiert;
auch ein abgelaufener `running`-Marker bleibt nach Recovery reserviert. Sie ersetzen
keine Windows-/Hostneustartprobe. Die echte Notes-Journey verwendet weiterhin echte
Keycloak-Code/PKCE-/SSO-Sitzungen, nun mit expliziter Operatorrolle und separater
Betriebsfreigabe für den zweiten Nutzer. Sie steuert ausschließlich über Core/Hub
Stop/Start/Restart und vergleicht vollständige Notes-Datensätze einschließlich IDs,
Autoren und Zeitstempeln. Eine gesonderte lesende Engineprobe belegt identische
Container, Images und Volumes, beide gestoppten Container und tatsächlich erhöhte
Startzeitpunkte nach Start/Restart. Keine simulierten Antworten als Runtimeabnahme.

Die Freigabe wird nach Browserreload aus der persistenten Historie fortgesetzt.
Runtimegrantentzug sperrt den Operatorbetrieb, während getrennte Appnutzung bestehen
bleibt; danach wird auch die Mitgliedschaft entzogen. Build- und Lifecyclemetadaten
werden als CI-Artefakt aufbewahrt. Finaler PR-/Mainnachweis folgt nach Abschluss.

Offen bleiben Windows-/VM-/Zielhostabnahme, vollständige OIDC-Betriebsmatrix,
koordinierter Backup/Restore und der umfassende Nachweisworkflow für unsichere
Operationen in P2-006. Bestehende Backups decken den Runtimestack nicht vollständig ab.


Nach dem ersten erfolgreichen Lifecyclelauf wurde ein konkurrierender lesender
Log-/Healthzugriff als Fehler erkannt und korrigiert. Zusätzliche Sperrentests prüfen
geteilte Leser, exklusive Mutationen und begrenzten Sperrerwerb; es gibt weiterhin
keine automatische Wiederholung einer Mutation. Die abschließenden Zahlen/Nachweise
unten ersetzen die Zwischenstände.


## P2-005 · Abschließender PR-Nachweis

[CI 39430552396](https://github.com/damiankaest/DKMan/actions/runs/39430552396)
für `f408059`, [PR #11](https://github.com/damiankaest/DKMan/pull/11): alle fünf Jobs
vollständig erfolgreich und ihre Logs eigenständig gelesen. 184 Backendtests mit
PostgreSQL 17 (1 Docker-Guard im separaten echten Adapterjob ausgeführt), 11 UI-Tests,
2 bestehende Browserchecks, tatsächlicher Adaptertest in 92,13 s, echte OIDC-/Notes-
Journey in 58,7 s und anschließende echte Persistenz-/Least-Privilege-Probe bestanden.
Keine 429-/503-Antwort im abschließenden Journeylog; erwartete unberechtigte Appdaten-
anfragen liefern 404.

Geprüft: drei getrennte echte Keycloak-Konten; zweiter Nutzer mit globaler Operatorrolle,
`app.use` allein ohne Runtimevollmacht, separate Betriebsfreigabe, gespeicherter Plan
nach Reload, passende Zustimmung, Stop beider vorhandenen Container, Start und Restart
über Core/Hub, sicher dargestellte echte Logs und identische vollständige Notizdatensätze.
Die zusätzliche Engineprobe belegt dieselben Container/Images/Volumes und tatsächliche
neue Startzeitpunkte. Betriebsgrantentzug erhält getrennte Appnutzung; anschließender
Mitgliedschaftsentzug sperrt auch direkte Notes-Datenanfragen.

Dauerhafter Nachweis: [p2-005-runtime.json](evidence/p2-005-runtime.json), einschließlich
Enginebeobachtungen, Core-Job-/Operations-IDs und Planhashes. Das verknüpfte Artefakt
wurde mit SHA-256 `d8a059da62cd81ae13333421924c18e3cebbd90af9ded1d36bdcd915410aeb2c`
verifiziert. Die enthaltenen Image-IDs sind Engine-lokale Testartefakte.
Lokaler Endstand nach Sperrregression: 173 bestanden / 12 explizite Dienst-/Docker-Skips.
Keine neue Migration; bestehende Core-/Adaptermigrationen und Lockfiles unverändert.

Nur P2-005 ist damit abgeschlossen. P2-006-Fehlermatrix/gesicherter Abschluss unsicherer
Operationen, Windows-/VM-/Zielhostabnahme, vollständige OIDC-Betriebsmatrix und
koordinierter Backup/Restore bleiben offen. Vorhandene Backup-/Restore-Skripte decken
den erweiterten Runtimestack weiterhin nicht vollständig ab.


## P2-005 · Main-Abnahme

Nach Integration von PR #11 als `07e18c5` wurde
[Main-CI 39431777779](https://github.com/damiankaest/DKMan/actions/runs/39431777779)
eigenständig vollständig geprüft: alle fünf Jobs erfolgreich. 184 Backendtests mit
PostgreSQL 17, 11 UI-Tests, 2 bestehende Browserchecks mit Testantworten, echter
Adaptertest in 96,54 s, echte Notes-/OIDC-Lifecycle-Journey in 1,0 min und nachfolgende
reale Datenerhalt-/Rollenprobe bestanden. Wieder drei getrennte Konten, Operatorrechte,
Reload, echte Freigaben/Operationen, Stop/Start/Restart, Logs, Datenidentität und
Widerruf geprüft. Keine 429-/503-Antwort im Main-Journeylog.

Der tatsächliche Main-Engine-Nachweis ist separat dauerhaft als
[p2-005-main-runtime.json](evidence/p2-005-main-runtime.json) gespeichert. Artefakt
`12268123279` heruntergeladen, SHA-256
`5cb0412cd2669197d5a842077c2a588ccb052d5783aa80de4db04bd34219a94d` bestätigt.
P2-005 ist abgeschlossen; der anschließende reine Dokumentationscommit überspringt
CI ausdrücklich. Die oben genannten Zielhost-/Windows-/OIDC-Betriebs-/Restoregates
und P2-006 bleiben offen.


## P2-006 · Belegter Abschluss und reale Fehlermatrix

[PR #12](https://github.com/damiankaest/DKMan/pull/12), Runtimecommit `99aaeed34192cf49abf7331f1a44ca1880acd17e`:
[CI 39566266737](https://github.com/damiankaest/DKMan/actions/runs/39566266737) vollständig
erfolgreich; alle fünf Joblogs selbst gelesen. 214 Backendtests mit PostgreSQL 17,
12 UI-Tests, zwei ältere Browserchecks mit Testantworten, echter Docker-Adaptertest
(95,71 s), echte OIDC-/Notes-Journey (1,9 min) und nachfolgende Daten-/DB-Rollenprobe.
Keine 429-Antwort. Erwartete Ausfallantworten sind Teil der Probe.

| Reale Probe | Tatsächlicher Nachweis |
| --- | --- |
| Nicht kuratiertes Image / freies Imagefeld | Adapter lehnt gültigen fremden Digest dauerhaft vor Mutation ab, kein Container; Core-Payload mit freiem Imagefeld 422 |
| Rolle / Ressourcenscope | echtes Operator-Konto mit Appnutzung ohne Betriebsscope 404; Member-Logzugriff 403; keine Runtimeänderung |
| Notes-DB down | reale DB gestoppt, Notes-Daten-API 503 mit festem Text, gemessen `unhealthy`, Öffnen-Link verborgen; Daten nach Start identisch |
| Core-DB down | echter PostgreSQL-Prozess gestoppt, Run/Ready 503 und Live 200; nach Wiederverbindung derselbe Job noch `queued`, danach einmaliger genehmigter Run |
| Prozessabsturz nach Belegcommit | echte Composeaktion, durable Enginebestätigung, Adapterprozess beendet vor Abschlusscommit; nach Restart/Reload derselbe unklare Job, belegt abgeschlossen, Nachweishash im Hub |
| Prozessabsturz vor Belegcommit | echte Composeaktion bereits erfolgt, keine dauerhafte Bestätigung; gesunde Runtime bleibt `reconciliation_required`, Code `execution_receipt_missing`, anderer Key/Mutation 409 |
| Kein versteckter Retry | Enginevergleich vor/nach Reconcile identisch einschließlich aller Startzeitpunkte; Daten/Container-/Image-/Volumenidentität erhalten |

Vollständige Matrix und Testgrenzen: [runtime-failure-matrix.md](runtime-failure-matrix.md).
Dauerhafter tatsächlicher Engine-/Operations-/Core-Nachweis:
[p2-006-runtime.json](evidence/p2-006-runtime.json). Artefakt `12330397133` heruntergeladen;
SHA-256 `fe9ca201c785cfeea00ddec541afa392d8366e03f4ae2e322c5c639b956d4a12` bestätigt;
Completionbindung und unveränderte Enginezustände zusätzlich geprüft. Engine-lokale
Image-IDs sind keine Registry-Pullreferenzen für andere Hosts.

Lokal: `uv sync --frozen`, Ruff/Format/Mypy, `uv run pytest -q` (203 bestanden / 12
explizite PostgreSQL-/Docker-Skips), `uv build`, Wheelinhalt und HTTP-Smoke erfolgreich.
Hub npm ci, Typgenerierung ohne Drift, Lint/Build/12 UI-Tests bestanden. Lokaler
Playwrightstart wegen fehlender Chromium-Binary blockiert; beide Checks in CI bestanden.
Bestehende Migrationen/Lockfiles unverändert; neue explizite Adaptermigration 0003 und
Legacyreplay-/Upgradeprüfung. Core bleibt auf Alembicrevision 0003.

Nicht abgenommen: Windows/VM/Zielhoststart und Autostart, volle OIDC-Betriebsmatrix,
koordinierter Runtime-Backup/Restore sowie Docker-Daemon-Ausfall auf dem Zielhost.
Tests verwenden echte Prozesse und Dockeraktionen, Prozessabbrüche aber ausschließlich
einen separat gemounteten CI-Entrypoint. Produktionsimage/-overlay enthält keinen
Faultschalter. Unklarheit ohne Beleg bleibt bewusst blockiert. Main-CI nach Integration folgt.


## P2-006 · Erfolgreiche Main-Abnahme

Nach Integration als `6c749e2` auch [Main-CI 39567571003](https://github.com/damiankaest/DKMan/actions/runs/39567571003)
vollständig erfolgreich; alle fünf Joblogs eigenständig gelesen. 214 Backendtests mit
PostgreSQL 17, 12 UI-Tests, 2 bestehende Browserchecks, echter Adaptertest 93,57 s,
echte Notes-/OIDC-Ausfalljourney 1,8 min und nachfolgende reale Daten-/Rollenprobe.
Die komplette positive Journey und beide DB-/Adapterabsturzfälle erneut bestanden;
kein weiterer Restart durch Reconcile, keine 429-Antwort im Journeylog.

Dauerhafter Mainnachweis [p2-006-main-runtime.json](evidence/p2-006-main-runtime.json),
heruntergeladenes Artefakt `12331021072`, bestätigtes SHA-256
`4a0df1299281213fbdf8e3357f9d60662b4cc7d9e5711e473dc118a59c5a31e1`.
Core-/Adapter-/Enginebindungen zusätzlich geprüft. P2-006 abgeschlossen. Folgender
Dokumentationscommit überspringt CI ausdrücklich; keine Runtimeänderung. Die genannten
Windows-/VM-/Zielhost-/OIDC-Betriebs-/Restoregates bleiben offen; nächste gemeinsame
Abnahme P0-007, nächste Entwicklung P3-001.
