---
name: downstream-patch-ledger
description: Use when tracking downstream LLVM fork patches across an upgrade, including patch intent, touched files, status, risk, validation evidence, and human review decisions.
---

# Downstream Patch Ledger

Keep upgrade state outside model context. Every patch should have intent, status, risk, and verification evidence.

## Workflow

1. Initialize a JSONL ledger for the patch series.
2. Add each downstream commit before attempting cherry-pick.
3. Update status after conflict resolution, build, lit, validation, and review.
4. Export or summarize the ledger before compaction, handoff, or dashboard review.

## Command

```bash
python3 skills/downstream-patch-ledger/scripts/ledger.py init --ledger DOWNSTREAM_PATCHES.jsonl
python3 skills/downstream-patch-ledger/scripts/ledger.py add --sha abc123 --summary "Metax lowering fix"
python3 skills/downstream-patch-ledger/scripts/ledger.py update --patch-id abc123 --status build-pass --note "ninja check passed"
python3 skills/downstream-patch-ledger/scripts/ledger.py list
```

