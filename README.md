# Fail2Pay

Fail2Pay is an autonomous AI revenue recovery platform that detects revenue at risk, diagnoses the root cause, chooses the right intervention, and executes bounded recovery workflows — from payment failures and checkout abandonment to failed subscriptions and overdue B2B receivables.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | React + TypeScript + Vite + Tailwind CSS + Recharts |
| **Backend** | Python 3.10+ + FastAPI + SQLAlchemy + Pydantic |
| **Database** | PostgreSQL |
| **Email** | Resend (configurable provider) |
| **Payments** | Razorpay (test mode + idempotent webhooks) |
| **Messaging** | WhatsApp Cloud API |
| **AI** | Bounded intent classification (rule-based fallback) |
| **Deploy** | Docker (multi-stage), Alembic migrations |

## How It Works

```
Revenue Event (webhook / trigger)
       │
       ▼
   ┌─────────────┐
   │   DETECT     │  Razorpay payment.failed / checkout abandoned / subscription failed / invoice overdue
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │  DIAGNOSE    │  Root cause: Technical? Liquidity? Mandate? Hesitation? Fraud?
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │ INTERVENE    │  Right action: Retry? Split EMI? Promise-to-pay? Hinglish nudge? Human escalation? Hard stop?
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │  RECOVER     │  WhatsApp / Email / Payment link → verified captured payment
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │   AUDIT      │  Every decision, every message, every state change logged
   └─────────────┘
```

## Features

### Payment Recovery (B2C)

- **Webhook-driven detection** — Razorpay `payment.failed`, `subscription.auth.failed`, `payment.authorization.failed` create recovery cases instantly
- **Root cause diagnosis** — 7 categories: Technical Glitch, Liquidity Constraint, User Hesitation, Mandate Expiry, Account Issue, Fraud Risk, Unknown
- **Risk assessment** — Amount thresholds + failure count + account status → HIGH / MEDIUM / LOW
- **Multi-turn agent dialogue** — WhatsApp Business-style conversation with quick-reply buttons, payment link cards, split-EMI options
- **Promise-to-pay tracker** — Customer commits a date → reminder scheduled at 11:00 AM IST → broken promise escalates to payment plan
- **Mandate retry sequencer** — Smart retry logic for recurring payment failures with degradation detection
- **Checkout drop-off recovery** — `POST /api/triggers/checkout-abandoned` ingests cart abandonment signals
- **Failed-subscription recovery** — Mandate re-setup flow for expired/declined recurring mandates

### B2B Receivables Chaser

- **Overdue detection** — Scans all receivable invoices, transitions PENDING → OVERDUE when past due date
- **5-tier escalation** with automated email dispatch:

| Tier | Days Overdue | Tone |
|------|-------------|------|
| FRIENDLY_REMINDER | 1-7 days | Warm, helpful |
| FORMAL_NOTICE | 8-30 days | Firm, professional |
| MANAGEMENT_ESCALATION | 31-60 days | Urgent, CC management |
| FINAL_DEMAND | 61-90 days | Legal language, deadline |
| LEGAL_COLLECTION | 91+ days | Collections referral |

- **Automated email sending** — Every escalation sends a real email via Resend (or mock-logs when unconfigured)
- **Payment recording** — Partial and full payments tracked with references and notes
- **Write-off & dispute** — Stop escalation for uncollectible or contested invoices
- **Batch runner** — `POST /api/receivables/batch/run` detects overdue + escalates + sends emails in one call
- **Scheduler integration** — Runs automatically with the autonomous scheduler loop

### Hinglish Voice Recovery

- Full Romanized Hinglish agent copy throughout (`agent_engine.py`)
- Language detection: English, Hindi, Hinglish, Odia
- Culturally-aware personalization ("ji" honorific, "kal 11 baje" promise scheduling)
- Customer can switch languages mid-conversation

### Compliance & Safety

- **10 hard stop conditions** — Payment succeeded, customer stopped, opted out, max attempts, deadline, plan cancelled, invoice paid, dispute, terminal state, conflicting action
- **Opt-out enforcement** — Keywords in English ("stop", "unsubscribe"), Hindi ("mat bhejo"), Hinglish ("band karo")
- **Attempt limits** — Default 5 max attempts, monitor mode after limit
- **Bounded AI** — AI classifies intent only; all actions are deterministic code
- **Deterministic copy** — Agent messages are templates personalized from context, never ad-hoc AI-generated

### Audit Trail

- **31 event types** logged to `AuditEvent` — REVENUE_DETECTED, RISK_DETECTED, INTENT_DETECTED, PROMISE_CREATED, PAYMENT_PLAN_ACCEPTED, HARD_STOP_*, RECEIVABLE_ESCALATED, etc.
- **Policy trace endpoint** — `GET /api/cases/{id}/policy-trace` shows the full deterministic decision chain
- **Receivable escalation events** — Every email sent, tier change, payment, write-off logged to `ReceivableEscalationEvent`
- **Verified Impact Ledger** — `GET /api/simulation/impact-ledger` — only captured payments count as revenue

### Email System

- **Transactional emails** — Failed payment, payment retry, invoice, plan confirmation, promise reminder, payment success
- **B2B escalation emails** — 5 templates with progressively firmer tone
- **Opt-out checks** — Before every send, checks case status, audit history, recent messages
- **Hard stop checks** — Email blocked when case is terminal, customer stopped, or max reached
- **Delivery tracking** — Every email persisted to `SentEmail` with provider message ID

## Project Structure

```
fail2pay/
├── frontend/                    # React + TypeScript + Vite app
│   └── src/
│       ├── components/          # UI components (dashboard, conversation, etc.)
│       ├── pages/               # Page components
│       ├── services/            # API service functions
│       ├── hooks/               # Custom React hooks
│       └── types/               # TypeScript type definitions
│
├── backend/                     # FastAPI app
│   └── app/
│       ├── models/              # 16 SQLAlchemy models
│       ├── schemas/             # Pydantic request/response schemas
│       ├── crud/                # Database query functions
│       ├── routes/              # API route handlers
│       ├── services/            # Business logic (30+ modules)
│       │   ├── agent_engine.py  # Contextual Hinglish agent copy
│       │   ├── agent_flow.py    # Multi-turn dialogue driver
│       │   ├── audit_logger.py  # Centralized audit logging (31 event types)
│       │   ├── email.py         # Email delivery with opt-out checks
│       │   ├── hard_stop.py     # 10 hard stop conditions
│       │   ├── intent_detector.py  # AI intent classification
│       │   ├── receivables_chaser.py  # B2B overdue escalation
│       │   ├── retry_sequencer.py     # Mandate retry logic
│       │   ├── root_cause.py    # Root cause diagnosis
│       │   ├── scheduler.py     # Autonomous background scheduler
│       │   ├── webhook_handler.py     # Razorpay webhook processing
│       │   └── workflow_engine.py     # State machine
│       └── workers/             # Background tasks
│
├── tests/                       # 1060+ tests
│   ├── test_receivables_chaser.py  # 83 tests for B2B chaser
│   ├── test_audit_logger.py        # 35 tests for audit trail
│   ├── test_hard_stop.py           # Hard stop condition tests
│   ├── test_workflow_engine.py     # State machine tests
│   ├── test_e2e_workflow.py        # End-to-end scenario tests
│   └── ...                         # 40+ test modules
│
├── Dockerfile                   # Multi-stage production build
├── deploy/
│   └── entrypoint.sh            # Container startup script
└── README.md
```

## API Endpoints

### Recovery

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/api/webhooks/razorpay` | Razorpay webhook (idempotent) |
| POST | `/api/webhooks/whatsapp` | WhatsApp inbound messages |
| GET | `/api/cases/{id}/policy-trace` | Deterministic decision audit |
| POST | `/api/cases/{id}/simulate-message` | Simulate customer reply |
| GET | `/api/plans/{id}/retry-sequencer` | Mandate retry sequencer |
| GET | `/api/simulation/impact-ledger` | Verified revenue impact |
| GET | `/api/analytics/summary` | Revenue dashboard metrics |
| GET | `/api/analytics/revenue-map` | Full revenue map analytics |

### B2B Receivables

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/receivables` | Create receivable invoice |
| GET | `/api/receivables` | List with filters |
| GET | `/api/receivables/summary` | Dashboard metrics |
| GET | `/api/receivables/{id}` | Get invoice details |
| POST | `/api/receivables/{id}/pay` | Record payment |
| POST | `/api/receivables/{id}/write-off` | Write off as uncollectible |
| POST | `/api/receivables/{id}/dispute` | Mark as disputed |
| POST | `/api/receivables/{id}/escalate` | Manual escalation |
| GET | `/api/receivables/{id}/escalation-preview` | Preview next action |
| GET | `/api/receivables/{id}/events` | Escalation audit trail |
| POST | `/api/receivables/batch/run` | Run batch detection + escalation |

### Triggers

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/triggers/checkout-abandoned` | Cart abandonment signal |
| POST | `/api/triggers/aging-invoice` | Overdue B2B invoice signal |
| POST | `/api/triggers/mandate-drop` | Recurring mandate failure |

## Database Models

| Model | Purpose |
|-------|---------|
| **Customer** | Customer information (email, phone, name) |
| **RevenueEvent** | Failed payment events from Razorpay |
| **RecoveryCase** | Recovery process tracking (10 states) |
| **RecoveryAttempt** | Individual recovery attempts |
| **Conversation** | Customer conversations (WhatsApp, email) |
| **ConversationMessage** | Individual messages |
| **PaymentPlan** | Payment recovery plans |
| **Installment** | Payment installments |
| **Invoice** | Invoices for payments |
| **AuditEvent** | Audit trail (31 event types) |
| **WebhookEvent** | Incoming webhook event log |
| **ScheduledAction** | Scheduled recovery actions |
| **SentEmail** | Outbound email records |
| **Promise** | Payment promises / intent to pay |
| **Payment** | Verified payment records |
| **PaymentLink** | Secure expiring payment links |
| **RecoverySetting** | Per-merchant recovery config |
| **ReceivableInvoice** | B2B overdue invoice tracking |
| **ReceivableEscalationEvent** | Receivable escalation audit trail |

## Setup

### Prerequisites

- Node.js 18+
- Python 3.10+
- PostgreSQL (optional — backend starts without it)

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in values
uvicorn app.main:app --reload
```

API: `http://localhost:8000` | Health: `GET /health`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App: `http://localhost:5173` (proxies `/api/*` to backend)

### Docker

```bash
docker build -t fail2pay .
docker run -d --rm --name fail2pay --env-file .env -p 8000:8000 fail2pay
```

### Tests

```bash
cd backend
source .venv/bin/activate
python -m pytest ../tests/ -v
```

## Environment Variables

```bash
DATABASE_URL=                  # PostgreSQL connection string
RAZORPAY_KEY_ID=               # Razorpay test key
RAZORPAY_KEY_SECRET=           # Razorpay test secret
RAZORPAY_WEBHOOK_SECRET=       # Webhook signature verification
AI_API_KEY=                    # OpenAI key for intent detection (optional)
WHATSAPP_ACCESS_TOKEN=         # WhatsApp Cloud API token
WHATSAPP_PHONE_NUMBER_ID=      # WhatsApp sender phone number
WHATSAPP_VERIFY_TOKEN=         # Webhook verification token
EMAIL_API_KEY=                 # Resend API key (leave empty for mock mode)
EMAIL_PROVIDER=resend          # "resend" or "mock"
EMAIL_PROVIDER_URL=https://api.resend.com/emails
EMAIL_FROM_ADDRESS=noreply@fail2pay.com
EMAIL_FROM_NAME=Fail2Pay
PAYMENT_LINK_BASE_URL=https://fail2pay.example.com
```

> **Email delivery:** Set `EMAIL_API_KEY` to your Resend key and `EMAIL_FROM_ADDRESS` to a verified domain to send real emails. Leave empty for mock/log-only mode.

## AI Usage

AI is used **only** for intent classification — understanding what the customer means in their message. Everything else is deterministic:

| Layer | AI? | Approach |
|-------|-----|----------|
| Intent detection | ✅ Yes | Bounded classification into 11 intents |
| Agent copy | ❌ No | Deterministic templates, personalized from context |
| Root cause diagnosis | ❌ No | Code lookup against gateway failure codes |
| Risk assessment | ❌ No | Amount thresholds + failure count rules |
| Sentiment analysis | ❌ No | Keyword-based (Cooperative/Frustrated/Neutral) |
| Escalation tiers | ❌ No | Calendar arithmetic (overdue days → tier) |
| Hard stops | ❌ No | 10 boolean conditions |
| Installment math | ❌ No | Integer division with remainder distribution |
| Audit logging | ❌ No | Every event recorded deterministically |

## Test Coverage

1060+ tests across 40+ test modules:

- **Unit tests** — Models, schemas, CRUD, services
- **Integration tests** — Webhook processing, email delivery, WhatsApp messages
- **End-to-end tests** — Full recovery scenarios (payment → recovery → audit)
- **Compliance tests** — Hard stops, opt-out, stopping rules, terminal states
- **B2B tests** — Overdue detection, escalation tiers, email templates, batch runner
- **Edge cases** — Duplicate invoices, terminal states, max escalations, partial payments
