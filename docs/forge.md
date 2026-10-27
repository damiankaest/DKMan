# Forge · Beginn P4-001

Der CodingProvider-Vertrag nimmt Plan-ID, Inhalts-Hash, Requirements und einen der
geplanten Vorlagennamen entgegen und liefert begrenzte Quelldaten. Die interne
Workspacefunktion schreibt diese in ein neues privates UUID-Verzeichnis unter einem
bereits vorhandenen vertrauenswürdigen Root. Sie validiert Pfade und Größe erneut,
verweigert Symlink-Roots und berechnet einen Hash über Planbezug und Quelltext.
Sie führt keinen Quelltext aus und vergibt keine Runtime- oder Deploymentrechte.

Der Betreiber muss Root und Eltern vor fremdem Schreibzugriff schützen. Die Funktion
ist keine Sandbox; Planfreigabe und Eigentümerschaft müssen vor späterer Verwendung
von einer noch zu implementierenden Orchestrierung überprüft werden. Der Quellenhash
ist keine Autorisierung. Zehn lokale Tests prüfen private getrennte Workspaces,
Pfadabwehr, Symlinks und nachträgliche Mutation der Eingaben. Ruff und mypy bestanden.

Historischer Stand: Damals waren Provider und Plananbindung noch offen.
Ausführung, Image-Build und Deployment benötigen weiterhin einen isolierten Worker.

## Deterministischer Starter

`TemplateProvider` erstellt für alle drei geplanten Vorlagentypen deterministisch
begrenzte Startdateien. Anforderungen und Planbezug stehen ausschließlich als Daten
in `plan.json`; Freitext wird nicht in ausführbaren Quellcode eingefügt. API-Varianten
enthalten einen Live-Endpunkt, React-Varianten eine einfache Startkomponente. Dieser historische Starter enthielt noch keine vollständigen Vorlagen; siehe den
aktuellen Abschnitt unten. Keine App wird dadurch erstellt
oder ausgeführt. Lokale Prüfung: 13 Forge-Tests, Ruff und mypy erfolgreich.

## Freigegebenen Plan lesen

`generation_request_for` leitet die Generator-Eingabe aus einer aktuellen,
freigegebenen Planrevision ab. Developer sehen nur ihre eigenen zugänglichen Pläne;
Admins dürfen alle prüfen. Ein erfolgreicher Freigabejob, gebundener Auftrag,
Ergebniseintrag und Dokumenthash werden überprüft. Geänderte oder überholte Pläne
werden abgewiesen. Die Funktion ist ein lesender Baustein ohne API, Job oder
Workspace. Spätere Orchestrierung muss vor einer externen Wirkung Rechte und
Planstand erneut prüfen; ein Rückgabewert ist keine dauerhafte Ausführungsvollmacht.
Lokale Prüfungen: zwei Integrationsfälle, Ruff und mypy erfolgreich. Vollständige
Vorlagen und die persistente sichere Orchestrierung bleiben offen.


## Ausführbare Vorlagen · Zwischenstand

P4-001 wird um echte Template-Dateien erweitert: Python-API mit delegierter
Appzugriffskontrolle, expliziter Migrationsbasis und gesperrten Python-Abhängigkeiten;
React-SPA mit OIDC/PKCE und Prüfung der Installationsfreigabe; Fullstack kombiniert
beide. Jede Vorlage enthält gesperrte Abhängigkeiten, Tests und ein Dockerfile.
Das Manifest enthält bis P4-002 absichtlich eine ungültige Image-Referenz.
Dieser Checkpoint ist noch kein Abschluss: Die generierten Projekte und die
Plananbindung müssen separat vollständig geprüft werden. Container- und Deployment-
Abnahme bleibt P4-002/P4-003.


## Persistente Quellstände · P4-001

Die aktuelle freigegebene Planversion kann von deren berechtigtem Developer oder
einem Admin in eine der drei Vorlagen überführt werden. Über den Hub unter
**App planen → App-Quellcode vorbereiten → Quellstände öffnen** erzeugt
**Quellstand erstellen** einen unveränderlichen, privaten Datenbanksnapshot. Der
Planinhalt wird nicht als Code ausgeführt. Nach Speicherung zeigt der Hub Dateien
und Inhalts-Hash und bietet einen ZIP-Download. Eine neue Version oder entzogene
Berechtigung verhindert eine neue Erzeugung; auch der Download prüft aktuelle
Rechte und den gespeicherten Hash. Historische Quellstände bleiben für ihren
berechtigten Besitzer lesbar. Ein Idempotenzschlüssel verhindert Doppelanlage bei
Wiederholung. Migration 0005 ist explizit auszuführen.

Die vollständigen Grundgerüste enthalten gesperrte Abhängigkeiten, Tests,
Dockerfiles und OIDC/PKCE bzw. die bestehende Core-Appzugriffsprüfung. Anforderungen
stehen ausschließlich als Daten in plan.json. Der Image-Platzhalter im Manifest ist
absichtlich ungültig: Erzeugung gewährt keine Build- oder Deploymentfreigabe.
`materialize_git_workspace` erstellt auf einem vertrauenswürdigen Worker-Root ein
separates Git-Repository ohne Hooks und ohne Netzaufruf. Der Core ruft diese
Funktion nicht auf und braucht keinen Hostzugriff. Für eine spätere Ausführung im
isolierten Worker müssen Berechtigung, Freigabe und Hash erneut überprüft werden.

Lokale Zwischenprüfung: 303 Backendtests bestanden, 15 Dienst-Skips; 24 Hubtests,
Lint und Build; generierte API-/Fullstack-Backendtests und SQLite-Migrationen sowie
SPA-/Fullstack-Frontendtests und Builds; PGlite-Migrationsroundtrip mit Revision
0005. GitHub-CI und die abschließende Browser-/Zielhostabnahme stehen noch aus.
Die Vorlagen sind Grundgerüste: die beschriebenen Fachfunktionen werden nicht
automatisch implementiert. P4-002 ergänzt isolierte Checks und Image-Build.
