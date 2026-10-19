FROM python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83 AS build
WORKDIR /build
COPY requirements.lock ./
RUN pip install --no-cache-dir --prefix=/install --require-hashes -r requirements.lock

FROM python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
RUN groupadd --gid 10001 dkman && useradd --uid 10001 --gid dkman --no-create-home dkman
COPY --from=build /install /usr/local
COPY backend ./backend
COPY examples ./examples
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "dkman.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
