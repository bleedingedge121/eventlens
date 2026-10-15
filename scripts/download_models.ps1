# EventLens Model Download Script
# Run from repository root: PowerShell -ExecutionPolicy Bypass -File scripts/download_models.ps1

$ErrorActionPreference = "Stop"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "EventLens Model Download & Verification"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# --- Settings ---
$SettingsPath = Join-Path $PSScriptRoot "..\config\settings.json"
$Settings = Get-Content $SettingsPath -Raw | ConvertFrom-Json

$VLMModel = $Settings.ollama.vlm_model
$ChatModel = $Settings.chat_model
$YoloModel = $Settings.vision.yolo_model
$ModelsDir = Join-Path $PSScriptRoot "..\data\models"

# Create directories
$dirs = @(
    $ModelsDir,
    (Join-Path $PSScriptRoot "..\data\frames"),
    (Join-Path $PSScriptRoot "..\data\videos"),
    (Join-Path $PSScriptRoot "..\data\logs")
)
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
        Write-Host "Created: $d" -ForegroundColor Green
    }
}

# --- Ollama Models ---
Write-Host "`n--- Ollama Models ---" -ForegroundColor Yellow

$OllamaModels = @($VLMModel, $ChatModel) | Sort-Object -Unique
foreach ($model in $OllamaModels) {
    Write-Host "Checking: $model" -NoNewline
    $exists = ollama list | Select-String -Pattern $model -Quiet
    if ($exists) {
        Write-Host " [FOUND]" -ForegroundColor Green
    } else {
        Write-Host " [MISSING] Pulling..." -ForegroundColor Yellow
        try {
            ollama pull $model
            Write-Host "  -> Pulled $model successfully" -ForegroundColor Green
        } catch {
            Write-Host "  -> FAILED to pull $model: $_" -ForegroundColor Red
            $global:HasErrors = $true
        }
    }
}

# --- YOLO Models ---
Write-Host "`n--- YOLO Models (Ultralytics) ---" -ForegroundColor Yellow
$YoloPath = Join-Path $ModelsDir $YoloModel
if (Test-Path $YoloPath) {
    Write-Host "$YoloModel [FOUND] at $YoloPath" -ForegroundColor Green
} else {
    Write-Host "$YoloModel [MISSING] Downloading via Ultralytics..." -ForegroundColor Yellow
    try {
        python -c "from ultralytics import YOLO; YOLO('$YoloModel')"
        if (Test-Path "yolo11s-pose.pt") {
            Move-Item "yolo11s-pose.pt" $YoloPath -Force
        }
        Write-Host "  -> Downloaded $YoloModel to $YoloPath" -ForegroundColor Green
    } catch {
        Write-Host "  -> FAILED to download $YoloModel: $_" -ForegroundColor Red
        $global:HasErrors = $true
    }
}

# Also download plain box model as fallback
$YoloBoxModel = "yolo11s.pt"
$YoloBoxPath = Join-Path $ModelsDir $YoloBoxModel
if (Test-Path $YoloBoxPath) {
    Write-Host "$YoloBoxModel [FOUND]" -ForegroundColor Green
} else {
    Write-Host "$YoloBoxModel [MISSING] Downloading..." -ForegroundColor Yellow
    try {
        python -c "from ultralytics import YOLO; YOLO('$YoloBoxModel')"
        if (Test-Path "yolo11s.pt") {
            Move-Item "yolo11s.pt" $YoloBoxPath -Force
        }
        Write-Host "  -> Downloaded $YoloBoxModel" -ForegroundColor Green
    } catch {
        Write-Host "  -> FAILED: $_" -ForegroundColor Red
        $global:HasErrors = $true
    }
}

# --- Summary ---
Write-Host "`n============================================" -ForegroundColor Cyan
if ($global:HasErrors) {
    Write-Host "COMPLETED WITH ERRORS - Check output above" -ForegroundColor Red
    exit 1
} else {
    Write-Host "ALL MODELS READY" -ForegroundColor Green
    exit 0
}