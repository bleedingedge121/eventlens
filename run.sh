#!/usr/bin/env bash
# ==============================================================================
# EventLens — Cross-Platform Startup & Control Script (macOS / Linux / WSL)
# Supports Apple Silicon (M1/M2/M3/M4 Metal MPS), NVIDIA CUDA, and CPU fallback.
#
# Usage:
#   ./run.sh              # Auto-detects environment and launches native stack
#   ./run.sh native       # Force native Python environment
#   ./run.sh docker       # Run via Docker Compose (Linux with NVIDIA GPU)
#   ./run.sh check        # Run hardware & environment pre-flight diagnostics
#   ./run.sh clean        # Wipe all recorded incident events and keyframe images
#   ./run.sh seed         # (Optional) Seed demo mock incidents for testing
#   ./run.sh down         # Stop background processes and Docker containers
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
BOLD='\033[1m'
NC='\033[0m' # No Color

OS="$(uname -s)"
ARCH="$(uname -m)"

print_banner() {
  echo -e "${CYAN}"
  echo "╔══════════════════════════════════════════════════════════════════════╗"
  echo "║                       EVENTLENS SOC CONSOLE                          ║"
  echo "║     Open-Source Live Video Intelligence & Conversational Engine      ║"
  echo "╚══════════════════════════════════════════════════════════════════════╝"
  echo -e "${NC}"
  
  if [ "$OS" = "Darwin" ]; then
    if [ "$ARCH" = "arm64" ]; then
      echo -e "${GREEN}[✓] Platform: macOS (Apple Silicon ${ARCH}) — Metal Performance Shaders (MPS) active${NC}"
    else
      echo -e "${GREEN}[✓] Platform: macOS (Intel ${ARCH})${NC}"
    fi
  elif [ "$OS" = "Linux" ]; then
    if command -v nvidia-smi >/dev/null 2>&1; then
      GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n1 || echo 'NVIDIA GPU')"
      echo -e "${GREEN}[✓] Platform: Linux with CUDA Acceleration (${GPU_NAME})${NC}"
    else
      echo -e "${YELLOW}[!] Platform: Linux (CPU mode)${NC}"
    fi
  else
    echo -e "${CYAN}[*] Platform: ${OS} (${ARCH})${NC}"
  fi
}

find_python() {
  for py in python3.11 python3.12 python3; do
    if command -v "$py" >/dev/null 2>&1; then
      echo "$py"
      return 0
    fi
  done
  echo "python3"
}

check_ollama() {
  if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo -e "${GREEN}[✓] Local Ollama service active on http://localhost:11434${NC}"
  else
    echo -e "${YELLOW}[!] Notice: Local Ollama is not responding on :11434.${NC}"
    if [ "$OS" = "Darwin" ]; then
      echo -e "${YELLOW}    On macOS: Open the Ollama app or run 'ollama serve' in another terminal.${NC}"
    else
      echo -e "${YELLOW}    Run 'ollama serve' in a separate terminal.${NC}"
    fi
    echo -e "${CYAN}[*] Rule-based fallback classification will be active until Ollama is online.${NC}"
  fi
}

clean_database() {
  echo -e "${CYAN}[*] Cleaning incident records and keyframe images...${NC}"
  mkdir -p data/frames data/videos
  
  # Remove keyframes
  find data/frames -name "*.jpg" -type f -delete 2>/dev/null || true
  
  # Reset SQLite database cleanly
  if [ -f ".venv/bin/python" ]; then
    .venv/bin/python -c "from backend.server.db import Database; db = Database('data/events.db'); db.clear_events(); print('Database cleared cleanly (0 rows).')"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c "from backend.server.db import Database; db = Database('data/events.db'); db.clear_events(); print('Database cleared cleanly (0 rows).')"
  fi
  echo -e "${GREEN}[✓] Database and frames wiped. Starting fresh.${NC}"
}

seed_database() {
  echo -e "${CYAN}[*] Seeding database with benchmark records...${NC}"
  if [ -f ".venv/bin/python" ]; then
    .venv/bin/python scripts/seed_demo_db.py
  else
    python3 scripts/seed_demo_db.py
  fi
}

run_docker() {
  if [ "$OS" = "Darwin" ]; then
    echo -e "${YELLOW}[!] Notice: Docker on macOS does not support NVIDIA GPU passthrough.${NC}"
    echo -e "${YELLOW}    Running natively with './run.sh native' provides Metal/MPS Apple Silicon acceleration.${NC}"
    echo -e "${CYAN}[*] Proceeding with Docker Compose...${NC}"
  else
    echo -e "${CYAN}[*] Starting EventLens via Docker Compose (NVIDIA GPU Passthrough)...${NC}"
  fi
  docker compose up --build
}

run_native() {
  print_banner
  echo -e "${CYAN}[*] Initializing EventLens native environment...${NC}"

  PY_BIN="$(find_python)"

  # 1. Setup Virtual Environment
  if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}[*] Creating Python virtual environment using ${PY_BIN}...${NC}"
    "$PY_BIN" -m venv .venv
    
    VENV_PY=".venv/bin/python"
    VENV_PIP=".venv/bin/pip"
    
    echo -e "${CYAN}[*] Installing dependencies...${NC}"
    "$VENV_PIP" install --upgrade pip
    
    # On macOS, standard pip wheels include Apple Silicon Metal (MPS) out of the box
    if [ "$OS" = "Darwin" ]; then
      echo -e "${CYAN}[*] Installing PyTorch with Apple Silicon MPS support...${NC}"
      "$VENV_PIP" install torch torchvision
    elif [ "$OS" = "Linux" ] && command -v nvidia-smi >/dev/null 2>&1; then
      echo -e "${CYAN}[*] Installing PyTorch with CUDA 12.8 wheel...${NC}"
      "$VENV_PIP" install torch torchvision --index-url https://download.pytorch.org/whl/cu128
    else
      "$VENV_PIP" install torch torchvision
    fi
    
    "$VENV_PIP" install -r requirements.txt
    echo -e "${GREEN}[✓] Dependencies installed successfully.${NC}"
  fi

  VENV_PY=".venv/bin/python"
  if [ ! -f "$VENV_PY" ]; then
    # Fallback if Windows path inside WSL or Git Bash
    if [ -f ".venv/Scripts/python.exe" ]; then
      VENV_PY=".venv/Scripts/python.exe"
    else
      VENV_PY="python3"
    fi
  fi

  # 2. Ensure data directories exist and database is initialized cleanly
  mkdir -p data/frames data/videos data/models
  if [ ! -f "data/events.db" ]; then
    echo -e "${CYAN}[*] Initializing clean SQLite events database...${NC}"
    "$VENV_PY" -c "from backend.server.db import Database; Database('data/events.db')"
  fi

  # 3. Check local Ollama
  check_ollama

  # 4. Start FastAPI server
  echo -e "${GREEN}[✓] Launching Uvicorn Server on http://${HOST}:${PORT}${NC}"
  echo "----------------------------------------------------------------------"
  echo -e "  » ${GREEN}Security Dashboard:${NC}   http://localhost:${PORT}"
  echo -e "  » ${GREEN}Query AI Interface:${NC}   http://localhost:${PORT}/chat.html"
  echo -e "  » ${GREEN}Interactive API Docs:${NC} http://localhost:${PORT}/docs"
  echo "----------------------------------------------------------------------"
  echo -e "${CYAN}[*] Server active. Press CTRL+C to terminate.${NC}\n"

  exec "$VENV_PY" -m uvicorn backend.server.main:app --host "${HOST}" --port "${PORT}"
}

case "$MODE" in
  docker)
    run_docker
    ;;
  native)
    run_native
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
  clean)
    clean_database
    ;;
  seed)
    seed_database
    ;;
  down)
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
      docker compose down
    fi
    # Also kill any local python uvicorn process running on port 8000
    if command -v lsof >/dev/null 2>&1; then
      PID=$(lsof -ti:8000 || true)
      if [ -n "$PID" ]; then
        kill -9 $PID 2>/dev/null || true
        echo -e "${GREEN}[✓] Terminated server process on port 8000.${NC}"
      fi
    fi
    echo -e "${GREEN}[✓] Stopped all services.${NC}"
    ;;
  auto)
    run_native
    ;;
  *)
    echo "Usage: $0 [native|docker|check|clean|seed|down]"
    exit 1
    ;;
esac