"""Gunicorn lifecycle hooks for the production service."""


def post_worker_init(worker):
    """Keep Telegram's webhook aligned with the deployed secret."""

    from app import (
        BOT_TOKEN,
        WEBHOOK_SECRET,
        WEBHOOK_URL,
        register_webhook,
    )

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
