# Customer Agent V6.2

A Telegram sales assistant that answers product, pricing, and delivery questions and records confirmed customer orders.

## Current behavior

- Answers product, price, and delivery questions in Arabic.
- Collects product, quantity, name, phone, and city.
- Shows a complete order review before saving.
- Saves only after the customer writes `تأكيد`, `نعم`, or another supported confirmation.
- Lets the customer change details before confirmation.
- Restores an unfinished or completed conversation after an app restart.
- Ignores Telegram updates that were already processed.
- Supports an optional Telegram webhook secret.

## Required environment variables

- `TELEGRAM_BOT_TOKEN`: Telegram bot token. Never put it in source code.
- `WEBHOOK_URL`: Public HTTPS base URL of this service.

## Optional environment variables

- `TELEGRAM_WEBHOOK_SECRET`: Random secret used to verify that webhook requests came from Telegram.
- `DB_PATH`: SQLite database path (default: `customer_agent.db`).
- `PORT`: HTTP port when starting with Python (default: `8000`).

## Start

Production:

```bash
gunicorn --bind 0.0.0.0:$PORT app:app
```

Local/demo:

```bash
python app.py
```

## Test

```bash
python -m unittest discover -s tests -v
```

Tests also run automatically on every push and pull request.

## Health checks

- `GET /`: service health, app version, and deployed Render commit.
- `GET /webhook-info`: Telegram webhook status.

## Storage note

Orders, processed Telegram updates, and conversation sessions currently use SQLite. They survive an app-process restart when `DB_PATH` points to retained storage. Render's default filesystem is ephemeral, so before promising durable multi-instance 24/7 operation, attach persistent storage or migrate orders and sessions to managed PostgreSQL/Redis.
