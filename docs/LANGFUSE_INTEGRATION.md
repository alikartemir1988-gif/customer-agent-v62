# Langfuse observability integration

This integration is an additive monitoring layer. The Python customer-agent core
continues to own catalog rules, conversation state, order confirmation, storage,
Telegram, Messenger, and the Botpress adapter.

## Safety contract

- Langfuse is optional and fail-open. Missing credentials or a tracing problem
  never blocks a customer reply.
- Raw chat and sender identifiers are never exported. A keyed HMAC creates a
  stable pseudonymous session identifier.
- Input and output content is redacted by default. Traces contain message length,
  response length, channel, version, duration, and non-sensitive order-progress
  flags.
- `LANGFUSE_CAPTURE_CONTENT=true` is reserved for synthetic or explicitly
  consented test conversations.
- API keys stay in GitHub or deployment secrets and are never committed.

## Connection values

```text
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=production
LANGFUSE_CAPTURE_CONTENT=false
```

The first three values are required to enable tracing.

## GitHub verification

GitHub Actions authenticates with the repository secrets and submits exactly one
synthetic `customer-agent-connection-check` trace on push. It contains no
customer data. A rejected or incomplete credential fails the connection-check
step without changing production.

## Render production setup

Repository secrets are not automatically copied to Render. In the Render web
service, open **Environment** and add the same three connection values, plus:

```text
LANGFUSE_TRACING_ENVIRONMENT=production
LANGFUSE_CAPTURE_CONTENT=false
```

Save the environment and let Render redeploy. The application then records a
`customer-message` trace for each handled Telegram, Messenger, or Botpress
message.

## Promotion gate

Before merging this branch into `main`:

1. Python compilation and the full unit-test suite pass.
2. The Langfuse credential check succeeds.
3. A synthetic trace appears in the Langfuse project.
4. Customer content remains redacted.
5. A Langfuse outage does not change agent replies.
