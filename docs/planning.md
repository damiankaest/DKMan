# App-Ideen und Planversionen · P3-001

Im Hub führt **App planen** zu einer manuellen, persistenten Planung. Member und
Developer können eigene Ideen anlegen und weiterentwickeln; Admins können alle Ideen
verwalten. Ziele, Funktionen, Entitäten, Ansichten, Abnahmekriterien und Anforderungen
an den Betrieb bleiben in der Core-Datenbank gespeichert. Der [DKMan Chat](chat.md)
aus P3-002 kann einen Entwurf in dieses Formular übernehmen. Der geführte Wizard und
automatische Dienstvorschläge folgen mit P3-003.

## Bedienung

1. **App planen** öffnen; Name, Ziel und mindestens eine Funktion eintragen.
2. Optional einen berechtigten Haushalt wählen. Die Idee bleibt bis zur späteren
   App-/Benutzerfreigabe privat; Haushaltsmitgliedschaft allein gibt anderen Personen
   keinen Zugriff auf die Planung. Die Zuordnung bleibt für diese Anforderung fest.
3. **App-Idee speichern** erzeugt die Anforderung und Planversion 1 atomar.
4. Eine gespeicherte Idee links öffnen. Änderungen über **Neue Planversion speichern**
   ergänzen eine Revision; bestehende Dokumente und frühere Freigaben bleiben erhalten.
5. Als Admin die aktuelle gespeicherte Version prüfen, **Freigabe vorbereiten** wählen,
   die konkrete Zustimmung markieren und **Planversion freigeben** anklicken.
6. **Freigabe abschließen** speichert den genehmigten Plan. Diesen letzten Schritt
   führt die anfordernde Adminidentität aus; andere Admins dürfen zustimmen/abbrechen.

Die Freigabe ist ausschließlich ein festgehaltener Plan zur späteren Umsetzung.
Sie erzeugt keinen Workspace, Build, Container oder Appzugriff. Forge (P4) benötigt
zusätzliche implementierte Schritte; die spätere Installation bleibt separat gebunden.
Ein erfolgreicher Job meldet ausdrücklich `effect: plan_recorded`.

## Daten- und API-Vertrag

`AppRequest` ist das derzeitige Planungsworkflow-Aggregat mit Eigentümer, optionalem
Haushalt und aktueller Revisionsnummer. `AppPlan` enthält ein unveränderliches
`schema_version: 1`-Dokument, `planning_mode: manual`, Inhalts-Hash und Autor.
Keine generische ungenutzte Workflowtabelle, keine produktiven Appdaten im Core.
Die Migration `0004_app_planning` ergänzt genau diese beiden Tabellen; alte
Migrationen bleiben unverändert. Core-Readiness verlangt die neue Revision.

| Route unter `/api/v1` | Zugriff und Ergebnis |
| --- | --- |
| `POST /app-requests` | Member/Developer/Admin; `Idempotency-Key`; 201 und `Location`; Anforderung plus erste Revision |
| `GET /app-requests` | eigene Ideen, Admin alle; `limit` 1–100, Standard 50 |
| `GET /app-requests/{id}` | Eigentümer mit aktuellen Rechten oder Admin; fremd/unbekannt 404 |
| `GET /app-requests/{id}/plans` | gleiche Sichtbarkeit; neueste zuerst, `limit` 1–100, Standard 50 |
| `POST /app-requests/{id}/plans` | gleiche Sichtbarkeit; `expected_revision`, neue Requirements und `Idempotency-Key`; 201 |
| `GET /app-plans/{id}` | gleiche Sichtbarkeit wie Anforderung |
| `GET /app-plans/{id}/jobs` | Admin; letzte 50 Reviewjobs zur Wiederaufnahme nach Browserneustart |
| `POST /app-plans/{id}/approve` | Admin; erwarteter `content_hash`, `Idempotency-Key`; 202 mit dauerhaftem Freigabejob |

Requirements sind streng typisiert: Name 1–120, Ziel 1–4000 Zeichen, Funktionen
1–30 Einträge, weitere Listen 0–30 Einträge mit jeweils 1–500 Zeichen. Zusätzliche
Felder werden abgewiesen. Freitexte bleiben Daten; sie werden weder als Tools noch
als Shell, URL, Manifest oder Deploymentkonfiguration interpretiert.
Keine Requirements oder freien Fehlermeldungen in Audit-/Jobevents.

Idempotenz der Anforderung gilt pro Subject, Revisionsidempotenz pro Anforderung,
Autor und Schlüssel. Gleicher Schlüssel/Inhalt liefert die vorhandene Ressource,
abweichender Inhalt 409. Eine absichtlich weitere Idee verwendet einen neuen Schlüssel.
`expected_revision` schützt vor überschriebenen Änderungen in mehreren Tabs.
Writes sperren die Anforderung; bei Haushaltszuordnung wird die Mitgliedschaft
unter dem Haushaltlock erneut geprüft. Entzogener Haushaltszugriff verbirgt die
zugehörigen eigenen Ideen und verhindert neue Revisionen; Adminverwaltung bleibt möglich.

## Freigabe und Fehlergrenzen

`app_plan.approve` verwendet unverändert Job/Event/Approval, sechs Bindungsfelder,
15 Minuten Ablauf, einmaligen Verbrauch, Lease und Recovery. Der typisierte
Command bindet Plan-ID, Anforderungs-ID, Revision, Adminsubject und Inhalts-Hash;
der Job-/Approval-Hash bindet diesen ganzen Command. Ein Review ist pro Revision
gleichzeitig offen. Eigentümer und Developer erhalten dadurch keine Runtimevollmacht.

Der Executor sperrt **Job → Anforderung** und prüft das aktuelle Dokument erneut.
Eine inzwischen neue Revision lässt einen alten Auftrag mit `app_plan_superseded`
fehlschlagen; geänderte Inhalte liefern `app_plan_changed`. Eine neue Revision erbt
keine Freigabe. Der historische alte Plan darf seinen damaligen Freigabenachweis behalten.

`approved_job_id`, erfolgreicher Job, Event und Audit committen atomar. Ein Fehler
vor diesem Commit veröffentlicht keine Freigabe. Nach einem Crash hinter dem
`running`-Marker bleibt die generische Recovery konservativ: unklarer Job, kein
Force-Success oder automatischer Retry. Die Planung kann über eine neue Revision
fortgesetzt werden. Für diesen Metadatenjob wird kein Runtime-Reconcile aufgerufen.

## Aktualisierung des vorhandenen Basisstacks

Nach Integration auf `main` im **WSL-Terminal im DKMan-Verzeichnis**:

```bash
git switch main
git pull --ff-only
bash scripts/linux/upgrade.sh --dry-run
bash scripts/linux/upgrade.sh --apply
```

Das bestehende Upgradeskript verlangt `UPGRADE` und anschließend `BACKUP`, baut den
ausgewählten Checkout, sichert Core/Identity, migriert und prüft den Basisstack.
Keine Zugangsdaten neu erzeugen, keine Volumes löschen. Anschließend den Browser
neu laden und **App planen** öffnen. Die Anleitung gilt für den Basisstack; ein
bereits aktiviertes Runtime-Overlay braucht den eigenen koordinierten Wartungsweg
aus [operations.md](operations.md). Kein Zielhost wurde hier fernbedient.

Prüfnachweise: [acceptance-tests.md](acceptance-tests.md). Nächster Entwicklungs-
schritt: P3-002, sicherer Intent-/Tool-Dispatcher mit austauschbarem Provider.


## Geführte Planung

Unter **App planen → Geführte Planung starten** lassen sich Ziel, Funktionen,
Daten und Ansichten schrittweise eingeben. Ein Gartenbeispiel füllt nur einen leeren
Entwurf. Der Wizard lädt die für den Nutzer sichtbaren Apps und kann einen
Prüfauftrag für eine mögliche Integration in die Betriebsanforderungen aufnehmen.
Die Auswahl begründet keinen Zugriff auf Appdaten und stellt keine Verbindung her.
**In Planung übernehmen** füllt das bestehende Formular; erst der anschließende
Speichern-Klick erstellt eine unveränderliche Planrevision. Ein Haushalt kann im
Formular gewählt werden. Planfreigabe und Installation bleiben getrennte Schritte.
