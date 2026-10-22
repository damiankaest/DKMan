# ADR 0013 · Geschlossener Intent-Dispatcher und austauschbare Interpretation

Status: angenommen; P3-002. Ergänzt ADR 0006/0007/0012.

Der Core interpretiert einzelne Nachrichten über `IntentProvider`, ohne dem Provider
Datenbankzugriff oder Ausführungsvollmacht zu geben. Der Standardprovider verwendet
feste, konservative Regeln und benennt den Modus sichtbar. Ein zweiter tatsächlicher
HTTP-Adapter spricht ein vom Betreiber gewähltes HTTPS-Chat-Completions-Endpoint mit
JSON-Modus an. Es gibt keinen eingebauten Modellnamen, Browser-API-Key, simulierten
Liveanbieter oder stillen Rückfall von einem fehlerhaften Modell auf Regeln.

Beide Provider liefern dieselbe streng validierte `IntentDecision`. Die geschlossene
Liste enthält Hilfe, App-/Registry-Suche, Jobstatus, Anforderungsentwurf sowie Vorschläge
für Start/Stop/Neustart und kuratierte Installation. Zusätzliche Tools, URLs, Shell,
Approval-/Run-Intents und unerwartete Parameter werden abgewiesen. Die Antworttexte
zu Suchergebnissen und Jobs entstehen im Core aus tatsächlichen Daten, nicht aus
Erfolgsaussagen eines Modells. Manifest-Capabilities werden nur als berechtigte
Metadaten angezeigt, niemals automatisch als frei adressierbare Tools ausgeführt.

Vor externem I/O wird ein reduzierter berechtigter Kontext erzeugt und die
Lesetransaktion beendet. Danach werden alle Rechte aus der Datenbank neu ermittelt.
Weder Modelltext noch ein zuvor sichtbares Ziel gewähren Zugriff nach einem Widerruf.
Eigene Jobs behalten zusätzlich die Runtime-Berechtigungsprüfung. Mehrdeutige
Appnamen verlangen eine eindeutige ID; es wird nicht die erste Installation gewählt.

Der Chat-Endpunkt schreibt keine Anforderung und erzeugt keinen Job. Typisierte
Vorschläge führen nach einem bewussten Klick zu den vorhandenen Hub-Formularen.
App-Ideen werden geprüft/ergänzt und über die bestehende idempotente Planungs-API
gespeichert; der gespeicherte Plan ist ein vom Nutzer überprüfter manueller Plan.
Runtime und Installation benötigen weiterhin Plan, gebundene Approval und gesonderten
Ausführungsauftrag. Rechte und Kuration werden dort erneut geprüft.

Nachrichten sind auf 4000 Zeichen begrenzt. Der externe Provider erhält pro Gruppe
höchstens 100 berechtigte IDs/Namen, keine Subjects, Tokens, Secrets, Manifeste, Pläne,
Logs oder Jobereignisse. Betreiber müssen berücksichtigen, dass Freitext freiwillig
eingegebene vertrauliche Informationen enthalten kann. API-Key nur als Laufzeitdatei;
kein Symlink/FIFO, maximal 4096 Bytes. HTTPS ohne Redirect/Umgebungsproxy,
1–20 Sekunden Sockettimeout, maximal 64 KiB Antwort und zwei parallele Modellaufrufe
pro Coreprozess. Ungültige Antworten, Refusal, Truncation und Transportfehler sind
feste Fehlercodes ohne Upstreambody. Keine automatischen Retries.

Der Verlauf liegt nur im geöffneten Hub im Speicher (maximal 20 Nachrichtenpaare).
Jede Nachricht steht für sich. Nur ausdrücklich gespeicherte Anforderungen/Planversionen
und bestehende Jobs sind persistent. Eine neue Chatdatenbank oder Migration ist für
diese Funktion nicht erforderlich. Der Requirements-Wizard bleibt P3-003.

Protokollreferenz (22.10.2026): [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
JSON-Modus garantiert allein keine gültigen DKMan-Aufträge; die lokale Schema- und
Berechtigungsprüfung bleibt entscheidend. Der Adaptervertrag wird ohne bezahlten
Modellaufruf geprüft; tatsächliche Anbieterkompatibilität ist eine separate Betreiberprobe.
