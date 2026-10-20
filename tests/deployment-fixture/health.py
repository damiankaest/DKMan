import os
import sys
import urllib.request

if os.environ.get("FIXTURE_UNHEALTHY") == "1":
    sys.exit(1)
urllib.request.urlopen("http://127.0.0.1:8080/", timeout=1).close()
