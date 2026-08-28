# Fail2Pay — Multi-stage production image
#
# Stage 1: Build the React frontend (static assets)
# Stage 2: Install backend Python dependencies
# Stage 3: Runtime image — backend API + serving the built frontend

# ---------------------------------------------------------------------------
# Stage 1 — Frontend build
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend-build

WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — Backend deps
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS backend-deps

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 3 — Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

# Backend code + deps (includes alembic/ + alembic.ini)
COPY --from=backend-deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=backend-deps /usr/local/bin /usr/local/bin
COPY backend/ ./backend/

# Built frontend static assets (served by the backend)
COPY --from=frontend-build /src/frontend/dist /app/frontend/dist

# Entrypoint
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
