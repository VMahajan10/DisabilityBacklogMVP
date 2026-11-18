#!/usr/bin/env bash
# Start backend (FastAPI :8000) and frontend (Vite :5173) together. Ctrl-C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
trap 'kill 0' EXIT INT TERM
(cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --reload --port 8000) &
(cd "$ROOT/frontend" && npm run dev -- --port 5173 --strictPort) &
echo "Backend:  http://127.0.0.1:8000/docs"
echo "Frontend: http://localhost:5173"
wait
