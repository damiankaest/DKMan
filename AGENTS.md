# Arbeit an DKMan

- Verbindliche Spezifikation: `docs/specification.md`. Kommunikation und Doku Deutsch;
  Quellcode, API-Namen und Commits Englisch. Keine Lizenz ohne Eigentümerentscheidung.
- Vor Änderungen `docs/progress.md`, `docs/backlog.md` und relevante ADRs lesen.
- Implementieren und tatsächlich prüfen. Unausgeführte Tests ausdrücklich markieren.
- Core bleibt modularer Monolith. Keine leeren Services/erfundenen Endpunkte.
- Keine bestehenden Hostdienste, Minecraft-Systeme oder Firewallregeln ändern.
- Alle Hostskripte planen standardmäßig ohne Mutation. Apply braucht Bestätigung.
- Docker-Socket gehört ausschließlich in den späteren separaten Deployment-Adapter.
  Core, Hub, Forge und Apps dürfen keinen Socket oder Hoststeuerungszugang erhalten.
- Registrierung != Freigabe != Installation. Kein Image allein durch ein Manifest ausführen.
- Produktionsauth niemals mit Testidentitäten umgehen; Tests nutzen Dependency Overrides
  ausschließlich in `tests/`. Kein `AUTH_DISABLED` oder festes Admin-Token.
- Secrets nur unter ignoriertem `.local/` bzw. Laufzeit-Secrets. Nie Tokens/SQL-Parameter loggen.
- Keine erfundenen Healthwerte. Ohne Messung `unknown` und kein Öffnen-Link.
- Migrationen explizit und unveränderlich; kein `metadata.create_all()` im Produktivstart.
  Zukünftige Tabellen erst mit ihrer Funktion hinzufügen.
- Python-Versionen: `pyproject.toml` + `uv.lock`; Docker: exportierte `requirements.lock` mit Hashes.
  Frontend: `npm ci`, exakt gepinntes `package.json` + `package-lock.json`.
- Prüfungen: `uv sync --frozen`; `uv run ruff check backend scripts tests`;
  `uv run ruff format --check backend scripts tests`; `uv run mypy`; `uv run pytest`;
  Hub: `npm ci`, `npm run lint`, `npm run build`, `npm test`, `npm run test:e2e`.
- API-/Schemaänderungen: `uv run python scripts/export_contracts.py`, danach im Hub
  `npm run generate:api`; generierte Verträge einchecken und Drift prüfen.
- PostgreSQL-Migrationstest nutzt ausschließlich Datenbanken mit Suffix `_test`.
- Nach jedem Paket Fortschritt mit Befehlen, Ergebnissen, Grenzen und nächstem Ticket
  aktualisieren. Nur getestete Arbeit als geprüft markieren.
