# MVP Skill Pack

This MVP packages the LLVM upgrade agent as portable skills plus a board-driven workflow.

## Import

Copy the folders under `skills/` into the target agent skills directory, for example:

```bash
cp -R skills/* "$CODEX_HOME/skills/"
```

For Claude Code-style skill directories, copy the same folders into the equivalent internal skills path. The skills are self-contained and use Python 3 standard library scripts.

## Short-Term Flow

Use this when MiniMax M2.5 is only available inside CodeBuddy:

1. The local runner applies/cherry-picks a patch.
2. `git-conflict-context` generates a conflict work packet.
3. `llvm-api-grounding` adds verified LLVM 22 API context.
4. A human pastes the work packet into CodeBuddy.
5. CodeBuddy/M2.5 performs a focused edit.
6. The runner verifies with build, lit, `update-test-checks`, `tablegen-expand`, and `alive2-verify`.
7. `downstream-patch-ledger` records the result.
8. `patch-progress-dashboard` renders shared progress files into `DASHBOARD.md`, `dashboard.html`, and JSON summaries.

## Progress Dashboard

Use a ledger-first dashboard for long cherry-pick runs. Sub-agents write deterministic progress data; the dashboard only reads and renders it.

Recommended layout:

```text
progress/
  events.jsonl
  agents/
    agent-001.json
  packets/
    <sha>.md
  api/
    summary.json
    patches.json
    agents.json
  DASHBOARD.md
  dashboard.html
```

Render it with:

```bash
python3 skills/patch-progress-dashboard/scripts/render_dashboard.py progress/
```

Every patch state transition should append one JSON object to `progress/events.jsonl`. Every worker should update only its own `progress/agents/<agent-id>.json` heartbeat. A patch without a progress event is treated as unfinished.

## Long-Term Flow

When Claude/GPT-class API access exists, keep the same skills and replace the CodeBuddy manual step with API workers:

- `orchestrator`: owns the patch ledger and state transitions.
- `conflict-resolver`: uses `git-conflict-context`.
- `api-grounder`: uses `llvm-api-grounding`.
- `build-fixer`: consumes build errors and validated API signatures.
- `lit-triager`: uses `lit-failure-triage` and `update-test-checks`.
- `validator`: runs `alive2-verify`, `tablegen-expand`, kernel smoke tests, and fuzzing.
- `dashboard`: uses `patch-progress-dashboard` to publish local progress for humans and automation.

## Validate

```bash
python3 tests/test_skill_pack.py
```

Optional skill validator:

```bash
python3 /Users/admin/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/llvm-api-grounding
```

## MVP Limits

- Scripts do not depend on internal systems.
- Gerrit, xwiki, and trilium integration points are represented as inputs or future context, not hard-coded clients.
- The runner itself is not implemented yet; this package creates the skill layer it will call.
