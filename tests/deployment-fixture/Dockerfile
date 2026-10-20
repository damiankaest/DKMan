FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ARG FIXTURE_UNHEALTHY=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FIXTURE_UNHEALTHY=${FIXTURE_UNHEALTHY}
RUN mkdir -p /data /app && chown 10001:10001 /data
COPY tests/deployment-fixture/app.py tests/deployment-fixture/health.py /app/
USER 10001:10001
VOLUME ["/data"]
HEALTHCHECK --interval=2s --timeout=2s --retries=2 CMD ["python", "/app/health.py"]
CMD ["python", "/app/app.py"]
