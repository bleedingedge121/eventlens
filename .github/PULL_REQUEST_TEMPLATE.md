## Description
<!-- Provide a concise description of the changes made and the motivation. -->

## Team Role & Path Ownership
- [ ] Backend A: Vision (`backend/vision/`)
- [ ] Backend B: Server & Chat (`backend/server/`)
- [ ] Frontend 1: Dashboard (`frontend/index.html`, `dashboard.js`, `styles.css`, `docs/`)
- [ ] Frontend 2: Chat & Eval (`frontend/chat.html`, `chat.js`, `eval/`)

## Contract Verification
- [ ] Does NOT modify the frozen API contract (AGENTS.md Section 8) without prior team agreement.
- [ ] Does NOT modify the SQLite schema (AGENTS.md Section 9) without prior team agreement.
- [ ] All inference remains 100% open-source and local (no cloud APIs).

## Testing Performed
<!-- Describe the commands run and paste test/verification outputs. -->
- `python scripts/check_env.py`
- `python scripts/seed_demo_db.py`
