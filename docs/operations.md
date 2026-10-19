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

## GitHub-Übergabe

GitHub-Verbindung ist vorhanden, bietet in dieser Sitzung aber keine Funktion
zum Erstellen eines Repositories. Es wurde kein entferntes DKMan-Repo erstellt
und nichts gepusht. Der lokale Git-Verlauf wird als Bundle mit dem Quellpaket
übergeben. Nach privater Repoerstellung kann der Eigentümer pushen:

```bash
git remote add origin https://github.com/damiankaest/DKMan.git
git push -u origin main
```

Falls das Paket ohne `.git` entpackt wurde: Bundle neben `DKMan/` nutzen:
`git clone DKMan-history.bundle DKMan-git`, danach in diesem Checkout arbeiten.
Alternativ nach Entpacken `git init -b main` und den gelieferten Quellstand committen.
Kein Remote ist als bereits existent anzunehmen; neues Repository privat anlegen.
