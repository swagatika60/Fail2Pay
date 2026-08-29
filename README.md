# Fail2Pay

Fail2Pay is an autonomous revenue recovery platform that detects revenue at risk and automatically executes bounded recovery workflows.

## Tech Stack

**Frontend:** React + TypeScript + Vite + Tailwind CSS + Recharts

**Backend:** Python + FastAPI + SQLAlchemy + Pydantic

**Database:** PostgreSQL

**Integrations:** Razorpay (test mode + idempotent webhooks), WhatsApp Cloud API, Email (SmTP, recoverable dispatches), AI intent detection, automated recovery workflows with policy engine, scheduling, hard stops, and audit logging.

## Project Structure

```
fail2pay/
├── frontend/           # React + TypeScript + Vite app
│   └── src/
│       ├── components/ # UI components (layout, dashboard, revenue, etc.)
│       ├── pages/      # Page components
│       ├── services/   # API service functions
│       ├── hooks/      # Custom React hooks
│       ├── types/      # TypeScript type definitions
│       └── lib/        # Utility functions
│
├── backend/            # FastAPI app
│   └── app/
│       ├── models/     # SQLAlchemy database models
│       ├── schemas/    # Pydantic request/response schemas
│       ├── crud/       # Database query functions
│       ├── routes/     # API route handlers
│       ├── services/   # Business logic
│       ├── workers/    # Background tasks
│       └── utils/      # Utility functions
│
└── tests/              # Backend tests

# Root
Dockerfile              # Multi-stage production build (frontend + backend)
.dockerignore
deploy/
└── entrypoint.sh       # Container startup: alembic migrations + uvicorn
```

## What's Built

### Backend

- ✅ FastAPI app with health check endpoint (`GET /health`)
- ✅ 14 SQLAlchemy models (Customer, RevenueEvent, RecoveryCase, etc.)
- ✅ Pydantic schemas for all models
- ✅ CRUD functions for all entities
- ✅ Razorpay test-mode orders + idempotent webhook handler
- ✅ WhatsApp Cloud API client (message send/receive)
- ✅ Email delivery service (dispatches, receipts, retries)
- ✅ Recovery orchestrator: policy engine, intent detection, promise lifecycle, installment workflows, hard stops
- ✅ Scheduler background engine, simulation routes, audit logging
- ✅ Deterministic decision audit trail + policy inspector endpoint (`GET /api/cases/{id}/policy-trace`)
- ✅ Explicit opt-out & stopping rules (`POST /api/cases/{id}/simulate-message`)
- ✅ Payment degradation & mandate retry sequencer (`GET /api/plans/{id}/retry-sequencer`)
- ✅ Batch recovery simulation + verified impact ledger (`GET /api/simulation/impact-ledger`) — only captured payments count as recovered revenue
- ✅ Contextual & empathetic agent engine (`agent_engine.py` + `agent_flow.py`): human-like copy, structured quick-reply/payment-card/language payloads, split-EMI plans, promise reminders, wrong-bill/human escalation
- ✅ Synchronized transactional HTML email generation (`POST /api/cases/{id}/agent-initial`, `POST /api/cases/{id}/generate-email`)
- ✅ Database initialization support
- ✅ Environment variable configuration

### Frontend

- ✅ React app with Tailwind CSS
- ✅ Backend status indicator (Connected/Offline)
- ✅ Revenue dashboard with metrics, revenue-flow chart, recovery table
- ✅ Case detail page (timeline, promises, payment plans, conversations, emails, hard stops)
- ✅ WhatsApp Business-style conversation thread (sender badges w/ verified tick, quick-reply buttons, payment link cards, typing indicator)
- ✅ HTML email preview rendering in the Emails tab
- ✅ Interactive multi-turn simulate-customer-reply controls (quick replies, run full dialogue cycle)
- ✅ Policy inspector modal, retry sequencer panel, verified impact ledger / funnel UI
- ✅ Recovery simulation page
- ✅ Health check service
- ✅ TypeScript throughout

### Tests

- ✅ 978 tests passing across the backend suite (health, models, payments, webhooks, WhatsApp, email, PDF invoices, recovery workflow, batch simulation, revenue map, recovery settings, policy trace, simulation/messaging, impact ledger, agent engine)

## Database Models

| Model | Purpose |
|-------|---------|
| **Customer** | Customer information (email, phone, name) |
| **RevenueEvent** | Failed payment events from Razorpay |
| **RecoveryCase** | Recovery process tracking |
| **RecoveryAttempt** | Individual recovery attempts |
| **Conversation** | Customer conversations (WhatsApp, email) |
| **ConversationMessage** | Individual messages |
| **PaymentPlan** | Payment recovery plans |
| **Installment** | Payment installments |
| **Invoice** | Invoices for payments |
| **AuditEvent** | Audit trail for all changes |
| **WebhookEvent** | Incoming webhook event log |
| **ScheduledAction** | Scheduled recovery actions |
| **SentEmail** | Outbound email records |
| **Promise** | Payment promises / intent to pay |

## Local Setup

### Prerequisites

- Node.js 18+
- Python 3.10+
- PostgreSQL (optional for now — the backend starts without it)

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in values when needed
uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000`. Health check: `GET http://localhost:8000/health`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The app runs at `http://localhost:5173` and proxies `/api/*` to the backend.

### Docker (production build)

The repo ships a multi-stage `Dockerfile` that builds the React frontend into static
assets, installs the backend dependencies, and produces a single runtime image that
**serves both the API and the built frontend** (no separate `npm run dev` needed).

| Stage | Base | Purpose |
|-------|------|---------|
| `frontend-build` | `node:22-alpine` | `npm ci` + `npm run build` → `dist/` |
| `backend-deps` | `python:3.12-slim` | install backend requirements |
| `runtime` | `python:3.12-slim` | FastAPI + serves `frontend/dist`, runs migrations via entrypoint |

On container startup, `deploy/entrypoint.sh` runs `alembic upgrade head` (set
`FAIL2PAY_SKIP_MIGRATIONS=1` to skip) then launches uvicorn on `0.0.0.0:8000`.

```bash
# 1. Build the image
docker build -t fail2pay .

# 2. Run it, mounting your .env (needs DATABASE_URL + API keys)
docker run -d --rm --name fail2pay \
  --env-file .env \
  -p 8000:8000 \
  fail2pay

# 3. Open the app
#    http://localhost:8000    (frontend + API)
#    http://localhost:8000/health
```

The container exposes port `8000` with a built-in healthcheck. There is currently
**no** `docker-compose.yml`; if you want to run PostgreSQL alongside the app with a
single `docker compose up`, add one (or ask — it can be added).

### Tests

```bash
cd backend
source .venv/bin/activate
python -m pytest ../tests/ -v
```

### Initialize Database (when PostgreSQL is configured)

```bash
cd backend
source .venv/bin/activate
python -m app.init_db
```

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```bash
DATABASE_URL=  # PostgreSQL connection string
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
AI_API_KEY=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_VERIFY_TOKEN=
EMAIL_API_KEY=
```

## Current Status

- ✅ Project structure complete
- ✅ Backend health check working
- ✅ Frontend building and linting clean
- ✅ Database models and schemas ready
- ✅ Razorpay, WhatsApp, Email integrations wired
- ✅ Automated recovery workflows (orchestrator, policy engine, scheduler)
- ✅ Contextual & empathetic agent engine (WhatsApp Business thread UI, split-EMI plans, human escalation, synchronized email threads)
- ✅ Decision audit trail, explicit opt-out/stopping rules, retry sequencer, verified impact ledger
- ✅ Multi-stage production Docker build (Dockerfile + deploy/entrypoint.sh, healthcheck)
- ✅ All 978 tests passing

**Next steps:** live channel credentials (Razorpay/WhatsApp/Email), PostgreSQL persistence, AI risk-scoring volumes, production deployment.
