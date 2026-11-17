# Heimnetz-Zugang: Vorbereitung und Abnahme

Ziel: DKMan später auf Handy und Gym-Screen unter einer gemeinsamen HTTPS-Adresse
nutzen. Der aktuelle Standard bleibt an `127.0.0.1` gebunden und nutzt
`http://localhost:8080`. Dieses Dokument schaltet keinen Netzwerkzugang frei.
Ein SSH-Tunnel kann einzelne Geräte verbinden, ist aber noch kein fertig eingerichteter
Heimnetz-Zugang. Siehe ADR 0002 und `windows10-setup.md`.

## Vor der Umsetzung klären

- Dauerhafter Host und Erreichbarkeit der Linux-VM/WSL vom geplanten Reverse Proxy.
- Ein stabiler HTTPS-Name, DNS-Auflösung und auf allen Clients vertrauenswürdiges
  Zertifikat; keine Zertifikatsprüfung deaktivieren.
- TLS-Endpunkt, Netzgrenzen und Firewall: nur die tatsächlich beabsichtigten Clients;
  keine öffentliche Portweiterleitung als Standard. Docker-API und Datenbank bleiben privat.
- Exakt gleicher öffentlicher Origin für Proxy, Core-Issuer, Keycloak-Hostname,
  Hub-Konfiguration und erlaubte Redirects/Web Origins der tatsächlich verwendeten
  Clients. Bei vorhandenen Realms müssen Clients im laufenden Realm geprüft und
  angepasst werden; das Ändern der Importdatei aktualisiert sie nicht automatisch.
- Backup und überprüfter Rückweg für Konfiguration und Identity vor Änderungen.
  Bestehende App-/Runtime-Daten zusätzlich nach P5-003 absichern.

Die konkrete Netz-/Proxy-Konfiguration und die Anpassung des bestehenden Realms
sind noch nicht implementiert oder auf Damians Host geprüft. Keine URL, Firewallregel
oder vorhandene Dienste werden durch diesen Plan verändert.

## Lesende Client-Vorprüfung

Erst nachdem eine HTTPS-Adresse tatsächlich eingerichtet wurde, auf einem Gerät mit
Python 3 im selben Netz ausführen:

```bash
python3 scripts/check_home_access.py https://dkman.example
```

Den Beispielnamen durch die echte HTTPS-Origin ersetzen. Das Skript prüft mittels
GET die Erreichbarkeit von Hub, Live/Ready und OIDC-Discovery, den exakten Issuer
und `401` für `/api/v1/me` ohne Token. Es nutzt die normale Zertifikatsprüfung,
folgt keinen Redirects und verändert nichts. Es prüft weder Firewall-Isolation noch
Browser, Login, Client-Redirects oder das Auslesen und Sichern von App-Daten.
Ein Erfolg ist daher **keine Freigabe für den produktiven Mehrgerätebetrieb**.

## Abnahme nach Einrichtung

1. Zielhost: Konfiguration und Zertifikat prüfen, `scripts/linux/doctor.sh` ausführen;
   beachten, dass dieser Check die aktuelle öffentliche URL auf dem Host erreichen muss.
2. Zweites Gerät: DNS, HTTPS und das obige Skript prüfen; anschließend im Browser
   echten Login, Logout und erlaubte/nicht erlaubte Benutzer prüfen.
3. Geräte außerhalb des vorgesehenen Netzes dürfen keinen Zugriff erhalten;
   Firewall und ggf. Router prüfen. Keine Internetfreigabe voraussetzen.
4. App öffnen und auf zweitem Gerät prüfen; Ergebnisse, Umgebung und offene Fehler
   in `acceptance-tests.md` festhalten. Daten-Backup und Restore separat nachweisen.

Für H1-002 erst Teamgeists tatsächliche URL, Authentifizierung und Health-Verhalten
prüfen. Registrierung ist keine Installation und erteilt keinen Zugang. Ohne echte
Statusmessung bleibt der Status `unknown`; kein Öffnen-Link vortäuschen.
