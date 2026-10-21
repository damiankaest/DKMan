# Betrieb und Recovery

Alle Skripte verwalten nur das Compose-Projekt `dkman`. Vor dem ersten Start
`bootstrap.sh --dry-run` lesen. Niemals auf einem Host mit unbekanntem gleichnamigem
Stack fortfahren. Compose veröffentlicht nur 8080 auf Loopback; DB/Core/Identity
haben keine separaten Hostports.

## Diagnose

```bash
bash scripts/linux/doctor.sh
docker compose --env-file .env -f infrastructure/compose/compose.yaml ps --all
docker compose --env-file .env -f infrastructure/compose/compose.yaml logs --tail=100 core keycloak migrate
```

Logs können bei zukünftigen Fremdapps sensible Inhalte enthalten; nicht ungeprüft
teilen. `.local/logs` enthält Bootstrap-/Upgrade-/Restoreprotokolle. Core-Requests
erhalten eigene UUID-Korrelationen ohne Tokens/Querystrings. Readiness 503 bedeutet
DB oder Alembic-Revision nicht bereit; Liveness bleibt vom DB-Zustand unabhängig.

Stoppen und erneut starten ohne Datenlöschung:

```bash
docker compose --env-file .env -f infrastructure/compose/compose.yaml stop
docker compose --env-file .env -f infrastructure/compose/compose.yaml up -d --wait
```

`down` ohne `-v` entfernt Container/Netze, erhält das Volume. Kein Skript führt
`down -v`, Volume-Prune oder Image-Prune aus. Nicht manuell Datenvolumes löschen.

## Backup und Restore

```bash
bash scripts/linux/backup.sh --dry-run
bash scripts/linux/backup.sh --apply
bash scripts/linux/restore.sh .local/backups/<backup> --dry-run
# Nur nach neuer Sicherung und Prüfung:
bash scripts/linux/restore.sh .local/backups/<backup> --apply
```

Backup verlangt `BACKUP`, Restore `RESTORE`. Gesichert werden je ein
transaktionskonsistenter Dump von Core und Keycloak, Config/Secrets und die
Git-Revision mit Prüfsummen. Kein global koordinierter Snapshot über mehrere DBs;
die aktuellen Domänen schreiben unabhängig. Sobald Appdaten hinzukommen, Konzept
um Volume-/App-Backups und koordinierte Konsistenz erweitern. Dateien liegen mit
privaten Rechten unter `.local/backups`; auf separatem verschlüsseltem Medium
zusätzlich sichern, wenn ein echter Betrieb beginnt.

Restore überschreibt beide DKMan-Datenbanken und stoppt dafür Hub/Core/Identity.
Config/Secrets werden nicht automatisch aus einem Tararchiv entpackt. Bei Recovery
auf demselben Stack aktuelle DB-Rollen/Secrets beibehalten. Bei komplett neuem Host
die gesicherte Config vor dem ersten Bootstrap kontrolliert wiederherstellen,
POSIX-Rechte prüfen und denselben Code-/Schemastand verwenden. Archive nur aus
vertrauenswürdigen eigenen Backups extrahieren. Nach Restore Doctor, Login und
Freigaben prüfen. Diese Skripte sind vorhanden, aber noch nicht live abgenommen.

## Upgrade

`upgrade.sh` arbeitet auf dem bereits vom Betreiber ausgewählten Checkout; es
führt kein `git pull` aus. Default ist Dry-run. Apply verlangt `UPGRADE`, baut
Images und erstellt ein gesondert bestätigtes Backup vor Datenänderungen. Danach
stoppt es Appdienste, migriert und startet mit Healthprüfung. Bei Fehlern bleibt
der Zustand zur Diagnose bestehen; keine automatische Datenrücksetzung.

Rollback: alten geprüften Checkout auschecken und Images neu bauen. Nur bei
rückwärtskompatiblem Schema starten. Andernfalls vollständiges Backup mit passender
Git-Revision in kontrollierter Wartung wiederherstellen. DB-Downgrades nicht auf
Verdacht produktiv ausführen. Erster Alembic-Roundtrip wird in einer wegwerfbaren
Testdatenbank geprüft, was spätere Migrationen nicht automatisch sicher macht.

## Optionaler Deployment-Adapter

P2-002 enthält einen separaten, standardmäßig nicht gestarteten Adapter. Vorbereitung,
eigene Journalmigrationen und Grenzen stehen in [deployment-adapter.md](deployment-adapter.md).
Nur dieser Prozess darf den lokalen Docker-Socket erhalten; keine Proxyroute oder
öffentlichen Ports hinzufügen. Socketgruppe und Linux-Engine vorher am Zielhost prüfen.

Der aktuelle Backupprozess sichert Core/Identity und deren Konfiguration; er erfasst
weder das persistente Adapterjournal noch `.local/adapter/catalog.json`. Der neue
Delegationsschlüssel und der ausschließlich dem Adapter zugängliche Datenschlüssel
liegen unter `.local/secrets`, die der bestehende Backupplan
bereits einschließt. Vor Livebetrieb Journal, Katalog, Corezustände und Appvolumes
koordiniert sichern und Restore abnehmen. Ohne Journal keine vermeintliche Übernahme
bereits laufender Container und kein neuer Auftrag zum Überspielen unbekannter Ergebnisse.

Notes und genehmigte Hubinstallation sind als explizites Runtime-Overlay implementiert;
Vorbereitung, OIDC-Client und Startauswahl stehen in [Notes](notes.md). Notes hat eine
eigene PostgreSQL-Instanz/ein eigenes Volume. Die alten Backup-/Restore-/Upgradeskripte
sind weiterhin nur für den Basisstack ausgelegt. Sie sind kein koordinierter
Runtime-Wartungsweg. Vor Zielhostaktivierung müssen diese Betriebsabnahmen erfolgen.

## GitHub-Übergabe

Das private Repository besteht unter [damiankaest/DKMan](https://github.com/damiankaest/DKMan).
`main` ist maßgeblich; Fortschritt, CI-Nachweise und nächste Tickets stehen in
`progress.md`, `acceptance-tests.md` und `backlog.md`. P2-001 und P2-002 wurden über
PR #8 und #9 integriert; P2-003/P2-004 über PR #10. Der vollständige
Main-CI-Lauf 39409720195 ist erfolgreich; Nachweise siehe `acceptance-tests.md`. Der archivierte ursprüngliche Git-Bundle ist historischer
Quellnachweis und kein Ersatz für den aktuellen Repository-Stand.


## Runtimebedienung P2-005

Im Hub unter Verwaltung → Containerbetrieb die bestehende Installation wählen.
Admin: alle Installationen. Operator: Haushaltsmitgliedschaft plus separate Betriebsfreigabe
`app.operate`; Appfreigabe `app.use` reicht nicht. Globale Rollen werden in Keycloak verwaltet.
Der Adminbereich „Haushalte und Freigaben“ erteilt oder entzieht Betriebsfreigaben separat.

„Container starten/stoppen/neu starten“ erzeugt zunächst einen konkreten gespeicherten
Plan. Hash, Aktion, Installation, Identität, Images und Ablauf prüfen, zustimmen, erst
danach „Runtimeaktion ausführen“. Pro Installation nur ein offener Auftrag. Nach
Browserreload dieselbe Installation auswählen; gespeicherte Jobs und Verlauf wieder laden.
Status/Logs können ohne Freigabe lesend abgerufen werden. Logs vor Weitergabe trotzdem
prüfen; Muster erkennen nicht jedes Secret. Keine ungefilterten Enginefehler ausgeben.

Bei Transportverlust/Timeout `reconciliation_required` erhalten. „Runtimeergebnis
abgleichen“ liest ausschließlich die bereits gespeicherte Adapteroperation. Aktuell
gesunde Container belegen keinen erfolgreichen Restart. Fehlende/unsichere Resultate
sperren weitere Mutationen und den Öffnen-Link. Weder Journal löschen noch neue Keys,
Force-Retry oder pauschales Entsperren verwenden. Belegter weiterer Abschluss folgt
P2-006. Laufende Jobs nicht per DB-Update auf Erfolg setzen.

Stop/Start verändert keine Containerdefinition und löscht keine Daten. Lifecycle setzt
vollständig vorhandene Container voraus. Fehlende Container sind ein Diagnosefall,
kein automatischer Neuinstallationsauftrag. Die Zielhost-/Windows-/VM-Abnahme, vollständige
OIDC-Betriebsmatrix und koordinierter Backup/Restore bleiben offen. Vorhandene Backups
und Upgrades sind weiterhin nur für den Basisstack ausgelegt.


P2-005 ist über PR #11 in `main` (`07e18c5`) integriert; Main-CI `39431777779` ist
vollständig erfolgreich, einschließlich echter OIDC-/Notes-Lifecycleprobe. Der genaue
Mainnachweis steht in [p2-005-main-runtime.json](evidence/p2-005-main-runtime.json).
Das ist eine isolierte CI-Abnahme und keine Zielhost-/Restorefreigabe.

## Abgleich im Betrieb · P2-006

Bei unklarem Auftrag im Hub „Runtimeergebnis abgleichen“ wählen. Es wird ausschließlich
beobachtet. Ein vollständiger Enginebeleg kann den ursprünglichen Auftrag und genau seine
Sperre abschließen; der Hub zeigt den Nachweishash. Fehlender Beleg oder abweichende
Container bleiben gesperrt. `execution_receipt_missing` bedeutet fehlende dauerhafte
Befehlsbestätigung, `execution_evidence_incomplete` einen unzureichenden Zustands-/Transitionsnachweis.
Neuen Key, manuelle SQL-Erfolgsmarkierung oder Journallöschung nicht als Reparatur verwenden.
Ein leeres Journal kann vorhandene Runtime nicht übernehmen. Host-/Dockeradministratoren
müssen außerhalb des Adaptervertrags vorgenommene Änderungen gesondert untersuchen.

Adapterupdate von Journal 2 auf 3 benötigt eine kontrollierte Wartung und explizite
Journalmigration (derselbe `adapter-migrate`-Dienst im Runtime-Overlay). Keine Anwendung
alter Adapterversionen auf das neue Journal. Bestehende Plan-/Operationsdaten bleiben
erhalten; alte unklare Operationen ohne Beleg bleiben unklar. Die Basis-Upgrade- und
Backupskripte sind weiterhin **kein** koordinierter Runtime-Wartungs-/Restoreweg.

Der reale Fehlertest verwendet ausschließlich wegwerfbare CI-Container. Sein
`tests/notes-faults.compose.yaml` und der dort gemountete Prozess-Faultentrypoint gehören
**nicht** zur Zielhost-Konfiguration. Produktionsstart verwendet nur die beiden Dateien
`compose.yaml` und `runtime.yaml` aus `infrastructure/compose/`.
