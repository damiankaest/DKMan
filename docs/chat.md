# DKMan Chat · P3-002

Nach der Aktualisierung erscheint **DKMan Chat** im Hub. Standardmäßig steht dort
**Regelbasierter Modus · Kein LLM verbunden**. Die folgenden Beispiele funktionieren
ohne API-Key und ohne einen externen Modellanbieter:

| Nachricht | Ergebnis |
| --- | --- |
| `Zeige meine Apps` / `Suche Apps Notes` | berechtigte Installationen mit gespeicherten Messwerten |
| `Suche Dienste` / `Suche Dienste Notes` | berechtigte Registry-Metadaten und Capabilitynamen |
| `Zeige Jobs` / `Job <UUID>` | letzte zehn sichtbare Jobs bzw. ein konkreter Job, jeweils letzte 20 Ereignisse |
| `Plane eine Garten-App mit Pflanzen und Fotos` | prüfbarer Anforderungsentwurf |
| `Stoppe Notes` / `Starte Notes neu` | Vorschlag für eine zum Betrieb freigegebene Installation |
| `Installiere Notes` | Adminvorschlag, sofern passender registrierter und kuratierter Build vorhanden |

Jede Nachricht wird einzeln ausgewertet; „ja“ übernimmt keinen vorherigen Auftrag.
Bei mehreren Installationen desselben Namens den Auftrag mit der angezeigten ID
wiederholen. Unklare, negierte oder nicht unterstützte Aufträge führen zu Hilfe.
Der Regelmodus versteht die dokumentierten einfachen Formen, kein freies Gespräch.

**Entwurf in App-Planung prüfen** übernimmt die Requirements in das Formular. Dort
kannst du Namen, Ziel, Funktionen und weitere Felder bearbeiten und einen Haushalt
wählen. Erst **App-Idee speichern** legt AppRequest und Planversion dauerhaft an.
Der Plan wird als vom Nutzer geprüfte manuelle Planung gespeichert. Der Chatverlauf
bleibt beim Tabwechsel im geöffneten Hub erhalten, geht beim Neuladen verloren und
enthält höchstens 20 Nachrichtenpaare.

**Im Containerbetrieb prüfen** wählt die konkrete Installation vor. Wähle dort die
passende Aktion und prüfe den neu erzeugten Runtimeplan. **Installation planen**+wählt die kuratierte Definition vor; Haushalt und Ressourcenplan müssen anschließend
geprüft werden. Ein Vorschlag erzeugt keinen Job, keine Freigabe und keinen Container.
Alle bisherigen Rechte-, Idempotenz-, Approval- und Ausführungsprüfungen gelten weiter.
Ein zwischenzeitlich entzogener Zugriff wird beim nächsten Backendaufruf wirksam.

Job- und Healthanzeigen sind ausdrücklich zeitgestempelte Abfragen. Zum Aktualisieren
erneut abfragen; Apps ohne aktuelle Messung bleiben `unknown`. Chatkarten enthalten
keinen möglicherweise veralteten Link zum Öffnen einer App. „Meine Apps“ prüft die
aktuellen Öffnungsbedingungen weiterhin selbst.

## API und Berechtigungen

`GET /api/v1/chat/config` liefert nur Modus, Anzeigenamen und Datenschutzhinweis.
`POST /api/v1/chat` erwartet ausschließlich `{"message":"…"}` (1–4000 Zeichen).
Beide Routen erfordern reguläres OIDC. Der Dispatcher ist lesend; ein Idempotenzschlüssel
ist hier nicht nötig. Persistente Änderungen verwenden die bestehenden APIs.

Die Antwort enthält den tatsächlich verwendeten Provider, Intent, serverseitige
Zusammenfassung, Abfragezeitpunkt und typisierte Suchergebnisse oder einen Vorschlag.
Member/Developer dürfen Anforderungsentwürfe übernehmen. Runtimevorschläge erfordern
Admin oder Operator mit Haushaltsmitgliedschaft **und** expliziter `app.operate`-Freigabe.
Appnutzung ist keine Runtimevollmacht. Registrydaten bleiben auf berechtigte
Installationen beschränkt; Admins sehen alle registrierten Definitionen. Jobs gehören
zum eigenen Subject oder sind für Admin sichtbar; entzogener Runtimezugriff gilt auch hier.

Es gibt keine generische Tool-URL, Shell, automatische Capabilityausführung,
Chatfreigabe oder Chatinstallation. Unbekannte/überzählige Modellfelder ergeben 502;
fehlende Rechte 403, verborgene Ziele 404, fehlender kuratierter Build 409.

## Optionaler echter Modellprovider

Der Standard bleibt `DKMAN_CHAT_PROVIDER=rules`. Ein Betreiber kann explizit
`openai_compatible` verwenden. Dafür sind serverseitig erforderlich:

| Einstellung | Bedeutung |
| --- | --- |
| `DKMAN_CHAT_API_URL` | vertrauenswürdige vollständige HTTPS-URL mit `/chat/completions`, ohne URL-Credentials/Query/Fragment |
| `DKMAN_CHAT_MODEL` | Betreiberwahl eines Modells mit Chat Completions und JSON-Modus |
| `DKMAN_CHAT_PROVIDER_LABEL` | optionaler sichtbarer Anbietername, maximal 80 Zeichen |
| `DKMAN_CHAT_API_KEY_FILE` | standardmäßig `/run/secrets/chat-model-api-key` |
| `DKMAN_CHAT_TIMEOUT_SECONDS` | Sockettimeout 1–20 Sekunden, Standard 10 |

Der optionale Compose-Zusatz `infrastructure/compose/chat-model.yaml` mountet
`.local/secrets/chat-model-api-key` ausschließlich im Core. Die Datei muss als reguläre
Datei ohne Symlink vorliegen und für dessen UID 10001 lesbar sein, wie die anderen
Core-Laufzeitsecrets. Den tatsächlichen Schlüssel weder in `.env` noch in Git, UI oder
Chat eintragen. Die beiden nicht geheimen Werte URL/Modell können in `.env` stehen.

Zur Konfigurationsprüfung den Zusatz **nach** den bereits verwendeten Compose-Dateien
angeben, z. B. für den Basisstack:

```bash
docker compose --env-file .env -f infrastructure/compose/compose.yaml -f infrastructure/compose/chat-model.yaml config --quiet
```

Beim anschließenden bewussten Stackstart dieselbe Dateiliste verwenden; beim Runtimestack
bleibt zusätzlich dessen `runtime.yaml` vor `chat-model.yaml` enthalten. Die normalen
Bootstrap-/Upgrade-/Runtime-Skripte aktivieren diesen optionalen Zusatz nicht. Keine
zusätzlichen Ports, Docker-Sockets oder Hostrechte werden vergeben. Hier wurde kein
Anbieter ausgewählt, Schlüssel angelegt oder Zielhost verändert.

Im externen Modus gehen die Nachricht und begrenzte berechtigte Namen/IDs an den
konfigurierten Anbieter. Der Hub zeigt das **vor dem Senden** an. Keine Secrets,
Manifeste, Jobpläne, Logs oder Subjects werden aus dem Corekontext übertragen.
Fehlende Konfiguration und Upstreamfehler sind sichtbar; kein stiller Regel-Fallback.
Der Adapter wurde mit kontrolliertem HTTP-Vertrag geprüft; ein echter kostenpflichtiger
Modellaufruf und die Kompatibilität eines konkreten Anbieters wurden nicht ausgeführt.

Der nächste Schritt ist **P3-003**: geführte Requirements-Erhebung und berechtigte
Dienstvorschläge. App-Erzeugung, Build und Vorschau folgen mit Forge in P4.
