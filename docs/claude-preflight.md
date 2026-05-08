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

LLVM19_BASE_HASH="ab51eccf88f532"
METAXGPU_SOURCE_REF="master"
METAXGPU_FIRST_HASH="39bc139c133f5c0a0015f648c44c93a5e66d9998"

echo "$LLVM19_REPO"
echo "$LLVM22_REPO"
echo "$AGENT_REPO"
echo "$CLAUDE_SKILLS"
```

What this does:

- `LLVM19_REPO` is the old LLVM19 + MetaxGPU source repo.
- `LLVM22_REPO` is the LLVM22 target repo where cherry-picks are applied.
- `AGENT_REPO` is this skill-pack repo.
- `CLAUDE_SKILLS` is the Claude skills directory.
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

export LLVM19_BASE_HASH="ab51eccf88f532"
export METAXGPU_FIRST_HASH="39bc139c133f5c0a0015f648c44c93a5e66d9998"
export METAXGPU_SOURCE_HASH=$(git rev-parse metax19/master)

git rev-parse "$LLVM19_BASE_HASH"
git rev-parse "${METAXGPU_FIRST_HASH}^"
test "$(git rev-parse "${METAXGPU_FIRST_HASH}^")" = "$(git rev-parse "$LLVM19_BASE_HASH")" \
  && echo "first MetaxGPU commit parent OK"

python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py init-manifest \
  --range "$LLVM19_BASE_HASH..$METAXGPU_SOURCE_HASH" \
  --output patches-master.jsonl

wc -l patches-master.jsonl
sed -n '1,5p' patches-master.jsonl

python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py init-config \
  --output runner-config.json
```

What this does:

- Uses the base hash and fetched `metax19/master` endpoint to build `patches-master.jsonl`.
- Keeps the manifest fixed even if `master` moves later.
- Creates `runner-config.json`, where build/test commands can be filled in later.

Expected pilot result from the current repo shape:

```text
6031 patches-master.jsonl
```

The first manifest entry should be `39bc139c133f5c0a0015f648c44c93a5e66d9998`.

## 6. Dry-Run The Runner And Render Dashboard

```bash
cd "$LLVM22_REPO"

python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py run \
  --manifest patches-master.jsonl \
  --config runner-config.json \
  --progress progress-master \
  --workers 1 \
  --limit 20 \
  --dry-run

sed -n '1,200p' progress-master/DASHBOARD.md
```

What this does:

- Exercises manifest ordering and dashboard rendering without changing the LLVM22 worktree.
- Confirms the runner can process the first 20 manifest entries.

Important: dry-run writes `DONE` events into `progress-master`. Remove this dry-run progress before real cherry-pick work, or the real runner will skip those entries.

## 7. Create Pilot Branch And Clear Dry-Run Progress

```bash
cd "$LLVM22_REPO"

git branch --show-current
git status --short
git log -1 --oneline

git switch -c metaxgpu-llvm22-pilot

rm -rf progress-master

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
- Leaves `patches-master.jsonl` and `runner-config.json` in the working tree as runner control files.

## 8. Start Claude

```bash
cd "$LLVM22_REPO"
claude --dangerously-skip-permissions
```

What this does:

- Starts Claude in the prepared LLVM22 repo.
- The workspace now has the manifest, config, branch, and skills needed for controlled one-patch-at-a-time work.

Initial Claude instruction should keep it bounded:

```text
Run exactly one command invocation of the cherry-pick runner with --limit 1.
Use patches-master.jsonl, runner-config.json, and progress-master.
Do not retry.
Do not resume.
Do not run another patch.
Do not resolve conflicts manually unless the runner stops and you inspect the generated packet first.
After the command exits, print git status --short and sed -n "1,120p" progress-master/DASHBOARD.md, then stop.
```

Runner command for Claude:

```bash
python3 "$CLAUDE_SKILLS"/cherry-pick-runner/scripts/cherry_pick_runner.py run \
  --manifest patches-master.jsonl \
  --config runner-config.json \
  --progress progress-master \
  --workers 1 \
  --limit 1
```
