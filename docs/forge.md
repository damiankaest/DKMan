# Forge · P4-001 und P4-002

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

Das Manifest enthält weiterhin absichtlich eine ungültige Image-Referenz. Der Build
ändert das Manifest nicht und installiert keine App. Preview, Übernahme und Deployment
gehören zu P4-003.

## Isolierter Build-Worker

Der Worker ist ein manueller erster Betriebsweg für die drei **unveränderten**
Startervorlagen. Er gehört auf einen getrennten, vertrauenswürdig eingerichteten
Linux-Builder, nicht auf den DKMan- oder Minecraft-Produktionshost. Dieser Builder
benötigt Python 3.12, das installierte DKMan-Paket derselben Revision, `buildctl`
und einen lokalen BuildKit-Daemon. Der BuildKit-Socket ist kein Docker-Socket.
Es dürfen weder Docker-/Host-Sockets noch produktive Daten, SSH-Agenten oder Secrets
in den Build gegeben werden. Netzwerkzugang für Image-/Paketdownloads und wirksame
CPU-, Speicher-, Platten- und Netzgrenzen sind auf dem isolierten Builder gesondert
einzurichten. Der Worker prüft diese Umgebung nicht vollständig; ein Socket beweist
keine Isolation. Paketdownloads benötigen Netzwerk, die eigentlichen Test- und
Frontend-Buildbefehle laufen ohne Netzwerk. Die verwendeten Basisimages und
Abhängigkeiten sind gepinnt.

Voraussetzungen: ein aktueller freigegebener Plan, ein zugehöriger Quellstand, ein
kurzlebiges OIDC-Access-Token eines aktuell berechtigten Developers oder Admins und
ein sicher erreichbarer HTTPS-Core. HTTP ist nur für Loopback erlaubt. Der Builder
muss unter dieser Core-URL das vom Login verwendete Token vor und während des Builds
prüfen lassen können. Die Quellstand-ID steht im Hub unter „Dateien und Prüfsumme“.
Auf einem isolierten Builder kann ein Operator zunächst nur den Ablauf prüfen:

```bash
uv run python -m dkman.forge.build_worker \
  --core https://dkman.example \
  --workspace QUELLSTAND-UUID \
  --root /pfad/zum/privaten-builder-verzeichnis \
  --buildkit-socket unix:///pfad/zum/buildkitd.sock
```

Das Verzeichnis muss bereits existieren, dem ausführenden Benutzer gehören und den
Modus `0700` haben; Pfade dürfen keine Symlinks oder Kommas enthalten. Der Dry-Run
startet keinen Build. Auf dem nachweislich isolierten Builder wird der gleiche Befehl
mit `--apply --confirm BUILD_FORGE_ISOLATED` gestartet. Das OIDC-Access-Token wird
danach verdeckt abgefragt und weder als Befehlsargument noch in die Buildumgebung
gegeben. Bei einem abgelaufenen Token fragt der Worker einmal nach einem neuen;
ohne erfolgreich erneuerte Authentifizierung entsteht kein freigegebenes Image.
Eine integrierte Tokenbeschaffung oder ein Buildstart im Hub sind noch nicht vorhanden.

Die Prüfungen umfassen Python-Syntax, Pytest einschließlich SQLite-Migrationsprobe
sowie für Webvorlagen Vitest und TypeScript-/Vite-Build. Eine PostgreSQL-Integration,
separate Python-Typprüfung und Formatter-/Lintprüfung des generierten Projekts sind
damit nicht abgedeckt. Die Ausführung ist auf 15 Minuten pro BuildKit-Aufruf begrenzt;
nach einem Timeout kann der Zustand des separaten Daemons unklar sein. Keine
automatische Wiederholung oder Freigabe erfolgt.

Unter `<root>/<build-id>/build-artifact.json` stehen Status, Plan-/Quellhash,
Ergebnis der Checks, OCI-Manifest-Digest, Archiv-SHA-256 und ein begrenzter
Fehlerlog. Nur ein `image.oci.tar` mit zugehörigem Status `succeeded` und erneut
geprüftem Digest darf als erfolgreiches Artefakt behandelt werden.
Die Datei und Logs bleiben privat auf dem Builder und können vertrauliche Inhalte
enthalten; die Muster-Maskierung erkennt nicht jedes Geheimnis. `running` nach einem
Absturz bedeutet unbekannt, nicht erfolgreich. Das Artefakt allein ist weder eine
Registryfreigabe noch eine Installation und wird nicht im Hub angezeigt.

Das Buildrezept prüft die Vorlage gegen die lokal installierten Starterdateien. Wenn
Vorlagen in einer späteren Revision geändert werden, muss für einen neuen Build ein
passender neuer Quellstand erstellt werden. Der OCI-Digest identifiziert das gebaute
Image; ein bitgenau reproduzierbarer Rebuild wird nicht behauptet.

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
