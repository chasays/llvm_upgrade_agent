---
name: agent-memory
description: Use when recording, promoting, searching, or summarizing durable LLVM upgrade agent memories such as verified decisions, conflict patterns, API changes, test-failure patterns, and session summaries.
---

# Agent Memory

Keep reusable knowledge in local files, not in model-only context. Use memory for facts and reviewed experience that should survive context compaction, handoff, and future upgrade runs.

## Memory Layers

Use three layers:

1. `progress/events.jsonl` and `progress/agents/*.json` for live runtime state.
2. `DOWNSTREAM_PATCHES.jsonl` for per-patch intent, status, risk, validation, and review.
3. `memories/` for reusable lessons that apply beyond one event.

## Data Contract

Recommended layout:

```text
memories/
  candidates.jsonl
  trusted.jsonl
  session-summaries/
```

Write candidates automatically after a conflict, build failure, test failure, or API-grounding result produces a lesson. Promote only after evidence or human review.

Trusted memories should include:

- `kind`: for example `llvm-api-change`, `conflict-pattern`, `test-failure-pattern`, `decision`
- `summary`: short reusable lesson
- `source`: file, command, document, or packet that supports the lesson
- `evidence`: verification commands, review notes, or observed results
- `applies_to`: LLVM version, subsystem, backend, or workflow scope
- `confidence`: `candidate` or `trusted`

## Commands

Record a candidate:

```bash
python3 skills/agent-memory/scripts/memory.py record \
  --kind llvm-api-change \
  --summary "Use getIterator overload for moveBefore insertion points." \
  --source llvm/include/llvm/IR/Instruction.h \
  --applies-to LLVM22 \
  --evidence "ninja check-llvm-codegen-metax passed"
```

Promote after review:

```bash
python3 skills/agent-memory/scripts/memory.py promote --id <memory-id> --reviewer human
```

Search trusted memories:

```bash
python3 skills/agent-memory/scripts/memory.py search --query moveBefore
```

Summarize a session from progress events:

```bash
python3 skills/agent-memory/scripts/memory.py summarize-session \
  --progress progress-master \
  --session-id pilot-20
```

## Runner Hook

`cherry-pick-runner` can record attention states automatically when its config contains:

```json
{"memory":{"enabled":true,"memory_dir":"memories","record_attention":true}}
```

This records only candidate memories for `CONFLICT`, `NEED_HUMAN`, `BLOCKED`, `BUILD_FAILED`, and `TEST_FAILED`.

## Policy

Automatically write deterministic facts. Treat model interpretations as candidates until they are backed by build, lit, alive2, API grounding, or human review.
