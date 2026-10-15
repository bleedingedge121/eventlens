# EventLens Model Download & Verification Script

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "EventLens: Pulling required local models" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Download YOLO model
Write-Host "[1/2] Downloading YOLOv11 small/nano model..." -ForegroundColor Green
$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = "python"
}

& $venvPython -c "from ultralytics import YOLO; model = YOLO('yolo11n.pt'); print('YOLO11n model ready.')"

# 2. Pull Ollama Vision model
Write-Host "[2/2] Checking & pulling Ollama models..." -ForegroundColor Green
# Recommended compact vision models for local inference
ollama pull qwen2.5-vl:7b

Write-Host "Current available Ollama models:" -ForegroundColor Cyan
ollama list
