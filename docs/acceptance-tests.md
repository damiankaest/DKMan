# Ausgeführte Prüfungen · 19.10.2026

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

- Separate Negativtests zur Datenbankrollen-Isolation und Volume-Persistenz.
- Echter Login/Passwortwechsel/Logout/Refresh/JWKS-Abruf,
  CSP-Integration im echten Login und zwei echte Benutzer.
- Windows-10-Preflight auf echter Hardware, Featureaktivierung, Ubuntu-VM/WSL2,
  Netzwerk, Host-/VM-Neustart und Autostart. Syntaxprüfung ist keine Hostabnahme.
- Backup, Restore und Upgrade im laufenden Stack; Skripte existieren, aber kein
  behaupteter Recovery-Erfolg. Container-Securityscan mangels gebauter Images offen.
- Journey B: Notes-App/DeploymentService/Approval-Jobs/Proxyroute sind noch nicht
  implementiert. Entsprechend keine behauptete Installations-E2E-Abnahme.

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
