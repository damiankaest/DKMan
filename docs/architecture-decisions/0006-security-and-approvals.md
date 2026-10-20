# ADR 0006 · Strukturierte Aktionen und Genehmigungen

Status: angenommen, Deploymentfreigaben folgen in Phase 2. Jede Aktion erhält Risiko
read_only/reversible/sensitive/destructive. Genehmigungen binden Subject, Aktion,
Ressource, Plan-Hash und Ablaufzeit. Jobs persistieren Request-ID und Statuswechsel;
kein Modell führt Shelltext direkt aus. Approval ist keine Chat-Zustimmungserkennung.

Externe Manifeste sind untrusted Daten. Registrierung validiert und auditiert, gibt
aber kein Image frei. Image-Allowlist und sichere Compose-Pläne sind Voraussetzung
für jede spätere Installation. Secrets bleiben außerhalb Git/Browser/Logs.
Hostskripte haben Dry-run als Default und explizite Bestätigung vor Apply.
Fortschreibung: P2-004 ergänzt genehmigte Installation, P2-005 den autorisierten
Runtime-Lifecycle. Beide verwenden dieselbe persistente Freigabe-/Jobgrenze;
Details in ADR 0007–0010 und [Jobs](../jobs.md).
