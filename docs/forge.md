# Forge · P4-001

Forge erstellt für freigegebene Planrevisionen reproduzierbare Quellstände. Zur Wahl
stehen eine Python-API, eine React-SPA und eine Kombination beider Vorlagen. Die
Vorlagen enthalten gesperrte Abhängigkeiten, Tests, Dockerfiles und eine Anleitung.
Die API besitzt eine explizite Alembic-Migrationsbasis und prüft den Appzugriff über
Core. Das Frontend verwendet OIDC mit PKCE und prüft die Installationsfreigabe.

Der freigegebene Plan wird einschließlich seines Hashes als Daten in `plan.json`
gespeichert. Anforderungen werden nicht in ausführbaren Code eingefügt und die
beschriebenen Fachfunktionen nicht automatisch implementiert. Nur ausdrücklich
aufgelistete Vorlagendateien werden übernommen; lokale Caches und weitere Dateien
können nicht versehentlich in den Quellstand gelangen. Ein identischer Plan und
eine identische Vorlage ergeben denselben Quellinhalt und Hash.

## Quellstand im Hub erstellen

1. Unter **App planen** eine aktuelle Planversion freigeben.
2. Unter **App-Quellcode vorbereiten** die Quellstände öffnen, eine Vorlage wählen
   und **Quellstand erstellen** auswählen.
3. Dateien und Inhalts-Hash prüfen und den Quellstand bei Bedarf als ZIP herunterladen.

Admins können alle zugänglichen Pläne bearbeiten; Developer ihre eigenen Pläne, für
deren Haushalt sie noch berechtigt sind. Quellstände sind für ihren Eigentümer und
Admins sichtbar. Ein historischer Quellstand bleibt bei fortbestehender Berechtigung
lesbar; neue Erzeugung erfordert die aktuelle freigegebene Revision. Planfreigabe,
Dokumenthash und Berechtigung werden serverseitig geprüft. Beim Abruf werden die
aktuellen Rechte sowie die Bindung und Integrität des gespeicherten Inhalts geprüft.
Idempotenzschlüssel verhindern eine doppelte Anlage bei einer Wiederholung.

Die Quellstände werden als unveränderliche Datenbanksnapshots gespeichert. Migration
`0005_forge_workspaces` muss vor der Nutzung über die üblichen Migrationsschritte
ausgeführt werden. Die ZIP-Datei ist reproduzierbar und enthält keine Hostpfade.
Die Erzeugung startet keinen Container und erstellt keine Appinstallation.

## Worker-Grenze

`materialize_git_workspace` kann einen geprüften Snapshot unter einem vertrauenswürdigen
Worker-Root in einem eigenen Verzeichnis als frisches Git-Repository materialisieren.
Git-Hooks, globale Konfiguration und interaktive Netzabfragen sind ausgeschaltet. Der
Core ruft diese Funktion nicht auf und benötigt keinen Zugriff auf Hostdateien oder
Docker. Der Worker-Root muss vor fremdem Schreibzugriff geschützt werden; die Funktion
ist keine Sandbox. Vor späterem Build oder Deployment müssen Berechtigung, Freigabe
und Inhalts-Hash erneut überprüft werden.

Das Manifest enthält bis zu einem geprüften Build absichtlich eine ungültige
Image-Referenz. P4-002 ergänzt einen isolierten Build-Worker und ein Buildartefakt;
Preview und Deployment gehören zu P4-003.

## Prüfungen

Lokal bestanden: 308 Backendtests (16 Diensttests übersprungen), Ruff/Format und
mypy, 24 Hubtests, Lint und Build sowie acht Desktop-/Handy-Browsertests mit expliziten
HTTP-/Auth-Testdaten. Die drei erzeugten Projekte wurden getrennt installiert und ihre
Backend- und Frontendtests sowie Frontendbuilds ausgeführt; lokale Migrationstests
verwenden SQLite. PGlite prüft Migration 0005 einschließlich Downgrade und erneutem
Upgrade, ersetzt aber keinen Netzwerktest gegen PostgreSQL 17.

Die GitHub-CI ergänzt PostgreSQL-17-Migrationen, parallele Anfragen und eine echte
Keycloak-/Core-Journey für die Forge-Erzeugung und den Zugriffsschutz. Der letzte
Lauf für den aktuellen PR ist maßgeblich. Eine Zielhostabnahme wurde hier nicht
durchgeführt.
