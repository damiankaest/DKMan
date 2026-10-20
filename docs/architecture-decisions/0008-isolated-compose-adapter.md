# ADR 0008 · Isolierter Compose-Adapter

Status: angenommen; Implementierung P2-002. Baut auf ADR 0003/0006/0007 auf.

Der Docker-Socket liegt ausschließlich im eigenständigen Deployment-Adapter. Der
reguläre Stack und sein Bootstrap bleiben unverändert; ein separates Compose-Projekt
ist explizit vorzubereiten und zu starten. Kein veröffentlichter Adapterport und keine
Proxyroute. Core erhält einen typisierten HTTP-Client ohne Docker-/Subprozesszugriff.
Die Core-Job-API nimmt weiterhin nur Manifestvalidierung an; Integration folgt P2-004.

Der Adapter akzeptiert ausschließlich typisierte Pläne aus einem eigenen kuratierten
Katalog. Standardkatalog leer. Nur unveränderliche Registry-Digests oder tatsächlich
gebaute lokale Image-IDs. Registrierung eines Manifests ist keine Kuration. Ressourcen,
Nutzer und persistenter Containerpfad müssen exakt der geprüften Katalogrevision entsprechen.
Keine freien Befehle, Environments, Hostpfade, Ports, Compose-Dateien oder Netzwerke.

Compose wird serverseitig als JSON generiert: Non-root, read-only, alle Capabilities
entzogen, no-new-privileges, Ressourcen-/PID-Limits, begrenzte Logs, interne Netzwerke
und höchstens ein benanntes Datenvolume. Images müssen diesen Nutzer, eine vorhandene
CMD-Healthprüfung und den zulässigen Volumevertrag erfüllen. Keine erfundene Health.
CLI-Aufrufe verwenden feste Argumentlisten, expliziten lokalen Socket, bereinigtes
Environment und keine Shell. CLI und Compose stammen aus einem digestgepinnten Image.

Authentifizierung: maximal 60 Sekunden gültige HS256-Delegation vom Core mit eigener
Issuer/Audience und zufälligem Secret. Bindung an Operation-ID (= spätere Job-ID),
Subject, Rollen, Aktion, Installations-ID und Plan-Hash. Jede Mutation verlangt außerdem
Approval-ID und Ablauf; Datenlöschung ist eine eigene Aktion. Keine Benutzer-OIDC-Tokens
oder allgemeinen API-Keys als Ersatz. Ein späterer Core-Aufrufer muss zuerst seine
OIDC-/Ressourcenrechte prüfen und die konkrete persistierte Freigabe verbrauchen.
Es gibt keinen HTTP-Endpunkt zum Ausstellen von Delegationen.

Eigenes SQLite-Operationsjournal im persistenten Adaptervolume, explizite SQL-Migration
und unabhängige Revision 2 (0001 Operationsjournal, 0002 einmalige Approvals).
Keine Erweiterung der Core-Migrationen oder gemeinsamen
DB-Schreibrechte. SQLite-Transaktionen und OS-Dateisperren serialisieren Installationen
über Threads und Prozesse. Operation-ID/Fingerprint verhindert doppelte Ausführung.
Der Marker `running` wird vor dem ersten mutierenden Provideraufruf dauerhaft gespeichert.
Approval-IDs werden in derselben Transaktion einmalig an eine Operation gebunden;
auch eine neu signierte Delegation kann sie nicht für eine zweite Operation verwenden.

Nach Timeout, Fehler oder verwaistem Marker: `reconciliation_required`; die Ressource
bleibt auch für andere Operation-IDs gesperrt. Startup/periodischer Abgleich respektiert
die Sperre noch aktiver Worker. Es gibt keinen Leasewechsel, der einen alten externen
Dockeraufruf parallel zu einer neuen Mutation weiterlaufen ließe. Reconcile liefert
tatsächliche Beobachtungen und hebt die Sperre nicht ohne beweisbaren Abschluss auf.
Kein Erfolgs-/Force-Retry-Endpunkt. Bestätigter Wiederanlauf folgt als eigener Workflow.

Containernetzwerke/-volumes und Projekte müssen eindeutig DKMan und einer bereits
bekannten Installation zugeordnet sein; fremde oder nur vermeintlich eigene Kollisionen
werden abgelehnt. Remove erhält Daten; Remove-Data verlangt abgebauten Workload und
eigene Freigabe. Keine Prune-, Remove-Orphans- oder Down-Volumes-Operation.

Docker bleibt eine privilegierte Hostgrenze. Dieser Adapter begrenzt seine API, ersetzt
aber keine Hostisolation. Zielhostaktivierung bleibt offen. Details: [Deployment-Adapter](../deployment-adapter.md).
Grundlagen: [Compose up](https://docs.docker.com/reference/cli/docker/compose/up/),
[Compose-Modell](https://docs.docker.com/compose/intro/compose-application-model/),
[offizielles CLI-Image](https://github.com/docker-library/docker/blob/master/29/cli/Dockerfile).
