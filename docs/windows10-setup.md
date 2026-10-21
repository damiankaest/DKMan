# Windows 10 → Linux-Container

Diese Sitzung hat deinen Windows-Rechner nicht geprüft oder verändert. Der
Stackstart ist eine ausstehende Abnahme. Alle Befehle aus dem Projektwurzelverzeichnis
ausführen. Standardport 8080, keine öffentliche Freigabe.

## 1. Nur prüfen

In Windows PowerShell 5.1 oder neuer:

```powershell
.\scripts\windows\preflight.ps1 -Json
.\scripts\windows\setup.ps1 -Mode server-linux-vm
```

Falls deine Execution Policy das Skript blockiert: erst Datei lesen und Herkunft
prüfen, dann bei Bedarf `Unblock-File .\scripts\windows\preflight.ps1` gezielt für
diese Datei. Keine globale Execution Policy abschalten. Featureabfragen können
ohne Adminrechte `unknown` liefern; ggf. Preflight administrativ wiederholen.
Vorhandene Dienste und belegte Ports unverändert lassen.

## 2. Laufzeit auswählen

| Variante | Einsatz | Grenzen |
| --- | --- | --- |
| Ubuntu-VM | empfohlen für Dauerbetrieb | Virtualisierung, Edition, freier RAM/Disk und VM-Autostart prüfen |
| Ubuntu unter WSL2 | Entwicklung/erster Versuch | Windows-Login, WSL-Shutdown, Hostreboot und Netzwerk ausdrücklich testen |

Hyper-V ist auf unterstützten Pro-/Enterprise-Editionen und geeigneter Hardware
verfügbar, nicht auf Windows 10 Home. WSL2 kann auch auf Home verwendet werden.
Bei fehlendem Hyper-V eine kompatible VM-Lösung nach Herstelleranleitung wählen.
Empfehlung für diese Plattform: Ubuntu 24.04 LTS, 4 vCPU, 6 GB RAM und 40 GB Disk.
Nicht als bereits geprüfte Anforderung deines Hosts verstehen.

Das Setup erstellt keine VM und installiert weder Docker Desktop noch fremde
VM-Software. WSL-Voraussetzungen können nach Lesen des Plans explizit aktiviert
werden, mit administrativer PowerShell und manueller Bestätigung:

```powershell
.\scripts\windows\setup.ps1 -Mode dev-wsl2 -PrepareWslFeatures -Apply -Confirm
```

Kein automatischer Neustart. Danach WSL2/Ubuntu nach Microsoft-Anleitung einrichten
und `wsl --list --verbose` auf Version 2 prüfen. Rollback der Windows-Features nur
nach Prüfung anderer Nutzer: `Disable-WindowsOptionalFeature -Online -FeatureName
Microsoft-Windows-Subsystem-Linux -NoRestart` bzw. `VirtualMachinePlatform`.
Dadurch könnten andere WSL-Workloads unbenutzbar werden; nie automatisch ausführen.

## 3. Linux vorbereiten

In Ubuntu Docker Engine und Compose-Plugin nach offizieller Docker-Anleitung
installieren. Dies ist eine gesonderte Hostinstallation und wird vom Bootstrap
nicht ausgeführt. Python 3, Git und curl müssen ebenfalls vorhanden sein.
Dockerberechtigung prüfen; Mitgliedschaft in der Dockergruppe entspricht weitgehend
Rootrechten. Nicht pauschal jedem Haushaltsnutzer gewähren.

```bash
docker version
docker info --format '{{.OSType}}'   # muss linux sein
docker compose version              # v2.24+ oder kompatibles neueres Compose
python3 --version
curl --version
git --version
```

Projekt innerhalb des Linux-Dateisystems ablegen, unter WSL z. B. `~/DKMan`,
nicht auf `/mnt/c`. `.local/` schützt Secretdateien durch POSIX-Verzeichnisrechte;
auf Windowslaufwerken sind diese Rechte nicht zuverlässig abgebildet.

## 4. Plan lesen und starten

```bash
cd ~/DKMan
bash scripts/linux/bootstrap.sh --dry-run
bash scripts/linux/bootstrap.sh --apply
```

`--apply` verlangt die Eingabe `INSTALL`. Der Bootstrap generiert `.env`, getrennte
zufällige Secrets und einen Realm, validiert Compose, baut Images, migriert und
startet nur den DKMan-Stack. Containerdownloads brauchen Netzwerkzugriff auf die
gepinnten Registries. Erststart kann mehrere Minuten dauern. Er schreibt keine
Passwörter in die Konsole. Bei Fehlern bleiben Daten/Container zur Diagnose bestehen.

Der Hub erscheint unter http://localhost:8080. Die erste Anmeldung erfolgt als
`platform-admin`; das zufällige temporäre Passwort steht in
`.local/initial-credentials.txt`. Beim ersten Login neues Passwort setzen. Für
Nutzerverwaltung: http://localhost:8080/auth/admin/ mit `bootstrap-admin`; dessen
Passwort steht in `.local/secrets/keycloak-admin-password`. Nach Einrichtung
Bootstrapkonto entfernen/deaktivieren. Keine produktiven Standardpasswörter in Git.

Bei einer VM erreicht Windows deren Loopback nicht direkt. Zunächst einen sicheren
SSH-Tunnel nutzen, wenn OpenSSH in der VM bereits bewusst eingerichtet wurde:

```powershell
ssh -N -L 8080:127.0.0.1:8080 <linux-user>@<vm-ip>
```

Dann in Windows http://localhost:8080 öffnen. Der Origin muss exakt `localhost:8080`
bleiben, damit Issuer/PKCE-Redirects passen. In WSL ist localhost-Weiterleitung
abhängig von der Hostkonfiguration zu prüfen. Kein `netsh portproxy`- oder
Firewall-Automatismus. Kein Routerportforwarding.

## 5. Abnahme und Neustart

```bash
bash scripts/linux/doctor.sh
```

Danach manuell Login, Logout und Registryansicht testen. Ausgelieferte UI zeigt
Notes erst nach bewusster Runtime-Aktivierung und genehmigter Hubinstallation.
Docker-Daemon und VM-Autostart auf dem realen Host gesondert einrichten und prüfen.
`restart: unless-stopped` startet Container erst bei laufender Linux-Docker-Engine;
es startet weder Windows, VM noch WSL. Nach bewusstem `compose stop` erneut `up -d`.

Für weitere Geräte TLS und kontrollierten Heimnetz-/VPN-Zugang samt neuem
Issuer/Redirect-Origin planen. Aktuelles HTTP-Realm und Loopback-Binding sind keine
Abnahme für LAN-/Internetbetrieb. Windows 10s regulärer Support ist beendet;
Wartung/ESU bzw. spätere unterstützte Hostplattform eigenständig vorsehen.

## Primärquellen

- https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/install-hyper-v
- https://learn.microsoft.com/en-us/windows/wsl/faq
- https://learn.microsoft.com/en-us/windows/wsl/install
- https://docs.docker.com/engine/install/ubuntu/
- https://docs.docker.com/compose/install/linux/
- https://www.keycloak.org/server/hostname
- https://www.keycloak.org/server/reverseproxy

## Heutiger Einstieg: erst Hostabnahme, dann Notes

Den Windows-Rechner kannst du bereits für Schritt 1 (lesender Preflight) starten.
Für Änderungen zuerst Ausgabe, freie Ressourcen, vorhandene Dienste und gewählte Linux-
VM prüfen. Keine bestehende Minecraft-Umgebung übernehmen oder Ports freiräumen. Der
Zeitpunkt für den Stackstart ist **nach grüner P2-006-Main-CI und dieser Hostprüfung**;
der Entwicklungsabschluss ist keine bereits ausgeführte Windows-/VM-Abnahme.

In einer eigens dafür freigegebenen Ubuntu-VM den aktuellen geprüften `main` über deine
GitHub-Berechtigung klonen. Keine Tokens in Befehlszeilen oder Ausgaben teilen. Basisstack
zunächst wie in Schritt 4 starten, Doctor/Erstlogin/Passwortwechsel durchführen. Für den
Notes-Quellbuild zusätzlich `uv` nach offizieller Anleitung bereitstellen und im Checkout
`uv sync --frozen` ausführen. Keine alten CI-Image-IDs als Registryreferenzen verwenden.

Danach die in [Notes](notes.md) dokumentierten Dry-runs für Adapterkonfiguration und
Quellbuild lesen. Mit eigener Freigabe die dort genannten `ADAPTER_CONFIG`-/`BUILD_NOTES`-
Befehle ausführen. Beim frischen Realm ist der Notes-OIDC-Client bereits enthalten; bei
vorhandenem Realm zuerst die dokumentierte Clientkonfiguration prüfen. Erst dann:

```bash
export DKMAN_DOCKER_SOCKET_GID=$(stat -c '%g' /var/run/docker.sock)
docker compose -p dkman --env-file .env -f infrastructure/compose/compose.yaml -f infrastructure/compose/runtime.yaml config --quiet
# Nur im freigegebenen isolierten Testsystem nach Lesen des Plans:
docker compose -p dkman --env-file .env -f infrastructure/compose/compose.yaml -f infrastructure/compose/runtime.yaml up -d --build --wait --wait-timeout 300
bash scripts/linux/doctor.sh
```

Diese genaue Produktions-Dateiauswahl hat keine CI-Faultsteuerung. Sie migriert ein
frisches Adapterjournal explizit über `adapter-migrate`; vorhandene Runtime benötigt den
kontrollierten Wartungsablauf aus [operations.md](operations.md). Im Hub Notes planen,
konkret freigeben, installieren, öffnen, Testnotiz anlegen und Stop/Start/Restart prüfen.
Danach VM-/Windows-Neustart/Autostart und echten Mehrbenutzerbetrieb abnehmen. Bis zum
koordinierten Runtime-Backup/Restore ausschließlich entbehrliche Testdaten einsetzen;
die bisherigen Backups sichern Notesdaten und Adapterjournal weiterhin nicht vollständig.
