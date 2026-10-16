# ==============================================================================
# EventLens - One-Command Startup Script for Windows PowerShell
# High-reliability launcher for FastAPI backend, AI models, and SOC console
#
# Usage:
#   .\run.ps1               # Run native stack (FastAPI + local SQLite + Ollama)
#   .\run.ps1 -Mode docker  # Run via Docker Compose (with NVIDIA GPU passthrough)
#   .\run.ps1 -Mode seed    # Reset and seed data/events.db with benchmark records
#   .\run.ps1 -Mode check   # Run environment and hardware checks
#   .\run.ps1 -Mode down    # Stop Docker services
# ==============================================================================

param (
    [string]$Mode = "native",
    [int]$Port = 8000,
    [string]$BindHost = "0.0.0.0"
)

function Show-Banner {
    Write-Host ""
    Write-Host "+----------------------------------------------------------------------+" -ForegroundColor Cyan
    Write-Host "|                       EVENTLENS SOC CONSOLE                          |" -ForegroundColor Cyan
    Write-Host "|     Open-Source Live Video Intelligence & Conversational Engine      |" -ForegroundColor Cyan
    Write-Host "+----------------------------------------------------------------------+" -ForegroundColor Cyan
    Write-Host ""
}

function Check-Ollama {
    try {
        $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 2 -ErrorAction Stop
        Write-Host "[OK] Ollama service detected on http://localhost:11434" -ForegroundColor Green
    } catch {
        Write-Host "[!] Notice: Local Ollama service is not responding on :11434." -ForegroundColor Yellow
        Write-Host "    Make sure to run 'ollama serve' in another terminal for VLM and Chat." -ForegroundColor Yellow
    }
}

function Run-Seed {
    Write-Host "[*] Seeding database with demo incident records..." -ForegroundColor Cyan
    $pythonExe = ".\.venv\Scripts\python.exe"
    if (Test-Path $pythonExe) {
        & $pythonExe scripts\seed_demo_db.py
    } else {
        python scripts\seed_demo_db.py
    }
}

function Run-Check {
    Write-Host "[*] Running environment diagnostics..." -ForegroundColor Cyan
    $pythonExe = ".\.venv\Scripts\python.exe"
    if (Test-Path $pythonExe) {
        & $pythonExe scripts\check_env.py
    } else {
        python scripts\check_env.py
    }
}

function Run-Docker {
    Write-Host "[*] Starting EventLens via Docker Compose..." -ForegroundColor Cyan
    docker compose up --build
}

function Run-Native {
    Show-Banner

    # 1. Virtual Environment check
    $venvPython = ".\.venv\Scripts\python.exe"

    if (-not (Test-Path $venvPython)) {
        Write-Host "[*] Creating Python virtual environment (.venv)..." -ForegroundColor Yellow
        python -m venv .venv
        & $venvPython -m pip install --upgrade pip
        & $venvPython -m pip install -r requirements.txt
    }

    # 2. Database check
    if (-not (Test-Path "data\frames")) {
        New-Item -ItemType Directory -Force -Path "data\frames" | Out-Null
    }
    if (-not (Test-Path "data\clips")) {
        New-Item -ItemType Directory -Force -Path "data\clips" | Out-Null
    }

    if (-not (Test-Path "data\events.db")) {
        Write-Host "[!] Database 'data\events.db' not found. Seeding initial benchmark events..." -ForegroundColor Yellow
        & $venvPython scripts\seed_demo_db.py
    }

    # 3. Ollama health check
    Check-Ollama

    # 4. Launch Uvicorn
    Write-Host "[OK] Launching Uvicorn Server on http://${BindHost}:${Port}" -ForegroundColor Green
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Gray
    Write-Host "  * Security Dashboard:   http://localhost:${Port}" -ForegroundColor White
    Write-Host "  * Query AI Interface:   http://localhost:${Port}/chat.html" -ForegroundColor White
    Write-Host "  * Interactive API Docs: http://localhost:${Port}/docs" -ForegroundColor White
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Gray
    Write-Host "[*] Server active. Press CTRL+C to terminate.`n" -ForegroundColor Cyan

    & $venvPython -m uvicorn backend.server.main:app --host $BindHost --port $Port --reload
}

switch ($Mode.ToLower()) {
    "docker" { Run-Docker }
    "native" { Run-Native }
    "seed"   { Run-Seed }
    "check"  { Run-Check }
    "down"   { docker compose down; Write-Host "[OK] Stopped all containerized services." -ForegroundColor Green }
    default  { Run-Native }
}
