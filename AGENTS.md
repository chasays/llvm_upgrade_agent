# LLVM Upgrade Agent Workspace Rules

Start every session by reading `BOARD.md`, then inspect the documents linked from the current board items before making changes.

This workspace is a documentation and portable-skill pack for an LLVM 19-to-22 upgrade agent. Keep artifacts importable into an intranet environment:

- Do not add network-only dependencies to skills.
- Prefer Python 3 standard library scripts.
- Keep each skill self-contained under `skills/<skill-name>/`.
- Update `BOARD.md` whenever you finish, block, or create follow-up work.
- Treat CodeBuddy/MiniMax M2.5 as a short-term interactive worker only; design new automation so it can later call Claude/GPT-class API models and parallel workers.
- Never claim a skill is ready until `python3 tests/test_skill_pack.py` and the skill validator pass.

