# ADR 0011 · Belegter Abschluss unsicherer Runtimeoperationen

Status: angenommen; P2-006. Ergänzt ADR 0007–0010.

Ein Abgleich darf keine Dockeraktion wiederholen. Er kann ausschließlich das Ergebnis
bereits autorisierter Ausführung belegen. Die aktuelle Health allein reicht insbesondere
für Restart nicht. Auch eine fehlende Operation ist kein Beleg, dass nichts ausgeführt wurde.

Der Adapter speichert nach erfolgreicher Rückkehr des konkreten Composebefehls einen
unveränderlichen Enginebeleg in einer eigenen FULL-synchronen SQLite-Transaktion,
vor der finalen Operationsantwort. Neue explizite Journalmigration 0003 ergänzt nur
`execution_receipts`; bestehende Migrationen, Command-/Planhashes und Fingerprints bleiben
unverändert. Core bleibt auf Alembicrevision 0003. Alte Operationsresultate bleiben lesbar.
Alte unklare Operationen ohne Beleg erhalten durch das Upgrade keinen erfundenen Nachweis.

Der Beleg bindet Operation, Aktion, Installation, vollständigen Commandhash, die unmittelbar
vor dem Composebefehl gemessenen Container und den Zeitpunkt seiner erfolgreichen Rückkehr.
Persistiert werden nur Dienst, Container-/Image-ID, Runtimeplanhash, Status/Health,
Start-/Endzeit und Volumenname. Keine vollständigen Inspect-Daten, Environments oder Logs.
Eine SHA-256-Prüfsumme erkennt Beschädigung; sie ersetzt nicht die vertrauenswürdige
Adapter-/Enginegrenze und schützt nicht vor einem böswilligen Docker-/Hostadministrator.

`POST /v1/operations/{id}/reconcile` ist ein Metadatenabschluss mit kurzlebiger, exakt
gebundener `reconcile`-Delegation des ursprünglichen Subjects. Er erwirbt dieselbe exklusive
Ressourcensperre wie Ausführung und respektiert aktive Worker. Er verwendet ausschließlich
Preflight/Inspect, niemals Start/Stop/Restart. Der alte GET bleibt beobachtend kompatibel.
Originalkommando und dauerhafter Beleg werden gelesen und erneut gebunden. Alle erwarteten
Container müssen vorhanden, plan-/image-/volumengetreu und im passenden Zustand sein.
Lifecycle verlangt dieselben Container wie vor Ausführung. Restart verlangt für **jeden**
Container einen erhöhten Startzeitpunkt im belegten Ausführungsintervall. Stop verlangt
gestoppte Container mit passender Transition; Start erlaubt einen belegten No-op für
bereits laufende Container. Spätere ungeklärte Starts/Rekreationen reichen nicht.

Nur ein vollständiger Nachweis ändert atomar die ursprüngliche Operation auf `succeeded`
und löst genau deren Ressourcensperre. Core prüft denselben Beleg nochmals, bindet den
Operationsabschluss an seinen Job und speichert Nachweisart/-hash im Ergebnis. Job/Event/
Audit bleiben transaktional. Aktuelle Rollen und Ressourcenrechte werden vor und nach
externem I/O geprüft. Keine neue Freigabe für diese reine Beobachtung/Metadatenauflösung;
die ursprünglich ausgeführte Mutation besitzt bereits ihre verbrauchte Freigabe.

Kuration oder lesender Preflight können eine Ausführung nachweislich verhindern. Für
Install/Start/Stop/Restart persistiert der Adapter dann ein gebundenes `failed`-Resultat
mit `preflight_rejected`-Nachweis und festem Fehlercode. Keine Provider-Mutation und keine
Ressourcensperre werden angelegt/gelöst. Core akzeptiert ausschließlich diese konkrete
Nichtausführungsbindung; HTTP-Fehlertexte oder 404 können keine Jobs entsperren.

Crash vor dem Enginebeleg, verlorenes Journal, abweichende Identität/Zeiten, fehlende
Sidecars, Timeout ohne erfolgreiche Befehlsrückkehr oder unvollständige Health bleiben
`reconciliation_required`. Codes `execution_receipt_missing` und
`execution_evidence_incomplete` erklären die Beleggrenze. Kein Force-Success, generischer
Unblock, neuer Idempotency-Key oder Retry. Auch gesunde Container bleiben in diesem Fall
für weitere Mutationen reserviert. Koordinierter Restore/Hostbetrieb bleiben eigene Gates.

Verifikation: Unit-/API-/Migrations-/Konkurrenztests sowie echte CI-Fehlermatrix mit
Keycloak, PostgreSQL, Notes und gezielten Prozessabbrüchen ausschließlich durch einen
separat gemounteten Testentrypoint. Keine Produktionsfaultschalter oder Testantworten.
Enginefeldvertrag: https://docs.docker.com/reference/api/engine/version/v1.56/ ;
Compose: https://docs.docker.com/reference/cli/docker/compose/restart/ .
