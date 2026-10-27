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

Noch offen: deterministischer Provider, drei vollständige Vorlagen, Job- und
Freigabeanbindung. Ausführung, Tests und Image-Build benötigen später einen isolierten
Worker. Es gibt noch keinen Forge-Endpunkt und keinen Build-/Deploybutton.

## Deterministischer Starter

`TemplateProvider` erstellt für alle drei geplanten Vorlagentypen deterministisch
begrenzte Startdateien. Anforderungen und Planbezug stehen ausschließlich als Daten
in `plan.json`; Freitext wird nicht in ausführbaren Quellcode eingefügt. API-Varianten
enthalten einen Live-Endpunkt, React-Varianten eine einfache Startkomponente. Diese
Dateien sind ausdrücklich keine vollständigen Vorlagen: Paketdefinitionen, Tests,
OIDC-Anbindung, Datenhaltung und Deployment fehlen. Keine App wird dadurch erstellt
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
