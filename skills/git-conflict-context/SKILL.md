---
name: git-conflict-context
description: Use when resolving LLVM rebase or cherry-pick conflicts and an agent needs base/ours/theirs, commit intent, conflict markers, and nearby git history before editing.
---

# Git Conflict Context

Always give the model the three-way conflict, not just conflict markers. This is mandatory for LLVM upgrade work.

## Workflow

1. Run the collector for every conflicted file.
2. Read base, ours, and theirs before proposing an edit.
3. Preserve downstream target behavior unless the work packet says the downstream patch is obsolete.
4. Add API grounding for any renamed LLVM API.
5. Escalate if the conflict touches TableGen, IR transforms, target lowering, ABI, debug info, or sanitizer/runtime code.

## Command

```bash
python3 skills/git-conflict-context/scripts/collect_conflict_context.py \
  llvm/lib/Target/Metax/Example.cpp \
  --output /tmp/metax-conflict.md
```

Paste the generated markdown into CodeBuddy or an API worker prompt.

