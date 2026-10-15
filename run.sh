#!/usr/bin/env bash
# ==============================================================================
# EventLens — One-Command Startup & Control Script
# High-reliability launcher for FastAPI backend, AI models, and SOC console
#
# Usage:
#   ./run.sh              # Auto-detects Docker, otherwise starts native stack
#   ./run.sh native       # Force native Python environment
#   ./run.sh docker       # Force Docker Compose with NVIDIA GPU passthrough
#   ./run.sh seed         # Reset and seed data/events.db with benchmark records
#   ./run.sh check        # Run hardware & environment pre-flight diagnostics
#   ./run.sh down         # Stop all running background processes / containers
# ==============================================================================

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

MODE="${1:-auto}"
PORT=8000
HOST="0.0.0.0"

# ANSI Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

print_banner() {
  echo -e "${CYAN}"
  echo "╔══════════════════════════════════════════════════════════════════════╗"
  echo "║                       EVENTLENS SOC CONSOLE                          ║"
  echo "║     Open-Source Live Video Intelligence & Conversational Engine      ║"
  echo "╚══════════════════════════════════════════════════════════════════════╝"
  echo -e "${NC}"
}

have_docker() {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

check_ollama() {
  if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo -e "${GREEN}[✓] Ollama service detected on http://localhost:11434${NC}"
  else
    echo -e "${YELLOW}[!] Notice: Local Ollama service is not responding on :11434.${NC}"
    echo -e "${YELLOW}    Start it in another terminal with: 'ollama serve'${NC}"
  fi
}

seed_database() {
  echo -e "${CYAN}[*] Seeding database with demo incident records...${NC}"
  if [ -f ".venv/bin/python" ]; then
    .venv/bin/python scripts/seed_demo_db.py
  elif [ -f ".venv/Scripts/python.exe" ]; then
    .venv/Scripts/python.exe scripts/seed_demo_db.py
  else
    python3 scripts/seed_demo_db.py
  fi
}

run_docker() {
  echo -e "${CYAN}[*] Starting EventLens via Docker Compose (NVIDIA GPU Passthrough)...${NC}"
  docker compose up --build
}

run_native() {
  print_banner
  echo -e "${CYAN}[*] Initializing EventLens native environment...${NC}"

  # 1. Python virtual environment
  if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}[*] Creating Python virtual environment (.venv)...${NC}"
    python3 -m venv .venv
    # Activate and install dependencies
    if [ -f ".venv/bin/activate" ]; then
      # shellcheck disable=SC1091
      source .venv/bin/activate
    elif [ -f ".venv/Scripts/activate" ]; then
      # shellcheck disable=SC1091
      source .venv/Scripts/activate
    fi
    pip install --upgrade pip
    pip install -r requirements.txt
  else
    if [ -f ".venv/bin/activate" ]; then
      # shellcheck disable=SC1091
      source .venv/bin/activate
    elif [ -f ".venv/Scripts/activate" ]; then
      # shellcheck disable=SC1091
      source .venv/Scripts/activate
    fi
  fi

  # 2. Check Database existence
  mkdir -p data/frames
  if [ ! -f "data/events.db" ]; then
    echo -e "${YELLOW}[!] Database 'data/events.db' not found. Seeding initial benchmark events...${NC}"
    python scripts/seed_demo_db.py
  fi

  # 3. Check Ollama inference engine
  check_ollama

  # 4. Start FastAPI server
  echo -e "${GREEN}[✓] Launching Uvicorn Server on http://${HOST}:${PORT}${NC}"
  echo "----------------------------------------------------------------------"
  echo -e "  » ${GREEN}Security Dashboard:${NC}   http://localhost:${PORT}"
  echo -e "  » ${GREEN}Query AI Interface:${NC}   http://localhost:${PORT}/chat.html"
  echo -e "  » ${GREEN}Interactive API Docs:${NC} http://localhost:${PORT}/docs"
  echo "----------------------------------------------------------------------"
  echo -e "${CYAN}[*] Server active. Press CTRL+C to terminate.${NC}\n"

  uvicorn backend.server.main:app --host "${HOST}" --port "${PORT}" --reload
}

case "$MODE" in
  docker)
    run_docker
    ;;
  native)
    run_native
    ;;
  seed)
    seed_database
    ;;
  check)
    if [ -f ".venv/bin/python" ]; then
      .venv/bin/python scripts/check_env.py
    elif [ -f ".venv/Scripts/python.exe" ]; then
      .venv/Scripts/python.exe scripts/check_env.py
    else
      python3 scripts/check_env.py
    fi
    ;;
  down)
    if have_docker; then
      docker compose down
    fi
    echo -e "${GREEN}[✓] Stopped all containerized services.${NC}"
    ;;
  auto)
    run_native
    ;;
  *)
    echo "Usage: $0 [native|docker|seed|check|down]"
    exit 1
    ;;
esac