# Customer Agent 7.0

Arabic-first Telegram sales and order automation for merchants.

## What it does

- Answers common product, pricing and delivery questions in Arabic.
- Answers color and payment-method questions from configurable product data.
- Combines answers when an Arabic message contains several recognized questions.
- Answers information questions during an active order, then resumes the exact missing step without losing progress.
- Detects purchase intent and guides customers through an order flow.
- Captures customer name, phone, city, product and quantity.
- Stores orders and conversation state persistently in SQLite.
- Prevents duplicate order creation within an active completed session.
- Provides a protected admin API for order management and sales statistics.
- Provides dashboard search by customer, phone, order number, product, or city.
- Supports configurable products and delivery rules through environment variables.
- Supports Telegram webhook secret verification.
- Processes each Telegram update once, while allowing safe retry after transient failures.
- Includes health endpoints suitable for cloud hosting.

## Commercial positioning

This repository is the deployable backend for a customizable customer-sales agent. A commercial delivery can include deployment, merchant-specific catalog configuration, branding, onboarding and support. Production customers with high traffic should use a managed persistent database and production observability rather than relying on a local SQLite file.

## Required environment variables

- `TELEGRAM_BOT_TOKEN` — Telegram bot token. Never commit it.
- `WEBHOOK_URL` — public HTTPS base URL of the deployed service.
- `ADMIN_API_KEY` — long random secret protecting admin endpoints.
- `WEBHOOK_SECRET` — long random secret used to verify Telegram webhook requests.
- `DASHBOARD_SESSION_SECRET` — independent long random secret used to sign dashboard sessions.

## Optional environment variables

- `DB_PATH` — SQLite path. Default: `customer_agent.db`.
- `PORT` — local server port. Default: `10000`.
- `PRODUCTS_JSON` — JSON object replacing the default product catalog.
- `DELIVERY_JSON` — JSON object replacing the default delivery rules.

Example `PRODUCTS_JSON`:

```json
{
  "منتج 1": {
    "price": 25,
    "currency": "$",
    "available": true,
    "aliases": ["منتج 1", "المنتج الاول"],
    "colors": ["أسود", "أبيض"],
    "payment_methods": ["الدفع عند الاستلام"]
  }
}
```

## Start

Development:

```bash
python app.py
```

Production:

```bash
gunicorn --bind 0.0.0.0:$PORT app:app
```

## Deployment sequence

1. Create the Telegram bot and obtain its token.
2. Deploy this repository to a Python hosting service.
3. Configure all required environment variables.
4. Use persistent disk storage for `DB_PATH` if SQLite is used.
5. Start the application with Gunicorn.
6. POST `/admin/setup-webhook` with header `X-Admin-Key: <ADMIN_API_KEY>`.
7. Check `/health` and `/webhook-info`.
8. Send `/start` to the Telegram bot and test a complete order.

## Admin API

All `/admin/*` routes require:

```text
X-Admin-Key: <ADMIN_API_KEY>
```

Endpoints:

- `GET /admin/orders?limit=50&offset=0`
- `GET /admin/orders?status=new&limit=50&offset=0`
- `GET /admin/stats`
- `PATCH /admin/orders/<id>/status`
- `POST /admin/setup-webhook`

Allowed order statuses:

- `new`
- `confirmed`
- `processing`
- `shipped`
- `delivered`
- `cancelled`

The orders endpoint accepts integer limits from 1 to 200. Invalid limits or status
filters return a structured `400` response instead of an internal server error.
It also accepts an integer `offset` from 0 to 1,000,000 and returns pagination
metadata containing `limit`, `offset`, `total`, and `has_more`.

## Health endpoints

- `GET /`
- `GET /health`
- `GET /webhook-info`

`/health` returns `503` with named configuration errors when `PRODUCTS_JSON` or
`DELIVERY_JSON` is malformed or has an invalid schema, while never echoing the
configured value. Product entries require a non-negative numeric `price` and a
non-empty `currency`; optional aliases, colors and payment methods are type-checked.
Delivery entries require non-empty text keys and values. This lets deployment health
checks stop a release that would otherwise use fallback catalog data.

## Security

- Never commit Telegram tokens, admin keys, wallet addresses intended to stay private, passwords or exchange credentials.
- Use long random values for `ADMIN_API_KEY` and `WEBHOOK_SECRET`.
- Use a separate long random value for `DASHBOARD_SESSION_SECRET`; if omitted, the dashboard derives a stable fallback from `ADMIN_API_KEY`.
- Dashboard state-changing forms are protected against cross-site request forgery (CSRF), and dashboard responses are marked non-cacheable.
- Telegram transport failures expose only sanitized errors so bot tokens cannot leak through request URLs or logs.
- HTTP request bodies are limited to 256 KiB; oversized webhook or admin requests receive a structured `413` response.
- Rotate secrets after sharing them in insecure channels.
- Keep customer phone/order data private and restrict admin API access.
- For larger deployments, add HTTPS termination, managed PostgreSQL, rate limiting, backups, centralized logs and monitoring.

## Product limitations

This is a deterministic conversational commerce engine rather than a general-purpose LLM. That makes order flows predictable and inexpensive, but merchant-specific customization and testing are required before production use. SQLite is appropriate for demos and small single-instance deployments; multi-instance/high-volume installations should migrate to PostgreSQL.
