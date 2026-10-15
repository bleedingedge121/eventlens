# Contributing to EventLens

EventLens is developed for HackHive 2026 (Problem Statement 3). To maintain development speed and avoid merge conflicts, team ownership is strictly divided across modules as detailed in `AGENTS.md`.

## Team Roles and Ownership

| Role | Person | Owned Directories / Files |
|---|---|---|
| **Backend A: Vision** | John (Repo Owner, Demo Laptop) | `backend/vision/`, shared configs |
| **Backend B: Server, DB, VLM, Chat** | Person B | `backend/server/` |
| **Frontend 1: Dashboard, Slides** | Person C | `frontend/index.html`, `frontend/dashboard.js`, `frontend/styles.css`, `docs/` |
| **Frontend 2: Chat, Evaluation** | Person D | `frontend/chat.html`, `frontend/chat.js`, `eval/` |

## Collaboration Rules

1. **Strict Path Isolation**: Only edit files within your assigned path. If a change is needed in another person's path, submit a suggestion or message the owner.
2. **Frozen API Contract**: The API contract defined in Section 8 of `AGENTS.md` and the database schema in Section 9 are frozen. Any changes must be mutually agreed upon by all four team members.
3. **Open-Source Local Inference Only**: No cloud AI APIs in runtime code. Everything runs locally on the laptop GPU (NVIDIA RTX 5070 Ti) via Ollama and PyTorch CUDA.
4. **Clean Commits**: Commit frequently with clear, conventional commit messages (e.g., `feat: add tailgating trigger`, `fix: handle VLM json parse timeout`).
