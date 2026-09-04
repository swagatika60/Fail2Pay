<div align="center">

# Fail2Pay

An AI revenue-recovery platform that detects revenue at risk, diagnoses the root cause, chooses the right intervention, and executes a bounded, fully audited recovery workflow — from failed payments and checkout abandonment to failed subscriptions and overdue B2B receivables.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React_19-61DAFB?logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-6-3178C6?logo=typescript&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)

</div>

---

## Overview

Revenue loss rarely happens as a single event. A payment degrades, a checkout is abandoned, a subscription renewal fails, or an invoice goes overdue — and each is a separate, silent leak. Recovering that revenue requires closing a full loop: detect the risk, understand why it happened, choose the right intervention, execute it under guardrails, and prove the money actually came back.

Fail2Pay implements that loop end to end:

```
revenue signal (webhook / trigger / simulation)
      │
      ▼
detect ──► recovery case + root-cause diagnosis + risk score
      │
      ▼
diagnose ──► bounded intervention: retry, split plan, promise-to-pay,
             payment link, escalation, or hard stop
      │
      ▼
recover ──► a captured payment (webhook-verified) is the only event
            that counts as recovered revenue
      │
      ▼
audit ──► every decision, message, and state change is logged and
          replayable via a per-case policy trace
```

The system follows one design rule above all others:

> **Only verified, captured payments count as recovered revenue.** A promise in chat or a "will pay" message is never treated as money.

---

## Capabilities

### Payment recovery and diagnosis

- **Webhook-driven detection.** Razorpay `payment.failed`, `subscription.auth.failed`, and `payment.authorization.failed` events create a recovery case immediately. Processing is idempotent — duplicate events are skipped.
- **Root-cause diagnosis.** Failures are classified into one of seven causes (technical glitch, liquidity, user hesitation, mandate expiry, account issue, fraud risk, unknown) from gateway failure codes.
- **Risk scoring.** Amount, failure history, and account status produce a HIGH / MEDIUM / LOW risk level and a recoverability decision.
- **Agent dialogue.** A WhatsApp-style conversation with quick-reply buttons, payment-link cards, and split-EMI options is driven by deterministic, context-aware templates.

### Checkout and subscription drop-off recovery

`POST /api/triggers/checkout-abandoned` and `POST /api/triggers/subscription-failure` ingest cart-abandonment and renewal-failure signals into the same recovery pipeline. Mandate drops get a re-setup flow with smart retry sequencing rather than blind re-charging of a dead mandate.

### B2B receivables chaser

Receivable invoices transition `PENDING → OVERDUE` once past their due date and move through a five-tier escalation ladder, with an automated email dispatched at each tier:

| Tier | Days overdue | Tone |
|---|---|---|
| Friendly reminder | 1–7 | Warm, helpful |
| Formal notice | 8–30 | Firm, professional |
| Management escalation | 31–60 | Urgent, CC management |
| Final demand | 61–90 | Legal language, deadline |
| Legal collection | 91+ | Collections referral |

Partial and full payments, write-offs, disputes, and a batch runner (`POST /api/receivables/batch/run`) are all recorded in the same audit trail.

### Promises and payment plans

A customer commitment is stored as a real `Promise` row with a scheduled reminder; a broken promise escalates to a payment plan. Installment plans support split amounts, per-installment tracking, and a degradation detector (`GET /api/plans/{id}/retry-sequencer`) that recommends a rewarded split plan or an alternate-gateway link after repeated failures.

### Multilingual and voice recovery

Agent copy is available in English, Hindi, Hinglish, and Odia, with mid-conversation language switching ("Hindi mein baat karein"). An IVR voice-recovery path uses the same deterministic templates.

---

## Compliance, safety, and audit

- **Ten hard-stop conditions** halt outreach when a payment succeeds, a customer opts out, attempts exceed the limit, a deadline passes, a plan is cancelled, an invoice is paid, a dispute is filed, or a case reaches a terminal state.
- **Opt-out enforcement** uses multilingual keywords ("stop", "unsubscribe", "mat bhejo", "band karo") that short-circuit all processing, including AI.
- **Attempt caps** default to five, after which the case enters monitor mode and automated outreach stops.
- **Thirty-one audit event types** record every decision, message, payment, and escalation. Each case exposes a replayable policy trace (`GET /api/cases/{id}/policy-trace`) and a live reasoning stream over WebSocket.

---

## AI usage

AI is used only for intent classification. Every action that touches money, policy, or compliance is implemented as deterministic code, and intent detection falls back to rule-based classification when an AI provider is unconfigured, rate-limited, or unavailable.

| Layer | AI used | Implementation |
|---|---|---|
| Intent detection | Yes | Bounded classification into 11 intents, rule-based fallback |
| Agent copy | No | Deterministic templates personalized from context |
| Root-cause diagnosis | No | Code lookup against gateway failure codes |
| Risk assessment | No | Amount thresholds and failure-count rules |
| Escalation tiers | No | Calendar arithmetic on overdue days |
| Hard stops and opt-out | No | Boolean conditions and keyword enforcement |
| Installment math | No | Integer division with remainder distribution |
| Audit logging | No | Every event recorded deterministically |

---

## Architecture

```
fail2pay/
├── backend/                     # FastAPI application
│   ├── app/
│   │   ├── models/              # 21 SQLAlchemy models
│   │   ├── schemas/             # Pydantic request/response contracts
│   │   ├── crud/                # Query layer
│   │   ├── routes/              # 14 API routers
│   │   ├── services/            # 37 business-logic modules
│   │   │   ├── agent_engine.py      # Deterministic agent copy
│   │   │   ├── agent_flow.py        # Dialogue driver
│   │   │   ├── audit_logger.py      # Audit events
│   │   │   ├── hard_stop.py         # Hard-stop conditions
│   │   │   ├── intent_detector.py   # Bounded AI intent with rule fallback
│   │   │   ├── receivables_chaser.py# B2B overdue escalation
│   │   │   ├── retry_sequencer.py   # Mandate degradation strategy
│   │   │   ├── root_cause.py        # Root-cause diagnosis
│   │   │   ├── scheduler.py         # Autonomous background loop
│   │   │   ├── webhook_handler.py   # Razorpay webhook processing
│   │   │   └── workflow_engine.py   # Case state machine
│   │   └── workers/             # Background tasks
│   ├── alembic/                 # Database migrations
│   └── requirements.txt
├── frontend/                    # React + TypeScript + Vite ops console
│   └── src/
│       ├── pages/               # Dashboard, cases, conversation, revenue map
│       ├── components/          # Charts, cards, live agent stream
│       └── services/            # Typed API clients and WebSocket
├── Dockerfile                   # Multi-stage production build
└── deploy/entrypoint.sh         # Migration + start script
```

**Stack:** FastAPI · SQLAlchemy 2 · Pydantic v2 · React 19 + TypeScript + Vite + Tailwind · PostgreSQL (SQLite for local development) · Razorpay · WhatsApp Cloud API · Resend · Docker + Alembic.

---

## Getting started

**Prerequisites:** Python 3.10+, Node 18+, and optionally PostgreSQL. The backend runs on SQLite with no external services for local development.

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Configure the database (pick one):

```bash
# Option A — SQLite for local development
export DATABASE_URL="sqlite:///./fail2pay.db"
python -c "import app.models; from app.database import Base, engine; Base.metadata.create_all(engine)"

# Option B — PostgreSQL
export DATABASE_URL="postgresql://user:password@localhost:5432/fail2pay"
alembic upgrade head
```

Start the API:

```bash
uvicorn app.main:app --reload    # http://localhost:8000 — health check at GET /health
```

### Frontend

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

The dev server proxies `/api/*` and `/ws/*` to the backend, so the dashboard, live agent stream, and case console work out of the box.

### Docker

```bash
docker build -t fail2pay .
docker run -d --rm --name fail2pay --env-file .env -p 8000:8000 fail2pay
```

The entrypoint runs `alembic upgrade head`, starts the API, and serves the built React app at `/`.

### Demo data

Simulation data is marked `DEMO_SIMULATION` and can be cleared with `DELETE /api/simulation/reset`.

```bash
# Run 100 failed transactions through the full pipeline
curl -X POST http://localhost:8000/api/simulation/run

# Create a single case (returns its id)
curl -X POST http://localhost:8000/api/simulation/single \
     -H 'Content-Type: application/json' -d '{"amount": 49900, "name": "Asha Rao"}'

# Verified-impact funnel: only captured payments count
curl http://localhost:8000/api/simulation/impact-ledger
```

To drive a full conversation on a real case:

```bash
curl -X POST http://localhost:8000/api/cases/{case_id}/simulate-message \
     -H 'Content-Type: application/json' -d '{"trigger": "promise_tomorrow"}'
# Available triggers: promise, stop, installments, pay_link, support, wrong_bill,
# language_hi, language_en, pay_now, split_2 … split_4
```

---

## API overview

**Recovery and webhooks**

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/webhooks/razorpay` | Razorpay events (idempotent, signature-verified) |
| GET/POST | `/api/webhooks/whatsapp` · `/api/whatsapp/webhook` | WhatsApp verification and inbound messages |
| GET | `/api/cases/{id}/policy-trace` · `/timeline` · `/agent-steps` | Decision audit trail |
| POST | `/api/cases/{id}/simulate-message` · `/agent-initial` · `/generate-email` | Conversation simulation and email sync |

**Simulation**

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/simulation/run` · `/single` | Batch / single demo cases |
| GET | `/api/simulation/impact-ledger` · `/analytics` | Verified-impact metrics |
| DELETE | `/api/simulation/reset` | Clear demo data |

**Revenue triggers**

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/triggers/checkout-abandoned` | Cart abandonment |
| POST | `/api/triggers/aging-invoice` | Overdue B2B invoice |
| POST | `/api/triggers/mandate-drop` | Recurring mandate failure |
| POST | `/api/triggers/subscription-failure` | Subscription renewal failure |

**B2B receivables**

| Method | Endpoint | Purpose |
|---|---|---|
| POST/GET | `/api/receivables` | Create and list invoices |
| GET | `/api/receivables/summary` · `/{id}` · `/{id}/events` | Metrics, detail, escalation trail |
| POST | `/api/receivables/{id}/pay` · `/write-off` · `/dispute` · `/escalate` | Invoice actions |
| POST | `/api/receivables/batch/run` | Batch overdue scan, escalation, and email |

**Console and analytics**

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/analytics/summary` · `/revenue-map` · `/recovery-cases` | Revenue dashboard |
| GET | `/api/payment-plans` · `/conversations` · `/invoices` | Operations lists |
| GET | `/api/plans/{id}/retry-sequencer` | Mandate degradation strategy |
| GET/PUT | `/api/settings/recovery` | Merchant recovery policy |
| POST | `/api/operations/autonomous/scheduler/run` | Run one scheduler pass |

---

## Configuration

Copy `backend/.env.example` to `backend/.env`. The application fails fast at startup when mandatory variables are missing.

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL, or `sqlite:///./fail2pay.db` for development |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | Yes | Razorpay test keys |
| `RAZORPAY_WEBHOOK_SECRET` | No (dev) | Empty disables webhook signature verification |
| `API_KEY` | No | Enables Bearer-token auth on private `/api/*` routes |
| `AI_API_KEY` / `AI_MODEL` | No | Empty or unavailable falls back to rule-based intent detection |
| `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` / `WHATSAPP_VERIFY_TOKEN` | No | Without them, outbound messages are generated and stored, not delivered |
| `EMAIL_PROVIDER` / `EMAIL_API_KEY` / `EMAIL_FROM_*` | No | `resend` or `mock`; an empty key enables log-only mode |
| `PAYMENT_LINK_BASE_URL` | No | Public host for payment links |

---

## Design notes

- **Runs without external providers.** When WhatsApp or email providers are unconfigured, outbound messages are still generated, persisted, and broadcast with `delivery_status: not_configured`, so the full decision pipeline can be exercised locally.
- **Idempotent by construction.** Duplicate webhooks, revenue events, payments, and escalations are detected and skipped.
- **Deterministic finalizers.** A verified capture closes open promises, cancels pending reminders, marks invoices paid, and expires payment links in a single idempotent pass.
