FROM postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
RUN groupadd --gid 10001 notes && useradd --uid 10001 --gid 10001 notes && chown -R 10001:10001 /var/lib/postgresql/data /var/run/postgresql
COPY apps/notes/database/01-notes.sh /docker-entrypoint-initdb.d/01-notes.sh
USER 10001:10001
HEALTHCHECK --interval=3s --timeout=3s --retries=15 CMD ["psql", "-h", "127.0.0.1", "-U", "notes_app", "-d", "notes", "-c", "SELECT 1"]
CMD ["postgres", "-c", "max_connections=20", "-c", "shared_buffers=32MB"]
