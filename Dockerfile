# Closet Cupid: one container serves the app and its API.

# 1. Build the app.
FROM node:22-slim AS app
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2. The API, with the fashion model on CPU.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --extra vision --no-dev
COPY backend/ ./
COPY --from=app /app/dist /srv/frontend/dist
ENV CUPID_FRONTEND=/srv/frontend/dist
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync uvicorn cupid.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
