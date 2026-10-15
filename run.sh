#!/usr/bin/env bash
# Run EventLens full stack (FastAPI backend + React frontend)
# Usage: ./run.sh [docker|native|down]

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

MODE="${1:-auto}"

have_docker() {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

run_docker() {
  echo "Starting via Docker Compose..."
  docker compose up --build
}

run_native() {
  echo "Starting natively (Python venv + npm)..."

  # Backend
  if [ ! -d backend/.venv ]; then
    echo "Creating backend venv..."
    python3 -m venv backend/.venv
  fi
  # shellcheck disable=SC1091
  source backend/.venv/bin/activate
  pip install -q -r backend/requirements.txt

  # Frontend build
  if [ ! -d frontend/node_modules ]; then
    echo "Installing frontend deps..."
    npm --prefix frontend install
  fi
  echo "Building frontend..."
  npm --prefix frontend run build

  # Start backend
  (
    cd backend
    uvicorn server.main:app --reload --host 0.0.0.0 --port 8000 &
    echo $! > /tmp/eventlens-backend.pid
  )
  trap 'kill "$(cat /tmp/eventlens-backend.pid 2>/dev/null)" 2>/dev/null || true' EXIT

  echo "Backend:  http://localhost:8000 (docs at /docs)"
  echo "Frontend: served by backend at http://localhost:8000"
  wait
}

case "$MODE" in
  docker) run_docker ;;
  native) run_native ;;
  down) docker compose down ;;
  auto)
    if have_docker; then run_docker; else echo "Docker not found — falling back to native."; run_native; fi
    ;;
  *) echo "Usage: $0 [docker|native|down]"; exit 1 ;;
esac