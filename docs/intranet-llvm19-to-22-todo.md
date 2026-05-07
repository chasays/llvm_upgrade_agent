# Intranet LLVM 19.1.3 to 22.1.3 Startup TODO

This checklist is for the first Ubuntu intranet session.

## Known Paths

```bash
LLVM19_REPO="$HOME/llvm-project"
LLVM22_REPO="$HOME/llvm22/llvm-project"
AGENT_REPO="$HOME/llvm_upgrade_agent"
CLAUDE_SKILLS="$HOME/.claude/skills"

LLVM19_BASE_REF="llvm19-base"
METAXGPU_SOURCE_REF="master"
```

Current branch meaning:

- `llvm19-base`: the community LLVM 19.1.3 base commit used by the MetaxGPU LLVM19 fork.
- `master`: weekly integrated LLVM19 + MetaxGPU downstream branch.
- `development`: daily development LLVM19 + MetaxGPU downstream branch.
- `metaxgpu-branch` in earlier notes means the downstream source branch to migrate. Use `master` first unless the goal is latest development state.

`LLVM19_BASE_REF` and `METAXGPU_SOURCE_REF` can be branch names, tag names, or commit hashes. For the first formal run, resolve both to hashes and use the hash range so the generated manifest cannot change when `master` or `development` moves later.

Do not copy LLVM source trees into `~/.claude/skills/`. Only copy the agent skills.

## Step 1: Install And Validate Skills

Run this after the repo is copied into the intranet machine:

```bash
cd "$AGENT_REPO"

python3 tests/test_skill_pack.py

mkdir -p "$CLAUDE_SKILLS"
rsync -a skills/ "$CLAUDE_SKILLS"/
```

If `rsync` is unavailable:

```bash
cp -a skills/. "$CLAUDE_SKILLS"/
```

Keep existing intranet skills such as `gerrit`, `jira`, `trilium-search`, and `xwiki`. They provide internal history and documentation context; this repo provides the LLVM upgrade workflow skills.

## Step 2: Confirm LLVM 19.1.3 Base Commit

This is the first required confirmation for tomorrow.

```bash
cd "$LLVM19_REPO"

git fetch --all --prune

git rev-parse "$LLVM19_BASE_REF"
git show -s --format='%H%n%ci%n%an <%ae>%n%s' "$LLVM19_BASE_REF"
git tag --contains "$LLVM19_BASE_REF" | grep 'llvmorg-19' | head
git describe --contains "$LLVM19_BASE_REF"
```

If `llvm19-base` only exists as a remote branch:

```bash
LLVM19_BASE_REF="origin/llvm19-base"

git rev-parse "$LLVM19_BASE_REF"
git show -s --format='%H%n%ci%n%an <%ae>%n%s' "$LLVM19_BASE_REF"
git tag --contains "$LLVM19_BASE_REF" | grep 'llvmorg-19' | head
git describe --contains "$LLVM19_BASE_REF"
```

Resolve the base and source endpoint to fixed hashes:

```bash
METAXGPU_SOURCE_REF="master"

LLVM19_BASE_HASH=$(git -C "$LLVM19_REPO" rev-parse "$LLVM19_BASE_REF")
METAXGPU_SOURCE_HASH=$(git -C "$LLVM19_REPO" rev-parse "$METAXGPU_SOURCE_REF")

printf 'LLVM19_BASE_HASH=%s\n' "$LLVM19_BASE_HASH"
printf 'METAXGPU_SOURCE_HASH=%s\n' "$METAXGPU_SOURCE_HASH"

git -C "$LLVM19_REPO" show -s --format='%H%n%ci%n%an <%ae>%n%s' "$LLVM19_BASE_HASH"
git -C "$LLVM19_REPO" show -s --format='%H%n%ci%n%an <%ae>%n%s' "$METAXGPU_SOURCE_HASH"
```

Record the result:

```text
LLVM19_BASE_HASH=
METAXGPU_SOURCE_HASH=
LLVM19_RELEASE_TAG=llvmorg-19.1.3
LLVM19_BASE_REF=llvm19-base
METAXGPU_SOURCE_REF=master
```

If `git describe --contains` does not show `llvmorg-19.1.3`, stop and verify with internal Gerrit history before generating the migration manifest.

## Step 3: Prepare LLVM22 Target Repo

```bash
cd "$LLVM22_REPO"

git status --short
git config rerere.enabled true
git config merge.conflictStyle diff3

git remote get-url metax19 || git remote add metax19 "$LLVM19_REPO"
git fetch metax19 \
  llvm19-base:refs/remotes/metax19/llvm19-base \
  master:refs/remotes/metax19/master \
  development:refs/remotes/metax19/development
```

Create a pilot branch in the LLVM22 repo:

```bash
git switch -c metaxgpu-llvm22-pilot
```

If the branch already exists:

```bash
git switch metaxgpu-llvm22-pilot
```

## Step 4: Smoke Test LLVM22 API Grounding

```bash
python3 "$CLAUDE_SKILLS"/llvm-api-grounding/scripts/ground_api.py \
  --repo "$LLVM22_REPO" \
  "Instruction::moveBefore"
```

Expected result: the command should return real matches from the LLVM22 source tree. If it returns no useful matches, check `LLVM22_REPO` first.

## Step 5: Generate Patch Manifests

Stable weekly-integrated source first:

```bash
cd "$LLVM22_REPO"

LLVM19_BASE_HASH=$(git -C "$LLVM19_REPO" rev-parse "$LLVM19_BASE_REF")
METAXGPU_SOURCE_HASH=$(git -C "$LLVM19_REPO" rev-parse master)

python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py init-manifest \
  --range "$LLVM19_BASE_HASH..$METAXGPU_SOURCE_HASH" \
  --output patches-master.jsonl

wc -l patches-master.jsonl
sed -n '1,5p' patches-master.jsonl
```

Equivalent ref-based range, useful for quick inspection but less stable if the branch moves:

```bash
python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py init-manifest \
  --range metax19/llvm19-base..metax19/master \
  --output patches-master-ref-range.jsonl
```

Latest development source, only after the `master` pilot is understood:

```bash
METAXGPU_SOURCE_HASH=$(git -C "$LLVM19_REPO" rev-parse development)

python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py init-manifest \
  --range "$LLVM19_BASE_HASH..$METAXGPU_SOURCE_HASH" \
  --output patches-development.jsonl

wc -l patches-development.jsonl
sed -n '1,5p' patches-development.jsonl
```

Use `patches-master.jsonl` for the first pilot unless there is a product reason to migrate unmerged daily development commits immediately.

## Step 6: Create Runner Config

```bash
cd "$LLVM22_REPO"

python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py init-config \
  --output runner-config.json
```

Before a real run, edit `runner-config.json` and fill local build/test commands. Keep `worker_count` as `1` for the first pilot.

Initial fields to fill after confirming the internal build directory:

```json
{
  "quick_build_commands": [],
  "quick_test_commands": [],
  "heavy_build_commands": [],
  "heavy_test_commands": [],
  "full_build_commands": [],
  "full_test_commands": []
}
```

Do not treat empty build/test commands as a verified migration. Empty commands only validate the runner loop.

## Step 7: Dry Run The First 20 Patches

```bash
cd "$LLVM22_REPO"

python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py run \
  --manifest patches-master.jsonl \
  --config runner-config.json \
  --progress progress-master \
  --workers 1 \
  --limit 20 \
  --dry-run

python3 "$CLAUDE_SKILLS"/patch-progress-dashboard/scripts/render_dashboard.py progress-master
```

Review:

```bash
sed -n '1,200p' progress-master/DASHBOARD.md
```

## Step 8: Real Pilot On 20 Representative Patches

After build/test commands are configured, run without `--dry-run`:

```bash
cd "$LLVM22_REPO"

python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py run \
  --manifest patches-master.jsonl \
  --config runner-config.json \
  --progress progress-master \
  --workers 1 \
  --limit 20
```

If the runner stops on a conflict, use the generated packet under `progress-master/packets/`. For any conflicted file, generate full three-way context:

```bash
CONFLICT_FILE=<conflicted-file>

python3 "$CLAUDE_SKILLS"/git-conflict-context/scripts/collect_conflict_context.py \
  "$CONFLICT_FILE" \
  --output "progress-master/packets/$(basename "$CONFLICT_FILE").context.md"
```

Paste that packet into CodeBuddy/MiniMax M2.5 together with the relevant `gerrit`, `xwiki`, or `trilium-search` results.

## Step 9: Use The Right Skill Per Failure

- Conflict: `git-conflict-context`
- LLVM API uncertainty: `llvm-api-grounding`
- Failing lit test: `lit-failure-triage`
- Autogenerated CHECK drift: `update-test-checks`
- IR transform semantic risk: `alive2-verify`
- TableGen edits: `tablegen-expand`
- Patch status tracking: `downstream-patch-ledger`
- Progress view: `patch-progress-dashboard`
- Ordered cherry-pick loop: `cherry-pick-runner`

## Stop Conditions

Stop and resolve before continuing if any of these happen:

- `llvm19-base` cannot be tied back to LLVM 19.1.3 or the internal base history.
- `git status --short` is dirty before starting a real cherry-pick run.
- The runner writes `NEED_HUMAN`, `BLOCKED`, `BUILD_FAILED`, or `TEST_FAILED`.
- A conflict touches TableGen, IR transforms, target lowering, ABI, debug info, sanitizer/runtime code, or MetaxGPU backend lowering.
- Build/test commands are still empty and someone wants to claim migration progress.

## Tomorrow's First Record

Fill this block before the first real run:

```text
Date:
Host:
LLVM19_BASE_HASH:
LLVM19_BASE_SHOW:
LLVM19_RELEASE_TAG:
Source branch for pilot: master
Target branch in LLVM22 repo:
Build directory:
Quick build command:
Quick test command:
Alive2 available: yes/no
Skill validation:
  python3 tests/test_skill_pack.py:
  quick_validate.py:
```
