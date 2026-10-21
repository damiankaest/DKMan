# Deployment-Adapter · P2-002

Eigenständiger interner FastAPI-Prozess mit einem echten Compose-Provider. Nur dieser
Prozess besitzt Dockerzugriff. Das reguläre Core-/Hub-Compose-Projekt aktiviert ihn
nicht. Der ausgelieferte kuratierte Katalog ist leer; die Manifestbeispiele installieren
weiterhin keine Images. P2-003 ergänzt den expliziten Quellbuild der Notes-App;
P2-004 verknüpft ihn mit Core und Hub. Anleitung: [Notes](notes.md).

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
Geräte oder Hostnetzwerke. Das konkrete Profil `notes-postgres-v1` ergänzt einen
festen PostgreSQL-Sidecar und die interne Gatewayroute; seine zusätzlichen Secrets,
Netze und Ressourcen entstehen ausschließlich serverseitig gemäß ADR 0009.
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
prüft seit P2-004 OIDC-/Ressourcenrechte und die persistente Approvalbindung,
verbraucht Freigaben vor Dispatch und verwendet dieselbe Job-ID als Operation-ID.
Die Core-Installationsroute nimmt keine freien Pläne entgegen. Auch ein 200-Operationsresultat muss
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
Das erzeugt einen leeren Katalog und getrennte zufällige Delegations-/Datenschlüssel;
bestehende Konfiguration/Secrets bleiben erhalten. Beim expliziten Upgrade von v1
wird nur der vorher noch nicht vorhandene Datenschlüssel ergänzt. Ein verlorener
v2-Schlüssel wird nicht ersetzt. Es startet keinen Container.

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

P2-003/P2-004 ergänzen Notes-Quellbuild, Kuration und die echte Installationsjourney;
deren eigener Nachweis steht in `acceptance-tests.md`. Offen: erweiterte
belegbarer Workflow zum Abschluss unsicherer Mutationen (P2-006), Zielhost-OIDC,
Windows-/VM-Betrieb sowie koordinierte Persistenz-/Restoreabnahme. Die Runtimebedienung
P2-005 ist implementiert; echte OIDC-/Containerabnahme siehe `acceptance-tests.md`.
Logredaktion entfernt bekannte Muster, kann frei formulierte oder unbekannte Secrets
in beliebigen App-Logs nicht vollständig erkennen; Apps müssen sichere Logs erzeugen.


## Fortschreibung P2-005

Core und Hub verwenden nun Start/Stop/Restart sowie lesenden Status/Logzugriff.
Der optionale Lifecycle-Command bindet Aktion/Identität und den vollständigen bereits
installierten Plan; der neue Envelopehash steht auch im Operationsresultat. Ohne
Envelope bleiben alle bisherigen v1-Hashes/Fingerprints stabil. Keine Journalmigration.
Nur bekannte, vollständige Workloads können verändert werden. Start verwendet `start`
statt `up`; Restart wartet bis zu 30 Sekunden auf tatsächliche Health. Stop prüft beide
Notes-Container. Die bestehenden Aufruflimits und dauerhaften Unklarheitssperren gelten
weiter. Vollständiger Ressourcen-/Freigabevertrag: [Jobs](jobs.md), ADR 0010.
Logs sind auf 100 Zeilen/8 KiB UTF-8 beschränkt, auf beiden HTTP-Grenzen maskiert und
im Hub als Text gerendert. Dies kann unbekannte freie Secrets weiterhin nicht erkennen.


Lesende Adapteroperationen teilen sich eine Prozesssperre; Mutationen bleiben
exklusiv. Beim Sperrerwerb wird höchstens zwei Sekunden auf kurze Beobachtungen
gewartet, danach ein fester Busy-Fehler ausgegeben. Wiederholt wird ausschließlich
der Sperrversuch vor dem Adapter-Ausführungsmarker, niemals ein Provideraufruf.
Delegationsablauf wird nach Sperrerwerb/Preflight erneut geprüft. Recovery verwendet
weiterhin exklusiven, nicht wartenden Sperrerwerb und respektiert aktive Leser/Worker.

## Dauerhafte Enginebelege · P2-006

Explizite Journalrevision **3**, neue Migration `0003_execution_receipts.sql`. Erst nach
kontrolliertem Adapterstopp und abgestimmter Sicherung ausführen; der Service migriert
weiterhin nicht automatisch. Alte Migrationen und gespeicherte Command-/Planhashes bleiben
unverändert. Ein v2-Journal wird ohne explizite Migration abgelehnt.

Nach erfolgreicher Compose-Rückkehr wird der an Operation/Aktion/Ressource/Hash gebundene
Enginebeleg separat synchron committed. Ein Crash danach, vor dem Operationsabschluss,
kann durch `POST /v1/operations/{id}/reconcile` belegt aufgelöst werden. Neustart verlangt
nachweislich neue Startzeitpunkte aller ursprünglichen Container; aktuelle Health allein
reicht nicht. Derselbe Ressourcensperrmechanismus schützt Abgleich und Ausführung. Es gibt
keinen Provider-Retry und keine neue Runtime. Der bisherige GET bleibt beobachtend.

Install/Start/Stop/Restart können eine persistierte `failed`-Operation mit gebundenem
Nichtausführungsnachweis ausgeben, wenn Kuration oder rein lesender Preflight vor dem
Marker ablehnen. HTTP 200 enthält dann ausdrücklich `state=failed`, niemals Erfolg.
Andere Fehler und Ausführung mit möglicher Wirkung bleiben unklar. Rejection löst keine
fremde Ressourcensperre und verbrauchte Approval-IDs bleiben einmalig gebunden.

Kein Beleg nach Crash **vor** dessen Commit: `execution_receipt_missing`. Geänderte/
unvollständige Container oder fehlende Transition: `execution_evidence_incomplete`.
Diese Fälle bleiben blockiert, auch nach Adapterneustart oder aktuell gesunder Runtime.
Die Prüfsumme ist Integritätserkennung innerhalb der vertrauenswürdigen Adaptergrenze.
Keine vollständigen Inspect-Daten/Environments im Journal oder API-Nachweis. Siehe ADR 0011.
