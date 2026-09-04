<div align="center">

# Fail2Pay — AI Revenue Recovery

**Find revenue that's slipping away — and win it back.**

An autonomous AI platform that **detects revenue at risk**, **diagnoses the root cause**, chooses the right intervention, and **executes a bounded, fully-audited recovery workflow** — from failed payments and checkout abandonment to failed subscriptions and overdue B2B receivables.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React_19-61DAFB?logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-6-3178C6?logo=typescript&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-dev--ready-003B57?logo=sqlite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-multi--stage-2496ED?logo=docker&logoColor=white)

</div>

---

## The problem

Revenue loss rarely happens in one clean step. A payment degrades, a checkout is abandoned, a subscription fails, an invoice goes overdue — and each one silently leaks money. Fixing it well needs more than a notification: you have to **detect** the risk, **diagnose why** it happened, **pick the right intervention**, and **execute it under guardrails** — then prove the money actually came back.

Fail2Pay closes that loop end-to-end, with one non-negotiable rule at the core:

> **Only verified, captured payments count as recovered revenue.**
> A promise in chat, a "will pay" message, or a simulated capture is never treated as money.

```
Revenue Event (webhook / trigger / simulation)
       │
       ▼
   ┌─────────────┐
   │   DETECT     │  payment.failed · checkout abandoned · subscription failed · invoice overdue
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │  DIAGNOSE    │  Root cause: Technical? Liquidity? Mandate? Hesitation? Fraud?
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │ INTERVENE    │  Right action: Retry? Split EMI? Promise-to-pay? Nudge? Escalate? Hard stop?
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │  RECOVER     │  WhatsApp / Email / Payment link  →  verified captured payment
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │   AUDIT      │  Every decision, every message, every state change logged + streamed
   └─────────────┘
```

---

## What counts: measured recovery

- **Verified Impact Ledger** — `GET /api/simulation/impact-ledger` shows the funnel *At Risk → Intervention Dispatched → Promise Captured → Verified Recovered*. Only `payment.captured` webhooks and real gateway captures create `Payment` rows; customer messages and promises never do.
- **Revenue Map & dashboards** — `GET /api/analytics/*` roll up verified recovered amount, cost-of-recovery ratio, and per-case outcomes.
- **Agent Thought Stream** — every case persists its reasoning chain (Trigger → Diagnosis → Policy → Action → Ledger), visible live over WebSocket and replayable via `GET /api/cases/{id}/policy-trace`.

---

## Feature tour

### 1. Payment degradation → root cause → recovery action
- **Webhook-driven detection** — Razorpay `payment.failed`, `subscription.auth.failed`, `payment.authorization.failed` create a recovery case instantly (idempotent; duplicate events are skipped).
- **Root-cause diagnosis** — 7 categories (Technical Glitch, Liquidity, User Hesitation, Mandate Expiry, Account Issue, Fraud Risk, Unknown) from gateway failure codes.
- **Risk engine** — amount thresholds + failure count + account status → HIGH / MEDIUM / LOW, and whether the case is recoverable at all.
- **Multi-turn agent dialogue** — WhatsApp Business-style chat with quick-reply buttons, payment-link cards, and split-EMI options.

### 2. Checkout drop-off recovery
`POST /api/triggers/checkout-abandoned` ingests cart-abandonment signals (amount, cart ref, abandonment count) straight into the same recovery pipeline.

### 3. Failed-subscription recovery
Mandate re-setup flow for expired/declined recurring mandates — smart retry sequencing instead of blind re-charging of a dead mandate.

### 4. B2B receivables chaser
Scans receivable invoices, transitions `PENDING → OVERDUE` past due date, and drives a **5-tier escalation ladder** with automated email at each tier:

| Tier | Days overdue | Tone |
|---|---|---|
| FRIENDLY_REMINDER | 1–7 | Warm, helpful |
| FORMAL_NOTICE | 8–30 | Firm, professional |
| MANAGEMENT_ESCALATION | 31–60 | Urgent, CC management |
| FINAL_DEMAND | 61–90 | Legal language, deadline |
| LEGAL_COLLECTION | 91+ | Collections referral |

Partial/full payments, write-offs, disputes, and a batch runner (`POST /api/receivables/batch/run`) all flow into the same audit trail.

### 5. Mandate retry sequencer
`GET /api/plans/{id}/retry-sequencer` detects UPI/autopay degradation (3+ failures) and recommends a strategy — rewarded **split plan** (50% now + 50% in 14 days) vs **alternate-gateway** link — with a timestamped retry timeline.

### 6. Promise-to-pay tracker
Customer commits a date → real `Promise` row → reminder scheduled for 11:00 AM IST → a broken promise escalates to a payment plan automatically. Language-aware date parsing ("kal", "kal 11 baje").

### 7. Hinglish voice & multilingual recovery
Romanized Hinglish copy across the agent, language detection (English / Hindi / Hinglish / Odia), mid-conversation switching ("Hindi mein baat karein"), and an IVR voice-recovery path — all deterministic templates, never ad-hoc AI copy.

---

## Compliance, safety & audit

- **10 hard-stop conditions** — payment succeeded, customer stopped, opted out, max attempts, deadline passed, plan cancelled, invoice paid, dispute, terminal state, conflicting action.
- **Opt-out enforcement** — multilingual keywords ("stop", "unsubscribe", "mat bhejo", "band karo") short-circuit everything, including AI.
- **Attempt limits** — default 5 max attempts, then monitor mode: the agent stops automated outreach and the merchant drives the case manually.
- **Bounded AI** — AI classifies intent only; every action, message and state change is deterministic code (see below).
- **31 audit event types** — every decision, message, payment and escalation is logged to `AuditEvent` and replayable via the policy trace.

---

## AI: the right tool in the right place

AI is used **only** for intent classification — understanding what the customer means. Everything that touches money, policy, or compliance is deterministic code. When the AI provider is down, rate-limited (429), or unconfigured, the system **falls back to rule-based classification** without skipping a beat — no hard dependency, no silent degradation of safety.

| Layer | AI? | Approach |
|---|---|---|
| Intent detection | ✅ | Bounded classification into 11 intents, rule-based fallback |
| Agent copy | ❌ | Deterministic templates personalized from context |
| Root-cause diagnosis | ❌ | Code lookup against gateway failure codes |
| Risk assessment | ❌ | Amount thresholds + failure-count rules |
| Sentiment analysis | ❌ | Keyword-based (Cooperative / Frustrated / Neutral) |
| Escalation tiers | ❌ | Calendar arithmetic (overdue days → tier) |
| Hard stops / opt-out | ❌ | 10 boolean conditions, keyword enforcement |
| Installment math | ❌ | Integer division with remainder distribution |
| Audit logging | ❌ | Every event recorded deterministically |

---

## Architecture

```
fail2pay/
├── backend/                     # FastAPI app (Python 3.10+)
│   ├── app/
│   │   ├── models/              # 21 SQLAlchemy models
│   │   ├── schemas/             # Pydantic request/response contracts
│   │   ├── crud/                # 14 query modules
│   │   ├── routes/              # 14 API routers
│   │   ├── services/            # 37 business-logic modules
│   │   │   ├── agent_engine.py      # Deterministic contextual agent copy
│   │   │   ├── agent_flow.py        # Multi-turn dialogue driver
│   │   │   ├── audit_logger.py      # 31 audit event types
│   │   │   ├── hard_stop.py         # 10 hard-stop conditions
│   │   │   ├── intent_detector.py   # Bounded AI intent (rule fallback)
│   │   │   ├── receivables_chaser.py# B2B overdue escalation
│   │   │   ├── retry_sequencer.py   # Mandate degradation strategy
│   │   │   ├── root_cause.py        # Root-cause diagnosis
│   │   │   ├── scheduler.py         # Autonomous background loop
│   │   │   ├── webhook_handler.py   # Razorpay webhook processing
│   │   │   └── workflow_engine.py   # State machine + finalizer
│   │   └── workers/             # Background tasks
│   ├── alembic/                 # DB migrations (alembic upgrade head)
│   └── requirements.txt
├── frontend/                    # React + TypeScript + Vite ops console
│   └── src/
│       ├── pages/               # Dashboard, Cases, Conversation, Revenue Map…
│       ├── components/          # Charts, cards, live agent stream
│       └── services/            # Typed API clients + WebSocket
├── Dockerfile                   # Multi-stage production build
├── deploy/entrypoint.sh         # Migrate + start
└── README.md
```

**Stack:** FastAPI · SQLAlchemy 2 · Pydantic v2 · React + TS + Vite + Tailwind · PostgreSQL (SQLite for local dev) · Razorpay · WhatsApp Cloud API · Resend · Docker + Alembic.

---

## Quickstart

> **Prereqs:** Python 3.10+, Node 18+, and (optionally) PostgreSQL. The backend runs on SQLite with zero external services for local dev.

### 1. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then edit DATABASE_URL (see below)
```

**Database — pick one:**

```bash
# A) Zero-setup SQLite (great for the demo)
export DATABASE_URL="sqlite:///./fail2pay.db"
python -c "import app.models; from app.database import Base, engine; Base.metadata.create_all(engine)"

# B) PostgreSQL (production-like) — needs a running postgres
export DATABASE_URL="postgresql://user:password@localhost:5432/fail2pay"
alembic upgrade head
```

**Start the API:**

```bash
uvicorn app.main:app --reload     # → http://localhost:8000  (health: GET /health)
```

### 2. Frontend (ops console)

```bash
cd frontend
npm install
npm run dev                       # → http://localhost:5173
```

The dev server proxies `/api/*` and `/ws/*` to the backend, so the dashboard, live agent stream and case console work out of the box.

### 3. Docker (single container, backend + built frontend)

```bash
docker build -t fail2pay .
docker run -d --rm --name fail2pay --env-file .env -p 8000:8000 fail2pay
```

The entrypoint runs `alembic upgrade head`, starts uvicorn, and serves the built React app at `/`. Healthcheck: `GET /health`.

---

## See it recover money in 60 seconds

Everything below is clearly marked `DEMO_SIMULATION` and can be wiped with `DELETE /api/simulation/reset`.

```bash
# Batch: 100 controlled failed transactions through the full pipeline
curl -X POST http://localhost:8000/api/simulation/run

# Single case (returns a clickable case id)
curl -X POST http://localhost:8000/api/simulation/single \
     -H 'Content-Type: application/json' -d '{"amount": 49900, "name": "Asha Rao"}'

# The verified funnel + per-case ledger (only captured payments count)
curl http://localhost:8000/api/simulation/impact-ledger

# Analytics: recovered amount, recovery rate, cost-of-recovery
curl http://localhost:8000/api/analytics/summary
```

**Simulate the customer conversation on a real case** (drive the full intent → policy → action loop):

```bash
curl -X POST http://localhost:8000/api/cases/{case_id}/simulate-message \
     -H 'Content-Type: application/json' -d '{"trigger": "promise_tomorrow"}'
# triggers: promise, stop, installments, pay_link, support, wrong_bill,
#           language_hi, language_en, pay_now, split_2 … split_4
```

**Or replay the real Razorpay webhook flow:**

```bash
curl -X POST http://localhost:8000/api/webhooks/razorpay \
     -H 'Content-Type: application/json' -d '{
       "id": "evt_demo_1", "event": "payment.failed",
       "payload": {"payment": {"entity": {
         "id": "pay_demo_1", "order_id": "order_demo_1", "amount": 49900,
         "currency": "INR", "status": "failed", "method": "card",
         "email": "asha@example.com", "contact": "+919999000001",
         "customer_id": "cust_demo_1",
         "error_code": "BAD_REQUEST_ERROR",
         "error_description": "The payment was declined by your bank"}}}}'
```

> If you set `RAZORPAY_WEBHOOK_SECRET` in `.env`, webhooks must be signed (HMAC-SHA256 of the raw body in `X-Razorpay-Signature`). Leave it empty for local/dev testing.

---

## API surface (highlights)

**Recovery & webhooks**

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health`, `/api/health` | Liveness |
| POST | `/api/webhooks/razorpay` | Razorpay events (idempotent, signature-verified) |
| GET/POST | `/api/webhooks/whatsapp` · `/api/whatsapp/webhook` | WhatsApp verify + inbound messages |
| GET | `/api/cases/{id}/policy-trace` · `/timeline` · `/agent-steps` | Decision audit trail |
| POST | `/api/cases/{id}/simulate-message` · `/agent-initial` · `/generate-email` | Demo + email sync |

**Simulation**

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/simulation/run` · `/single` | Batch (100) / single demo cases |
| GET | `/api/simulation/impact-ledger` · `/analytics` | Verified impact funnel |
| DELETE | `/api/simulation/reset` | Wipe demo data |

**External revenue triggers**

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/triggers/checkout-abandoned` | Cart abandonment |
| POST | `/api/triggers/aging-invoice` | Overdue B2B invoice |
| POST | `/api/triggers/mandate-drop` | Recurring mandate failure |
| POST | `/api/triggers/subscription-failure` | Subscription renewal failure |

**B2B receivables**

| Method | Endpoint | Purpose |
|---|---|---|
| POST/GET | `/api/receivables` | Create / list invoices |
| GET | `/api/receivables/summary` · `/{id}` · `/{id}/events` | Metrics, detail, escalation trail |
| POST | `/api/receivables/{id}/pay` · `/write-off` · `/dispute` · `/escalate` | Actions |
| POST | `/api/receivables/batch/run` | Batch overdue scan + escalate + email |

**Console & analytics**

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/analytics/summary` · `/revenue-map` · `/recovery-cases` | Revenue dashboard |
| GET | `/api/payment-plans` · `/conversations` · `/invoices` | Ops lists |
| GET | `/api/plans/{id}/retry-sequencer` | Mandate degradation strategy |
| GET/PUT | `/api/settings/recovery` | Merchant recovery policy |
| GET | `/api/checkout-abandonments[/summary]` · `/api/subscription-failures[/summary]` | Failure consoles |
| POST | `/api/operations/autonomous/scheduler/run` | Run one scheduler pass |

---

## Database models (21)

| Model | Purpose |
|---|---|
| Customer, RevenueEvent | Who, what failed |
| RecoveryCase, RecoveryAttempt, RecoverySetting | Case lifecycle + merchant policy |
| Conversation, ConversationMessage | WhatsApp/email threads |
| PaymentPlan, Installment | EMI / split plans |
| Invoice, Payment, PaymentLink | Billing + **verified** captures |
| Promise | Intent-to-pay tracking |
| AuditEvent, WebhookEvent | Audit trail + idempotency |
| ScheduledAction, SentEmail | Reminders + outbound mail |
| ReceivableInvoice, ReceivableEscalationEvent | B2B chaser |
| CheckoutAbandonment, SubscriptionFailure | Drop-off / renewal failures |

---

## Environment variables

Copy `backend/.env.example` → `backend/.env`. The app fails fast at startup if mandatory keys are missing.

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | ✅ | PostgreSQL (or `sqlite:///./fail2pay.db` for dev) |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | ✅ | Razorpay test keys |
| `RAZORPAY_WEBHOOK_SECRET` | dev: ✗ | Empty ⇒ webhook signatures skipped |
| `API_KEY` | ✗ | Set to enforce Bearer auth on private `/api/*` |
| `AI_API_KEY` / `AI_MODEL` | ✗ | Empty / outage ⇒ rule-based fallback |
| `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` / `WHATSAPP_VERIFY_TOKEN` | ✗ | Without them, messages are generated + stored (not delivered) |
| `EMAIL_PROVIDER` / `EMAIL_API_KEY` / `EMAIL_FROM_*` | ✗ | `resend` or `mock`; empty key ⇒ log-only |
| `PAYMENT_LINK_BASE_URL` | ✗ | Public payment link host |

> **Email:** leave `EMAIL_API_KEY` empty for mock/log-only mode — every send is still recorded in `SentEmail` with `delivery_status`.

---

## Notes & design decisions

- **Recovery without a gateway**: if WhatsApp/Resend are unconfigured, outbound messages are still *generated, persisted and broadcast* (delivery_status `not_configured`) — the decision logic is fully exercisable without external accounts.
- **Idempotency everywhere**: duplicate webhooks, revenue events, payments and escalations are detected and skipped.
- **Deterministic finalizers**: a verified capture closes promises, cancels pending reminders, marks invoices paid and expires payment links in one idempotent pass.
