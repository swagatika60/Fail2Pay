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
- ✅ Database initialization support
- ✅ Environment variable configuration

### Frontend

- ✅ React app with Tailwind CSS
- ✅ Backend status indicator (Connected/Offline)
- ✅ Revenue dashboard with metrics, revenue-flow chart, recovery table
- ✅ Case detail page (timeline, promises, payment plans, conversations, emails, hard stops)
- ✅ Recovery simulation page
- ✅ Health check service
- ✅ TypeScript throughout

### Tests

- ✅ 902 tests passing across 29 test files (health, models, payments, webhooks, WhatsApp, email, PDF invoices, recovery workflow, batch simulation, revenue map, recovery settings, resilience)

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
- ✅ All 902 tests passing

**Next steps:** live channel credentials (Razorpay/WhatsApp/Email), PostgreSQL persistence, AI risk-scoring volumes, production deployment.
