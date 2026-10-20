# Sicherheitsmodell und offene Abnahmen

| Grenze / Bedrohung | Implementierte Kontrolle | Noch erforderlich |
| --- | --- | --- |
| Browser → API / gefälschte Identität | RS256, JWKS, Issuer, Audience, Ablauf, Subject; kein Dev-Bypass | echte CI-Code/PKCE-/SSO-Probe vorhanden; Zielhost-/Logout-/Refresh-Matrix offen |
| Benutzer → fremde App / IDOR | Subject-Grant pro Installation; Admin separat; versteckte Details 404 | CRUD/Widerruf/Audit implementiert und echte CI-Mehrbenutzerprobe bestanden; Zielhost offen |
| Nutzer → Adminfunktion | serverseitige Rolle, 401/403-Tests | alle späteren Mutationen gleich absichern |
| Manifest → Runtime / Injection | strenges Schema, separate unveränderliche Image-Kuration, Plan-Hash/Approval, isolierter Adapter | verbleibende Fehlermatrix und Zielhostabnahme |
| App → Docker/Host | Socket ausschließlich im separaten Adapter; Core/Hub/Apps ohne Hostzugriff | echte CI-Containerprüfung vorhanden; Zielhostgrenze weiterhin abnehmen |
| Core → Identity-/Appdaten | eigene DB/Rolle, kein Superuser, keine DB-Ports | eigene Notes-DB/Approlle in echter CI geprüft; Core-/Identity-Isolation am Zielhost offen |
| Logs → Secrets | keine Bearertokens/Bodies/Querystrings/SQL-Parameter, sichere Fehler, Proxyzugriffslog aus | Adapterredaction getestet; unbekannte freie Secrets bleiben Appverantwortung |
| Netz → Management | nur Loopback-Port, DB intern, keine Docker-API | TLS/VPN vor Zugriff anderer Geräte; Firewallabnahme |
| Browser / XSS und CSRF | React-Escaping, CSP, Token im Speicher, keine Cookieauth in Core, gleicher Origin | echte CI-Journey mit CSP/Keycloak bestanden; Zielhost-/Geräteprüfung offen |
| Ressourcen / DoS | Ressourcenlimits, Bodylimit 64 KiB, Proxy-Ratelimit, DB-Timeout | Quotas für Jobs/Builds und JWKS-Rotation unter Last |
| Installer / versehentliche Hoständerung | Dry-run, Bestätigung, keine automatischen Paketinstallationen/Neustarts | tatsächlicher Windows-Preflight und VM-Abnahme |

DB-Readiness verrät nur Zustand/Zeitpunkt, keine Hostadressen oder Fehlermeldungen.
JWKS-Adresse kommt ausschließlich aus Betreiberkonfiguration. Manifestpfade werden
noch nicht für Requests verwendet; ein späterer Healthworker darf nur vom Provider
zugewiesene interne Ziele erreichen, keine frei gelieferten URLs oder Redirects.

`.local/` wird ignoriert und auf Linux als 0700 angelegt. Secretdateien und die
Import-Realmdatei sind innerhalb des Verzeichnisses 0444, damit Compose sie ohne
UID-Umschreibung an nicht privilegierte Container mounten kann; über den Hostpfad
schützt das private Elternverzeichnis. Zugangsdatenübersicht und `.env` sind 0600.
Nur benötigte Secrets werden pro Dienst gemountet. Docker-Administratoren können
diese Werte grundsätzlich lesen. Backups enthalten Secrets und sind entsprechend
vertraulich zu behandeln. Git/Artefaktpaket enthalten keine generierten Zugangsdaten.

Die lokale Realmdatei enthält das ursprüngliche temporäre Benutzerpasswort. Nach
dem ersten Login gilt der neue Wert aus der Identity-DB; bestehende Realms werden
beim Import nicht überschrieben. Plattform-Admin ist kein Keycloak-Masteradmin.
Bootstrap-Masterkonto nach Einrichtung über die Admin-Konsole entfernen/deaktivieren.

Noch keine Zielhostfreigabe: echter Compose-/OIDC-/Appbetrieb wurde ausschließlich
auf wegwerfbaren GitHub-Runnern geprüft. Windows/VM, TLS, Damians Benutzer und
koordinierter Backup/Restore bleiben Hostabnahmen. Nur geprüfte eigene Apps teilen
diesen Origin; unbekannte Fremd-/Forge-Apps benötigen später eine eigene Isolationsentscheidung.
Konkrete Testergebnisse stehen in `docs/acceptance-tests.md`.


Die Notes-API enthält ausschließlich eine feste interne Core-Autorisierungsadresse;
keine frei wählbaren URLs oder vom Browser übernommene Identitätsheader. Jede Datenanfrage
verifiziert OIDC und die aktuelle App-Freigabe über Core. Die öffentliche leere Apphülle
enthält keine Daten; ein bekannter Direktlink ersetzt keine Berechtigung. Apptext wird
als Text gerendert. Der App-Datenschlüssel liegt nur beim Adapter und ist getrennt
vom Core-Delegationsschlüssel; Passwörter stehen nicht in Job-/Plan-/Browserantworten.


P2-005: Runtimezugriff erfordert Admin oder Operator + aktuelle Haushaltsmitgliedschaft
+ installationsgebundenes `app.operate`. Appnutzung bleibt separat. Erneute Prüfung
vor Approval und Dispatch; Job-/Operations-ID und vollständiger Lifecyclehash sind
gebunden. Konkurrierende Keys/Subjects umgehen keine offene Ressourcenreservierung.
Keine neue Dockergrenze in Core/Hub. Logs werden erneut im Core begrenzt/maskiert und
in React als Text angezeigt. Unklare Ausgänge werden weder durch Healthpolling noch
durch einen neuen Auftrag entsperrt. P2-006 erweitert den belegbaren Abschluss.
