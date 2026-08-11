#!/bin/bash
# Voice Studio local preview: backend + mock GPU worker + frontend dev server.
# The frontend dev server is the exposed port (5173) and proxies /api and /auth
# to the backend (8000). Use the mock worker by default so no GPU is needed.
#
# Usage:
#   ./start.sh                # backend (8000) + mock worker + frontend (5173)
#   WORKER_BACKEND=qwen ./start.sh   # real GPU worker (GPU host only)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
WORKER_BACKEND="${WORKER_BACKEND:-mock}"

# Backend env. Copy backend/.env.example to backend/.env to override.
export WORKER_TOKEN="${WORKER_TOKEN:-dev-worker-token}"
export DEV_LOGIN="${DEV_LOGIN:-1}"
export FRONTEND_URL="${FRONTEND_URL:-http://localhost:5173}"

echo ">> Starting backend on :8000"
(
  cd "$ROOT/backend"
  exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
) &
BACKEND_PID=$!

# Wait for the backend to accept connections.
for i in $(seq 1 30); do
  if curl -fsS "$BACKEND_URL/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo ">> Starting GPU worker (backend=$WORKER_BACKEND)"
(
  cd "$ROOT/worker"
  export BACKEND_URL="$BACKEND_URL"
  export WORKER_BACKEND="$WORKER_BACKEND"
  exec python3 -m qwen_tts_worker.main --backend "$WORKER_BACKEND"
) &
WORKER_PID=$!

cleanup() {
  echo ">> Shutting down..."
  kill "$WORKER_PID" "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ">> Starting frontend on :5173"
(
  cd "$ROOT/frontend"
  exec npm run dev
)
