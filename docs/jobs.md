# Jobs und Freigaben · P2-001

`registry.validate` prüft eine registrierte Manifestrevision erneut; ihr Erfolg
bedeutet **Manifest gültig**. Seit P2-004 existiert zusätzlich `deployment.install`
mit eigenem typisierten Planner, isoliertem Adapter und Hub-Oberfläche. Die folgenden
Grundregeln gelten auch für die Runtimeaktionen aus P2-005; deren genaue Rechte und
Envelopebindung sowie die Installationsbesonderheiten stehen unten.

## API und Rechte

| Route unter `/api/v1` | Zugriff und Verhalten |
| --- | --- |
| `POST /jobs` | Admin; `Idempotency-Key` Pflicht; 202 mit `Location` und persistiertem Job |
| `GET /jobs` | eigene Jobs, Admin alle; `limit` 1–100 |
| `GET /jobs/{id}` | eigenes Subject oder Admin; fremd/unbekannt 404 |
| `GET /jobs/{id}/events` | gleiche Sichtbarkeit; `after` ab 0, `limit` 1–200; aufsteigende Sequenz |
| `GET /jobs/{id}/approval` | gleiche Sichtbarkeit; 404 bei Job ohne Approval |
| `POST /approvals/{id}/decision` | Admin; Operator nur eigene aktuell berechtigte Runtimejobs; vollständige erwartete Bindung plus `approve`/`reject` |
| `POST /jobs/{id}/run` | aktuell aktions-/ressourcenberechtigtes anforderndes Subject; Executor passend zum gespeicherten Plan |
| `POST /jobs/{id}/reconcile` | ursprünglich anforderndes Subject mit aktuellen Aktions-/Ressourcenrechten; nur belegter Abschluss, keine Runtimewiederholung |
| `POST /jobs/{id}/cancel` | Admin oder Operator für eigene aktuell berechtigte Runtimejobs; nur vor Claim; wiederholter Abbruch idempotent |

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
Seit P2-006 kann ein dauerhafter Enginebeleg einen unsicheren Marker belegt abschließen;
fehlende Belege bleiben gesperrt (Abschnitt unten).

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

## Runtimeaktionen · P2-005

`POST /installations/{id}/start`, `/stop`, `/restart` planen ausschließlich eine
bestehende, belegbar installierte App. Body `{}`, `Idempotency-Key` Pflicht, Antwort
202 mit Job/Location. Kein Installieren, Remove oder Datenlöschen über diese Routen.
`GET /runtime/installations` listet nur die zum Runtimebetrieb berechtigten Instanzen;
`GET /installations/{id}/jobs` liefert bis zu 100 gespeicherte Aufträge (Operatoren
nur eigene). Bestehende Job-/Event-/Approvalrouten bleiben der Ausführungsweg.

| Person | Planung, Status, Logs | Freigabe / Abbruch / Run / Reconcile |
| --- | --- | --- |
| Admin | alle tatsächlich installierten Apps | Admin; Run/Reconcile nur anforderndes Subject |
| Operator | Haushaltsmitglied **und** explizites `app.operate` für diese Installation | eigene Runtimejobs; gleiche aktuelle Ressourcenrechte; Run/Reconcile nur anforderndes Subject |
| Member / Developer | keine Runtimevollmacht | keine Runtimevollmacht |

`app.use` erteilt ausschließlich Appnutzung. Admins verwalten `app.operate` separat
mit `PUT/DELETE /installations/{id}/runtime-grants/{user_id}`. Wie bei Appnutzung
muss die Person dem Haushalt angehören. Globale Rollen kommen weiterhin ausschließlich
aus Keycloak. Haushaltsentfernung löscht beide Freigaben; Rejoin stellt sie nicht wieder her.
Ein Operator kann sich keine Betriebsfreigabe erteilen oder Installationsjobs ausführen.

Jeder neue Lifecycleplan enthält Aktion, Installations-ID, anforderndes Subject und
den **gesamten unveränderten installierten Deploymentplan**. Dieser vollständige neue
Hash bindet Job, Approval, Delegation und Adapterresultat. Das optionale `lifecycle`-
Commandfeld wird bei alten Commands weggelassen; bestehende v1-Planhashes und
Journalfingerprints bleiben unverändert. Keine neue DB-/Journalmigration erforderlich;
Stand P2-005: Core auf 0003, Adapter auf Journalrevision 2; P2-006 ergänzt Adapterrevision 3.

Mutation: Risiko `reversible`, zwingende einmalige Freigabe, 15 Minuten ab Planung.
Die vorhandenen sechs Bindungsfelder müssen exakt zurückgegeben werden. Admins dürfen
auch den Plan eines Operators freigeben; ausführen darf nur dessen ursprüngliches Subject.
Rechte, installierter Snapshot, Manifest, Kuration, Ablauf und Hash werden erneut geprüft.
Joblock vor Haushaltlock; Planung sperrt Haushalt und Installation bis zum Commit.
Es ist höchstens ein offener Lifecycleauftrag pro Installation zulässig, einschließlich
wartender Pläne und `reconciliation_required`. Andere Keys/Subjects umgehen ihn nicht.
Terminaler Abbruch/Ablauf oder belegter Fehler vor Dispatch erlaubt einen neuen Plan.
Alte Keys liefern weiterhin den alten Auftrag; anderer Inhalt mit gleichem Key: 409.

Claim hat 180 Sekunden Lease; `running`/verbrauchte Freigabe werden **vor** HTTP
committet. Job-ID bleibt Operation-ID. Unbekannte Ausgänge/fehlende Antworten werden
nie erneut gesendet. Reconcile liest nur das gespeicherte Resultat derselben Operation.
Erfolg erfordert passende Aktion, ID, Ressource, vollständigen Hash, abgeschlossenen
Adapterstatus und eine Messung nach Ausführungsbeginn. Stop erwartet `stopped`, Start
und Restart `running` mit Container-ID. Der aktuelle gesunde Zustand allein ist kein
Restartnachweis. Ein unsicherer Adaptermarker oder fehlendes Resultat bleibt gesperrt.
Der inzwischen implementierte Belegabschluss aus P2-006 steht im Abschnitt unten.

`GET /installations/{id}/status` misst read-only mit Beobachtungszeit, festem `reason`
und gegebenenfalls `blocked_job_id`. Engine-/Transportfehler ergeben `unknown` und
`runtime_observation_unavailable`; ungefilterte Providerfehler werden nicht ausgegeben.
Verspätete ältere Beobachtungen überschreiben keine neuere Messung im Core.
`GET /installations/{id}/logs` liefert ausschließlich Text, Abrufzeit und feste Limits:
maximal 100 Zeilen / 8192 UTF-8-Bytes, erneut im Core redigiert. Lesende Aufrufe erzeugen
keine Core-Mutationsjobs, verbrauchen keine Freigabe und ändern keine Container.


Lesende Adapteroperationen teilen sich eine Prozesssperre; Mutationen bleiben
exklusiv. Beim Sperrerwerb wird höchstens zwei Sekunden auf kurze Beobachtungen
gewartet, danach ein fester Busy-Fehler ausgegeben. Wiederholt wird ausschließlich
der Sperrversuch vor dem Adapter-Ausführungsmarker, niemals ein Provideraufruf.
Delegationsablauf wird nach Sperrerwerb/Preflight erneut geprüft. Recovery verwendet
weiterhin exklusiven, nicht wartenden Sperrerwerb und respektiert aktive Leser/Worker.

## Belegter Abgleich · P2-006

Core `POST /jobs/{id}/reconcile` ruft nun den expliziten **POST**-Abgleich des Adapters
mit `reconcile`-Delegation auf. Docker bleibt dabei vollständig lesend. Ein bereits
gespeichertes abgeschlossenes Legacyresultat wird weiterhin akzeptiert. Neue Enginebelege
werden zusätzlich in Core aktionsspezifisch geprüft; Nachweisart und SHA-256 stehen als
`evidence_kind`/`evidence_hash` in `Job.result` und im Hub. Der ursprüngliche Job und dessen
verbrauchte Freigabe bleiben erhalten. Keine zweite Mutation und kein Zurücksetzen der Lease.

Auch `failed` kann nachträglich sicher abschließen: ausschließlich mit dem gebundenen
Nichtausführungsnachweis des Adapters aus Kuration/lesendem Preflight. Ein HTTP-Fehler oder
ein fehlender Adapterdatensatz ist kein solcher Nachweis. Bei Beleglücken bleibt der Job
unklar und die Installation reserviert. Die Codes `execution_receipt_missing` bzw.
`execution_evidence_incomplete` werden begrenzt übernommen; keine Providertexte.
Vollständige Belegbedingungen und Crashgrenzen: [ADR 0011](architecture-decisions/0011-evidence-based-runtime-reconciliation.md).
