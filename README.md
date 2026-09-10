# Customer Agent V6.2

A Telegram and Facebook Messenger sales assistant that answers product, pricing,
and delivery questions and records confirmed customer orders.

## Current behavior

- Answers product, price, and delivery questions in Arabic.
- Collects product, quantity, name, phone, and city.
- Shows a complete order review before saving.
- Saves only after the customer writes `تأكيد`, `نعم`, or another supported confirmation.
- Lets the customer change details before confirmation.
- Restores an unfinished or completed conversation after an app restart.
- Ignores Telegram updates that were already processed.
- Supports an optional Telegram webhook secret.
- Supports Meta webhook verification, signed Messenger events, and duplicate-message protection.

## Required environment variables

- `TELEGRAM_BOT_TOKEN`: Telegram bot token. Never put it in source code.
- `WEBHOOK_URL`: Public HTTPS base URL of this service.
- `DATABASE_URL`: PostgreSQL connection URL. Render supplies this automatically
  when the database is linked to the web service.
- `META_PAGE_ACCESS_TOKEN`: Page access token created by Meta for the connected Facebook Page.
- `META_VERIFY_TOKEN`: A private random value used while configuring the Meta webhook.
- `META_APP_SECRET`: Meta App Secret used to verify signed webhook requests.

## Optional environment variables

- `TELEGRAM_WEBHOOK_SECRET`: Random secret used to verify that webhook requests came from Telegram.
- `META_GRAPH_VERSION`: Graph API version used for replies (default: `v23.0`).
- `DB_PATH`: SQLite database path used only when `DATABASE_URL` is absent
  (default: `customer_agent.db`).
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
- `GET /messenger`: Meta webhook verification endpoint.
- `POST /messenger`: Signed Facebook Messenger message webhook.

## Storage note

Orders, processed Telegram updates, and conversation sessions use PostgreSQL
when `DATABASE_URL` is configured, and otherwise fall back to SQLite for local
development. Render's default filesystem is ephemeral, so production should
always have `DATABASE_URL` linked to the managed PostgreSQL instance.
