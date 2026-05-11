---
name: llvm-api-grounding
description: Use when upgrading LLVM code and an agent needs to confirm a class, method, enum, intrinsic, attribute, pass API, header, or caller against the local LLVM source tree before editing.
---

# LLVM API Grounding

Ground every LLVM API claim in the checked-out source tree before editing. Do not rely on model memory for LLVM 20/21/22 APIs.

## Workflow

1. Identify the symbol, method, intrinsic, enum, or header that the change depends on.
2. Run `scripts/ground_api.py` against the LLVM 22 source tree.
3. Use only APIs that appear in the script output or in files you explicitly read afterward.
4. If no match is found, say the API is ungrounded and search for adjacent names or upstream replacement patterns.
5. Put the grounding excerpt into the CodeBuddy work packet or worker prompt.
6. When memory is enabled, record successful grounding as trusted local-source evidence.

## Command

```bash
python3 skills/llvm-api-grounding/scripts/ground_api.py \
  --repo /path/to/llvm-project \
  --memory-dir memories \
  "Instruction::moveBefore" "captures(none)"
```

Useful environment default:

```bash
export LLVM_REPO=/path/to/llvm-project
```

## Escalate

Mark the task high risk if grounding involves IR transforms, SelectionDAG, GlobalISel, TableGen-generated APIs, debug info, ABI, or target lowering.
