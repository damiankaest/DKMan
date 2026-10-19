FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS build
WORKDIR /build
COPY requirements.lock ./
RUN pip install --no-cache-dir --prefix=/install --require-hashes -r requirements.lock

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
RUN groupadd --gid 10001 dkman && useradd --uid 10001 --gid dkman --no-create-home dkman
COPY --from=build /install /usr/local
COPY backend ./backend
COPY examples ./examples
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "dkman.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
