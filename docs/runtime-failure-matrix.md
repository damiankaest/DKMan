# Runtime-Fehlermatrix · P2-006

Belegbedingungen: [ADR 0011](architecture-decisions/0011-evidence-based-runtime-reconciliation.md).
Die folgende CI-Abnahme läuft in einem wegwerfbaren Linux-Stack; PR-/Mainnachweis wird
nach tatsächlichem Abschluss ergänzt. Testidentitäten/Transportdoubles der schnellen
Backendtests sind ausdrücklich keine OIDC-/Dockerabnahme.

| Fehlergrenze | Implementierte Prüfung | Erwarteter belastbarer Ausgang |
| --- | --- | --- |
| Gültiger Digest, aber nicht kuratiert | echte Adapter-Dockerprobe; Core lässt kein freies Imagefeld zu | persistiertes `failed` mit Nichtausführungsbeleg; kein Container |
| Appnutzung ohne Runtimefreigabe / fehlende globale Rolle | echte PKCE-Konten: Operator ohne `app.operate` 404, Member-Logs 403 | keine Mutation/Jobanlage, keine fremden Details |
| Notes-Datenbank gestoppt | echte DB wird ausschließlich in CI gestoppt | Daten-API 503 mit festem Text, Runtime `unhealthy`, kein Öffnen-Link |
| Core-Datenbank vor Run ausgefallen | echter PostgreSQL-Prozess stoppt | Run/Ready 503, Live 200; nach Wiederverbindung derselbe Job noch `queued` |
| Wiederanlauf nach DB-Ausfall | derselbe gespeicherte konkrete Plan, gültige Freigabe | einmaliger echter Run; keine versteckte Ausführung während Ausfall |
| Adapter stirbt nach Enginebeleg, vor Operationsabschluss | echter Prozessabbruch im separat gemounteten CI-Entrypoint | persistierter Job nach Reload unklar; Belegabgleich schließt genau diese Operation erfolgreich ab |
| Adapter stirbt vor Enginebeleg, obwohl Docker bereits neu gestartet hat | zweiter echter Prozessabbruch | gesunde Container reichen nicht; `execution_receipt_missing`, neue Keys/Mutationen 409 |
| Unbelegter Restart wird abgeglichen | echte Enginebeobachtung vor/nach Abgleich | Container-/Image-/Volume-/Startzeiten unverändert; kein zweiter Restart |
| Beleg enthält falsche IDs/Hash/Zeiten, Rekreation, fehlende Sidecars oder Health | parametrische Backend-/Journaltests | Sperre bleibt erhalten; nie Force-Success |
| Alter Worker, paralleler Worker oder anderer Benutzer | Journal-/API-/bestehende echte PostgreSQL-Konkurrenztests | Sperren respektiert, ursprüngliche Identität und aktuelle Rechte erforderlich |
| Antwortverlust / nicht erreichbarer Adapter / fehlende Operation | Transport-/Recoverytests plus echte Prozessabbrüche | kein Dispatch-Retry; gespeicherter Job bleibt auffindbar/gesperrt |
| Logs / Fehler / Darstellung | Backendgrenzen und Hub-Textdarstellung; echte Notes-Logs | begrenzt/maskiert, feste Fehlercodes, keine Providerfehler/Secrets in Audit |
| Journalrevision 2 → 3 | echter SQLite-Migrations-/Legacyreplaytest | explizites Upgrade, alte Operationen/Fingerprints unverändert, keine erfundenen Belege |

Die positive Journey B bleibt dieselbe echte Kette: drei Keycloak-Konten, Hubplan,
gebundene Zustimmung, reale Installation/SSO, gemeinsame Notes, Stop/Start/Restart mit
identischen vollständigen Datensätzen und Container-/Volumenidentität, Rechtewiderruf.
Erweiterte Enginebeobachtungen, Corejobs und feste Fehlercodes liegen im CI-Artefakt.
Die vorläufige lokale Abnahme umfasst 200 Backend- und 12 UI-Tests; native PostgreSQL-
und Dockerprüfungen sind lokal explizit übersprungen. Lokaler Playwrightstart benötigt
eine hier fehlende Chromium-Binary; die bisherigen Browserchecks laufen in GitHub CI.

Keine Zielhost-/Windows-/VM-Neustartprobe, kein Docker-Daemon-Shutdown auf einem echten
Zielhost, keine vollständige OIDC-Refresh-/Logout-/Passwortwechselmatrix und kein
koordinierter Runtime-Backup/Restore. Ein Crash ohne dauerhaften Befehlsbeleg bleibt
bewusst ungeklärt; es gibt keinen sicheren allgemeinen Retry aus reiner Healthmessung.
Forge-/Buildabbruch gehört zur späteren Forgephase; die vorhandenen Buildtests prüfen,
dass ein fehlgeschlagener lokaler Notes-Build keine Kuration behauptet.
