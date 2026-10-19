# ADR 0003 · Ein Compose-Adapter hinter Providervertrag

Status: angenommen, Umsetzung Phase 2. DeploymentProvider erhält Discover, Pull,
Install/Deploy, Start, Stop, Restart, Status, Logs und Remove. Pläne und Genehmigungen
bleiben vom Provider unabhängig. Ein separater interner Adapter rendert ausschließlich
erlaubte Compose-Strukturen; kein Durchreichen beliebiger YAML-/Shellinhalte.

Dockerzugriff ist praktisch Hostadministration. Core/Hub/Forge/Apps bekommen weder
Socket noch Docker-API. Datenlöschung ist ein eigener genehmigungspflichtiger Vorgang.
Coolify wird erst nach dem funktionierenden Compose-Durchstich anhand der offiziellen
API evaluiert; aktuell keine zweite Implementierung und keine Kompatibilitätsbehauptung.
