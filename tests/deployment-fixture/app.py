"""Disposable CI fixture, not the curated Notes application."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

counter = Path("/data/counter")
count = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(count))
print(f"counter={count}", flush=True)
print("password=smoke-only-secret", flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ready")

    def log_message(self, format: str, *args: object) -> None:
        pass


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
