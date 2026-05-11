---
name: metaxgpu-cherry-pick-operator
description: Use when the user says continue next patch, continue next N patches, fix conflict, resume the MetaxGPU LLVM cherry-pick pilot, or asks Claude to drive the LLVM19 MetaxGPU to LLVM22 cherry-pick runner.
---

# MetaxGPU Cherry-Pick Operator

Operate the LLVM19 MetaxGPU to LLVM22 pilot from the prepared LLVM22 repo. Keep the work bounded: deterministic runner first, AI repair only when the runner stops.

## Required Workspace

Run from the LLVM22 repo on `metaxgpu-llvm22-pilot`.

Expected files:

```text
../output/patches-master.jsonl
../output/runner-config.json
../output/progress-master/
```

Expected skills:

```text
cherry-pick-runner
git-conflict-context
llvm-api-grounding
patch-progress-dashboard
```

## Continue Next Patches

Use this when the user says `continue next patch`, `continue next 5 patches`, or similar.

1. Parse the requested count. Default to `1`.
2. Print:

```bash
OUTPUT_DIR="${OUTPUT_DIR:-../output}"

git branch --show-current
git status --short
```

3. Stop if the branch is not `metaxgpu-llvm22-pilot`.
4. Stop if there are modified tracked files or unmerged files.
5. Run exactly one runner invocation:

```bash
python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py run \
  --manifest "$OUTPUT_DIR/patches-master.jsonl" \
  --config "$OUTPUT_DIR/runner-config.json" \
  --progress "$OUTPUT_DIR/progress-master" \
  --workers 1 \
  --limit <count>
```

6. Print:

```bash
git status --short
sed -n "1,180p" "$OUTPUT_DIR/progress-master/DASHBOARD.md"
```

7. If the dashboard or runner output shows `CONFLICT`, `NEED_HUMAN`, `BLOCKED`, `BUILD_FAILED`, or `TEST_FAILED`, stop. Do not run another patch.

## Fix Conflict

Use this when the user says `fix conflict`.

Do not run the cherry-pick runner again. Work only on the stopped patch.

1. Inspect:

```bash
OUTPUT_DIR="${OUTPUT_DIR:-../output}"

git status --short
git diff --name-only --diff-filter=U
sed -n "1,180p" "$OUTPUT_DIR/progress-master/DASHBOARD.md"
ls -t "$OUTPUT_DIR/progress-master/packets" | head
```

2. Read the newest packet under `$OUTPUT_DIR/progress-master/packets/`.
3. For each conflicted file, use `git-conflict-context` or run:

```bash
CONFLICT_FILE=<conflicted-file>

python3 "$CLAUDE_SKILLS"/git-conflict-context/scripts/collect_conflict_context.py \
  "$CONFLICT_FILE" \
  --output "$OUTPUT_DIR/progress-master/packets/$(basename "$CONFLICT_FILE").context.md"
```

4. Resolve by preserving:

- existing upstream LLVM22 changes,
- previous MetaxGPU changes already on this branch,
- the intent of the current patch.

5. Ground renamed LLVM APIs before editing with `llvm-api-grounding`.
6. Make the smallest safe edit. Do not continue to another patch.
7. Verify:

```bash
git diff --name-only --diff-filter=U
git diff --check
```

8. Run the configured LLVM22 build command if the user has supplied one. If no LLVM22 build command exists, say so and do not claim build verification.
9. If checks pass:

```bash
git add <resolved-files>
git cherry-pick --continue
python3 "$CLAUDE_SKILLS"/metaxgpu-cherry-pick-operator/scripts/complete_manual_patch.py \
  --progress "$OUTPUT_DIR/progress-master" \
  --agent claude-001
```

10. Print:

```bash
git log -1 --oneline
git status --short
sed -n "1,180p" "$OUTPUT_DIR/progress-master/DASHBOARD.md"
```

Then stop.

## Guardrails

- Never run beyond the requested count.
- Never run the runner while a conflict is unresolved.
- Never mark progress `DONE` before `git cherry-pick --continue` succeeds.
- Never claim LLVM22 build verification unless the LLVM22 build command actually ran and passed.
