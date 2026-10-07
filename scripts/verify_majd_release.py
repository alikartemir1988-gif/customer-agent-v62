"""Wait for Render to serve the healthy Majd release for this workflow commit."""

import argparse
import json
import math
import re
import sys
import time
import urllib.request


def wait_for_release(health_url, expected_commit, wait_seconds=600,
                     poll_interval=10, request_timeout=20):
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("Expected commit must be a full 40-character Git SHA")
    if any(not math.isfinite(value) or value <= 0 for value in
           (wait_seconds, poll_interval, request_timeout)):
        raise ValueError("Wait, poll interval, and request timeout must be positive and finite")

    deadline = time.monotonic() + wait_seconds
    last_observation = "no health response"
    print(f"Waiting up to {wait_seconds:g}s for Majd commit {expected_commit}", flush=True)
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            with urllib.request.urlopen(
                health_url, timeout=min(request_timeout, remaining)
            ) as response:
                health = json.load(response)
            if not isinstance(health, dict):
                raise ValueError("Health response must be a JSON object")
            metadata = {key: health.get(key) for key in
                        ("status", "version", "commit", "ai_engine", "gemini_model")}
            print("Live Majd health: " + json.dumps(metadata, ensure_ascii=False), flush=True)
            last_observation = f"status={health.get('status')!r}, commit={health.get('commit')!r}"
            if health.get("status") == "ok" and health.get("commit") == expected_commit:
                print(f"Verified live Majd commit {expected_commit}", flush=True)
                return health
        except (OSError, ValueError) as exc:
            last_observation = type(exc).__name__
            print(f"Health attempt: {last_observation}; retrying within deployment wait", flush=True)

        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(poll_interval, remaining))

    raise TimeoutError(
        f"Could not verify healthy Majd commit {expected_commit} within {wait_seconds:g}s; "
        f"last observation: {last_observation}"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-url", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--wait-seconds", type=float, default=600)
    parser.add_argument("--poll-interval", type=float, default=10)
    parser.add_argument("--request-timeout", type=float, default=20)
    args = parser.parse_args(argv)
    try:
        wait_for_release(args.health_url, args.expected_commit, args.wait_seconds,
                         args.poll_interval, args.request_timeout)
    except (ValueError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
