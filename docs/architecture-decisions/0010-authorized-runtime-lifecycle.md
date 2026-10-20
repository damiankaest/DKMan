# ADR 0010 · Autorisierter Runtime-Lifecycle

Status: angenommen; P2-005. Baut auf ADR 0006–0009 auf.

Operator ist eine globale Fähigkeit, keine Freigabe für sämtliche Installationen.
Seine Ressourcenrechte benötigen Haushaltsmitgliedschaft und ein explizites
`app.operate`. Admins erteilen/entziehen diese Freigabe getrennt von `app.use`.
Die vorhandene PermissionGrant-Tabelle unterstützt beide Rechte; keine Datenmigration.
Member/Developer erhalten auch mit Appnutzung keine Runtimevollmacht. Ein Betriebsgrant
allein erteilt umgekehrt keine Appnutzung. Rollenänderungen werden mit dem jeweils
aktuell verifizierten OIDC-Token wirksam; bestehende Tokenlaufzeiten gelten weiter.

Ein Lifecycle ändert die installierte Runtimebeschreibung nicht. Deshalb bleibt der
bereits installierte Deploymentplan unverändert (inklusive ursprünglicher Context-
Identität und Compose-Labels). Ein neues versioniertes Lifecycle-Envelope bindet die
konkrete Aktion, Ressource, ausführende Identität und den gesamten Runtimeplan. Sein
Hash wird vom Core bis zum Adapterjournal verwendet. Der Adapter prüft Übereinstimmung
mit Command, Delegationssubject und aktuellem installierten Plan. Das optionale neue
Commandfeld wird ohne Wert nicht serialisiert, alte Plan-/Replayverträge bleiben stabil.

PostgreSQL-Haushalt-/Installationslocks serialisieren die Anlage. Ein offener Auftrag
reserviert die Installation bis zum terminalen Abschluss. Jobs, einmalige Freigaben,
Leases und Events bleiben dieselbe Zustandsmaschine. Der Adapter behält seine getrennten
Dateisperren und dauerhaften Unklarheitssperren. Kein DB-Lock bleibt über HTTP bestehen.
Aktive/geplante/unklare Mutationen sperren den Öffnen-Link, während der Status weiterhin
die tatsächlich gemessene Beobachtung zeigt. 45 Sekunden Frischegrenze gelten weiter.

Start nutzt Compose `start` für vorhandene Container. Fehlende oder unvollständige
Workloads werden abgelehnt; kein `up` als Ersatz. Stop verlangt belegtes Stoppen beider
Notes-Container. Restart wartet auf echte Health. Core akzeptiert nur abgeschlossene
passende Operationsnachweise und aktionsgerechte Zustände; niemals eine neue Installation
oder einen aktuellen Healthwert als Ersatz für den Operationsabschluss. Journalverlust
oder unsichere Marker bleiben blockiert. P2-006 führt diesen Nachweisworkflow weiter.

Logredaktion ist ein gemeinsames reines Textmodul ohne Dockerabhängigkeit, auf Adapter-
und Coregrenze angewandt. React rendert Logs ausschließlich als Text. Musterbasierte
Maskierung kann unbekannte frei formulierte Secrets nicht erkennen; sichere App-Logs
bleiben erforderlich. Keine Rohfehler oder Logtexte in Jobs/Events/Audit.


Lesende Adapteroperationen teilen sich eine Prozesssperre; Mutationen bleiben
exklusiv. Beim Sperrerwerb wird höchstens zwei Sekunden auf kurze Beobachtungen
gewartet, danach ein fester Busy-Fehler ausgegeben. Wiederholt wird ausschließlich
der Sperrversuch vor dem Adapter-Ausführungsmarker, niemals ein Provideraufruf.
Delegationsablauf wird nach Sperrerwerb/Preflight erneut geprüft. Recovery verwendet
weiterhin exklusiven, nicht wartenden Sperrerwerb und respektiert aktive Leser/Worker.
