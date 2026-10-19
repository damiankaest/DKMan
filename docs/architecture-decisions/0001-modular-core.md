# ADR 0001 · Modularer Monolith

Status: angenommen. Core bündelt Registry, Autorisierung und Health in einem
FastAPI-Prozess. Explizite Module und versionierte REST-/Manifestverträge erlauben
späteres Auslagern. Eigene Prozesse nur für tatsächliche Sicherheits-/Betriebsgrenzen:
Identity, Deployment-Adapter und Forge. Konsequenz: wenige bewegliche Teile und
transaktionale Metadaten; keine verteilten Jobs vor Bedarf.
