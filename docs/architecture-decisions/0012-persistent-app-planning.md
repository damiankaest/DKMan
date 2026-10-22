# ADR 0012 · Persistente Anforderungen, Planrevisionen und Freigabe

Status: angenommen; P3-001. Ergänzt ADR 0006/0007, ohne Runtimevollmachten zu erweitern.

Der erste P3-Durchstich ist eine manuell bedienbare Planung im Hub mit zwei neuen
Tabellen, `app_requests` und `app_plans`. AppRequest ist der konkrete Workflow-
Anker. Ein generisches Workflowframework oder eine ungenutzte Workflowtabelle wird
nicht vorgezogen. Chat/Wizard verwenden später dieselbe API und dieselben Requirements.

Jede Änderung erzeugt ein vollständiges unveränderliches Dokument mit Versionsfeld
und SHA-256, statt Requirements in einem freigegebenen Plan zu überschreiben.
Optimistische erwartete Revision und pessimistische Anforderungssperre verhindern
verlorene Updates; Unique Constraints sichern Request- und Revisionsidempotenz.
Member/Developer verwalten ausschließlich eigene Anforderungen, Admins alle.
Ein optionaler Haushalt schränkt die Eigentümersicht zusätzlich auf aktuelle
Mitgliedschaft ein; er erteilt keine gemeinsame Planung oder Appfreigabe.

Die neue implementierte Aktion `app_plan.approve` verwendet die vorhandene
Jobzustandsmaschine mit zwingender gebundener Freigabe und Adminrolle. Ihr Ergebnis
ist eine dauerhafte Planentscheidung, keine Build-/Installationsvollmacht.
Freigaben binden einen serverseitigen Command samt Dokumenthash. Änderungen machen
alte Reviewjobs vor Abschluss ungültig; eine neue Revision erbt keine Zustimmung.
Abschluss sperrt Job vor Anforderung und speichert Planentscheidung und Jobabschluss
in derselben Transaktion. Die konservative Crash-Recovery bleibt unverändert.

Manueller Modus wird sichtbar benannt. Es werden keine Modellantworten, automatisch
wiederverwendbaren Dienste, Workspaces oder Builds vorgetäuscht. Freitexte bleiben
Anforderungsdaten und werden im Browser als Text dargestellt. Core/Hub erhalten
keinen Docker- oder Hostzugriff. Einzelheiten und Abnahme: [Planungsvertrag](../planning.md).
