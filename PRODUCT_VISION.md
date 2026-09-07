# Customer Agent — Commercial Product Vision

## Positioning
A customizable AI customer-service and sales system for businesses — not a generic chatbot.

The product is configured around each customer's products, policies, delivery rules, brand voice, sales process, knowledge and escalation rules.

## Commercial outcome
The system should help a business:
- answer customer questions 24/7,
- qualify inbound leads,
- recommend products/services,
- capture structured customer information,
- create and manage orders/leads,
- hand difficult conversations to a human,
- preserve customer context,
- measure conversations, orders and revenue,
- operate in Arabic and expand to additional languages/channels.

## Product architecture target

### 1. Company workspace
Each client gets isolated configuration and data.

Configuration includes:
- company name and branding,
- tone/personality,
- products/services,
- pricing,
- FAQs and policies,
- delivery/service areas,
- business hours,
- escalation rules,
- enabled channels.

### 2. Knowledge layer
The agent must answer from company-approved information and avoid inventing business facts.

Target sources:
- structured catalog,
- FAQ/knowledge entries,
- website/document ingestion later,
- company policies.

### 3. Sales agent
Capabilities:
- identify buying intent,
- product/service discovery,
- pricing answers,
- lead qualification,
- objection handling using approved rules,
- order/lead capture,
- appointment/demo request capture,
- human handoff for negotiation or exceptions.

### 4. Customer support agent
Capabilities:
- FAQ resolution,
- order/status questions,
- complaint intake,
- support ticket creation,
- urgency classification,
- escalation to humans,
- conversation history.

### 5. Channels
Initial production channel:
- Telegram

Commercial roadmap:
- website chat,
- WhatsApp Business,
- email,
- Instagram/Messenger where supported.

### 6. Admin / operations
Required:
- authenticated admin API,
- orders/leads list,
- status management,
- performance statistics,
- configuration without editing source code.

Next:
- browser dashboard,
- team users/roles,
- searchable conversations,
- export/integrations.

### 7. Reliability and safety
- secrets only through environment variables,
- webhook verification,
- persistent conversation state,
- persistent business records,
- health endpoint,
- audit-friendly timestamps,
- human escalation for sensitive or uncertain cases,
- no autonomous discounts/refunds/financial commitments without configured authority.

## Commercial package
Target positioning: custom implementation rather than source-code sale.

Minimum project target: USD 5,000.

A client engagement can include:
1. discovery and workflow mapping,
2. company-specific configuration,
3. catalog/knowledge setup,
4. channel setup,
5. deployment,
6. testing and acceptance,
7. onboarding/training,
8. post-launch support.

Recurring hosting/support/maintenance should be quoted separately rather than silently included forever.

## Definition of a sellable v1
A sellable v1 should demonstrate end-to-end:
1. customer contacts the company,
2. agent understands the request,
3. agent answers from company configuration,
4. agent qualifies a buyer or resolves a common support question,
5. agent records a lead/order/ticket,
6. business staff can inspect and update the record,
7. conversation survives restart,
8. system can be reconfigured for another company without rewriting core logic.

## Current build direction
The productization branch introduces persistent sessions, protected administration endpoints, configurable catalog/delivery data, order lifecycle states, health checks and safer Telegram webhook handling.

The next engineering milestone is true multi-company configuration and a browser administration dashboard.