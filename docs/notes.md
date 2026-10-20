# Notes · Quellbuild, Installation und SSO

Notes 0.1.0 bietet gemeinsames Lesen und Anlegen von Notizen pro Installation.
Alle freigegebenen Haushaltsmitglieder teilen denselben Datensatz. Autoridentität
kommt aus der aktuellen Core-/OIDC-Autorisierung, niemals aus dem Formular.
Text wird als Text gerendert, begrenzt und über gebundene SQL-Parameter gespeichert.

Quellen: `backend/notes_demo`, `apps/notes`; explizite Migration unter
`backend/notes_demo/migrations`. Infrastruktur und Rechte: ADR 0009.

## Isolierter Build

Voraussetzungen: geprüfter Checkout, `uv sync --frozen`, grünes CI, dedizierter
Linux-Docker-Builder. Diese Befehle starten keine App und verändern keine Hostdienste.
Der erste Aufruf zeigt nur den Plan:

```bash
uv run python scripts/generate_adapter_config.py
uv run python scripts/build_notes.py
```

Nur nach bewusster Prüfung der lokalen Umgebung Konfiguration und Build bestätigen:

```bash
uv run python scripts/generate_adapter_config.py --apply --confirm ADAPTER_CONFIG
uv run python scripts/build_notes.py --apply --confirm BUILD_NOTES
```

Der Builder prüft UID und CMD-Healthvertrag, speichert tatsächliche lokale Image-IDs
und den Quellhash in `.local/adapter/catalog.json` und `notes-build.json`. Er kuratiert
keine beliebigen Images und überschreibt keine abweichende Notes-Revision.
Die IDs gelten auf diesem Engine-Speicher. Keine erfundene GHCR-/Registryreferenz;
ein anderer Builder muss die geprüften Quellen neu bauen und explizit kuratieren.
CI bewahrt die erzeugten Metadaten als `notes-build-evidence` auf, keine Secrets.

## Bewusste Runtime-Aktivierung

Dies ist ein separater Schritt nach den offenen Zielhost-Gates, keine Erweiterung
des automatischen Bootstraps. Keine Ausführung dieser Schritte auf Damians Host erfolgt.
Frischer Realm benötigt den Client `demo-notes` aus der Realmvorlage. Bei bestehenden
Realms in Keycloak einen öffentlichen Client mit Code Flow, PKCE S256, Audience
`dkman-api`, erlaubter Redirect-URL `<origin>/run/*` und Web-Origin `<origin>` anlegen.
Kein Password Grant, kein Clientsecret, keine Wildcard für fremde Origins.

Konkrete Compose-Auswahl nach Host-/Socket-/Projektprüfung:

```bash
export DKMAN_DOCKER_SOCKET_GID=$(stat -c '%g' /var/run/docker.sock)
docker compose -p dkman --env-file .env -f infrastructure/compose/compose.yaml -f infrastructure/compose/runtime.yaml config --quiet
```

Erst nach eigener Hostfreigabe dieselbe Dateiauswahl mit
`up -d --build --wait --wait-timeout 300` starten. Der Socket ist allein beim Adapter.
Core erhält nur Delegationsschlüssel/Katalog; App-Datenschlüssel bleibt ausschließlich
beim Adapter. Kein zusätzlicher veröffentlichter Port. Das externe App-Gatewaynetz
wird vom Runtime-Overlay als internes, gelabeltes Netzwerk angelegt.

## Bedienung und Fehler

1. Im Hub als Admin Haushalt anlegen, unter Katalog den Stand neu laden.
2. Notes/Haushalt wählen, Plan erstellen. Images, Ressourcen, Datenvolume, Identität,
   vollständigen Hash und Ablauf lesen. Noch keine Installation vorhanden.
3. Konkreten Plan freigeben, danach „Jetzt installieren“. Derselbe Job bleibt bei
   Reload/Verbindungsfehler erhalten. Jobverlauf und Fehlercode sind sichtbar.
4. Nach gesundem Adapterergebnis unter „Meine Apps“ öffnen. Notes führt einen eigenen
   OIDC-Code/PKCE-Flow durch; vorhandene Keycloak-Sitzung ermöglicht SSO.
5. Andere Person einmal anmelden lassen, Haushaltsmitgliedschaft hinzufügen und
   explizite App-Freigabe erteilen. Mitgliedschaft allein genügt nicht. Entfernen
   entzieht auch direkten API-/Appzugriff bei der nächsten Anfrage.

Bei `reconciliation_required` nicht neu installieren. „Ergebnis abgleichen“ liest
die bestehende Operation. Nur ein abgeschlossenes passendes Ergebnis kann den Job
abschließen. Fehlender Datensatz oder unsicherer Adaptermarker bleiben ungeklärt;
es gibt keinen Force-Retry. Vor erneutem Betrieb ist ein belegter Abschluss nötig
(weiterer Workflow in P2-006).

Runtime-Lifecycle über Core/Hub ist P2-005. Das Adapterinterface ist bereits vorhanden;
die Notes-Datenpersistenz wird zusätzlich mit echten CI-Containern geprüft.

## Betrieb und verbleibende Grenzen

Notes-DB-Volume, Core-DB, Adapterjournal, Katalog, OIDC-Konfiguration und beide
Adapterkeys müssen zusammen gesichert/wiederhergestellt werden. Die alten
Backupskripte sichern weiterhin nicht das vollständige Runtime-System. Restore
ist offen; keine Produktionsfreigabe oder Datenhaltbarkeitsgarantie daraus ableiten.
Kein automatischer Austausch verlorener Secrets. Keine blinden Installationswiederholungen.

Ein Haushalt bekommt in diesem MVP eine Notes-Installation. Bekannte Fehler vor
dem Ausführungsmarker bzw. Abbruch/Ablauf erlauben einen neuen Plan; installierte
oder ungeklärte Ressourcen blockieren andere Keys. Es gibt noch keinen Update-,
Rollback-, Mehrinstanz- oder UI-Lifecycle-Workflow.

Die automatisierte echte CI-Journey ersetzt nicht die Abnahme mit Damians echten
Benutzern und Windows-/VM-/Netzwerkumgebung. Diese bleibt gesondert dokumentiert offen.


## Geprüfter Main-Build

[CI 39409720195](https://github.com/damiankaest/DKMan/actions/runs/39409720195)
hat beide Images tatsächlich gebaut, kuratiert, über den Hub installiert und mit
drei echten Keycloak-Benutzern getestet. Vollständige lokale Image-IDs, Quellhash,
Commit, Artefaktlink und Checksumme sind in
[build-evidence.json](../examples/demo-notes/build-evidence.json) versioniert.
Das ist ein Build-/Testnachweis; diese Engine-lokalen IDs werden auf einem anderen
Host nicht automatisch als verfügbar ausgegeben.
