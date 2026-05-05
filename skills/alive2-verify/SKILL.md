---
name: alive2-verify
description: Use when an LLVM upgrade changes IR transforms, InstCombine, optimization passes, intrinsics, attributes, or lowering logic and semantic equivalence needs alive-tv validation.
---

# Alive2 Verify

Use alive2 as a semantic gate for IR-level changes. Passing build and lit is not enough for transformation correctness.

## Workflow

1. Extract the smallest IR before/after case possible.
2. Run `alive-tv` through the wrapper.
3. Treat any incorrect transformation, timeout, or unsupported construct as a review blocker.
4. Put the command and result into the patch ledger.

## Command

```bash
python3 skills/alive2-verify/scripts/alive2_verify.py before.ll after.ll
```

Useful environment default:

```bash
export ALIVE_TV=/path/to/alive-tv
```

