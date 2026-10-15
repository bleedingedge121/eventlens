#!/usr/bin/env python3
"""
EventLens Environment Check Script
Run: python scripts/check_env.py
"""

import subprocess
import sys
import json
from pathlib import Path


def run_cmd(cmd, capture=True):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=capture, text=True, timeout=30)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, "", str(e)


def check_python_version():
    ok, out, _ = run_cmd(f"{sys.executable} --version")
    if not ok:
        return False, "python --version failed"
    version = out.split()[1]
    major_minor = ".".join(version.split(".")[:2])
    if major_minor in ("3.11", "3.12"):
        return True, f"Python {version} (OK: 3.11 or 3.12)"
    return False, f"Python {version} (NEED 3.11 or 3.12)"


def check_venv():
    if hasattr(sys, "real_prefix") or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix):
        return True, "Virtual environment active"
    return False, "No virtual environment detected"


def check_cuda():
    ok, out, _ = run_cmd(f"{sys.executable} -c \"import torch; print(torch.cuda.is_available())\"")
    if not ok or out != "True":
        return False, "CUDA not available (torch.cuda.is_available() is False)"
    ok2, out2, _ = run_cmd(f"{sys.executable} -c \"import torch; print(torch.cuda.get_device_name(0))\"")
    if ok2:
        return True, f"CUDA GPU: {out2}"
    return True, "CUDA available"


def check_ollama():
    ok, out, _ = run_cmd("ollama --version")
    if not ok:
        return False, "Ollama not found in PATH"
    ok2, out2, _ = run_cmd("ollama list")
    if not ok2:
        return False, "Ollama list failed"
    return True, f"Ollama {out.split()[1]}\nModels:\n{out2}"


def check_models():
    settings_path = Path("config/settings.json")
    if not settings_path.exists():
        return False, "config/settings.json missing"
    with open(settings_path) as f:
        settings = json.load(f)
    
    vlm = settings["ollama"]["vlm_model"]
    chat = settings["ollama"]["chat_model"]
    
    ok, out, _ = run_cmd("ollama list")
    if not ok:
        return False, "Cannot list Ollama models"
    
    missing = []
    if vlm not in out:
        missing.append(vlm)
    if chat not in out:
        missing.append(chat)
    
    if missing:
        return False, f"Missing Ollama models: {', '.join(missing)}"
    return True, f"Ollama models present: {vlm}, {chat}"


def check_directories():
    required = [
        "data/frames",
        "data/videos",
        "data/models",
        "data/logs",
    ]
    missing = []
    for d in required:
        if not Path(d).exists():
            missing.append(d)
    if missing:
        return False, f"Missing directories: {', '.join(missing)}"
    return True, "All data directories exist"


def check_ports():
    import socket
    port = 8000
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return False, f"Port {port} already in use"
    return True, f"Port {port} free"


def main():
    checks = [
        ("Python Version", check_python_version),
        ("Virtual Env", check_venv),
        ("CUDA / GPU", check_cuda),
        ("Ollama", check_ollama),
        ("Models", check_models),
        ("Directories", check_directories),
        ("Port 8000", check_ports),
    ]
    
    print("=" * 56)
    print("EventLens Environment Check")
    print("=" * 56)
    
    all_ok = True
    for name, fn in checks:
        ok, msg = fn()
        status = "OK" if ok else "FAIL"
        color = "\033[92m" if ok else "\033[91m"
        reset = "\033[0m"
        print(f"  [{color}{status}{reset}] {name}: {msg}")
        if not ok:
            all_ok = False
    
    print("=" * 56)
    if all_ok:
        print("\033[92mALL CHECKS PASSED\033[0m")
        return 0
    else:
        print("\033[91mSOME CHECKS FAILED\033[0m")
        return 1


if __name__ == "__main__":
    sys.exit(main())