# ADR 0015 · Signierte Forge-Nachweise und getrennte Preview

Status: P4-003 in Arbeit. Implementierung und Teststand stehen in `progress.md`;
Vorschau-Nachweise sind noch keine Installationsfreigabe.

Der Core erhält signierte Buildnachweise, niemals das OCI-Archiv oder einen Docker-
Socket. Ein Ed25519-Schlüssel auf dem isolierten Builder signiert Quellstand, Plan,
Buildrezepte, durchgeführte Checks, OCI-Manifest-/Konfigurations-Digest und Archivhash.
Core akzeptiert sie nur bei unverändertem, aktuellem, freigegebenem Plan und prüft
Signatur, Schlüssel, Rezept, Inhalt und aktuelle Benutzerrechte. Dieselbe Build-ID
ist idempotent; abweichende Daten werden abgelehnt. Der Betreiberschlüssel ist eine
Vertrauensannahme und keine kryptografische Garantie gegen einen kompromittierten
Builder. Das Archiv muss vor jeder Verwendung unabhängig gegen den Nachweis geprüft
werden.

Ein eigener Preview-Adapter wird manuell auf einer dedizierten, isolierten Linux-VM
ausgeführt. Er akzeptiert ausschließlich die drei unveränderten Startervorlagen und prüft erneut den
signierten Build, den aktuellen Plan, die Core-Registrierung und das OCI-Archiv, lädt
das Image auf der separaten Engine und startet es ohne Produktionssecrets, Volumes
oder Produktionsnetzwerk. Das Netzwerk ist intern; es gibt keine Docker-Portfreigabe.
Ein Forwarder bindet auf der VM an Loopback und leitet ausschließlich an die geprüfte
Adresse des Preview-Containers weiter;
Prozess-, CPU- und Speichergrenzen sowie Read-only und Capability-Entzug sind fest.
Ein Docker-Netzwerk ersetzt keine VM-Isolation; die Bestätigung durch den Betreiber
und die Einrichtung der getrennten Maschine sind Voraussetzungen. Für API- und
Fullstack-Previews wird eine SQLite-Testdatenbank in einem begrenzten tmpfs angelegt;
die fest vorgegebene Startermigration läuft im Container. Mit dessen Entfernung sind
die Testdaten verschwunden.

Nach tatsächlich gemessener HTTP-Readiness signiert die Preview-VM mit einem vom
Buildschlüssel getrennten Schlüssel einen auf Build, Quellstand und Container-ID
gebundenen, höchstens 15 Minuten gültigen Beobachtungsnachweis. Core prüft ihn und
den Plan erneut. Er ist eine historische Messung, keine aktuelle Healthanzeige,
kein Beweis, dass ein Mensch die Preview inhaltlich abgenommen hat, und keine
Deploymentfreigabe. Die Preview läuft nur während des begrenzten CLI-Aufrufs;
bei hartem Prozessabbruch können eigene Ressourcen zurückbleiben und müssen mit dem
gezielten Cleanup-Befehl entfernt werden. Es gibt keinen globalen Docker-Prune.

Noch offen für P4-003: sichere Übernahme des Archivs zur produktiven Adaptergrenze,
ein expliziter previewgebundener Genehmigungs-/Installationsplan, dieselbe bestehende
Deployment- und Recovery-Zustandsmaschine, Darstellung im Hub sowie ein Update als
neue Revision. Keine automatische Bereitstellung oder Freigabe durch die Nachweise.
