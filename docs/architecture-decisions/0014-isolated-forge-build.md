# ADR 0014 · Isolierter Forge-Build

Status: implementiert und auf einem CI-Builder getestet; Zielhostabnahme steht aus.

Der Core gibt einen privaten Forge-Quellstand nur dann als Build-Eingabe aus, wenn
der aufrufende Developer oder Admin aktuell Zugriff auf den Haushalt und die
aktuelle, unveränderte, freigegebene Planrevision besitzt. Der Core führt keinen
Quellcode aus und erhält keinen Docker- oder BuildKit-Socket.
Haushaltsmitgliedschaft und Planstand werden jeweils aus der Datenbank geprüft;
die Rollen entstammen dem gültigen OIDC-Token und können bis zu dessen Ablauf
einen früheren Stand abbilden.

Ein separat von einem Operator gestarteter BuildKit-Client läuft auf einem eigens
isolierten Builder. Er akzeptiert zunächst ausschließlich exakt die drei im Worker
installierten Forge-Vorlagen. Prüf- und Buildrezepte werden nicht aus Textanweisungen
erzeugt. Die Abhängigkeiten sind gesperrt; Paketdownloads benötigen Netzwerkzugang,
Test- und Frontend-Buildbefehle laufen mit `RUN --network=none`. Der Worker gibt
keine Produktionssecrets, SSH-Agenten oder privilegierten BuildKit-Entitlements weiter.
Die Isolation des Hosts, Ressourcenlimits und das Ausmaß des Netzwerkzugangs müssen
vom Betreiber außerhalb des Workers bereitgestellt und geprüft werden; ein
BuildKit-Socket allein belegt diese Isolation nicht.

Vor Prüfungen und Image-Build sowie nach dem Build wird der Plan erneut über Core
geprüft. Die Prüfung ist keine dauerhafte Deployfreigabe. Der Worker exportiert ein
OCI-Archiv ohne Registry-Push. Er prüft Manifest, Konfiguration und Layer anhand
der OCI-Deskriptoren und speichert Manifest-Digest, Archiv-SHA-256, Checks und einen
begrenzten privaten Fehlerlog im BuildArtifact. Bei Abbruch oder fehlender
Revalidierung ist das Ergebnis nicht freigegeben; ein vorhandenes `running`-Artefakt
nach einem Absturz darf nicht als Erfolg behandelt werden. Es gibt keinen
automatischen Retry und keinen Import ins produktive Deployment.

Die erste Version wird bewusst manuell per CLI gestartet. Sie speichert Ergebnisse
auf dem Builder, nicht in der Core-Datenbank, und nimmt nur unveränderte Starter an;
Änderungen durch einen Coding-Agenten benötigen später eine eigene Sicherheits- und
Versionsstrategie. Vorschau, Übernahme des Artefakts und Freigabe für denselben
DeploymentService gehören zu P4-003.

Referenz: [BuildKit buildctl und OCI-Export](https://github.com/moby/buildkit#exploring-dockerfiles),
[Dockerfile-Netzwerkmodus](https://docs.docker.com/reference/dockerfile/#run---network).
