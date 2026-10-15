# Contributing to EventLens

EventLens is developed for HackHive 2026 (Problem Statement 3). We welcome contributions across the vision pipeline, server infrastructure, machine learning models, and frontend interface.

## Collaboration Guidelines

1. **Frozen API Contract**: The API contract defined in Section 8 of `AGENTS.md` and the database schema in Section 9 are the backbone of the system. Propose any modifications via issues or pull requests before changing them.
2. **Open-Source Local Inference Only**: No cloud AI APIs in runtime code. Everything runs locally on the laptop GPU (NVIDIA RTX 5070 Ti) via Ollama and PyTorch CUDA.
3. **Clean Commits & Testing**: Commit frequently with clear, conventional commit messages (e.g., `feat: add tailgating trigger`, `fix: handle VLM json parse timeout`). Always verify changes by running the test suite: `python -m unittest discover -s tests -p "test_*.py"`.
4. **Living Documentation**: Keep documentation in `docs/` and `README.md` updated as new features or endpoints are introduced.
