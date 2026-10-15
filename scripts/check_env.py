#!/usr/bin/env python3
"""EventLens Environment & System Verification Script.

Checks Python version, PyTorch CUDA capability, Ollama server connectivity,
and available local vision/chat models.
"""

import json
import sys
import urllib.request
import urllib.error


def check_python() -> bool:
    v = sys.version_info
    print(f"[1/4] Python Version: {v.major}.{v.minor}.{v.micro}")
    if v.major == 3 and (v.minor in (11, 12, 13, 14)):
        print("  -> OK (Python runtime compatible)")
        return True
    else:
        print("  -> WARNING: Expected Python 3.11 or 3.12 per AGENTS.md brief.")
        return False


def check_cuda() -> bool:
    print("[2/4] PyTorch & CUDA Acceleration:")
    try:
        import torch

        version = torch.__version__
        cuda_avail = torch.cuda.is_available()
        print(f"  -> PyTorch version: {version}")
        print(f"  -> CUDA Available: {cuda_avail}")
        if cuda_avail:
            device_name = torch.cuda.get_device_name(0)
            mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"  -> Active GPU: {device_name} ({mem_gb:.1f} GB VRAM)")
            return True
        else:
            print("  -> WARNING: PyTorch is currently CPU-only. Install CUDA PyTorch for RTX 5070 Ti.")
            return False
    except ImportError:
        print("  -> PyTorch is not yet installed in this environment.")
        return False


def check_ollama(host: str = "http://localhost:11434") -> bool:
    print(f"[3/4] Ollama Server Connectivity ({host}):")
    try:
        req = urllib.request.Request(f"{host}/api/tags", headers={"User-Agent": "EventLens-Check"})
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
                print(f"  -> OK: Ollama is running. Available models ({len(models)}): {models}")
                return True
    except Exception as e:
        print(f"  -> FAIL: Cannot reach Ollama at {host}. Error: {e}")
        print("     Make sure Ollama is running ('ollama serve')")
        return False
    return False


def check_storage() -> bool:
    print("[4/4] Local Data Storage:")
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent
    data_dir = base / "data"
    frames_dir = data_dir / "frames"
    videos_dir = data_dir / "videos"

    for d in [data_dir, frames_dir, videos_dir]:
        d.mkdir(parents=True, exist_ok=True)
    print(f"  -> OK: Data directories initialized at {data_dir}")
    return True


def main():
    print("=" * 60)
    print("EventLens Environment Check - HackHive 2026 PS-3")
    print("=" * 60)
    c1 = check_python()
    c2 = check_cuda()
    c3 = check_ollama()
    c4 = check_storage()
    print("=" * 60)
    if c1 and c3 and c4:
        print("System is ready for development. (CUDA check status: %s)" % ("PASS" if c2 else "ATTN"))
    else:
        print("Some checks require attention before running full inference.")


if __name__ == "__main__":
    main()
