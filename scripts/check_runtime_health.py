"""Container health probe; never includes credentials in diagnostics."""

import json
import os
import sys
import urllib.error
import urllib.request


def main():
    service = os.environ.get("APP_SERVICE", "core")
    path = "/ready" if service == "core" else "/health"
    port = int(os.environ.get("PORT", "8080"))
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
            healthy = response.status == 200 and json.load(response).get("ok") is True
    except (OSError, ValueError, urllib.error.HTTPError):
        healthy = False
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
