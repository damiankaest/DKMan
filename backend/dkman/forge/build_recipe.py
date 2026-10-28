"""Reviewed build recipes shared by the isolated worker and attestation verifier."""

from pathlib import Path

from dkman.forge.workspace import SourceBundle

PYTHON_IMAGE = (
    "python:3.12-slim-bookworm@sha256:"
    "34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258"
)
NODE_IMAGE = (
    "node:24-bookworm-slim@sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5"
)
CHECK_LOCK = Path(__file__).with_name("worker_assets") / "requirements-check.lock"


def expected_checks(kind: str) -> list[str]:
    if kind == "python-api":
        return ["api-passed"]
    if kind == "react-spa":
        return ["web-passed"]
    if kind == "fullstack-fastapi-react":
        return ["api-passed", "web-passed"]
    raise ValueError("unsupported_template")


def checks_dockerfile(kind: str) -> str:
    api = kind in {"python-api", "fullstack-fastapi-react"}
    web = kind in {"react-spa", "fullstack-fastapi-react"}
    expected_checks(kind)
    stages: list[str] = []
    outputs: list[str] = []
    if api:
        stages.append(
            f"FROM {PYTHON_IMAGE} AS api-check\n"
            "WORKDIR /src\n"
            "COPY requirements-check.lock /tmp/requirements-check.lock\n"
            "RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements-check.lock\n"
            "COPY backend/ ./\n"
            "RUN --network=none python -m compileall -q app "
            "&& python -m pytest -q && touch /passed\n"
        )
        outputs.append("COPY --from=api-check /passed /api-passed\n")
    if web:
        stages.append(
            f"FROM {NODE_IMAGE} AS web-check\n"
            "WORKDIR /src\n"
            "COPY web/package*.json ./\n"
            "RUN npm ci --ignore-scripts --no-audit --no-fund\n"
            "COPY web/ ./\n"
            "RUN --network=none npm test && npm run build && touch /passed\n"
        )
        outputs.append("COPY --from=web-check /passed /web-passed\n")
    return "\n".join(stages) + "\nFROM scratch AS checks\n" + "".join(outputs)


def image_dockerfile(bundle: SourceBundle) -> str:
    paths = {
        "python-api": "backend/Dockerfile",
        "react-spa": "web/Dockerfile",
        "fullstack-fastapi-react": "Dockerfile",
    }
    kind = bundle.request.template
    recipe = bundle.files[paths[kind]].replace(
        "RUN npm run build", "RUN --network=none npm run build"
    )
    # Workspaces stay private (directories 0700, files 0600). Docker COPY preserves
    # those modes, so only the fixed, unprivileged runtime user must own its inputs.
    copies = {
        "python-api": [
            ("COPY app ./app", "COPY --chown=10001:10001 app ./app"),
            ("COPY alembic.ini ./", "COPY --chown=10001:10001 alembic.ini ./"),
            ("COPY migrations ./migrations", "COPY --chown=10001:10001 migrations ./migrations"),
        ],
        "react-spa": [
            (
                "COPY nginx.conf /etc/nginx/conf.d/default.conf",
                "COPY --chown=101:101 nginx.conf /etc/nginx/conf.d/default.conf",
            )
        ],
        "fullstack-fastapi-react": [
            ("COPY backend/app ./app", "COPY --chown=10001:10001 backend/app ./app"),
            ("COPY backend/alembic.ini ./", "COPY --chown=10001:10001 backend/alembic.ini ./"),
            (
                "COPY backend/migrations ./migrations",
                "COPY --chown=10001:10001 backend/migrations ./migrations",
            ),
        ],
    }
    for before, after in copies[kind]:
        if recipe.count(before) != 1:
            raise ValueError("unsupported_image_recipe")
        recipe = recipe.replace(before, after)
    return recipe
