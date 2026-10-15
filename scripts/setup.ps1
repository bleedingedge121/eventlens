# EventLens Environment Setup Script (PowerShell)
# Sets up Python 3.11 virtual environment and installs PyTorch CUDA + requirements

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "EventLens: Setting up development environment" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Check for uv
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "[1/4] Creating virtual environment using uv (Python 3.11)..." -ForegroundColor Green
    uv venv .venv --python 3.11
} else {
    Write-Host "[1/4] Creating virtual environment using standard python..." -ForegroundColor Green
    python -m venv .venv
}

$venvPython = ".\.venv\Scripts\python.exe"
$venvPip = ".\.venv\Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment creation failed." -ForegroundColor Red
    exit 1
}

Write-Host "[2/4] Activating venv and upgrading pip..." -ForegroundColor Green
& $venvPython -m pip install --upgrade pip

Write-Host "[3/4] Installing PyTorch with CUDA support (CUDA 12.8+ build for RTX 50-series)..." -ForegroundColor Green
# Install latest cu128 PyTorch from official pytorch wheel repo
& $venvPip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

Write-Host "[4/4] Installing EventLens runtime and dev requirements..." -ForegroundColor Green
& $venvPip install -r requirements.txt
& $venvPip install -r requirements-dev.txt

Write-Host "Verifying PyTorch CUDA acceleration..." -ForegroundColor Cyan
& $venvPython -c "import torch; print('CUDA Available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None')"

Write-Host "Setup completed! Activate with: .\.venv\Scripts\Activate.ps1" -ForegroundColor Green
