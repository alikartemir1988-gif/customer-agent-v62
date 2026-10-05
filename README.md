# Customer Agent V6.4.0

A Telegram and Facebook Messenger sales assistant that answers product, pricing,
and delivery questions and records confirmed customer orders.

## Current behavior

- Answers product, price, and delivery questions in Arabic.
- Optionally uses Gemini for open Telegram questions. Catalog answers and order
  confirmation stay in the local sales flow; contact details are not sent to Gemini.
- Collects product, optional colour, quantity, name, phone, and city.
- Shows a complete order review before saving.
- Saves only after the customer writes `تأكيد`, `نعم`, or another supported confirmation.
- Lets the customer change details before confirmation.
- Persists a selected product colour and shows it in the review, confirmation,
  administration API, and dashboard.
- Restores an unfinished or completed conversation after an app restart.
- Ignores Telegram updates that were already processed.
- Supports an optional Telegram webhook secret.
- Supports Meta webhook verification, signed Messenger events, and duplicate-message protection.
- Supports an optional Botpress evaluation/customer-service layer while keeping this core authoritative.
- Supports optional fail-open Langfuse tracing with customer content redacted by default.
- Understands common Arabic quantity, colour, payment, cancellation and multi-question phrases.
- Exposes a protected administration API and a CSRF-protected browser dashboard.
- Tracks order status changes in an audit trail and reports revenue by currency.
- Supports validated merchant catalog and delivery configuration without source edits.

## Reviewed answers and staff follow-up

Open `/dashboard/login` on the existing core service, sign in with `ADMIN_API_KEY`,
then choose **إدارة الإجابات المعتمدة وطلبات الموظف**. A separate dashboard service
is optional; the operator interface now also runs inside the core service.

- Create a question, answer, source title, optional HTTPS source URL, and up to
  20 alternative question phrasings. Entries start as drafts unless approved.
- Reviewed answers match complete normalized questions/aliases, not semantic
  search. Add Arabic or English Q&A explicitly; the order workflow remains Arabic.
- The reply cites that entry's source. The source title is supplied and reviewed
  by the merchant; V6 does not fetch or independently validate the cited document.
- A customer can write `موظف` or `talk to a human` to create a private follow-up
  ticket with current order context. Further messages append to that ticket.
  `ارجع للبوت` or `back to bot` closes it and resumes the existing order flow.
- Operators review and close tickets in the dashboard. This is a follow-up queue;
  it does not connect an online staff member or send their replies automatically.
- Local counters report reviewed FAQ replies, messages that reached the no-answer
  fallback, and staff requests. They do not establish resolution rate, satisfaction,
  labor savings, or billing outcomes. Optional Gemini replies remain separate.
- The public demo uses fictional FAQ policies and simulated staff requests.
  It never loads merchant FAQ content or writes production support tickets/counters.

Tables are created automatically in the existing PostgreSQL/SQLite database.
No new provider or paid dependency is required. Keep the database backed up;
operator tickets contain customer-provided details.

Protected API endpoints, with `X-Admin-Key`:

- `GET /admin/support/faqs`, `POST /admin/support/faqs`
- `PUT /admin/support/faqs/<id>`, `DELETE /admin/support/faqs/<id>`
- `GET /admin/support/tickets?status=open` (or `closed`)
- `POST /admin/support/tickets/<id>/close`
- `GET /admin/support/stats`

See [the market comparison](docs/MARKET_COMPARISON_2026-10-05.md) and
[commercial scope](SALES.md) before using these features in an offer.

## Required environment variables

- `TELEGRAM_BOT_TOKEN`: Telegram bot token. Never put it in source code.
- `WEBHOOK_URL`: Public HTTPS base URL of this service.
- `DATABASE_URL`: PostgreSQL connection URL. Render supplies this automatically
  when the database is linked to the web service.
- `TELEGRAM_WEBHOOK_SECRET`: Random secret sent by Telegram with webhook calls.
- `ADMIN_API_KEY`: Long random key for administration API and dashboard login.
- `DASHBOARD_SESSION_SECRET`: Independent long random value for dashboard sessions.
- `META_PAGE_ACCESS_TOKEN`: Page access token created by Meta for the connected Facebook Page.
- `META_VERIFY_TOKEN`: A private random value used while configuring the Meta webhook.
- `META_APP_SECRET`: Meta App Secret used to verify signed webhook requests.

## Optional environment variables

- `PRODUCTS_JSON`: Optional validated product catalog JSON.
- `DELIVERY_JSON`: Optional validated delivery-times JSON.
- `BOTPRESS_INTEGRATION_SECRET`: Independent secret for the optional Botpress adapter.
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`: Optional Langfuse connection values.
- `LANGFUSE_TRACING_ENVIRONMENT`: Trace environment such as `production` or `staging`.
- `GEMINI_API_KEY`: Optional Gemini API key stored as a Render secret. Without it,
  Telegram uses the local replies. A free-tier key is subject to Google quotas.
- `GEMINI_MODEL`: Defaults to `gemini-3.5-flash-lite`. Set it only to a model
  available to the project's free tier if billing must remain disabled.
- `LANGFUSE_CAPTURE_CONTENT`: Defaults to `false`; enable only for synthetic or consented conversations.
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

Dashboard (run as a separate private service sharing the same database):

```bash
gunicorn --bind 0.0.0.0:$PORT dashboard:dashboard_app
```

## Test

```bash
python -m unittest discover -s tests -v
```

Tests also run automatically on every push and pull request.

## Health checks

- `GET /`: lightweight liveness and deployed version.
  Its `ai_engine` field is `gemini` when the key is configured, otherwise `local`.
- `GET /health`: database and merchant-configuration health.
- `GET /ready`: production readiness, including required secrets and HTTPS webhook.
- `GET /webhook-info`: Telegram webhook status.
- `GET /messenger`: Meta webhook verification endpoint.
- `POST /messenger`: Signed Facebook Messenger message webhook.
- `POST /integrations/botpress/message`: Secret-protected Botpress adapter endpoint.

## Botpress lab

The [`botpress/`](botpress/) project is an additive adapter and regression-test
lab. It forwards messages to this Python core, which continues to own catalog
rules, sessions, confirmation, and orders. It does not replace or copy the core.
See [`docs/BOTPRESS_INTEGRATION.md`](docs/BOTPRESS_INTEGRATION.md) for the safety
contract and promotion gate.

## Langfuse observability

Langfuse is an optional monitoring layer. It measures message-processing traces
without changing the sales logic, and failures in Langfuse do not block customer
replies. Customer and conversation identifiers are pseudonymized, and message
content is redacted unless `LANGFUSE_CAPTURE_CONTENT=true` is explicitly set.

GitHub Actions secrets only power the synthetic connection check. Add the same
three connection values to the Render service environment to trace production
traffic. See [`docs/LANGFUSE_INTEGRATION.md`](docs/LANGFUSE_INTEGRATION.md).

## Administration API

Send `X-Admin-Key: <ADMIN_API_KEY>` with every request:

- `GET /admin/orders?limit=50&offset=0&status=new&q=search`
- `GET /admin/stats`
- `PATCH /admin/orders/<id>/status` with JSON `{ "status": "processing" }`
- `GET /admin/orders/<id>/history`
- `POST /admin/setup-webhook`

The dashboard login uses `ADMIN_API_KEY`. Deploy it behind HTTPS and do not expose
either administration secret in source control or logs.

## Storage note

Orders, processed Telegram updates, and conversation sessions use PostgreSQL
when `DATABASE_URL` is configured, and otherwise fall back to SQLite for local
development. Render's default filesystem is ephemeral, so production should
always have `DATABASE_URL` linked to the managed PostgreSQL instance.

## Public web demo

The web demo uses the same sales core as the Telegram service:

```bash
gunicorn --workers 1 --bind 0.0.0.0:$PORT demo_app:demo_app
```

- `GET /` opens the interactive demo.
- `GET /health` includes the full deployed Render commit.
- `POST /api/message` and `POST /api/reset` operate a browser demo session.
- Demo orders and conversation details are not persisted, and the demo worker
  does not register the production Telegram webhook.

Use `main` for both Render services to keep future releases aligned.
