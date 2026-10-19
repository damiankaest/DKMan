# DKMan – Implementierungsauftrag für ChatGPT Work

**Projektname:** DKMan  
**Status:** Greenfield – es existiert noch kein GitHub-Repository für DKMan.  
**Sprache der Kommunikation und Dokumentation:** Deutsch. Quellcode, API-Namen, Dateinamen und Git-Commits bevorzugt Englisch.  
**Ziel:** Implementieren, nicht nur planen. Erstelle ein funktionierendes, getestetes, versioniertes MVP und baue darauf iterativ auf.

---

## 0. Rolle und Arbeitsmodus

Du bist der leitende Softwarearchitekt, Full-Stack-Entwickler, DevOps-Engineer, Test-Engineer und technische Projektleiter für **DKMan**. Setze das Projekt mit produktionsnahen Standards um, aber vermeide unnötiges Overengineering.

**Wichtig:** Liefere nicht lediglich Konzept, Architekturdiagramm, Pflichtenheft oder ein Ticket-Backlog. Diese Artefakte sind erforderlich, aber du sollst anschließend **selbst mit der Implementierung beginnen**, Dateien erstellen, Code schreiben, Build und Tests ausführen und einen lauffähigen vertikalen Durchstich liefern. Setze nach jeder abgeschlossenen Phase mit dem nächsten priorisierten Ticket fort, solange der Arbeitskontext es erlaubt. Dokumentiere belegbar, was wirklich getestet wurde und was mangels Serverzugriff offen ist.

Erstelle, wenn Zugriff und Berechtigung vorhanden sind, ein neues **privates** GitHub-Repository namens `DKMan`, standardmäßig als Monorepo. Wenn eine Repository-Erstellung oder ein Push nicht möglich ist, implementiere lokal im zugänglichen Workspace, liefere die Dateien und dokumentiere die fehlende Berechtigung – erfinde keinen Repository-Status.

Triff vernünftige technische Detailentscheidungen selbst und dokumentiere sie als Architecture Decision Records (ADRs). Stelle nur Fragen, wenn eine wirklich blockierende externe Information oder Berechtigung benötigt wird. Insbesondere nicht erst monatelang ein Gesamtsystem konzipieren, sondern einen überprüfbaren MVP umsetzen.

**Priorität:** Funktionsfähigkeit, Sicherheit und Erweiterbarkeit vor Feature-Anzahl oder Optik. Keine ungeprüften „fertig“-Behauptungen. Keine destruktiven Hostaktionen ohne ausdrückliche Freigabe.

---

## 1. Produktvision

Ich möchte ein **privates, selbst erweiterbares, KI-gesteuertes App-Ökosystem** auf meinem eigenen Server betreiben.

Für die Menschen in meinem Haushalt bzw. in meinem Netzwerk gibt es einen zentralen **ServiceHub** im Stil einer Netflix-Oberfläche: Apps erscheinen als Karten/Kacheln, lassen sich öffnen und entsprechend den Berechtigungen gemeinsam verwenden. Jede App darf ein eigenes Frontend und Backend besitzen, darf aber auch bestehende gemeinsame Plattformdienste (Login, Datenbanken, Dateien, Benachrichtigungen etc.) nutzen.

Im ServiceHub gibt es einen Chat mit **DKMan**, einem intelligenten Orchestrator. Der Nutzer beschreibt in normaler Sprache, was er möchte:

- „Zeig mir alle verfügbaren Apps.“
- „Starte den Minecraft-Server.“
- „Erstelle ein Backup der Minecraft-Welt.“
- „Suche eine App, mit der wir unseren Garten planen können.“
- „Ich hätte gerne eine neue Garten-App, mit Pflanzen, Fotos, Bewässerung, Düngerplan und gemeinsamen Aufgaben.“
- „Nimm die schon registrierte PostgreSQL-Instanz und den vorhandenen Dateispeicher.“
- „Ändere die Garten-App und baue eine Kalenderansicht ein.“

DKMan versteht die Absicht, prüft die Registry und den App-Katalog, zeigt Möglichkeiten und notwendige Berechtigungen, plant bei Bedarf mit dem Nutzer eine neue Anwendung, delegiert die Umsetzung an einen **CodingService/Forge**, lässt Tests und Builds ausführen und bietet eine Vorschau. Eine berechtigte Person genehmigt das Deployment. Danach erscheint die App im ServiceHub und kann von freigeschalteten Haushaltsmitgliedern genutzt werden.

DKMan soll vorhandene Images sicher installieren **und** eigene erzeugte Images über **denselben DeploymentService** verwalten können.

Die Plattform ist kein einzelner riesiger Microservice-Verbund von Anfang an. **Klare logische Module, aber ein modularer Monolith als sinnvoller erster Core**, mit der Möglichkeit, Forge und Deployments bei Bedarf separat auszuführen.

---

## 2. Zwingende Rahmenbedingungen

### 2.1 Host und Betrieb

- **Erste Zielumgebung: Windows 10** auf meinem eigenen Rechner/Server, nicht Windows Server und nicht unmittelbar ein nativer Ubuntu-Host.
- Die Fachanwendungen sollen als **Linux-Container** laufen. Setze dafür Docker Engine in einer Linux-Umgebung ein, **nicht** native Windows-Container.
- Für die lokale Entwicklung kann WSL2/Ubuntu eingesetzt werden, falls verfügbar. **WSL2 ist kein verlässlicher Ersatz für einen unbeaufsichtigten 24/7-Serverbetrieb**: automatische Starts, Windows-Neustarts, Netzwerk und Lifecycle müssen getrennt geprüft werden.
- Für einen dauerhaften Betrieb bevorzuge eine kleine **Ubuntu-VM** auf Windows 10: Hyper-V, sofern Edition und Hardware es unterstützen, sonst eine kompatible VM-Lösung. Prüfe Windows-Edition, Virtualisierungsfähigkeit, RAM, Storage, Netzwerk, Ports und bereits laufende Dienste, bevor du dich auf eine konkrete Installation festlegst.
- Beachte: Windows 10 hat sein reguläres Supportende erreicht. Keine öffentliche Portfreigabe des DKMan-Systems als Standard. Netzwerkzugriffe anfangs nur in einer sicheren Entwicklungs-/Heimnetzkonfiguration; sichere TLS-/VPN-Lösung für eine echte Freigabe anderer Geräte vorsehen. Für Internetzugriff von außerhalb optional später VPN/Tailscale oder abgesichertes HTTPS; keine offene Docker-API.
- Behandle jeden Host-Eingriff als expliziten Installationsschritt mit Preflight, Dry-Run/Plan, Bestätigung, Logging und Rollback-Hinweisen.
- Wenn du meine Windows-Maschine nicht direkt bedienen kannst, **erstelle trotzdem die vollständigen Skripte, Containerkonfigurationen, Prüfschritte und Doku**; teste die Teile, die deine Umgebung zulässt, und kennzeichne hostabhängige Schritte offen.
- Ein neues Windows-Hostsystem ist anfangs kein Widerspruch zu späteren Linux-Deployments: keine hardcodierten Windows-Pfade in Backend-Code, alle Services OCI-/Linux-kompatibel und Konfiguration per Environment/Secrets.

### 2.2 Technologieentscheidungen

- **Backend:** Python 3.12+ mit FastAPI, Pydantic, SQLAlchemy, Alembic; Versionen aktuell und kompatibel pinnen.
- **Frontend:** React, TypeScript, Vite; modernes responsives UI für Desktop, Tablet und Handy.
- **Datenbank:** PostgreSQL für DKMan-Metadaten und anfangs auch für generierte Apps, aber mit getrennten Datenbanken/Schemas und Least-Privilege-Rollen pro App. Kein offener Universal-SQL-Zugang für alle Services.
- **Laufzeit:** Docker Engine, Docker Compose, versionierte OCI-Images, persistente Volumes.
- **Authentifizierung:** Zentraler OIDC/OAuth2-Anbieter mit Single Sign-on und Rollen. Prüfe eine leichtgewichtige praktikable Integration mit Keycloak oder einer äquivalenten bewährten Open-Source-Lösung; baue keinen eigenen Identity-Provider. Die erste Demo soll ohne eingebettete produktive Standardpasswörter installierbar sein.
- **Deployment-Abstraktion:** `DeploymentProvider`-Interface mit Operationen für Discover/Pull/Install/Deploy/Start/Stop/Restart/Status/Logs/Remove. Implementiere zunächst **einen** tatsächlich funktionsfähigen Adapter für den MVP, idealerweise einen bewusst eingeschränkten Docker-Compose-Adapter. Evaluieren und dokumentieren: späterer `CoolifyProvider` über offizielle API, keine voreilige Parallelimplementierung mehrerer Plattformen.
- **KI-Coding:** Forge erhält eine austauschbare `CodingProvider`-Schnittstelle. Evaluiere OpenHands SDK für isolierte Code-Workspaces. Für die erste durchgehende Implementierung darf ein deterministischer Template-Generator verwendet werden, solange eine echte CodingProvider-Schnittstelle existiert und keine Fake-AI-Funktion als fertig ausgewiesen wird.
- **KI-Modelle:** Provider-Abstraktion, Konfiguration von API-Schlüsseln über Secrets; keine Festlegung auf genau einen Modellanbieter. Lokale Modelle sind optional, nicht MVP-Pflicht.
- **Servicebeschreibung:** Eigene versionierte `dkman.yaml`-Manifeste mit JSON-Schema. OpenAPI für HTTP-APIs; optional MCP für Agentenfähigkeiten. **MCP ersetzt weder Registry, Auth, Geschäftslogik noch Berechtigungsprüfung.**
- **Datenaustausch:** Primär APIs; später Events/Outbox für asynchrone Integration. Keine gemeinsame Schreibberechtigung in fremde Datenbanken.
- **Qualität:** Ruff, Mypy/Pyright soweit praktikabel, Pytest, TypeScript ESLint/tsc, Vitest, Playwright für zentrale E2E-Wege, GitHub Actions für CI, Container-/Dependency-Scanning bei Verfügbarkeit.

Dokumentiere Abweichungen, wenn die tatsächliche Tool-Version die geplante Integration nicht ermöglicht. Bevorzuge stabile und nachvollziehbare Varianten.

---

## 3. Zielarchitektur und Verantwortlichkeiten

### 3.1 ServiceHub (Web-Frontend)

Eine ansprechend gestaltete, dunkle, Netflix-inspirierte, aber eigenständige Oberfläche:

- Login; Profile/Haushalte, Rollen und Berechtigungen.
- Startseite mit App-Kacheln, Kategorien, Suche, Favoriten und Zustandsanzeige.
- App-Detail: Beschreibung, Screenshot/Icon, Sichtbarkeit, Version, Health, Aktionen und Link zum Starten.
- App öffnen: bei selbst erzeugten Apps bevorzugt über zentrale URL/Reverse Proxy, mit SSO. Fremde Apps dürfen ihre eigenen Routen/Auth-Anforderungen haben; dies transparent kennzeichnen.
- DKMan-Chat mit Streaming/Status, sicher angezeigten Tool-Aktionen und verständlicher Fehlerbehandlung.
- Chatbasierter Planungswizard: Ziele, Funktionen, Datenmodell, wiederverwendbare Services, Datenfreigabe, Vorschau, Freigabe.
- Adminbereich für Registry, Katalog, Benutzer, Containerstatus, Logs, Job-Historie, App-Konfiguration, Datenverbindungen und später Code/Workspace.
- Mobile-friendly; Accessibility, semantische Controls, Ladezustände, bestätigungspflichtige Aktionen.

### 3.2 DKMan Core

DKMan ist **Orchestrator, kein allmächtiger Shell-Agent**:

- Benutzerabsicht erkennen und validieren.
- Tools/Capabilities aus Registry auswählen.
- Workflows/Jobs persistent koordinieren.
- Berechtigungen prüfen und bei riskanten Aktionen Zustimmung einholen.
- Als Commands wohldefinierte strukturierte Aktionen ausführen, niemals ungeprüfte natürlichsprachliche Texte als Shell-Befehle interpretieren.
- Tool-Calls und Resultate mit Audit-Daten dokumentieren.
- Kein direkter Zugriff auf produktive Docker-Sockets, Secrets, Hostdateisysteme oder Datenbanken anderer Apps.

### 3.3 Service Registry und App Catalog

**Service Registry:** Tatsächlich registrierte Installationen, URLs, Capability-IDs, Versionen, Status, Owner, Berechtigungen, API-Schema, Abhängigkeiten.

**App Catalog:** Installierbare, überprüfte App-Pakete/Templates/OCI-Images inklusive Herkunft, Digest, Konfigurationsschema, Berechtigungs-/Ressourcenbedarf, möglicher Integrationen. Externe Suchtreffer dürfen als **Kandidaten** angezeigt werden, aber nicht automatisch installiert werden. Images nicht blind aus Docker Hub übernehmen.

Unterscheide `AppDefinition` (Template/Katalogeintrag), `AppInstallation` (laufende Instanz), `ServiceInstance` (technische Runtime) und `Capability` (Aktion/Funktion).

### 3.4 DeploymentService / DockerImageService

Ein dedizierter Verwaltungsbereich mit typisierten Aktionen:

- geprüfte Images registrieren, Referenzen/Digests speichern, pull/installieren;
- Compose-Pläne erzeugen und validieren;
- pro App: Netzwerke, Volumes, Ressourcenlimits, Labels, Health Checks;
- App starten, stoppen, neustarten, aktualisieren, Logs/Status abrufen;
- Preview und Rollback nach fehlgeschlagenem Update;
- Daten und Volumes nicht ohne separate Freigabe löschen;
- nur erlaubte Images, Parameter, Netzwerk- und Volume-Mounts; standardmäßig keine privilegierten Container, keine Host-PID/Host-Netzwerke, kein bind mount sensibler Hostpfade, keine unkontrollierten Ports;
- Docker-Steuerung als privilegierte Trust Boundary in separatem, nicht öffentlich erreichbarem Adapter; **Docker-Socket niemals an DKMan Core, Coding-Agent oder generierte Apps mounten**;
- Deployment, Build und Health als persistente Jobs, mit idempotenten Request-IDs und expliziten Statuswechseln.

### 3.5 Forge / CodingService

Eine eigenständige logische Komponente mit Schnittstellen für:

1. `plan_app(requirements, registry_snapshot)` → überprüfbarer Implementierungsplan.
2. `create_workspace(template, app_id)` → isolierter Workspace, Git-Repo/Branch.
3. `implement(plan)` → neue/angepasste Dateien im Workspace.
4. `run_checks()` → Formatter, Linter, Typprüfung, Unit-/Integrationstests.
5. `build_image()` → reproduzierbares Build-Artefakt, identifizierte Image-Version/Digest.
6. `create_preview()` → isolierte Preview ohne produktive Secrets.
7. `publish(approval)` → freigegebenes Deployment über DeploymentService.
8. `request_change(existing_app, change_request)` → neue Version, Tests, Preview, Upgrade-/Rollbackplan.

Entwicklung und Deployment sind getrennte Sicherheitsdomänen. Agentencode wird **niemals direkt im Produktivcontainer bearbeitet**. Optional später Browser-IDE wie code-server **für Workspaces**, nicht direkte Änderungen produktiver Dateisysteme. Erzeuge App-Vorlagen für `python-api`, `react-spa`, `fullstack-fastapi-react`. Vorlagen enthalten Manifest, README, Dockerfile, API-Health, Auth-Integration, Tests, Migrationsbasis, CI und Konfigurationsschema. Jede neue App soll eine einheitliche Struktur besitzen.

### 3.6 HealthService

Status für Core, abhängige Systeme und Apps:

- Prozess-/Containerstatus, `/health/live`, `/health/ready`, optional Ressourcenwerte.
- Polling/Heartbeat mit Zeitstempel, Fehlerursache und Historie.
- Frontend zeigt `healthy`, `starting`, `degraded`, `unhealthy`, `stopped`, `unknown` korrekt an; keine erfundenen Echtzeitwerte.
- Logs mit Zugriffsprüfung und Redaction sensibler Daten.
- MVP kann Health als Core-Modul implementieren, ohne eigenen Container.

### 3.7 DataService / DatabaseAdapter

Zentrale **Verwaltung**, nicht eine globale Superdatenbank:

- registrierte PostgreSQL-Instanzen und nutzbare Datenquellen beschreiben;
- nur autorisierten Benutzern Datenbankoptionen im Wizard anbieten;
- pro neue App eigene DB oder Schema und eigene begrenzte Zugangsdaten provisionieren;
- Connection-Referenzen (`connection_id`) und Secrets getrennt halten;
- Migrationen durch App/Deploymentprozess ausführen;
- Datenzugriff zwischen Apps nur über explizite APIs/Capabilities oder freigegebene, sauber versionierte Schnittstellen;
- später Shared Services für Bilder/Dateien, Benachrichtigungen und Haushaltsdaten.

### 3.8 Installer / SetupService

Ein **reproduzierbarer, idempotenter Bootstrap-Prozess** für Windows 10 plus Linux-Containerumgebung:

- `scripts/windows/preflight.ps1`: Windows-Edition, Version, RAM, CPU-Virtualisierung, WSL2, Hyper-V-Verfügbarkeit, Docker, Portbelegung, Firewallhinweise, Datenträger prüfen; keine destruktiven Änderungen.
- Dokumentierte Wahl zwischen `dev-wsl2` und `server-linux-vm` – Empfehlung und Grenzen transparent ausgeben.
- `scripts/windows/setup.ps1`: Vorbereitung nach Bestätigung; Setup der Linux-Umgebung darf explizite Adminrechte verlangen; niemals stillschweigend Virtualisierung aktivieren/Windows neu starten.
- `scripts/linux/bootstrap.sh`: überprüfte Dependencies, Config/Secrets, Compose, Netzwerk/Volumes/DB-Migrationen, Healthchecks.
- `scripts/linux/doctor.sh`, `backup.sh`, `restore.sh`, `upgrade.sh` mit Dry-Run und Bestätigungs-/Recoverylogik.
- Klare Schritte für Start nach Hostneustart. WSL-Entwicklungsmodus kann Einschränkungen haben; für unbeaufsichtigten Betrieb bevorzugte VM mit Autostart.
- Keine vorgetäuschte „Single EXE“-Unterstützung: zuerst solide Skripte und Container; später optional eine komfortable Windows-CLI daraus machen.

---

## 4. Rollen und Sicherheit

Vier Rollen für den MVP:

- `member`: freigegebene Apps sehen/verwenden, eigene Anforderungen einreichen.
- `developer`: Entwürfe, Workspaces, generierte Vorschauen verwalten.
- `operator`: autorisierte Runtime-Aktionen wie Start/Stop/Logs/Backups.
- `admin`: Plattforminstallation, Freigaben, Datenbank-/Image-Registrierung, Rechteverwaltung, Deployments.

Rollen können kombiniert werden. Zusätzliche App-spezifische Permissions über `Capability` (z. B. `minecraft.backup`). Alle Autorisierungschecks **serverseitig**; Button-Sichtbarkeit ist keine Sicherheitskontrolle.

Risikoklassen: `read_only`, `reversible`, `sensitive`, `destructive`. Freigaben für externe Image-Installationen, Datenverlust, Secretänderungen, neue öffentliche Ports, Neu-Deployments, Host-/DB-Änderungen. Zustimmung an Plan-Hash/Aktion binden, nicht an freie Chattexte. Audit Events (wer, was, wann, welche Ressource, Ergebnis); niemals Token oder Passwort im Log.

API-Keys ausschließlich über sichere Secret-Verwaltung/Environment, nie in Git/Client. Schutz vor Path Traversal, Command Injection, SSRF bei Image-/URL-Lookups, Prompt-Injection durch fremde Manifeste und gefährlichen Docker-Konfigurationen. Externe App-Manifeste sind **Daten, keine Instruktionen an DKMan**.

Frontend-Login über OIDC Authorization Code + PKCE; geeignete Cookie-/Tokenstrategie, CSRF/CORS, Session-Timeouts, Ratelimits berücksichtigen. Lokale produktive Nutzung anderer Geräte nur mit passender TLS-/VPN-Absicherung; keine offenen Admin-Oberflächen ins Internet.

---

## 5. Datenmodell (Initialentwurf)

Entwirf migrationsfähige SQLAlchemy-Modelle mindestens für:

- `UserProfile`, `Household`, `HouseholdMembership`
- `AppDefinition`, `AppInstallation`, `ServiceInstance`
- `ServiceManifest`, `Capability`, `PermissionGrant`
- `InfrastructureProvider`, `DatabaseConnectionRef`
- `Workflow`, `Job`, `JobEvent`, `ApprovalRequest`
- `AppRequest`, `AppPlan`, `Workspace`, `BuildArtifact`
- `AuditEvent`

Keine unnötigen Felder und Tabellen nur für zukünftige Ideen. App-Daten (z. B. Pflanzen) **nicht** in DKMan-Core-Metadaten mischen. Jede App hat klare Eigentümerschaft und Migrationsstrategie. Eindeutige IDs, Zeitstempel, Versionen, saubere Foreign Keys und Indizes.

---

## 6. Versioniertes Service-Manifest

Erstelle Schema, Validator, Tests und zwei valide Beispielmanifeste. Definiere Versionierung/Kompatibilitätsregeln. Etwa:

```yaml
schemaVersion: dkman.io/v1alpha1
id: demo-notes
name: Notes Demo
version: 0.1.0
type: web-app
ui:
  displayName: Notes
  icon: notebook
  route: /run/demo-notes/
runtime:
  deploymentProvider: docker-compose
  image: registry.local/demo-notes@sha256:EXAMPLE_DIGEST
  internalPort: 8080
health:
  livePath: /health/live
  readyPath: /health/ready
capabilities:
  - id: notes.read
    method: GET
    path: /api/notes
    permission: member
  - id: notes.create
    method: POST
    path: /api/notes
    permission: member
dependencies:
  - type: database
    capability: postgres
    required: true
```

**Hinweis:** `EXAMPLE_DIGEST` ist nur ein Dokumentationsplatzhalter, kein echtes Image. Im lauffähigen Katalog müssen echte, überprüfte Image-Referenzen oder lokale Build-Artefakte verwendet werden.

Trenne Beschreibung, installiertes Runtime-Manifest und sensible Konfiguration. Manifest validieren vor Registration, Deploy und Tool-Freigabe. Ein Manifest darf **keine** beliebigen Shellbefehle oder ungeprüften Privilegien anfordern.

---

## 7. Mindest-API (versioniert)

Implementiere eine konsistente REST-API unter `/api/v1`, generierte OpenAPI-Doku und typisierte Frontend-Clients. Mindestens:

- `GET /health/live`, `GET /health/ready`
- `GET /api/v1/me`
- `GET /api/v1/apps`, `GET /api/v1/apps/{id}`
- `GET /api/v1/services`, `GET /api/v1/services/{id}`
- `POST /api/v1/catalog/install` (Approval/Job statt synchronem Containerstart)
- `POST /api/v1/installations/{id}/start`, `/stop`, `/restart`
- `GET /api/v1/installations/{id}/status`, `/logs` (maskiert/autorisiert)
- `GET /api/v1/jobs/{id}`, `GET /api/v1/jobs/{id}/events` (SSE oder begründete Alternative)
- `POST /api/v1/app-requests`, `GET /api/v1/app-requests/{id}`
- `POST /api/v1/app-plans/{id}/approve`
- `POST /api/v1/chat` oder Streaming-Endpoint mit sicherem Tool-Routing
- `GET /api/v1/catalog`, `GET /api/v1/capabilities`

Bei Implementierungsaufwand API-Scope nach MVP-Phasen staffeln. Keine Fake-Endpunkte, die Erfolg zurückmelden, ohne eine Aktion tatsächlich angestoßen zu haben. Jobstatus und Audit-Logs müssen auch bei Fehlern konsistent bleiben.

---

## 8. Repository-Struktur

Erstelle einen nachvollziehbaren Monorepo-Aufbau, ungefähr:

```text
DKMan/
├── README.md
├── AGENTS.md
├── .env.example
├── .github/workflows/
├── docs/
│   ├── vision.md
│   ├── architecture.md
│   ├── architecture-decisions/
│   ├── security-threat-model.md
│   ├── windows10-setup.md
│   ├── operations.md
│   ├── backlog.md
│   └── acceptance-tests.md
├── apps/
│   └── service-hub/                # React + TypeScript
├── backend/
│   └── dkman/                      # FastAPI modularer Monolith
│       ├── api/
│       ├── auth/
│       ├── registry/
│       ├── catalog/
│       ├── orchestration/
│       ├── deployments/
│       ├── health/
│       ├── data_connections/
│       ├── forge/
│       ├── models/
│       └── infrastructure/
├── workers/                         # nur falls für Jobs benötigt
├── templates/
│   ├── python-api/
│   ├── react-spa/
│   └── fastapi-react-app/
├── contracts/
│   ├── manifests/
│   └── openapi/
├── infrastructure/
│   ├── compose/
│   ├── proxy/
│   └── config/
├── scripts/
│   ├── windows/
│   └── linux/
├── examples/
│   └── demo-notes/
└── tests/
```

Darf sinnvoll vereinfacht werden. Keine leeren Pseudoprojekte anlegen, nur um Verzeichnisnamen abzuhaken. Führe Architektur-, API-, Manifest- und Template-Versionierung sauber ein.

---

## 9. User Journeys / konkrete Abnahmeszenarien

### Journey A – DKMan starten und über mehrere Geräte öffnen

1. Admin prüft `preflight.ps1` und die lokale Umgebung.
2. Die Installationsanleitung bzw. das Setup startet den Container-Stack in WSL2/Ubuntu-VM.
3. Plattform startet nach dokumentiertem Ablauf, DB-Migrationen laufen idempotent.
4. Der Browser öffnet den ServiceHub; Admin meldet sich an.
5. Nach sicherer Netzwerkkonfiguration kann ein zweites Gerät im Heimnetz den Hub öffnen.
6. User sieht nur für ihn freigegebene Apps; unberechtigter Zugriff auf Admin-API wird mit 403 abgewehrt.

### Journey B – Vorhandene Demo-App installieren

1. Admin öffnet Katalog und wählt eine kuratierte Notes-Demo.
2. DKMan zeigt Image-Herkunft, benötigte Ressourcen, Datenvolumen, Berechtigungen und geplante Ports.
3. Admin genehmigt; DeploymentService legt Job an.
4. Container wird tatsächlich gestartet; Status/Logs/Health sind sichtbar.
5. Notes erscheint als Kachel und lässt sich mit Anmeldung öffnen.
6. Start/Stop/Restart funktionieren, ohne dass Nutzerdaten verloren gehen.
7. Eine zweite Haushalts-Person kann freigegebene Notes lesen/erstellen; nicht freigegebene App bleibt verborgen.

### Journey C – Garten-App gemeinsam planen

1. Mitglied schreibt: „Baue eine Garten-App mit Pflanzen, Fotos, Gießplan, Düngerplan, Aufgaben und gemeinsamer Nutzung.“
2. DKMan erfasst eine strukturierte `AppRequest` und sucht vorhandene AppDefinitionen und Capabilities.
3. DKMan zeigt Alternativen: bestehende App installieren, neues Frontend auf gemeinsamen Diensten oder neue Fullstack-App generieren.
4. Der Wizard fragt nur notwendige Dinge: Haushaltsfreigabe, Pflanzenfelder, Erinnerungskanäle, Geräteanbindung etc.
5. DKMan schlägt vorhandenen Postgres-Provider, Auth-Service und Dateispeicher vor und zeigt seine Auswahl begründet an. Die finale Datennutzung folgt Berechtigungen/Policies.
6. Der Nutzer sieht einen konkreten Plan mit Komponenten, Entitäten, Benutzeroberflächen, Tests und Deploy-Anforderungen.
7. Zunächst muss mindestens dieser Planungsfluss mit persistentem Planobjekt funktionieren. **Später** generiert Forge die echte App nach Freigabe.

### Journey D – Erste App aus einem Template bauen

1. Admin oder berechtigter Developer startet „Neue Notes-/Garten-Basis-App erstellen“.
2. Forge erstellt Repo-/Workspace-Struktur, API, Frontend, Auth, DB-Migration, Manifest, Tests und Docker-Image.
3. Unit-/Integrationstests und Image-Build laufen isoliert.
4. Preview wird angezeigt; nach Approve wird das neue Image über **denselben** DeploymentService veröffentlicht wie ein externes Image.
5. App erscheint als Kachel und ist nach Freigabe für Haushaltsmitglieder zugänglich.
6. Jede Änderung erzeugt eine neue versionierte Revision, keine Live-Dateiänderung im Prod-Container.

### Journey E – Minecraft später integrieren

Minecraft wird zunächst **nicht blind migriert oder verändert**. Beschreibe und teste einen Mock-/Adapter-Vertrag für `minecraft.status`, `minecraft.start`, `minecraft.stop`, `minecraft.backup`, `minecraft.restore`. Beginne reale Integration nur mit konkreten Zugangsdaten, Provider-Informationen und ausdrücklicher Freigabe. Beim Backup Konsistenz sicherstellen und eine Restore-Prüfung dokumentieren.

---

## 10. Umsetzungsphasen und genaue Deliverables

### Phase 0 – Fundament, Entscheidungen und Bootstrap (sofort beginnen)

**Implementieren:**

- Monorepo, README, AGENTS.md, Arbeitskonventionen, Lizenzentscheidung dokumentieren (keine Lizenz automatisch auswählen, wenn Eigentümerpräferenz fehlt), Gitignore, `.env.example`.
- ADRs zu modularem Monolith, Windows-Host/Linux-Container, Deployment-Abstraktion, zentralem OIDC, Datenisolation und Sicherheitsmodell.
- Windows-Preflight, Linux-Bootstrap, Docker-Compose-Grundgerüst.
- FastAPI-Skeleton, React-Shell, PostgreSQL-Schema/Migration, App-Builds.
- Minimal-CI mit Typecheck/Lint/Pytest.
- Ein tatsächlich dokumentierter, überprüfter Startbefehl plus notwendige Vorbedingungen.

**Abnahme:** Projekt lässt sich aus einem frischen Checkout in einer kompatiblen Linux-Docker-Umgebung anhand der Doku starten, sofern diese Umgebung vorhanden ist; nicht ausgeführte Schritte klar markieren.

### Phase 1 – ServiceHub, Registry, Auth und Health

**Implementieren:** Login/SSO, Rollen, Nutzer-/Haushaltsmodell, App-Karten, Adminansicht, Manifest-Schema und Registry-CRUD, Seed-Manifest, Health-API, automatisierte Tests.

**Abnahme:** Ein User sieht nur zugewiesene Apps; Admin kann Manifest registrieren; Status wird aus tatsächlichen Health-Checks angezeigt.

### Phase 2 – DeploymentService und App-Katalog

**Implementieren:** geprüfter Demo-Katalog, DeploymentProvider-Interface, ein echter Compose-Adapter, valide Ressourcenpläne, Approval, persistente Jobs, Start/Stop/Restart/Logs, Volume-Persistenz, proxybasierte App-URL. Nicht privilegierte Subsysteme ohne Docker-Zugriff.

**Abnahme:** Kuratierte Demo-App über UI installieren, öffnen, stoppen, starten, Neustart/Datenerhalt prüfen. Keine direkten Shell-Strings aus Chat-Eingaben.

### Phase 3 – DKMan-Chat und Wizard

**Implementieren:** einfacher sicherer Intent-/Tool-Dispatcher, Jobstatus im Chat, Registry-Suche, Chatbasierter AppRequest-/Planungswizard, persistierte Requirements/Planversionen. Wenn kein KI-Modell verfügbar ist, Mock-/regelbasierten Modus für Tests und eine klar gekennzeichnete echte KI-Provider-Schnittstelle anbieten.

**Abnahme:** Natürliche Sprache führt zu einem nachvollziehbaren Installationsvorschlag oder AppPlan; es wird nichts riskantes ohne Freigabe ausgeführt.

### Phase 4 – Forge / CodingService

**Implementieren:** Template-Generator, CodingProvider-Abstraktion, isolierte Workspaces, Build/Test-Pipeline, Preview, Freigabe, Publish über DeploymentService, Update-Workflow. Optional OpenHands-Integration erst nach funktionierender Adapterprobe.

**Abnahme:** Eine neue kleine App wird aus dem Wizard-Plan erzeugt, automatisiert getestet, als Image gebaut, in Preview geöffnet, nach Freigabe deployt und im Hub angezeigt. Fehlerfall mit Logs und ohne Kaputtmachen vorhandener Apps.

### Phase 5 – Gemeinsame Plattformdienste und echte Integrationen

**Implementieren, nachdem Phasen 0–4 laufen:** Datenbankverbindungs-Wizard, File-/Notification-Service, kontrollierte App-übergreifende Capabilities, Minecraft-Adapter, Browser-IDE auf isolierten Workspaces, Backup und Restore, Upgrade/Rollback, Ressourcenlimits/Quotas, optional CoolifyProvider.

**Abnahme:** Zwei Apps nutzen denselben kontrollierten Plattformdienst, ohne ihre privaten Datenbanken direkt zu teilen.

**Arbeitsregel:** Erzeuge zunächst alle Planungstickets mit Abhängigkeiten und eindeutigen Akzeptanzkriterien, aber implementiere und teste anschließend **Phase 0 und den größtmöglichen zusammenhängenden Teil der nächsten Phasen**. Nicht nach der reinen Ticketgenerierung stoppen. Keine nur simulierte Vollständigkeit.

---

## 11. Tests und nichtfunktionale Anforderungen

- **Unit:** Registry-Validierung, Capability-Auflösung, Autorisierung, Manifestversionen, Image-Allowlist, Planungszustände, Jobs, Parser.
- **Integration:** PostgreSQL-Migrationen, Provider-Mocks, reale Compose-Integration falls Docker erreichbar, App-Katalog, OIDC-Flow in Testumgebung.
- **E2E:** Login, Kacheln anzeigen, Adminrechte prüfen, Demo-Installation mit Freigabe, Start/Stop, Logs, Health, gemeinsamer Notes-Datensatz.
- **Fehlertests:** falsches Image, kaputte Manifestdatei, DB down, unterbrochener Build, nicht erreichbarer Docker Host, Neustart während eines Jobs, doppelte Installationsanforderung, fehlende Permission.
- **Sicherheitsprüfungen:** keine Docker-Socket-Exposition an User-Apps; Autorisierung auf API-Ebene; keine Secrets in Logs/Frontend; Pfad-/Container-Konfigurationsvalidierung; kein anonymer Adminzugang; Netzwerkzugriff dokumentiert.
- **Operativ:** strukturierte Logs mit Correlation-ID, Job-Historie, Health/Readiness, persistente Daten, Backups/Restore-Plan, Upgrade- und Rollback-Anleitung.
- **Qualität:** Versionierte Schnittstellen, kleine verständliche Module, README pro wesentlichem Subsystem, klare Fehlerantworten und Ressourcenlimits.

Führe jede tatsächlich mögliche Teststufe aus. Ungetestete Dinge in einer eigenen Rubrik dokumentieren; keine erfundenen Testergebnisse.

---

## 12. Was ausdrücklich nicht das MVP ist

- Eine vollständig autonome KI mit uneingeschränktem Serverzugriff.
- Beliebige Docker-Hub-Images automatisch und ohne Prüfung starten.
- Ein kompletter Kubernetes-Cluster.
- Automatische öffentliche Internetfreigabe.
- Vollwertiger No-Code-App-Builder mit Hunderten UI-Komponenten.
- Alle zukünftigen Shared Services sofort als separate Microservices.
- Bestehende Minecraft-Server oder Fremdanwendungen ohne Freigabe umbauen.
- Selbst erstellte Authentifizierung statt OpenID Connect.
- Direktes Editieren produktiver Container statt Git-/Workspace-basierter Änderungen.

Der MVP muss klein, echt, testbar und erweiterbar sein.

---

## 13. Wie du als ChatGPT Work konkret vorgehen sollst

1. **Bestandsaufnahme:** Prüfe verfügbare Tools, vorhandene Berechtigungen, Host-/Containerumgebung und ob ein neues privates GitHub-Repo erstellt werden kann. Gehe ausdrücklich von **keinem bestehenden DKMan-Repo** aus. Falls Serverzugriff fehlt, verwende einen lokalen Testworkspace/Mockprovider und dokumentiere das.
2. **Architektur festlegen:** Erstelle `docs/vision.md`, `docs/architecture.md`, sechs kompakte ADRs, `docs/backlog.md` mit priorisierten Tickets und `docs/security-threat-model.md`. Keine endlose Debatte – entscheide pragmatisch.
3. **Sofort Code erzeugen:** Setze Phase 0 um; Backend/Frontend/Compose/Tests/CI/Skripte müssen echte ausführbare Dateien sein.
4. **Lauffähigen Durchstich schaffen:** Implementiere Registry und Health; danach eine einzige echte, genehmigungspflichtige Katalog-Demo über DeploymentService. Verifiziere End-to-End, soweit die Umgebung dies erlaubt.
5. **Iterativ fortfahren:** Implementiere Phase 3 und anschließend Forge auf Basis der tatsächlich vorhandenen Funktionalität. Arbeite in kleinen logischen Commits und prüfe nach jedem Meilenstein Build und Tests.
6. **Transparent berichten:** Zum Ende jedes Meilensteins liefere Dateien/Commit-Referenzen, tatsächlich ausgeführte Befehle und Testergebnisse, offene Risiken und die nächsten priorisierten Schritte. Behaupte nicht, auf meinem Windows-Rechner installiert zu haben, wenn du keinen Zugriff hattest.

### Gefordertes erstes sichtbares Resultat

Ein neues DKMan-Projekt mit:

- vollständigem Repo-/Ordnergrundgerüst und dokumentierten Architekturentscheidungen;
- ausführbarer React-ServiceHub-Shell;
- FastAPI-Core mit `/health/live` und `/health/ready`;
- PostgreSQL-Verbindung und einer echten Migration;
- Manifest-JSON-Schema, Validator und mindestens einem gültigen Demo-Manifest;
- Docker-Compose-Stack inkl. Linux-Laufzeitbeschreibung;
- Windows-10-Preflight- und Setup-Dokumentation;
- automatisierten Backend-/Frontend-Basistests;
- klarer Anleitung, wie ich das lokal auf meinem Windows-10-Server starte;
- anschließend nahtloser Fortsetzung Richtung App-Katalog und DeploymentService.

**Starte jetzt mit der Implementierung. Liefere nicht nur einen Plan.**
