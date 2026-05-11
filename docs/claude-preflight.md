# Claude Preflight For LLVM22 Cherry-Pick Work

This document records the commands to run before starting `claude --dangerously-skip-permissions` for the LLVM 19.1.3 MetaxGPU to LLVM 22.1.3 cherry-pick pilot.

The goal is to prepare a deterministic workspace for Claude:

- point every tool at the correct intranet paths,
- validate and install the local skills,
- prove the LLVM 19.1.3 base and the first MetaxGPU commit are aligned,
- expose the LLVM19 MetaxGPU `master` branch inside the LLVM22 repo as `metax19/master`,
- generate the patch manifest and runner config,
- run a dry-run dashboard,
- switch to the dedicated pilot branch,
- clear dry-run progress before real cherry-pick work starts.

## 1. Set Paths And Known Refs

```bash
LLVM19_REPO="$HOME/llvm22_upgrade/llvm19_metaxgpu"
LLVM22_REPO="$HOME/llvm22_upgrade/llvm-project"
AGENT_REPO="$HOME/llvm22_upgrade/llvm_upgrade_agent"
CLAUDE_SKILLS="$HOME/.claude/skills"
OUTPUT_DIR="$HOME/llvm22_upgrade/output"

LLVM19_BASE_HASH="ab51eccf88f532"
METAXGPU_SOURCE_REF="master"
METAXGPU_FIRST_HASH="39bc139c133f5c0a0015f648c44c93a5e66d9998"

echo "$LLVM19_REPO"
echo "$LLVM22_REPO"
echo "$AGENT_REPO"
echo "$CLAUDE_SKILLS"
echo "$OUTPUT_DIR"
```

What this does:

- `LLVM19_REPO` is the old LLVM19 + MetaxGPU source repo.
- `LLVM22_REPO` is the LLVM22 target repo where cherry-picks are applied.
- `AGENT_REPO` is this skill-pack repo.
- `CLAUDE_SKILLS` is the Claude skills directory.
- `OUTPUT_DIR` is outside the LLVM22 repo so manifests, config, and progress do not pollute `git status`.
- `LLVM19_BASE_HASH` is the LLVM 19.1.3 base commit.
- `METAXGPU_FIRST_HASH` is the first known MetaxGPU downstream cherry-pick on `master`.
- `METAXGPU_SOURCE_REF=master` means the pilot only migrates the weekly integrated branch.

## 2. Validate And Install Skills

```bash
cd "$AGENT_REPO"

python3 tests/test_skill_pack.py

mkdir -p "$CLAUDE_SKILLS"
rsync -a skills/ "$CLAUDE_SKILLS"/

ls -la "$CLAUDE_SKILLS"
```

What this does:

- Verifies the portable skill pack still passes its stdlib tests.
- Copies all skills into Claude's local skill directory.
- Keeps existing internal skills such as `gerrit`, `jira`, `xwiki`, and `trilium-search`.

## 3. Verify LLVM19 Base And Source Endpoint

```bash
cd "$LLVM19_REPO"

git rev-parse "$LLVM19_BASE_HASH"
git describe --contains "$LLVM19_BASE_HASH"
git show -s --format='%H%n%ci%n%an <%ae>%n%s' "$LLVM19_BASE_HASH"

git rev-parse "$METAXGPU_SOURCE_REF"
METAXGPU_SOURCE_HASH=$(git -C "$LLVM19_REPO" rev-parse "$METAXGPU_SOURCE_REF")

git show -s --format='%H%n%ci%n%an <%ae>%n%s' "$METAXGPU_SOURCE_HASH"

git rev-parse "${METAXGPU_FIRST_HASH}^"
test "$(git rev-parse "${METAXGPU_FIRST_HASH}^")" = "$(git rev-parse "$LLVM19_BASE_HASH")" \
  && echo "first MetaxGPU commit parent OK"
```

What this does:

- Confirms the shortened `LLVM19_BASE_HASH` resolves to a real full commit.
- Shows whether the base is contained by the expected LLVM 19.1.3 tag.
- Resolves `master` to a fixed `METAXGPU_SOURCE_HASH`.
- Verifies the first MetaxGPU downstream commit starts immediately after the LLVM 19.1.3 base.

Stop here if the parent check does not print:

```text
first MetaxGPU commit parent OK
```

## 4. Prepare The LLVM22 Repo

```bash
cd "$LLVM22_REPO"

git status --short
git config rerere.enabled true
git config merge.conflictStyle diff3

if git remote get-url metax19 >/dev/null 2>&1; then
  git remote set-url metax19 "$LLVM19_REPO"
else
  git remote add metax19 "$LLVM19_REPO"
fi

git remote get-url metax19
git fetch metax19 master:refs/remotes/metax19/master

git rev-parse metax19/master
git show -s --format='%H%n%ci%n%an <%ae>%n%s' metax19/master
```

What this does:

- Enables `rerere` so repeated conflict resolutions can be reused by Git.
- Enables `diff3` conflict markers so base/ours/theirs are visible.
- Adds or updates a local remote named `metax19` that points at the LLVM19 MetaxGPU repo.
- Fetches only the `master` branch into the LLVM22 repo as `metax19/master`.

This avoids the noisy pattern:

```bash
git remote get-url metax19 || git remote add metax19 "$LLVM19_REPO"
```

That pattern is safe, but it prints `No such remote` the first time. The `if` block is cleaner and repeatable.

## 5. Generate Manifest And Runner Config

```bash
cd "$LLVM22_REPO"
mkdir -p "$OUTPUT_DIR"

export LLVM19_BASE_HASH="ab51eccf88f532"
export METAXGPU_FIRST_HASH="39bc139c133f5c0a0015f648c44c93a5e66d9998"
export METAXGPU_SOURCE_HASH=$(git rev-parse metax19/master)

git rev-parse "$LLVM19_BASE_HASH"
git rev-parse "${METAXGPU_FIRST_HASH}^"
test "$(git rev-parse "${METAXGPU_FIRST_HASH}^")" = "$(git rev-parse "$LLVM19_BASE_HASH")" \
  && echo "first MetaxGPU commit parent OK"

python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py init-manifest \
  --range "$LLVM19_BASE_HASH..$METAXGPU_SOURCE_HASH" \
  --output "$OUTPUT_DIR/patches-master.jsonl"

wc -l "$OUTPUT_DIR/patches-master.jsonl"
sed -n '1,5p' "$OUTPUT_DIR/patches-master.jsonl"

python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py init-config \
  --output "$OUTPUT_DIR/runner-config.json"
```

What this does:

- Uses the base hash and fetched `metax19/master` endpoint to build `$OUTPUT_DIR/patches-master.jsonl`.
- Keeps the manifest fixed even if `master` moves later.
- Creates `$OUTPUT_DIR/runner-config.json`, where build/test commands can be filled in later.
- Keeps runner control files outside the LLVM22 repo so `git status` stays focused on source changes.

Expected pilot result from the current repo shape:

```text
6031 $OUTPUT_DIR/patches-master.jsonl
```

The first manifest entry should be `39bc139c133f5c0a0015f648c44c93a5e66d9998`.

## 6. Dry-Run The Runner And Render Dashboard

```bash
cd "$LLVM22_REPO"

python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py run \
  --manifest "$OUTPUT_DIR/patches-master.jsonl" \
  --config "$OUTPUT_DIR/runner-config.json" \
  --progress "$OUTPUT_DIR/progress-master" \
  --workers 1 \
  --limit 20 \
  --dry-run

sed -n '1,200p' "$OUTPUT_DIR/progress-master/DASHBOARD.md"
```

What this does:

- Exercises manifest ordering and dashboard rendering without changing the LLVM22 worktree.
- Confirms the runner can process the first 20 manifest entries.

Important: dry-run writes `DONE` events into `$OUTPUT_DIR/progress-master`. Remove this dry-run progress before real cherry-pick work, or the real runner will skip those entries.

## 7. Create Pilot Branch And Clear Dry-Run Progress

```bash
cd "$LLVM22_REPO"

git branch --show-current
git status --short
git log -1 --oneline

git switch -c metaxgpu-llvm22-pilot

rm -rf "$OUTPUT_DIR/progress-master"

git branch --show-current
git status --short
```

If the branch already exists:

```bash
git switch metaxgpu-llvm22-pilot
```

What this does:

- Moves real cherry-pick work off the LLVM22 release tag onto a dedicated branch.
- Removes dry-run progress so real `DONE` events reflect actual cherry-pick commits.
- Leaves `$OUTPUT_DIR/patches-master.jsonl` and `$OUTPUT_DIR/runner-config.json` outside the LLVM22 working tree as runner control files.

## 8. Start Claude

```bash
cd "$LLVM22_REPO"
claude --dangerously-skip-permissions
```

What this does:

- Starts Claude in the prepared LLVM22 repo.
- The workspace now has the manifest, config, branch, and skills needed for controlled one-patch-at-a-time work.

The installed `metaxgpu-cherry-pick-operator` skill is the preferred interface after Claude starts. With that skill installed, the user should be able to use short commands:

```text
continue next patch
continue next 20 patches
fix conflict
```

Use the longer prompts below only if the skill is not installed or Claude does not trigger it.

## 9. Prompt: Start First Real Patch

Use this immediately after launching Claude for the first real patch:

```text
Use the metaxgpu-cherry-pick-operator skill.

Start the real pilot by running exactly one next unfinished patch.

Rules:
- Work in the current LLVM22 repo.
- Branch must be metaxgpu-llvm22-pilot.
- Use ../output/patches-master.jsonl, ../output/runner-config.json, and ../output/progress-master.
- Run exactly one cherry-pick runner invocation with --limit 1.
- Do not retry.
- Do not resume.
- Do not run another patch.
- Do not resolve conflicts manually unless the runner stops and you inspect the generated packet first.
- After the command exits, print git status --short and sed -n "1,120p" ../output/progress-master/DASHBOARD.md, then stop.
```

The runner command behind this prompt is:

```bash
python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py run \
  --manifest ../output/patches-master.jsonl \
  --config ../output/runner-config.json \
  --progress ../output/progress-master \
  --workers 1 \
  --limit 1
```

## 10. Prompt: Continue Next N Patches

Use this after previous patches are `DONE` and the worktree has no unresolved conflict:

```text
Use the metaxgpu-cherry-pick-operator skill.

Continue the next <N> unfinished MetaxGPU patches.

Rules:
- Run exactly one cherry-pick runner invocation with --limit <N>.
- Use existing ../output/patches-master.jsonl, ../output/runner-config.json, and ../output/progress-master.
- Before running, print git branch --show-current and git status --short.
- Stop if branch is not metaxgpu-llvm22-pilot.
- Stop if there are modified tracked files or unmerged files.
- If all selected patches are DONE, print git status --short and sed -n "1,180p" ../output/progress-master/DASHBOARD.md, then stop.
- If the runner stops with CONFLICT, NEED_HUMAN, BLOCKED, BUILD_FAILED, or TEST_FAILED, print git status --short, print sed -n "1,180p" ../output/progress-master/DASHBOARD.md, list ../output/progress-master/packets/, and stop.
- Do not run another runner invocation.
- Do not manually resolve conflicts in this continue step.
```

Example:

```text
continue next 20 patches
```

## 11. Prompt: Fix Current Conflict

Use this only after the runner has stopped at `CONFLICT` or `NEED_HUMAN`.

```text
Use the metaxgpu-cherry-pick-operator skill.

Fix the current stopped cherry-pick conflict only.

Rules:
- Do not run the cherry-pick runner.
- Do not continue to another patch.
- Read ../output/progress-master/DASHBOARD.md.
- Read the newest packet under ../output/progress-master/packets/.
- Inspect only conflicted files from git diff --name-only --diff-filter=U.
- For conflicted files, collect or read three-way context with git-conflict-context.
- Preserve existing upstream LLVM22 changes.
- Preserve previous MetaxGPU changes already on this branch.
- Apply only the current patch intent.
- Ground renamed LLVM APIs before editing.
- Make the smallest safe conflict resolution.

After editing:
1. Run git diff --name-only --diff-filter=U; it must be empty.
2. Run git diff --check.
3. Run the configured LLVM22 build command if available. If no LLVM22 build command exists, say that build verification was not run.
4. If checks pass, run git add <resolved-files>.
5. Run git cherry-pick --continue.
6. If cherry-pick --continue succeeds, run:
   python3 "$CLAUDE_SKILLS"/metaxgpu-cherry-pick-operator/scripts/complete_manual_patch.py --progress ../output/progress-master --agent claude-001
7. Print git log -1 --oneline, git status --short, and sed -n "1,180p" ../output/progress-master/DASHBOARD.md.
8. Stop.
```

Short form after the skill is installed:

```text
fix conflict
```

## 12. Progress Repair After Manual Fix

If a human resolves the conflict outside Claude and `git cherry-pick --continue` succeeds, update the progress dashboard with:

```bash
python3 "$CLAUDE_SKILLS"/metaxgpu-cherry-pick-operator/scripts/complete_manual_patch.py \
  --progress ../output/progress-master \
  --agent manual
```

What this does:

- Finds the latest `CONFLICT`, `NEED_HUMAN`, `BLOCKED`, `BUILD_FAILED`, or `TEST_FAILED` event.
- Appends a `DONE` event for the same original patch sha.
- Updates the agent heartbeat.
- Re-renders `../output/progress-master/DASHBOARD.md`, `../output/progress-master/dashboard.html`, and `../output/progress-master/api/*.json`.
