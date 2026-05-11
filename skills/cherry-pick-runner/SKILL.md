---
name: cherry-pick-runner
description: Use when driving a serial LLVM downstream patch cherry-pick run with configurable workers, hybrid build/test gates, repair packets, and dashboard progress events.
---

# Cherry Pick Runner

Run downstream LLVM patches one by one while keeping the process resumable and observable. The first production mode is strict serial execution with `worker_count` set to `1`; the config keeps the worker setting stable so later versions can run multiple isolated worktrees.

## Policy

- Preserve patch order by default.
- Use `worker_count: 1` unless separate worktrees and ordered landing are explicitly enabled later.
- Use the hybrid gate strategy:
  - quick gate for ordinary patches,
  - heavy gate for high-risk patches,
  - full gate every `full_gate_interval` patches.
- Stop on unresolved conflict, exhausted build repair, exhausted test repair, or dirty workspace.
- Write every state transition to `progress/events.jsonl`.
- Generate repair packets under `progress/packets/` for CodeBuddy/MiniMax M2.5 or a configured repair command.
- Amend successful repair edits into the current cherry-picked patch when `auto_amend_after_repair` is enabled.
- If `memory.enabled` is true, record attention states as candidate memories through `agent-memory`.

## Commands

Create a default config:

```bash
mkdir -p ../output
python3 skills/cherry-pick-runner/scripts/cherry_pick_runner.py init-config --output ../output/runner-config.json
```

Create a manifest from a git range:

```bash
python3 skills/cherry-pick-runner/scripts/cherry_pick_runner.py init-manifest \
  --range old_base..metaxgpu_branch \
  --output ../output/patches.jsonl
```

Run the serial upgrade loop:

```bash
python3 skills/cherry-pick-runner/scripts/cherry_pick_runner.py run \
  --manifest ../output/patches.jsonl \
  --config ../output/runner-config.json \
  --progress ../output/progress \
  --workers 1
```

Use `--dry-run` to validate manifest ordering, gate selection, progress files, and dashboard rendering without changing the git worktree.

## Repair Integration

If `build_repair.command` or `test_repair.command` is configured, the runner executes it after writing the packet path to environment variables. If the command fixes files and the gate then passes, `auto_amend_after_repair` stages the changed source files and amends the current patch commit. If no repair command is configured, the runner records `NEED_HUMAN` and stops with the packet ready to paste into CodeBuddy.

## Memory Integration

By default memory recording is off. Enable candidate memory recording for conflicts, blocked states, and build/test failures:

```json
{
  "memory": {
    "enabled": true,
    "memory_dir": "memories",
    "record_attention": true
  }
}
```

The runner writes only candidate memories. Promote them with `agent-memory` after verification or human review.
