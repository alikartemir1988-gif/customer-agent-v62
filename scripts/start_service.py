"""Start an existing V6 WSGI application on any container host."""

import os
import sys

APPLICATIONS = {
    "core": "app:app",
    "demo": "demo_app:demo_app",
    "dashboard": "dashboard:dashboard_app",
}


def main():
    service = os.environ.get("APP_SERVICE", "core")
    if service not in APPLICATIONS:
        raise SystemExit("APP_SERVICE must be core, demo, or dashboard")

    try:
        port = int(os.environ.get("PORT", "8080"))
    except ValueError:
        raise SystemExit("PORT must be an integer") from None
    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be between 1 and 65535")

    if service != "demo" and not os.environ.get("DATABASE_URL", "").strip():
        raise SystemExit("DATABASE_URL is required for durable core/dashboard storage")

    os.execv(sys.executable, [
        sys.executable, "-m", "gunicorn",
        "--bind", f"0.0.0.0:{port}",
        "--workers", "1",
        "--timeout", "120",
        "--graceful-timeout", "30",
        "--access-logfile", "-",
        "--error-logfile", "-",
        APPLICATIONS[service],
    ])


if __name__ == "__main__":
    main()
