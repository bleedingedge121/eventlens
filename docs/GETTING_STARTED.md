# Getting Started with EventLens

EventLens is an edge-native AI video surveillance platform that runs completely offline on consumer hardware:
- **Windows**: NVIDIA GeForce RTX GPU (e.g. RTX 5070 Ti) with CUDA 12.8+
- **macOS**: Apple Silicon MacBook (M1/M2/M3/M4) with Metal Performance Shaders (MPS) acceleration
- **Linux**: NVIDIA GPU with CUDA or CPU fallback

---

## 🚀 Quickstart

### On Windows 11 (PowerShell)

1. Open PowerShell in the project directory:
```powershell
cd D:\ClaudeCode\HackHive\EventLens
```

2. Run the native startup script:
```powershell
.\run.ps1
```
*(Automatically creates `.venv`, installs dependencies with PyTorch CUDA 12.8, verifies GPU, and launches the server on port 8000).*

### On macOS / MacBook (Bash / Zsh)

1. Open Terminal in the project directory:
```bash
cd /path/to/EventLens
```

2. Make executable and run:
```bash
chmod +x run.sh
./run.sh
```
*(Automatically detects macOS Apple Silicon `arm64`, installs PyTorch with Metal Performance Shaders acceleration, and launches the server).*

---

## 🌐 Web Console Access

Once the server is running, open your browser:
* **Security Operations Dashboard**: [http://localhost:8000](http://localhost:8000)
* **Conversational SafeSQL Querying**: [http://localhost:8000/chat.html](http://localhost:8000/chat.html)
* **Interactive OpenAPI Specs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📹 Using the Live Webcam

1. On the dashboard, click the **Webcam (0)** button under *Quick Test Scenarios*.
2. Your browser will prompt:
   > **"localhost:8000 wants to: Use your camera — [Allow] [Block]"**
3. Click **Allow**. EventLens will immediately start live tracking from your camera with tactical HUD bounding boxes and zero latency.

---

## 🛠️ CLI Utilities & Control Commands

### Windows (PowerShell)
```powershell
.\run.ps1                # Start native server
.\run.ps1 -Mode check    # Run hardware & environment pre-flight diagnostics
.\run.ps1 -Mode clean    # Wipe recorded incidents and saved keyframes cleanly
.\run.ps1 -Mode seed     # Seed database with benchmark sample incidents
.\run.ps1 -Mode docker   # Run in Docker Compose
.\run.ps1 -Mode down     # Terminate running servers and background workers
```

### macOS / Linux (Bash)
```bash
./run.sh                 # Start native server
./run.sh check           # Run hardware & environment pre-flight diagnostics
./run.sh clean           # Wipe recorded incidents and saved keyframes cleanly
./run.sh seed            # Seed database with benchmark sample incidents
./run.sh docker          # Run in Docker Compose
./run.sh down            # Terminate running servers and background workers
```

---

## 🤖 Local Models via Ollama (Optional)

EventLens includes built-in rule-based fallback summaries, but for rich natural-language event descriptions and SafeSQL translation:

1. Install Ollama from [ollama.com](https://ollama.com).
2. Start the Ollama server:
```bash
ollama serve
```
3. Pull the target models:
```bash
ollama pull qwen2.5-vl:7b      # Vision-Language Model for event summaries
ollama pull Hermes-4-14B:latest # Chat model for SafeSQL natural language queries
```
