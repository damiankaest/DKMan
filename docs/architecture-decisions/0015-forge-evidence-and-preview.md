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

Für die unveränderte React-SPA-Vorlage nimmt ein separater Operatorhelfer ein geprüftes
Archiv in ein privates Adapter-Staging auf; der Helfer hat selbst keinen Docker-Socket.
Der bestehende Deployment-Adapter prüft beide Signaturen, die Archiv-Digests und die
feste, volumenlose Laufzeitkonfiguration erneut. Der Core bindet eine separate,
kurzlebige Freigabe an Vorschau, Image, Haushalt und konkreten Installationsplan.
Nur nach dieser Freigabe darf der Adapter das Image laden und den Container starten.
Der Hub zeigt ausschließlich einen tatsächlich nachgewiesenen Abschluss an.

Eine spätere Planrevision benötigt einen neuen Build, eine neue Preview und eine
eigene Updatefreigabe. Der Updateplan bindet die alte und neue Laufzeit an dieselbe
Installation; ein Enginebeleg muss den Wechsel auf einen neuen gesunden Container
beweisen. Der alte Manifest-/Jobstand bleibt erhalten. Unbekannte Ergebnisse sperren
weitere Mutationen bis zu einem belegten Abgleich, ohne automatischen Retry oder
Rollback. Das Staging und die CI-Journey erfordern ausdrücklich eingerichtete
Vertrauensschlüssel und isolierte Arbeitsumgebungen. API-/Fullstack-Vorlagen bleiben
zunächst auf Preview beschränkt; Zielhostabnahme und Rollback bleiben offen.
