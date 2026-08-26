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
├── frontend/   # React + TypeScript + Vite app
├── backend/    # FastAPI app
└── tests/      # Backend tests
```

## Local Setup

### Prerequisites

- Node.js 18+
- Python 3.11+
- PostgreSQL (optional for now — the backend starts without it)

### Backend

```bash
cd backend
python -m venv .venv
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
pytest ../tests
```
