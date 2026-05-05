---
name: tablegen-expand
description: Use when LLVM TableGen .td files are changed or conflicted and an agent needs expanded records from llvm-tblgen before editing or reviewing generated behavior.
---

# TableGen Expand

Do not reason about complex `.td` changes from source text alone. Expand records first.

## Workflow

1. Run `llvm-tblgen --print-records` through the wrapper.
2. Include the expanded records relevant to the changed `def`, `defm`, or `multiclass` in the work packet.
3. After editing `.td`, run expansion again and compare the record-level diff.
4. Mark TableGen changes for human review.

## Command

```bash
python3 skills/tablegen-expand/scripts/tablegen_expand.py \
  llvm/lib/Target/Metax/MetaxInstrInfo.td \
  --llvm-source /path/to/llvm-project \
  --llvm-build /path/to/build \
  --grep MyRecord
```

