"""CI smoke test for three local containers using a disposable PostgreSQL DB."""

import json
import os
import time
import urllib.error
import urllib.request


def call(port, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read().decode(), response.headers
    except urllib.error.HTTPError as response:
        return response.code, response.read().decode(), response.headers


def wait_ready(port, path):
    for _attempt in range(30):
        try:
            status, body, _headers = call(port, path)
            if status == 200 and json.loads(body).get("ok") is True:
                return
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError(f"Container on port {port} did not become ready")


def main():
    commit = os.environ["GITHUB_SHA"]
    wait_ready(8080, "/ready")
    wait_ready(8081, "/health")
    wait_ready(8082, "/health")

    status, body, _ = call(8080, "/")
    assert status == 200 and json.loads(body)["commit"] == commit[:7]
    assert call(8080, "/telegram", {})[0] == 401

    status, body, _ = call(8081, "/")
    assert status == 200 and "<!doctype html>" in body.lower()
    _, body, _ = call(8081, "/health")
    health = json.loads(body)
    assert health["commit"] == commit and health["data_persistence"] is False
    status, body, headers = call(8081, "/api/message", {"message": "مرحبا"})
    assert status == 200 and json.loads(body)["ok"] is True
    assert "Secure" in headers.get("Set-Cookie", "")
    assert call(8081, "/api/reset", {})[0] == 200

    status, body, _ = call(8082, "/")
    assert status == 200 and 'name="password"' in body
    print("Portable core, demo, and dashboard HTTP checks passed")


if __name__ == "__main__":
    main()
