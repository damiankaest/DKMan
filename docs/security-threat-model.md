# Sicherheitsmodell und offene Abnahmen

| Grenze / Bedrohung | Implementierte Kontrolle | Noch erforderlich |
| --- | --- | --- |
| Browser → API / gefälschte Identität | RS256, JWKS, Issuer, Audience, Ablauf, Subject; kein Dev-Bypass | echter Login-/Logout-/Refresh-Test mit Keycloak |
| Benutzer → fremde App / IDOR | Subject-Grant pro Installation; Admin separat; versteckte Details 404 | Haushaltsverwaltung/Grant-CRUD mit Audit |
| Nutzer → Adminfunktion | serverseitige Rolle, 401/403-Tests | alle späteren Mutationen gleich absichern |
| Manifest → Runtime / Injection | strenges Schema, unbekannte Felder verboten, keine Shell-/Mountfelder; nur Registrierung | Image-Allowlist, Plan-Hash, Freigabe, isolierter Adapter |
| App → Docker/Host | kein Docker-Socket in irgendeinem aktuellen Dienst | Adapter als einzige privilegierte Grenze abnehmen |
| Core → Identity-/Appdaten | eigene DB/Rolle, kein Superuser, keine DB-Ports | Live-Negativtests für Rollen und spätere App-Provisionierung |
| Logs → Secrets | keine Bearertokens/Bodies/Querystrings/SQL-Parameter, sichere Fehler, Proxyzugriffslog aus | spätere Providerlogs redigieren und testen |
| Netz → Management | nur Loopback-Port, DB intern, keine Docker-API | TLS/VPN vor Zugriff anderer Geräte; Firewallabnahme |
| Browser / XSS und CSRF | React-Escaping, CSP, Token im Speicher, keine Cookieauth in Core, gleicher Origin | CSP und Keycloak-Cookies im echten Browser prüfen |
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

Noch keine Produktionsfreigabe: Compose wurde in dieser Sitzung nicht gestartet;
Windows, TLS, OIDC-Gesamtflow, DB-Rollen und Containerhärtung sind Hostabnahmen.
Konkrete Testergebnisse stehen in `docs/acceptance-tests.md`.
