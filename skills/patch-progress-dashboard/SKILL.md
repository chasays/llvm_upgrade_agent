---
name: patch-progress-dashboard
description: Use when rendering a local dashboard for LLVM downstream patch cherry-pick progress from JSONL events, agent heartbeats, conflict packets, and ledger status.
---

# Patch Progress Dashboard

Render a local, intranet-friendly dashboard from deterministic progress files. Sub-agents write data; this skill only reads that data and generates human-facing views.

## Data Contract

Use this layout in the upgrade workspace:

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

Every sub-agent must append one JSON object to `progress/events.jsonl` whenever a patch changes state. The recommended fields are:

```json
{"ts":"2026-05-07T12:30:01+08:00","agent":"agent-003","sha":"abc123","seq":184,"state":"CONFLICT","files":["llvm/lib/Target/MetaxGPU/X.cpp"],"message":"conflict in SelectionDAG API rename"}
```

Each sub-agent should also update only its own heartbeat file:

```json
{"agent":"agent-003","status":"working","current_sha":"abc123","current_seq":184,"state":"CONFLICT_FIXED","updated_at":"2026-05-07T12:35:10+08:00"}
```

## States

Use stable state names so the dashboard and automation can aggregate progress:

```text
PENDING
CLAIMED
CHERRY_PICKING
CLEAN
EMPTY
CONFLICT
CONFLICT_FIXED
BUILDING
BUILD_PASSED
BUILD_FAILED
TESTING
TEST_PASSED
TEST_FAILED
NEED_HUMAN
BLOCKED
DONE
```

## Command

```bash
python3 skills/patch-progress-dashboard/scripts/render_dashboard.py progress/
```

The command writes:

```text
progress/DASHBOARD.md
progress/dashboard.html
progress/api/summary.json
progress/api/patches.json
progress/api/agents.json
```

## Sub-Agent Rule

No patch is complete until it has a progress event. A sub-agent may only claim its assigned shard and must not edit another agent's heartbeat file.
