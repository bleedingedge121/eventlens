# Getting Started with EventLens

## Prerequisites
- Windows 11 with PowerShell
- Python 3.11 or 3.12 (via uv or official python installer)
- NVIDIA GeForce GPU (e.g. RTX 5070 Ti) with CUDA 12.8+ drivers
- Ollama installed locally (`ollama --version`)

## Quick Setup (PowerShell)

1. Clone or open the repository:
```powershell
cd D:\ClaudeCode\HackHive\EventLens
```

2. Run the automated environment setup script:
```powershell
.\scripts\setup.ps1
```

3. Pull local models via Ollama:
```powershell
ollama pull qwen2.5-vl:7b
ollama pull Hermes-4-14B:latest
```

4. Verify your environment:
```powershell
python .\scripts\check_env.py
```

5. Seed demo database with initial mock events:
```powershell
python .\scripts\seed_demo_db.py
```

6. Start the EventLens server:
```powershell
uvicorn backend.server.main:app --host 0.0.0.0 --port 8000
```

7. Open the interfaces in your browser:
- Operations Dashboard: [http://localhost:8000/index.html](http://localhost:8000/index.html)
- Conversational Chat: [http://localhost:8000/chat.html](http://localhost:8000/chat.html)
