FROM docker:29-cli@sha256:6fae2214c3121a28d5aa639d09032f61310b7c9c75ffbad1025f261a1b621800 AS docker-cli
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS build
WORKDIR /build
COPY requirements.lock ./
RUN pip install --no-cache-dir --prefix=/install --require-hashes -r requirements.lock

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
RUN groupadd --gid 10001 dkman && useradd --uid 10001 --gid dkman --no-create-home dkman \
    && mkdir -p /var/lib/dkman-adapter && chown 10001:10001 /var/lib/dkman-adapter
COPY --from=build /install /usr/local
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
COPY backend/dkman /app/backend/dkman
USER 10001:10001
EXPOSE 8010
CMD ["uvicorn", "dkman.deployment_adapter.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8010", "--no-access-log"]
