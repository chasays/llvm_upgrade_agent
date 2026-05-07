# LLVM Upgrade Agent Board

Last reviewed: 2026-05-07

## Current MVP

Build a portable, intranet-friendly MVP for the LLVM upgrade agent:

- A document board that every future Agent session reads first.
- A skill pack that can be copied into an internal Agent skills directory.
- Helper scripts that work offline with Python 3, git, LLVM build tools, lit, and alive2 when available.
- A strict-serial cherry-pick runner for ordered downstream patch application with hybrid build/test repair gates.
- A ledger-first progress dashboard for long cherry-pick runs, generated from JSONL events and agent heartbeat files.
- A short-term workflow for CodeBuddy/MiniMax M2.5 work packets.
- A long-term path to replace the interactive model step with Claude/GPT-class API workers.

## Doing

- [ ] Pilot the skill pack on 20 representative downstream patches.
- [ ] Fill internal paths for LLVM source, LLVM build, alive-tv, Gerrit, xwiki, and trilium.
- [ ] Pilot the `patch-progress-dashboard` protocol during a 20-patch cherry-pick run.
- [ ] Pilot `cherry-pick-runner` on a small MetaxGPU patch manifest with build/test repair commands configured.

## Done

- [x] Read `0505.md`.
- [x] Read `llvm19_22_conflict_research.md`.
- [x] Define MVP as "document board + portable skill pack + offline validation".
- [x] Package initial skills:
  - `llvm-api-grounding`
  - `git-conflict-context`
  - `update-test-checks`
  - `alive2-verify`
  - `lit-failure-triage`
  - `downstream-patch-ledger`
  - `tablegen-expand`
- [x] Add stdlib validation with `python3 tests/test_skill_pack.py`.
- [x] Smoke-test script entrypoints and sample ledger/conflict packet commands.
- [x] Add `patch-progress-dashboard` skill for rendering `progress/events.jsonl` and `progress/agents/*.json` into Markdown, HTML, and JSON summaries.
- [x] 2026-05-07: `python tests/test_skill_pack.py` passes on this Windows workstation; `python3` is not available here, but Python 3.12 is installed as `python`.
- [x] Add `cherry-pick-runner` skill with `worker_count: 1`, hybrid gate selection, dry-run validation, repair packets, and optional build/test repair commands.

## Blocked

- [ ] MiniMax M2.5 has no public API and can only be used through CodeBuddy. Short-term automation must generate precise work packets for humans to paste into CodeBuddy.
- [ ] Local official `quick_validate.py` currently needs `PyYAML`; this workstation does not have it installed. The stdlib validator is the active MVP check.

## Decisions

- The MVP is not a fully autonomous rebase bot.
- The short-term architecture is: local runner and deterministic skills drive git/build/test; CodeBuddy/M2.5 handles interactive semantic edits.
- The long-term architecture should preserve the same state machine and skills, then swap in API-based Claude/GPT-class worker models.
- Silent miscompile and fabricated LLVM APIs are the top two risks.
- The first progress format is JSONL events plus per-agent heartbeat JSON. SQLite can be added later as a query/cache layer, but sub-agents should not depend on it.
- The first runner mode is strict serial in one worktree. `worker_count` is configurable but values above `1` are rejected until separate worktrees and ordered landing exist.
- The first gate strategy is hybrid: quick by default, heavy for high-risk patches, and full every configured interval.

## Next Review Checklist

1. Read this board.
2. Read the active docs:
   - `docs/mvp-skill-pack.md`
   - `0505.md`
   - `llvm19_22_conflict_research.md`
3. Run `python3 tests/test_skill_pack.py`.
4. Run `python3 /Users/admin/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/<skill-name>` for changed skills when the validator is available.
5. Update this board with what changed and what remains.
