# Botpress Lab and Customer-Service Layer

This directory is an adapter around Customer Agent V6.3, not a replacement for
it. The Python application remains the source of truth for catalog rules,
conversation state, customer data, order confirmation, and order storage.

Botpress receives channel messages and forwards text to the protected core
endpoint. It displays the core reply without rewriting it. The same Botpress
message ID is safe to retry because the core claims it before processing,
caches its reply, and does not advance the conversation twice.

## Ownership and rollback guarantees

- Existing Telegram and Messenger routes keep working independently.
- Botpress sessions use a separate `botpress:` namespace.
- Botpress does not own or duplicate the order database.
- Disconnecting or undeploying this adapter leaves the original agent intact.
- Platform experiments must pass the regression evals before any behavior is
  moved into the Python core.

## Configuration

1. Deploy the Python core at a public HTTPS URL.
2. Set `BOTPRESS_INTEGRATION_SECRET` on the Python service to a long random
   value.
3. Set the Botpress secret `CORE_API_SECRET` to the same value.
4. Set Botpress configuration `coreApiUrl` to the Python service base URL,
   without `/integrations/botpress/message`.

Never commit either secret. Use a different value from Telegram, Meta, and the
administration keys.

## Development and evaluation

```bash
npm install
npm run typecheck
npm audit --omit=dev --audit-level=high
adk check --format json
adk dev
adk evals
```

The eval suite covers the Arabic greeting, approved product/delivery facts, and
the complete review-before-confirmation order flow. A Botpress experiment is a
candidate improvement only; promotion into the owned core is a separate,
reviewed change with Python regression tests.

The lockfile also overrides vulnerable transitive Axios and OpenTelemetry 2.x
versions while retaining the official Botpress ADK/runtime version. Keep those
overrides until Botpress publishes dependency versions that make them
unnecessary, and rerun both the audit and platform evals before removing them.
