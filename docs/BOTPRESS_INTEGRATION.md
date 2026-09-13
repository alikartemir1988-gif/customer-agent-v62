# Botpress Integration Safety Contract

## Purpose

Botpress is a development lab and an additional customer-service/channel layer.
Customer Agent V6.3.2 remains the owned, sellable product and the authoritative
system for business rules and records.

## Data flow

1. A customer sends a message through a channel connected to Botpress.
2. The Botpress adapter sends `conversation_id`, `message_id`, and `text` to
   `POST /integrations/botpress/message`.
3. The Python core authenticates the call with `X-Botpress-Secret`, executes the
   existing sales logic, saves the authoritative session/order, and returns the
   reply.
4. Botpress displays that reply unchanged.

The API response exposes only reply text and non-sensitive progress flags. It
does not return the customer's name or phone as structured data.

## Protection mechanisms

- The integration is disabled when `BOTPRESS_INTEGRATION_SECRET` is absent.
- Botpress has its own secret; no Telegram, Meta, or admin credential is reused.
- Requests are limited by the application's existing 256 KiB body limit and a
  4,000-character message limit.
- Botpress sessions are prefixed with `botpress:` and cannot collide with
  Telegram or Messenger sessions.
- Botpress message IDs are claimed before execution and their replies are
  persisted, so concurrent or sequential retries do not create duplicate state
  changes or orders.
- Order audit events record `botpress`, `telegram`, or `messenger` as the true
  source.

## Promotion gate to `main`

A platform-originated idea may be brought into the core only after:

1. the change is recorded on the `botpress-evaluation` branch;
2. Python unit tests and Botpress type checks pass;
3. Botpress regression evals pass in the development environment;
4. order confirmation, persistence, duplicate protection, and existing channel
   behavior are verified;
5. the diff is reviewed and contains no secret or customer export.

If an experiment fails, disable the Botpress adapter or revert its branch. The
original channel routes and database remain independent.

Use synthetic conversations in the Botpress development environment. Before
connecting real customers, review Botpress data retention, access, region, and
deletion settings for the merchant's privacy requirements.
