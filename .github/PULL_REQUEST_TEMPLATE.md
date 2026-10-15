## Description
<!-- Provide a concise description of the changes made and the motivation. -->

## Changes Included
- [ ] Vision Pipeline (`backend/vision/`)
- [ ] Server, Database, VLM, Chat (`backend/server/`)
- [ ] Frontend Console & UI (`frontend/`)
- [ ] Evaluation & Benchmarking (`eval/`)
- [ ] Documentation (`docs/`, `README.md`)

## Contract Verification
- [ ] Does NOT modify the frozen API contract (AGENTS.md Section 8) without prior discussion.
- [ ] Does NOT modify the SQLite schema (AGENTS.md Section 9) without prior discussion.
- [ ] All inference remains 100% open-source and local (no cloud APIs).

## Testing Performed
<!-- Describe the commands run and paste test/verification outputs. -->
- `python -m unittest discover -s tests -p "test_*.py"`
- `python scripts/check_env.py`
