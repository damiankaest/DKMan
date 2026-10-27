# DKMan starter

This is a starter, not an implementation of the requested features. The approved
requirements in plan.json are data for review, not executable source. They are not
included in the backend or frontend container build contexts.

Backend: use a dedicated database and `uv sync --frozen`, `uv run pytest`, followed
by explicit `DATABASE_URL=... uv run alembic upgrade head`. The app never creates
schema on startup. Configure `DKMAN_INSTALLATION_ID` after an administrator registers
the application and grants access. API requests use the real bearer token and the
DKMan Core access check. Never use production database credentials for development.

Frontend: `npm ci`, `npm test`, `npm run build`. Register the public OIDC client
`generated-app`, its exact `/run/<installation-id>/` redirect and the `dkman-api`
access-token audience with the identity provider. The installation ID is assigned
when the app is registered. Browser code cannot contain secrets.

The manifest contains a placeholder for the future build artifact and is not a
valid deployment manifest. An isolated build worker must produce a reviewed digest.
No image is automatically built, trusted, started or installed by this workspace.
