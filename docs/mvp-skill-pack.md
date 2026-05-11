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

1. `cherry-pick-runner` applies one patch at a time from the manifest.
2. Clean or empty cherry-picks are recorded immediately in progress events.
3. Conflicts produce a work packet through `git-conflict-context` and stop the serial run until resolved.
4. `metaxgpu-cherry-pick-operator` gives Claude short operational commands such as `continue next 20 patches` and `fix conflict`.
5. The runner selects the hybrid gate: quick by default, heavy for high-risk patches, full every `full_gate_interval` patches.
6. Build failures produce compact repair packets and optionally call a configured build repair command.
7. Test failures produce compact repair packets and optionally call a configured test repair command.
8. CodeBuddy/M2.5 performs focused edits from the packet when no API repair worker is configured.
9. The runner verifies with build, lit, `update-test-checks`, `tablegen-expand`, and `alive2-verify` as configured.
10. `downstream-patch-ledger` records durable patch state.
11. `patch-progress-dashboard` renders shared progress files into `DASHBOARD.md`, `dashboard.html`, and JSON summaries.
12. `agent-memory` records reusable candidate lessons and promotes only reviewed or verified experience into trusted memory.

## Cherry-Pick Runner

Generate a default runner config:

```bash
mkdir -p ../output
python3 skills/cherry-pick-runner/scripts/cherry_pick_runner.py init-config \
  --output ../output/runner-config.json
```

Generate a manifest from the LLVM 19 downstream range:

```bash
python3 skills/cherry-pick-runner/scripts/cherry_pick_runner.py init-manifest \
  --range old_base..metaxgpu_branch \
  --output ../output/patches.jsonl
```

Run the strict serial loop:

```bash
python3 skills/cherry-pick-runner/scripts/cherry_pick_runner.py run \
  --manifest ../output/patches.jsonl \
  --config ../output/runner-config.json \
  --progress ../output/progress \
  --workers 1
```

The config keeps `worker_count` as a stable field. The MVP supports only `1` writing worker in one worktree. A later multi-worker mode should use separate worktrees plus ordered landing.

For Claude-side operation after preflight setup, use `metaxgpu-cherry-pick-operator`:

```text
continue next patch
continue next 20 patches
fix conflict
```

The skill keeps each run bounded, stops on attention states, and can mark a manually resolved patch as `DONE` after `git cherry-pick --continue`.

The default `gate_strategy` is `hybrid`:

- ordinary patches use quick build/test commands,
- high-risk patches use heavy build/test commands,
- every `full_gate_interval` patches use full build/test commands.

`build_repair.command` and `test_repair.command` may point to an internal Claude Code, CodeBuddy, or MiniMax M2.5 wrapper. If no repair command is configured, the runner writes a packet and stops with `NEED_HUMAN`.

When a repair command edits files and the selected gate passes, `auto_amend_after_repair` stages those changed source files and amends the current patch commit. Keep runner-generated progress, manifest, and config files outside the LLVM worktree, for example under `../output/`, so `git status` stays focused on source changes.

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

## Agent Memory

Use `agent-memory` for knowledge that should survive model context limits and future handoffs:

```text
memories/
  candidates.jsonl
  trusted.jsonl
  session-summaries/
```

The rule is: write deterministic facts automatically, but keep model interpretations as candidates until build, lit, alive2, API grounding, or human review backs them. Good memory entries include a `kind`, short `summary`, `source`, `evidence`, and `applies_to` scope.

Common commands:

```bash
python3 skills/agent-memory/scripts/memory.py record \
  --kind llvm-api-change \
  --summary "Use getIterator overload for moveBefore insertion points." \
  --source llvm/include/llvm/IR/Instruction.h \
  --applies-to LLVM22 \
  --evidence "ninja check-llvm-codegen-metax passed"

python3 skills/agent-memory/scripts/memory.py promote --id <memory-id> --reviewer human
python3 skills/agent-memory/scripts/memory.py search --query moveBefore
python3 skills/agent-memory/scripts/memory.py summarize-session --progress ../output/progress-master --session-id pilot-20
```

To let the runner create candidate memories for attention states, enable this in `../output/runner-config.json`:

```json
{
  "memory": {
    "enabled": true,
    "memory_dir": "memories",
    "record_attention": true
  }
}
```

Several deterministic skills can also write memory when called with `--memory-dir memories`:

- `llvm-api-grounding` records successful local-source grounding as trusted memory.
- `lit-failure-triage` records classifications as candidate memory.
- `alive2-verify` records pass results as trusted memory and blockers as candidate memory.

## Long-Term Flow

When Claude/GPT-class API access exists, keep the same skills and replace the CodeBuddy manual step with API workers:

- `orchestrator`: owns the patch ledger and state transitions.
- `cherry-pick-runner`: keeps ordered patch application, hybrid gates, and repair loops.
- `conflict-resolver`: uses `git-conflict-context`.
- `api-grounder`: uses `llvm-api-grounding`.
- `build-fixer`: consumes build errors and validated API signatures.
- `lit-triager`: uses `lit-failure-triage` and `update-test-checks`.
- `validator`: runs `alive2-verify`, `tablegen-expand`, kernel smoke tests, and fuzzing.
- `dashboard`: uses `patch-progress-dashboard` to publish local progress for humans and automation.
- `memory-curator`: uses `agent-memory` to promote verified lessons and summarize sessions.

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
- The first runner mode is strict serial in one worktree. `worker_count` is configurable, but values above `1` require future separate worktree and ordered landing support.
