"""Run the actual ASGI HTTP server and verify fail-closed behavior with DB unavailable."""

import socket
import threading
import time
import urllib.error
import urllib.request

import uvicorn
from pydantic import SecretStr

from dkman.config import Settings
from dkman.main import create_app

settings = Settings(database_url=SecretStr("postgresql+psycopg://127.0.0.1:1/dkman_test"))
app = create_app(settings)
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started, "ASGI server did not start"
        for path, expected in [("/health/live", 200), ("/health/ready", 503), ("/api/v1/me", 401)]:
            try:
                response = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5)
                status = response.status
            except urllib.error.HTTPError as error:
                status = error.code
            assert status == expected, (path, status, expected)
            print(f"PASS {path}: HTTP {status}")
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive(), "ASGI server did not stop"
