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
Haushaltszugriff und Planstand werden bei jedem Abruf aus der Datenbank geprüft;
Rollen werden aus dem jeweils gültigen Token gelesen und nicht bei jedem Abruf
live beim Identity-Provider abgefragt.

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

## Erste Preview-Arbeit · P4-003

Dieser Teil ist in Arbeit: Eine produktive Übernahme oder Installation ist noch nicht
implementiert. Der Preview-Pfad unterstützt die drei unveränderten Startervorlagen und
benötigt eine separate Linux-VM mit eigener Docker-Engine; die VM darf keinen Zugriff auf produktive
Daten, Docker-Sockets oder Secrets haben. Die Isolation des Hosts muss der Betreiber
bereitstellen und prüfen. Ein internes Docker-Netz isoliert Container nicht vollständig
vom eigenen Host. Die Preview erfordert Docker Engine 28 oder neuer: Bei älteren Versionen
kann ein an Loopback veröffentlichter Port unter Umständen im gleichen Netz erreichbar sein.

Auf dem isolierten Builder und der separaten Preview-VM jeweils einen eigenen Schlüssel
in einem existierenden privaten Verzeichnis anlegen. Ohne `--apply` sind die Befehle
nur ein Dry-Run:

```bash
uv run python scripts/generate_forge_signing_key.py --root /pfad/privat --purpose build
uv run python scripts/generate_forge_signing_key.py --root /pfad/privat --purpose preview
```

Für die jeweilige tatsächliche Schlüsselanlage auf der passenden VM zusätzlich
`--apply --confirm CREATE_FORGE_SIGNING_KEY` verwenden. Private Schlüssel bleiben auf
der jeweiligen VM. Nur die öffentlichen Schlüssel werden zum Core übertragen und
explizit über `forge-attestation.yaml` bzw. `forge-preview.yaml` eingebunden. Sie
müssen verschieden und für den Core-Prozess lesbar sein. Änderungen an laufenden
Diensten benötigen eine gesonderte Hostwartung; kein Overlay wird automatisch aktiviert.

Einen neuen Build mit `--signing-key /pfad/privat/forge-build-private.pem` erzeugen.
Im Hub beim Quellstand die `build-attestation.json` importieren. Core prüft den
konfigurierten öffentlichen Schlüssel und den aktuellen Plan; das OCI-Archiv bleibt
außerhalb des Core. Alte unsignierte P4-002-Builds sind nicht als Nachweis importierbar.

Nach sicherer Übertragung von `image.oci.tar` und `build-attestation.json` in ein
privates Verzeichnis auf der Preview-VM lässt sich der Preview-Adapter zunächst planen:

```bash
uv run python -m dkman.deployment_adapter.forge_preview \
  --root /pfad/privat --core https://dkman.example \
  --artifact-dir /pfad/zum/build-verzeichnis \
  --builder-public-key /pfad/forge-build-public.pem \
  --preview-private-key /pfad/forge-preview-private.pem \
  --docker-binary /usr/bin/docker
```

Der Docker-Pfad muss zum ausführbaren Programm auf der Preview-VM passen. Vor dem
Laden verpackt der Adapter ausschließlich die geprüften OCI-Blobs ohne Tags in ein
temporäres Docker-Archiv und prüft die Image-ID nach dem Laden erneut. Das temporäre
Archiv benötigt zusätzlichen Speicherplatz und wird nach dem Ladevorgang entfernt.
Für die beiden API-Vorlagen setzt der Adapter ausschließlich eine SQLite-Datenbank in
`/tmp` innerhalb des Containers auf und führt die feste Startermigration aus. Diese
Testdatenbank liegt im begrenzten tmpfs und verschwindet mit dem Preview-Container.
Es werden keine produktiven Datenbankadressen oder Zugangsdaten übergeben.

Auf der ausdrücklich isolierten Preview-VM startet `--apply --confirm
PREVIEW_ISOLATED_VM` die Vorschau. Der Prozess fragt das aktuelle OIDC-Access-Token
verdeckt ab und zeigt einen nur auf dieser VM erreichbaren `127.0.0.1`-Port. Für einen
anderen Rechner ist ein bewusst eingerichteter SSH-Tunnel erforderlich. Der Browser
für die Vorschau muss ebenfalls isoliert sein: ein eigenes Profil ohne produktive
Anmeldungen und ohne Zugriff auf produktive Dienste oder Netze verwenden. Das gilt
auch bei einem SSH-Tunnel, da JavaScript mit den Netzwerkrechten des Browsers läuft.
Ohne echte
Identity-/Produktionsdienste kann die Vorlage ihre Anmeldung in der Vorschau nicht
vollständig durchführen. Enter oder der Zeitablauf entfernt Container und Netzwerk;
das geladene Image bleibt auf der Preview-Engine. Nach hartem Abbruch kann der Operator
mit `--root /pfad/privat --cleanup-id PREVIEW-UUID --apply --confirm
CLEANUP_FORGE_PREVIEW` ausschließlich die passend markierten Ressourcen entfernen.

Die `preview-attestation.json` lässt sich innerhalb ihrer Gültigkeit beim Build im Hub
importieren. Sie belegt eine beobachtete Readiness, keinen aktuellen Livezustand und
keine menschliche Abnahme. Es gibt noch keinen integrierten Preview-Link, keine
Archivübernahme in die Produktiv-Engine und keinen Deploy- oder Updateablauf.

## Prüfungen

P4-002: [PR-CI 40506720712](https://github.com/damiankaest/DKMan/actions/runs/40506720712)
hat die drei Vorlagen auf einem wegwerfbaren BuildKit-Runner gebaut und die OCI-Artefakte
verifiziert. Der Quellstand für diesen Build ist ein Testfixture; eine separate echte
Keycloak-Journey prüft die Berechtigungen und den Widerruf bei einer neueren Planversion.
Zielhost, interaktiver Workerbetrieb und die Isolation des vom Nutzer gewählten
Builders wurden nicht abgenommen. Der folgende Abschnitt dokumentiert P4-001.

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
