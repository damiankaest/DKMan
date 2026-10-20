# Deployment-Adapter · P2-002

Eigenständiger interner FastAPI-Prozess mit einem echten Compose-Provider. Nur dieser
Prozess besitzt Dockerzugriff. Das reguläre Core-/Hub-Compose-Projekt aktiviert ihn
nicht. Der ausgelieferte kuratierte Katalog ist leer; die Manifestbeispiele installieren
weiterhin keine Images. Notes-App und ihre echte Kuration folgen in P2-003.

## Implementierte Verträge

`deployments/contracts.py` definiert `DeploymentProvider`, versionierten Plan und
Command. `deployments/client.py` transportiert typisierte Requests zum festen internen
Adapter; keine Redirects, Proxyübernahme oder automatischen Wiederholungen. Planung
entsteht serverseitig aus Katalogrevision und Installations-ID. Der effektive Plan
enthält den genauen Digest, Nutzer, Ressourcen und einen zulässigen Datenpfad.

| Aktion | Tatsächliche Providerfunktion |
| --- | --- |
| discover / status | eigene Container inspizieren; Zustand plus Beobachtungszeit |
| pull | Digest pullen bzw. lokales Build-Artefakt prüfen; Imagevertrag validieren |
| install / deploy | sicheres Compose rendern, kein Build, exakt gepinntes Image; auf echte Health warten |
| start / stop / restart | ausschließlich bekannte eigene Installation verwalten |
| logs | maximal 100 Zeilen, 8 KiB Ausgabe; bekannte Token-/Passwort-/URLmuster und Kontrollzeichen bereinigen |
| remove | Workload/Netzwerk entfernen, Datenvolume erhalten |
| remove_data | separate freigegebene Aktion; Workload muss bereits entfernt sein; nur eigenes Volume |

Pläne gestatten keine eigenen Shellbefehle, Entrypoints, Environments, Mounts, Ports,
Geräte oder Hostnetzwerke. Interner Netzwerkzugang ohne veröffentlichte Ports ist
bewusst noch keine im Hub erreichbare App. Eine passende SSO-/Proxyroute folgt P2-004.
Der Katalog ist eine ausdrücklich gepflegte Vertrauensquelle; Registryeinträge und
Suchergebnisse ändern ihn nicht automatisch. Hot-Reload ist nicht implementiert.

## Interne API

Alle `/v1`-Routen verlangen eine kurzlebige, passend gebundene Core-Delegation.
Der Service akzeptiert weder Browser-OIDC-Tokens noch ein festes Admin-Token.

| Route | Verhalten |
| --- | --- |
| `POST /v1/plans` | Katalogrevision in einen konkreten Plan überführen; unbekannt 409 |
| `POST /v1/operations/{UUID}` | typisierte Aktion; vor Ausführung dauerhafter Marker; identische Wiederholung liefert vorhandenes Ergebnis |
| `GET /v1/operations/{UUID}` | vorhandenes Ergebnis mit passender Lese-Delegation |
| `GET /v1/operations/{UUID}/reconcile` | tatsächlichen Zustand beobachten; unsichere Mutation bleibt gesperrt |
| `/health/live`, `/health/ready` | Prozess bzw. Journalrevision und tatsächlich erreichbare Linux-Engine/Compose prüfen |

Delegation: HS256, exakter Issuer `dkman-core`, Audience `dkman-deployment-adapter`,
maximal 60 Sekunden; Subject, Rollen, Operation-ID, Installations-ID, Aktion und
Plan-Hash. Mutationen benötigen Approval-ID und Ablauf zusätzlich. Admins verwalten
Installationen; Operatoren dürfen delegierte Start-/Stop-/Restart-/Leseaktionen mit
den jeweiligen Freigaben ausführen. Member/Developer erhalten keine Runtimevollmacht.
Falsche/abgelaufene Tokens: 401, unpassende Vollmacht: 403, Konflikte: 409.

Die Signierfunktion ist eine interne Bibliothek, kein offener Aussteller. Der Core
muss in P2-004 OIDC-/Ressourcenrechte und die persistente Approvalbindung prüfen,
Freigaben vor Dispatch verbrauchen und dieselbe Job-ID als Operation-ID verwenden.
Aktuell besteht keine Core-Installationsroute. Auch ein 200-Operationsresultat muss
über sein Feld `state` ausgewertet werden; unsichere Ergebnisse sind kein Erfolg.

## Journal und Fehlergrenzen

Explizite Migration: `python -m dkman.deployment_adapter.journal --state-root ...`.
Der normale Service erzeugt keine Datenbanktabellen. Eigene Journalrevision 2
(0001 Operationsjournal, 0002 einmalige Approval-IDs),
getrennt von PostgreSQL/Alembic im Core. Das Adaptervolume gehört in ein späteres
koordiniertes Backup; sein Verlust darf nicht durch einen leeren Journalstart
kaschiert werden. Bestehende Runtime-Projekte ohne Journaleintrag werden nicht übernommen.

- Vorprüfungen verändern keine Runtime. Fremde gleichnamige Projekte, Netze oder
  Volumes werden abgelehnt. Ein gültiges Imageformat allein reicht nicht aus.
- Pro Installation gilt eine OS-Dateisperre über den gesamten Aufruf. Dieselbe
  Operation-ID mit anderem Inhalt, Subject oder anderer Approvalbindung: 409.
  Eine bereits verbrauchte Approval-ID ist auch für eine neue Operation-ID gesperrt.
- Nach dem dauerhaften `running`-Marker kann ein Timeout oder Fehler bereits
  wirksam gewordene Dockeraktionen betreffen. Deshalb `reconciliation_required` und
  dauerhafte Ressourcensperre statt neuem Versuch.
- Neustart/periodische Recovery markiert nur verwaiste Marker; aktive Prozesssperren
  bleiben respektiert. Verlorene HTTP-Antwort: vorhandene Operation lesen bzw.
  denselben Request wiederholen, keinen neuen Auftrag erfinden.
- Reconcile liefert Beobachtungen, beseitigt aber keine unbewiesene Unsicherheit.
  Kein öffentlicher Unblock-/Erfolgs-/Prune-Endpunkt und keine Journallöschung als Retry.

## Explizite Vorbereitung und Zielhostgrenzen

`uv run python scripts/generate_adapter_config.py` ist ausschließlich ein Dry-run.
Bewusste Konfigurationsvorbereitung benötigt `--apply --confirm ADAPTER_CONFIG`.
Das erzeugt einen leeren Katalog und ein neues zufälliges Secret nur bei Erstanlage;
bestehende Konfiguration/Secrets bleiben erhalten. Es startet keinen Container.

Das separate `infrastructure/deployment-adapter/compose.yaml` benötigt nach Host-Preflight
die tatsächliche Gruppe des lokalen Docker-Sockets in `DKMAN_DOCKER_SOCKET_GID`.
Der Adapter läuft als 10001:10001 plus dieser Gruppe. Nur er bekommt den Socket,
der Migrationscontainer nicht. Kein Hostport, nur internes Control-Netzwerk.
Aktivierung, Netzwerkverknüpfung mit Core und Secretfreigabe sind noch ausdrücklich
am Zielhost abzunehmen. Der bisherige Bootstrap wird dadurch nicht still erweitert.

## Verifikation und nächste Schritte

Unit-/Sicherheitstests: `uv run pytest tests/test_deployment_adapter.py -q`.
`tests/test_adapter_docker.py` benötigt ausdrücklich einen wegwerfbaren GitHub-Runner
mit `DKMAN_DISPOSABLE_DOCKER_TEST=1`; lokal ohne diesen Nachweis übersprungen.
Die Probe baut eigene Testimages und verwendet deren tatsächliche Image-IDs, keine
behauptete kuratierte Notes-App. Sie hat Lifecycle, echte Health, Volumenerhalt,
separate Datenlöschung, Kollisionen und unbekannten Ausgang nach Healthfehler geprüft.
[CI-Nachweis 39388427751](https://github.com/damiankaest/DKMan/actions/runs/39388427751)
und Details in `acceptance-tests.md`; PR #9 in `main` integriert.

Offen: Notes-App/Kuration P2-003, Core-Approval-Dispatch und Hub-UI/SSO P2-004,
erweiterte Runtimebedienung P2-005, belegbarer Workflow zum Abschluss unsicherer
Mutationen, Live-OIDC, Windows-/VM-Betrieb sowie koordinierte Persistenz-/Restoreabnahme.
Logredaktion entfernt bekannte Muster, kann frei formulierte oder unbekannte Secrets
in beliebigen App-Logs nicht vollständig erkennen; Apps müssen sichere Logs erzeugen.
