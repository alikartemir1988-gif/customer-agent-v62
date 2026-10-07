"""Gunicorn lifecycle hooks for the production service."""


def post_worker_init(worker):
    """Keep Telegram's webhook aligned and run optional diagnostics."""

    import os
    import sys
    import threading

    if "demo_app" in sys.modules:
        return

    from app import (
        BOT_TOKEN,
        WEBHOOK_SECRET,
        WEBHOOK_URL,
        ensure_db_initialized,
        register_webhook,
        run_gemini_smoke_tests,
        run_langfuse_smoke_tests,
    )

    ensure_db_initialized()

    if os.environ.get("LANGFUSE_RUN_SMOKE_TESTS", "").strip().lower() in (
        "1", "true", "yes", "on"
    ):
        threading.Thread(
            target=run_langfuse_smoke_tests,
            name="langfuse-deploy-smoke",
            daemon=True,
        ).start()

    if os.environ.get("GEMINI_RUN_SMOKE_TESTS", "").strip().lower() in (
        "1", "true", "yes", "on"
    ):
        threading.Thread(
            target=run_gemini_smoke_tests,
            name="gemini-deploy-smoke",
            daemon=True,
        ).start()

    if not (BOT_TOKEN and WEBHOOK_URL and WEBHOOK_SECRET):
        return

    try:
        result = register_webhook()
        if not result.get("ok"):
            worker.log.warning(
                "Telegram webhook registration was not acknowledged"
            )
    except Exception:
        # A temporary Telegram outage must not prevent the service from booting.
        worker.log.exception("Telegram webhook registration failed")
