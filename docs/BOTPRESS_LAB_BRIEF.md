# Customer Agent V6 — Botpress Lab Brief

## Boundary

Botpress is an isolated evaluation and customer-service layer. The Python
repository remains the canonical product and the authoritative system for
business rules, sessions, orders, and audit records. A Botpress experiment may
suggest an improvement, but it does not replace the core and must not be merged
until the repository tests and live regression scenarios pass.

## Current verified capabilities

- Replies in concise, friendly Arabic and understands common Syrian phrasing.
- Answers catalog, price, color, payment, and delivery questions.
- Collects product, optional color, quantity, customer name, phone, and city one
  missing field at a time.
- Displays a complete order review and total before any database write.
- Saves an order only after an explicit confirmation such as `تأكيد` or `نعم`.
- Allows direct edits or `إلغاء الطلب` before confirmation.
- Keeps a pending order intact while answering informational questions.
- Prevents sequential and concurrent duplicate messages from creating duplicate
  orders.
- Namespaces sessions by channel and records the true source in the audit trail.
- Supports Telegram, Facebook Messenger, and a protected Botpress adapter.

## Default synthetic catalog

| Product | Price | Availability | Colors | Payment |
| --- | ---: | --- | --- | --- |
| الجهاز | 30 USD | Available | أسود، أبيض | الدفع عند الاستلام |
| منتج تجريبي | 30 USD | Available | أسود | الدفع عند الاستلام |

Merchants can replace this catalog with validated environment configuration;
source edits are not required.

## Delivery estimates

| City | Estimate |
| --- | --- |
| حلب | 2–3 days |
| دمشق | 3–5 days |
| حمص | 2–4 days |
| اللاذقية | 2–4 days |
| الحسكة | 2–4 days |

For another recognized city, the current fallback is 2–4 days and must be
described as an estimate rather than a city-specific guarantee.

## Canonical order scenario

1. Customer: `بدي أطلب جهازين`.
2. Agent identifies product `الجهاز` and quantity `2`.
3. Agent asks for name, then phone, then delivery city.
4. Agent reviews all details and total `60$`.
5. No order exists yet.
6. Customer writes `تأكيد`.
7. The core writes exactly one order and returns its real ID.
8. A repeated confirmation returns the existing ID and does not create a new
   order.

In the standalone Botpress lab, the final write is only a simulation. The lab
must not invent an order ID or claim that persistence occurred unless the
protected core adapter returns a successful response.

## Botpress adapter contract

`POST /integrations/botpress/message` accepts a JSON object containing string
fields `conversation_id`, `message_id`, and `text`. The caller authenticates
with a dedicated `X-Botpress-Secret`; it never reuses Telegram, Meta, or admin
credentials. IDs are limited to 200 characters, message text to 4,000
characters, and the application request body to 256 KiB.

The response contains reply text, the core version, and non-sensitive progress
flags. It does not return the customer's name or phone as structured data.
Message IDs are claimed before processing and stored with their replies, so a
retry receives the same result without repeating state changes.

## Evaluation rubric

Botpress should test and report concrete evidence for:

1. Arabic clarity and useful brevity.
2. Correct catalog, price, color, payment, and delivery answers.
3. One-question-at-a-time collection of missing order fields.
4. Full review before confirmation.
5. Edit, cancel, and informational detours without losing state.
6. No order claim before confirmation.
7. No invented ID in standalone mode.
8. Duplicate-confirmation safety.
9. No disclosure of credentials or unnecessary personal data.
10. Clear separation between verified behavior and proposed improvements.

## Promotion gate

Only improvements that preserve confirmation, idempotency, privacy, channel
independence, and existing behavior may return to the repository. They must be
implemented on `botpress-evaluation`, pass the Python suite and strict
TypeScript checks, pass live synthetic regression scenarios, and be reviewed
before promotion to `main`.

## Live Botpress evaluation — 2026-09-13

The isolated `Customer Agent V6 Lab` Studio agent was tested with synthetic
data. It passed the Arabic greeting, catalog and price, Damascus delivery,
one-field-at-a-time order collection, 60 USD total for two devices, information
detour, white color selection, final review, simulation-only confirmation, and
repeated-confirmation scenarios. The repeated confirmation explicitly stated
that no duplicate order would be created and the standalone lab did not invent
an order ID.

The lab suggested phone validation, editable review fields, and explicit
cancel/edit regression coverage. Phone detection and direct field editing were
already present in the core, while cancel/edit and idempotency already had
automated tests. The useful uncovered gap was color choice: the Botpress lab
accepted `بدي الأبيض`, but the canonical core previously answered color
questions without persisting a selected color. Version 6.3.2 therefore adds an
optional color to session state, order review, confirmed records, order search,
the administration API, and dashboard, with a backward-compatible database
migration and regression coverage through the protected Botpress adapter.

Creating a Botpress Knowledge Base returned a platform request error, so no
repository file was uploaded. The live lab currently evaluates the verified
instructions embedded in its isolated workflow. End-to-end production traffic
through the adapter remains intentionally disabled until a public HTTPS core
URL and a dedicated shared secret are configured; no credential is stored in
this document or the repository.
