# Fail2Pay

Fail2Pay is an autonomous revenue recovery platform that detects revenue at risk and automatically executes bounded recovery workflows.

## Tech Stack

**Frontend:** React + TypeScript + Vite + Tailwind CSS + Recharts

**Backend:** Python + FastAPI + SQLAlchemy + Pydantic

**Database:** PostgreSQL

**Future integrations:** Razorpay (test mode + webhooks), WhatsApp Cloud API, Email, AI API — none of these are implemented yet.

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
- ✅ 10 SQLAlchemy models (Customer, RevenueEvent, RecoveryCase, etc.)
- ✅ Pydantic schemas for all models
- ✅ CRUD functions for Customer, RevenueEvent, RecoveryCase
- ✅ Database initialization support
- ✅ Environment variable configuration

### Frontend

- ✅ React app with Tailwind CSS
- ✅ Backend status indicator (Connected/Offline)
- ✅ Health check service
- ✅ TypeScript throughout

### Tests

- ✅ 26 tests passing (health check + model tests + relationship tests)

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
- ✅ Frontend displaying status
- ✅ Database models and schemas ready
- ✅ All tests passing

**Next steps:** Razorpay integration, WhatsApp/Email, AI features, recovery logic, dashboard.
