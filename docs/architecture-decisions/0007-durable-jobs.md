# ADR 0007 · Persistente Jobs, Freigaben und Recovery

Status: angenommen; P2-001 implementiert. Ergänzt ADR 0001 und 0006.

PostgreSQL ist die transaktionale Queue des modularen Core. `Job`, `JobEvent` und
`ApprovalRequest` folgen mit Alembic `0002_durable_jobs`. Kein zusätzlicher Broker
oder verteiltes Workflowframework für den ersten einzelnen Auftrag.

Unique Constraint auf `(requested_by, idempotency_key)`: identischer kanonischer
Request liefert denselben Job; anderer Inhalt 409. Schlüssel bleiben nach Fehler
und Abbruch gebunden. Zustand, sequenziertes Event, Approval und Audit werden
gemeinsam committed. Zeilensperren am Job serialisieren Entscheidung, Abbruch,
Claim, Ausführungsbeginn und Abschluss. Sperrreihenfolge immer Job vor Approval.
Recovery überspringt gesperrte Zeilen mit `SKIP LOCKED`.

Pläne entstehen serverseitig. SHA-256 über JSON mit sortierten Schlüsseln, kompakten
Separatoren, ASCII-Escaping, ohne NaN. Der versionierte Plan enthält Aktion,
Ressourcentyp/-ID, anforderndes OIDC-Subject und Manifest-Snapshot als ID plus Hash.
Freigaben speichern diese Bindung, Ablauf, entscheidendes Subject und Verbrauch.
Die Entscheidung wiederholt die vollständige Bindung. Vor Ausführung erneut prüfen
und einmalig verbrauchen. Nur die implementierte lesende Aktion kann ohne Approval
angelegt werden; sie verlangt es standardmäßig trotzdem.

Claims erhalten eine private 60-Sekunden-Lease mit zufälligem Token. Erst ein separat
committeter `running`-Marker erlaubt einen Aktionsaufruf. Nach Leaseverlust wird kein
Abschluss des alten Workers akzeptiert. Vor dem Marker ist erneutes Bereitstellen
sicher; danach ausschließlich `reconciliation_required`, kein automatischer Retry.
Ein neuer Coreprozess respektiert noch gültige Leases anderer Prozesse.

Startup und alle 15 Sekunden: ausschließlich Metadaten-Recovery, höchstens 100 Jobs
pro Durchlauf. DB-Ausfälle ohne SQL-/Exceptioninhalt melden; Readiness verlangt die
neue Revision. Events über begrenztes Cursor-Polling statt SSE: ohne zusätzliche
Langzeitverbindung und nach Verbindungsverlust über Sequenznummer fortsetzbar.

Erster echter Executor: `registry.validate` prüft erneut das gespeicherte Manifest,
ohne URL-Abfragen oder Imageausführung. Admins legen Jobs an, entscheiden und brechen
ab. `/run` verlangt außerdem dasselbe anfordernde Subject mit aktuell geprüfter
Adminrolle. Keine frei wählbare Aktion, kein freier Plan und kein Status-Patch.

P2-002 muss Runtimeaktionen erst mit typisiertem Planner und isoliertem Adapter
registrieren. Sensible/destruktive Aktionen erzwingen Approval. Der Adapter braucht
Ressourcenserialisierung, dauerhafte Operation-ID (= Job-ID), Fencing/Abgleich und
Laufzeitgrenzen bzw. Leaseerneuerung. Core-Leasetokens allein verhindern keine
bereits laufende externe Dockeroperation. Unsichere Jobs bleiben ohne belegbaren
Abgleich gesperrt; kein generischer Retry-/Erfolgsbutton.

Grundlagen: [PostgreSQL SELECT/Zeilensperren](https://www.postgresql.org/docs/17/sql-select.html),
[SQLAlchemy Transaktionen](https://docs.sqlalchemy.org/en/21/orm/session_transaction.html).
Eigener Vertrag: [Jobs und Freigaben](../jobs.md).
