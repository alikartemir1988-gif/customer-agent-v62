# Customer Agent V6.2 — Deploy

A Telegram sales assistant that answers product, pricing, and delivery questions and records customer orders.

## Required environment variables

- `TELEGRAM_BOT_TOKEN`: Telegram bot token. Never put it in source code.
- `WEBHOOK_URL`: Public HTTPS base URL of this service.

## Optional environment variables

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

## Health checks

- `GET /`: service health.
- `GET /webhook-info`: Telegram webhook status.

## Storage note

SQLite orders and in-memory conversation sessions are acceptable for a first demo. Before promising durable multi-instance 24/7 operation, migrate orders to PostgreSQL and sessions to Redis (or another persistent shared store).
