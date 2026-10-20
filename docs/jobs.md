# Jobs und Freigaben · P2-001

`registry.validate` prüft eine registrierte Manifestrevision erneut; ihr Erfolg
bedeutet **Manifest gültig**. Seit P2-004 existiert zusätzlich `deployment.install`
mit eigenem typisierten Planner, isoliertem Adapter und Hub-Oberfläche. Die folgenden
Grundregeln gelten für beide Aktionen; Installationsbesonderheiten stehen unten.

## API und Rechte

| Route unter `/api/v1` | Zugriff und Verhalten |
| --- | --- |
| `POST /jobs` | Admin; `Idempotency-Key` Pflicht; 202 mit `Location` und persistiertem Job |
| `GET /jobs` | eigene Jobs, Admin alle; `limit` 1–100 |
| `GET /jobs/{id}` | eigenes Subject oder Admin; fremd/unbekannt 404 |
| `GET /jobs/{id}/events` | gleiche Sichtbarkeit; `after` ab 0, `limit` 1–200; aufsteigende Sequenz |
| `GET /jobs/{id}/approval` | gleiche Sichtbarkeit; 404 bei Job ohne Approval |
| `POST /approvals/{id}/decision` | Admin; vollständige erwartete Bindung plus `approve`/`reject` |
| `POST /jobs/{id}/run` | aktueller Admin und anforderndes Subject; Executor passend zum gespeicherten Plan |
| `POST /jobs/{id}/cancel` | Admin; nur vor Claim; wiederholter Abbruch idempotent |

Anlagebeispiel (JSON-Body):

```json
{
  "action": "registry.validate",
  "resource_id": "demo-notes",
  "require_approval": true,
  "approval_ttl_seconds": 900
}
```

Kein freier Plan, Shelltext oder frei gesetztes Risiko im Request. Die Aktionspolicy
liegt im Code. `require_approval=false` gilt nur für die implementierte
`read_only`-Aktion; neue Aktionen brauchen einen eigenen typisierten Planner.

Vor Entscheidung `GET .../approval` lesen. `subject`, `action`, `resource_type`,
`resource_id`, `plan_hash` und `expires_at` unverändert mit `decision` zurückgeben.
Auch Admins können keinen anderen Plan oder ein längeres Ablaufdatum einschleusen.
TTL 60–3600 Sekunden beginnt bei Anlage, nicht bei Zustimmung. Die exakte wiederholte
Entscheidung derselben Person erzeugt kein neues Event und verlängert keine Frist.
Gegenentscheidungen, verbrauchte oder abgelaufene Freigaben: 409. Ablauf wird bei
Entscheidung/Ausführung sofort geprüft; Lesezustände werden spätestens beim nächsten
Recoverydurchlauf aktualisiert.

Ohne Token 401, unzureichende Rolle 403, ungültiger Body/Header 422. DB-Fehler:
bereinigtes 503. Worker-Leases, Idempotency-Keys und Request-Fingerprints werden
nicht in Jobantworten ausgegeben. Fremde Jobdetails, Approvals und Events bleiben 404.

## Zustände und Transaktionsgrenzen

| Ausgang | Ereignis | Ziel |
| --- | --- | --- |
| neu | Anlage mit Approval | `waiting_approval` |
| neu | lesende Aktion ohne Approval | `queued` |
| `waiting_approval` | passende, gültige Zustimmung | `queued` |
| `waiting_approval` | Ablehnung | `cancelled` |
| `waiting_approval` / `queued` | Adminabbruch | `cancelled` |
| vor Ausführung | Ablauf der Freigabe | `expired` |
| `queued` | exklusiver Claim, private Lease | `claimed` |
| `claimed` | Bindung/Lease prüfen, Approval verbrauchen, Marker committen | `running` |
| `claimed` | ungültige Freigabe/Planbindung | `failed` |
| `running` | tatsächliche Manifestprüfung erfolgreich | `succeeded` |
| `running` | bekannter Validierungsfehler/veränderter Snapshot | `failed` |
| `claimed` | Lease abgelaufen, kein Ausführungsmarker, Approval gültig | `queued` |
| `running` | Lease abgelaufen oder unerwarteter Aktionsfehler | `reconciliation_required` |

Terminale Jobs werden nicht zurückgesetzt. `reconciliation_required` kann weder
ausgeführt noch über den Abbruchendpunkt als erledigt deklariert werden. Keine
automatische Ausführung wartender Jobs: der Admin löst `/run` für die echte
Aktion aus. Nur Metadaten-Recovery läuft automatisch beim Start und alle
15 Sekunden, höchstens 100 Jobs pro Durchlauf und ohne Aktionsaufrufe.

Idempotenz gilt pro OIDC-Subject für die Lebensdauer des Jobs. Identischer Request
mit demselben Schlüssel liefert denselben Job im aktuellen Zustand, auch nach
Neustart/Abbruch/Fehler. Andere Ressource, Approvalwahl oder TTL mit demselben Schlüssel:
409. Andere Schlüssel bezeichnen neue Aufträge; keine automatische Deduplizierung
fachlich ähnlicher Wünsche. Verlorene HTTP-Antwort nach erfolgreichem Commit:
derselbe Schlüssel findet den vorhandenen Job.

Events haben pro Job eindeutige monoton steigende Sequenzen. Zustand, Event, Audit
und Approval werden atomar gespeichert. Polling mit der letzten Sequenz ermöglicht
Wiederaufnahme. Keine Manifestinhalte, Tokens, Passwörter oder rohen Exceptions in
Events/Audit. Kurze ausgegebene Fehlercodes statt Providerlogs.

## Crash- und Fehlerverhalten

- Vor dem ersten Commit: kein Auftrag angelegt; derselbe Request kann erneut ankommen.
- Nach Claim, vor `running`: nach Leaseablauf erneut `queued`; abgelaufene Freigabe
  führt stattdessen zu `expired`.
- Nach `running`, einschließlich verlorener Abschlussbestätigung: Ergebnis unbekannt,
  Recovery setzt `reconciliation_required`. Noch gültige Leases bleiben respektiert.
- Alter Worker nach Recovery: Abschluss mit altem Token abgelehnt. Ein erfolgreicher
  Aktionsaufruf mit verlorenem DB-Abschluss wird nicht blind wiederholt.
- DB-Ausfall: keine behauptete Persistierung; 503 bzw. Recovery nach Wiederverbindung.
- Ressource seit Planung geändert: fester Validierungsfehler ohne falschen Erfolg.

Für Validierung gilt eine feste 60-Sekunden-Lease, für die begrenzte Installation
180 Sekunden. Kein öffentlicher Claim-/Heartbeat-/Erfolgsendpunkt. Der HTTP-Transport
wartet höchstens 120 Sekunden, Compose-Aufrufe höchstens 90. Länger dauernde oder
unterbrochene Vorgänge werden nicht erneut gesendet. Ein neuer Auftrag ersetzt
keinen Abgleich einer möglicherweise bereits ausgeführten Runtimeaktion.

## Genehmigte Installation · P2-004

`POST /api/v1/deployments/installations` nimmt nur `definition_id` und `household_id`
mit Idempotency-Key entgegen. Der Server wählt die kuratierte Revision, erzeugt die
Installations-ID und bindet Haushalt, Subject und Manifestrevision/-hash in denselben
vollständigen Plan-Hash, den auch der Adapter prüft. Freigabe ist zwingend, Risiko
`sensitive`, Frist 15 Minuten ab Planung. Keine vom Browser wählbaren Images/Ports.

Migration 0003 ergänzt `deployment_targets`; ein reservierter Plan ist keine
Appinstallation. Haushaltlocks verhindern doppelte Instanzen auch bei verschiedenen
Keys. Abbruch/Ablauf/bekannter Fehler vor Ausführungsbeginn erlauben einen neuen Plan.
Installierte oder unklare Ergebnisse halten die Reservierung aufrecht.

Core prüft vor Ausführung erneut Rechte, Kuration und Snapshots, verbraucht die
Freigabe und committet `running`. Danach sendet er genau diese Job-ID als Operation-ID.
Erst ein passendes abgeschlossenes und gesundes Adapterergebnis erzeugt Installation,
Service und Healthbeobachtung atomar mit `succeeded`. Bei Transportverlust/Crash:
`reconciliation_required`, keine erneute Ausführung.

`POST /jobs/{id}/reconcile` liest ausschließlich die bestehende Operation. Nur ihr
belegter erfolgreicher Abschluss kann den Job nachträglich abschließen. Ein gesunder
Container bei weiterhin unsicherem Adaptermarker oder eine 404 reicht nicht aus.
Der spätere Workflow zum sicheren Auflösen solcher Sperren bleibt P2-006.

## Migration und Verifikation

`uv run alembic -c backend/alembic.ini upgrade head` führt 0002 und 0003 aus.
Bestehende Migrationen bleiben unverändert; Start erzeugt keine Tabellen. Readiness
verlangt `0003_deployment_targets`. Downgrade auf 0001 entfernt Reservierungen und
die drei Jobtabellen samt
Jobhistorie; vor echtem Downgrade Daten sichern.

API-/Rechte-/Recoverytests: `uv run pytest tests/test_jobs.py -q`.
Parallele PostgreSQL-Transaktionen: `uv run pytest tests/test_jobs_postgres.py -q`
mit `DKMAN_TEST_DATABASE_URL` auf einer wegwerfbaren Datenbank mit Suffix `_test`.
Ohne Variable ausdrücklich übersprungen; CI führt sie auf PostgreSQL 17 aus.
Testidentitäten bleiben ausschließlich in Tests.

Offen: Windows/VM-Neustart, echte OIDC-Mehrbenutzerrollen, Volume-Persistenz und
Backup/Restore. Automatisierte Crash-Grenztests und ein neues App-Lifespan auf
derselben Testdatenbank ersetzen diese Zielhostabnahmen nicht.
