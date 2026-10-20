# ADR 0009 · Kuratierte Notes-App und Installation über den Hub

Status: Implementierung P2-003/P2-004, abschließende CI-Abnahme ausstehend.

Notes ist eine eigenständige Quellapp mit eigener PostgreSQL-17-Instanz, eigener
eingeschränkter Loginrolle und expliziter, transaktionaler Migration. Keine Appdaten
in Core- oder Identitytabellen. Ein fest geprüftes Profil `notes-postgres-v1` erweitert
den Adapter um genau diesen Sidecar; es gibt weiterhin keine freien Befehle,
Umgebungsvariablen, Hostmounts, Ports oder Netzwerke aus einem Request.

Beide Images laufen als 10001:10001, read-only, mit Ressourcenlimits und echten
CMD-Healthprüfungen. Nur die Datenbank besitzt ein persistentes Datenvolume und ein
privates Netzwerk zur App. Nur die App wird zusätzlich an das interne Gatewaynetz
angeschlossen. Der Adapter prüft Netzwerkeigentum und tatsächliche Image-/Quellhashes.

Der explizite Build liest die geprüften Quellen/Lockfiles, baut beide Images und
erfasst ihre tatsächlichen lokalen SHA-256-Image-IDs. Der kuratierte Katalog enthält
keinen Platzhaltertag. Kein externer Registry-Push; auf einem anderen Linux-Builder
ist ein eigener bestätigter Build erforderlich. Der CI-Nachweis wird als Artefakt
aufbewahrt. Ein registriertes Beispielmanifest bleibt reine Beschreibung und kann
keine Kuration ersetzen. Ausgeführt wird ausschließlich der kuratierte Plan.

Core reserviert pro Haushalt/Definition einen noch nicht abgeschlossenen Plan in
`deployment_targets` (Migration 0003). Der Haushaltlock serialisiert auch verschiedene
Idempotency-Keys. Ein Plan enthält Image-/Quellrevision, Ressourcen, Installations-ID,
Haushalt, Subject und Manifestrevision/-hash. Derselbe vollständige Hash bindet Job,
Approval und Adapterdelegation. Eine Reservierung erzeugt noch keine Appinstallation.

Nach erneutem Berechtigungs-/Kurationscheck verbraucht Core die Freigabe und schreibt
den dauerhaften Ausführungsmarker vor dem HTTP-Aufruf. Job-ID = Adapter-Operation-ID.
Einzig ein passendes abgeschlossenes Adapterergebnis mit real gemessener gesunder
Runtime materialisiert Installation/Service/Health. Bei Transportverlust oder Crash
bleibt der Ausgang unklar. Reconcile liest dieselbe Operation; kein erneutes Install.
Ein gesund beobachteter Container allein ist kein Beweis für einen abgeschlossenen Job.

Der interne Delegationsschlüssel liegt nur bei Core und Adapter. Ein **getrennter**
Datenschlüssel liegt ausschließlich beim Adapter; domänengetrennte HMACs erzeugen
stabile eigene App-/DB-Adminpasswörter. Die App erhält nur ihre eingeschränkten
DB-Zugangsdaten. Passwörter stehen ausschließlich in der geschützten Runtime-
Konfiguration/Containerumgebung, nie in Plan, Git, API oder Browser. Dockeradministratoren
können sie sehen; Docker bleibt eine privilegierte Trust Boundary. Schlüsselrotation
erfordert eine koordinierte DB-Migration und ist kein automatischer Reparaturversuch.

Der Proxy routet ausschließlich UUID-abgeleitete interne DNS-Namen auf Port 8080.
Keine dynamischen Host-/Portparameter. Notes nutzt `keycloak-js` mit eigenem öffentlichen
OIDC-Client, Code/PKCE und Tokens nur im Speicher. Die leere HTML-/Assetoberfläche
enthält keine Nutzerdaten; jede Daten-API fragt mit dem echten Bearer-Token den Core
nach aktuellen `app.use`-Rechten. Ein bekannter Direktlink umgeht weder OIDC noch
Widerruf. Core ist die Autorisierungsinstanz, kein eigener Identity-Provider.
Der Hub prüft nach Reload mit dem offiziellen Adapter die bestehende OIDC-Sitzung;
Refresh oder Rückkehr von Notes benötigt keine gespeicherten Browsertokens.

Read-only-Polling speichert gemessenen Status und Historie. Nach 45 Sekunden ohne
frische Messung zeigt der Hub `unknown` und keinen Öffnen-Link. Die Runtime-Erweiterung
ist ein explizites Compose-Overlay; der bisherige Bootstrap aktiviert sie nicht.

Zielhost-, Windows-/VM-Neustart- und koordinierte Restoreabnahmen bleiben offen.
Bestehende Realmimporte werden nicht automatisch überschrieben: der neue OIDC-Client
ist dort vor Aktivierung ausdrücklich über Keycloak einzurichten.
