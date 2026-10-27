# DKMan · privater ServiceHub

FastAPI-Core, React-Oberfläche, PostgreSQL/Alembic und zentraler OIDC-Login mit
Keycloak. Ein versioniertes Fundament für ein privates App-Ökosystem auf Windows 10
mit Linux-Containern.

**Stand 0.1.0:** Phase 0 ist implementiert; Registry-/Auth-/Health-Basis aus Phase 1
ist enthalten. Der Docker-Stack und der Windows-Host sind in dieser Sitzung noch
nicht am Zielhost abgenommen. **Notes-Quellapp, isolierter Deployment-Adapter und
genehmigte Installation und autorisierter Runtime-Lifecycle über den Hub sind implementiert.**
P3-001 ergänzt **App planen**: manuelle Anforderungen, gespeicherte Planversionen
und konkrete Planfreigaben. P3-002 ergänzt **DKMan Chat** mit offengelegtem Regelmodus,
berechtigter App-/Registry-Suche, Jobereignissen, Anforderungsentwürfen und einer
optionalen echten Modellanbindung. Der Wizard und Forge-Quellstände sind vorhanden;
ein manueller BuildKit-Worker ist auf einem CI-Builder getestet; die Zielhostabnahme
steht noch aus.
Einstieg: [App planen und Basisstack aktualisieren](docs/planning.md),
[Chat und optionaler Modellprovider](docs/chat.md), [Forge und Build-Worker](docs/forge.md),
[Notes und offene Host-Gates](docs/notes.md).

## Start in vorbereiteter Linux-Docker-Umgebung

Voraussetzungen: Ubuntu in VM oder WSL2, Linux-Docker-Engine, Compose v2.24+ oder
kompatibel neuer, Python 3, curl, Git, freier Port 8080. Details und Windows-Preflight:
[Windows-10-Startanleitung](docs/windows10-setup.md).

```bash
bash scripts/linux/bootstrap.sh --dry-run
bash scripts/linux/bootstrap.sh --apply
```

Bestätigung: `INSTALL`. Danach http://localhost:8080 öffnen; VM ggf. per SSH-Tunnel.
Zufällige erste Zugangsdaten liegen ausschließlich in `.local/initial-credentials.txt`.
Beim ersten Login Passwort wechseln. Nur Loopback-Zugriff; weitere Geräte erst nach
TLS-/VPN-/Netzwerkabnahme. Keine Windowsinstallation oder Hoständerung wurde hier ausgeführt.

## Was schon funktioniert

- Core-API mit Liveness sowie gemessener Datenbank-/Migrationsreadiness.
- Explizite initiale Migration für Registry, Haushalte, Zugriff und Audit.
- OIDC-/JWT-Prüfung und vier Rollen, geschlossene API ohne anonymen Adminzugang.
- App-/Service-/Capabilitysichtbarkeit pro Benutzer; serverseitige Adminregistrierung.
- Striktes Manifestformat, JSON-Schema und zwei versionierte Vertragsbeispiele.
  Bootstrap registriert deren Metadaten idempotent; Notes wird separat gebaut und kuratiert.
- Responsiver dunkler ServiceHub mit Login, Appsuche, tatsächlichem Corestatus und
  Admin-Katalogansicht. Keine Laufzeitmessung bedeutet `unknown`.
- Compose, zufällige Secrets, Windows-Preflight, Bootstrap/Doctor sowie vorsichtige
  Backup-/Restore-/Upgradeskripte mit Dry-run/Bestätigung.
- Persistente Jobs/Events/Approvals, Idempotenz und Recovery ohne blinde Wiederholungen.
- Notes mit eigener PostgreSQL-Datenbank: geprüfter Quellbuild, UI-Plan/Freigabe,
  tatsächliche Installation und Öffnen per SSO; explizites Runtime-Overlay.
- Start/Stop/Restart als konkret freizugebende persistente Jobs; getrennte Operatorrechte
  pro Installation, gemessener Status und maskierte Textlogs; Daten bleiben erhalten.
- Belegter Abschluss unsicherer Operationen mit dauerhaften Enginebestätigungen;
  reale DB-/Prozessausfallmatrix, keine Wiederholung bei fehlendem Nachweis.
- App-Ideen im Hub planen und freigeben; Forge erstellt daraus unveränderliche
  Quellstände. Der getrennte Build-Worker ist manuell, eine Preview folgt in P4-003.
- CI mit PostgreSQL-Konkurrenz/Migration, echten Dockerproben und echter
  OIDC-Mehrbenutzerjourney einschließlich Rechteentzug und Notes-Datenerhalt.

## Entwicklung und Prüfungen

Python 3.12 und Node 24 verwenden. `uv` wird für Entwicklung und Notes-Quellbuild genutzt;
die Container installieren gehashte, exportierte Requirements.

```bash
uv sync --frozen
uv run ruff check backend scripts tests
uv run ruff format --check backend scripts tests
uv run mypy
uv run pytest -q
uv build
uv run python scripts/validate_manifests.py
uv run python scripts/export_contracts.py
cd apps/service-hub
npm ci --ignore-scripts --no-audit --no-fund
npm run generate:api
npm run lint
npm run build
npm test
npx playwright install chromium
npm run test:e2e
```

`uv run pytest` überspringt den nativen PostgreSQL-Test ohne
`DKMAN_TEST_DATABASE_URL`. Dafür ausschließlich eine wegwerfbare Datenbank mit
Suffix `_test` angeben. CI stellt eine solche PostgreSQL-17-DB bereit. SQLite wird
nur in schnellen isolierten Unit-/API-Tests genutzt, nie als produktive Alternative.
Browserprüfungen stubben Identity/Health ausdrücklich; sie ersetzen den Live-OIDC-Test nicht.

Zusätzliche PostgreSQL-DDL-Prüfung ohne Docker (WASM, kein Netzwerktest):

```bash
cd tests/postgres-wasm
npm ci --ignore-scripts --no-audit --no-fund
npm test
```

Backend lokal: Zugangsdaten separat über `DKMAN_DATABASE_URL` oder die vorgesehenen
Secretdateien konfigurieren, `uv run alembic -c backend/alembic.ini upgrade head`,
danach `uv run uvicorn dkman.main:create_app --factory --host 127.0.0.1 --port 8000
--no-access-log`. Hub: `npm run dev`; der vollständige OIDC-Flow benötigt den gleichen
konfigurierten Proxy-Origin, dafür bevorzugt den Compose-Stack verwenden.

## Orientierung und Fortsetzung

| Inhalt | Datei |
| --- | --- |
| verbindlicher Bauauftrag | [docs/specification.md](docs/specification.md) |
| aktueller Stand und nächster Einstieg | [docs/progress.md](docs/progress.md) |
| tatsächlich ausgeführte Prüfungen und Grenzen | [docs/acceptance-tests.md](docs/acceptance-tests.md) |
| Architektur/API/Manifest | [docs/architecture.md](docs/architecture.md) |
| Architekturentscheidungen | [docs/architecture-decisions/](docs/architecture-decisions/) |
| Tickets mit Abhängigkeiten | [docs/backlog.md](docs/backlog.md) |
| Runtime-Fehlermatrix | [docs/runtime-failure-matrix.md](docs/runtime-failure-matrix.md) |
| App-Anforderungen, Planversionen und Aktualisierung | [docs/planning.md](docs/planning.md) |
| Sicherheitsmodell | [docs/security-threat-model.md](docs/security-threat-model.md) |
| Betrieb und GitHub-Übergabe | [docs/operations.md](docs/operations.md) |
| Arbeitskonventionen | [AGENTS.md](AGENTS.md) |

Privates GitHub-Repository: [damiankaest/DKMan](https://github.com/damiankaest/DKMan).
Aktueller Main-/CI-Stand steht in `docs/progress.md`; der archivierte ursprüngliche
Git-Bundle ist ausschließlich historischer Quellnachweis.

Lizenz: noch nicht festgelegt. Es wird ohne Eigentümerentscheidung keine
Open-Source-Lizenz vergeben. Abhängigkeiten behalten ihre jeweiligen Lizenzen.
