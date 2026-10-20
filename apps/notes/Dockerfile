FROM node:24-bookworm-slim@sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5 AS web
WORKDIR /web
COPY apps/notes/web/package*.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY apps/notes/web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock && useradd --uid 10001 --create-home notes
COPY backend/notes_demo /app/notes_demo
COPY --from=web /web/dist /app/web
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=3s --timeout=3s --start-period=10s --retries=10 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready',timeout=2)"]
CMD ["/bin/sh", "-ec", "python -m notes_demo.migrate && exec uvicorn notes_demo.main:create_app --factory --host 0.0.0.0 --port 8080 --no-access-log --no-server-header"]
