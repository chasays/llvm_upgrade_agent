#!/usr/bin/env python3
"""Serial LLVM downstream patch cherry-pick runner."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


FINAL_STATES = {"DONE", "EMPTY"}
ATTENTION_STATES = {"CONFLICT", "NEED_HUMAN", "BLOCKED", "BUILD_FAILED", "TEST_FAILED"}

DEFAULT_CONFIG = {
    "worker_count": 1,
    "gate_strategy": "hybrid",
    "full_gate_interval": 50,
    "quick_build_commands": [],
    "quick_test_commands": [],
    "heavy_build_commands": [],
    "heavy_test_commands": [],
    "full_build_commands": [],
    "full_test_commands": [],
    "auto_amend_after_repair": True,
    "high_risk_patterns": [
        "*.td",
        "*TableGen*",
        "*DebugInfo*",
        "llvm/include/llvm/IR/*",
        "llvm/lib/IR/*",
        "llvm/lib/CodeGen/*",
        "compiler-rt/*",
    ],
    "build_repair": {"max_attempts": 3, "command": []},
    "test_repair": {"max_attempts": 2, "command": []},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if rows else ""), encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def load_config(path: Path | None) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if path and path.exists():
        override = json.loads(path.read_text(encoding="utf-8-sig"))
        deep_update(config, override)
    return config


def deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = value


def patch_sort_key(row: dict[str, Any]) -> tuple[int, int | str, str]:
    seq = row.get("seq")
    try:
        return (0, int(seq), str(row.get("sha", "")))
    except (TypeError, ValueError):
        return (1, str(seq), str(row.get("sha", "")))


def latest_states(progress: Path) -> dict[str, str]:
    states: dict[str, str] = {}
    for event in read_jsonl(progress / "events.jsonl"):
        sha = str(event.get("sha", "")).strip()
        state = str(event.get("state", "")).strip()
        if sha and state:
            states[sha] = state
    return states


def event(progress: Path, agent: str, patch: dict[str, Any], state: str, message: str, **extra: Any) -> None:
    row = {
        "ts": utc_now(),
        "agent": agent,
        "seq": patch.get("seq", ""),
        "sha": patch.get("sha", ""),
        "title": patch.get("title", patch.get("summary", "")),
        "state": state,
        "files": patch.get("files", patch.get("touched_files", [])),
        "message": message,
    }
    row.update(extra)
    append_jsonl(progress / "events.jsonl", row)
    heartbeat(progress, agent, patch, state)


def heartbeat(progress: Path, agent: str, patch: dict[str, Any], state: str, status: str = "working") -> None:
    path = progress / "agents" / f"{agent}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "agent": agent,
        "status": status,
        "current_sha": patch.get("sha", ""),
        "current_seq": patch.get("seq", ""),
        "state": state,
        "updated_at": utc_now(),
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def select_gate(patch: dict[str, Any], config: dict[str, Any]) -> str:
    strategy = config.get("gate_strategy", "hybrid")
    if strategy != "hybrid":
        return str(strategy)
    if is_high_risk(patch, config):
        return "heavy"
    interval = int(config.get("full_gate_interval") or 0)
    seq = patch.get("seq")
    try:
        if interval > 0 and int(seq) % interval == 0:
            return "full"
    except (TypeError, ValueError):
        pass
    return "quick"


def is_high_risk(patch: dict[str, Any], config: dict[str, Any]) -> bool:
    risk = str(patch.get("risk", "")).lower()
    if risk in {"high", "manual", "human", "semantic"}:
        return True
    files = patch.get("files", patch.get("touched_files", [])) or []
    if isinstance(files, str):
        files = [files]
    patterns = config.get("high_risk_patterns", [])
    for file_name in files:
        normalized = str(file_name).replace("\\", "/")
        for pattern in patterns:
            pat = str(pattern).replace("\\", "/")
            if fnmatch.fnmatch(normalized, pat) or pat in normalized:
                return True
    return False


def gate_commands(gate: str, config: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    if gate == "heavy":
        build = config.get("heavy_build_commands") or config.get("full_build_commands") or config.get("quick_build_commands") or []
        test = config.get("heavy_test_commands") or config.get("full_test_commands") or config.get("quick_test_commands") or []
        return build, test
    if gate == "full":
        return config.get("full_build_commands", []), config.get("full_test_commands", [])
    return config.get("quick_build_commands", []), config.get("quick_test_commands", [])


def run_command(command: Any, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    if isinstance(command, list):
        return subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return subprocess.run(str(command), cwd=cwd, env=env, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def run_command_group(commands: list[Any], cwd: Path, log_path: Path) -> tuple[bool, str, Any]:
    outputs = []
    for command in commands:
        proc = run_command(command, cwd)
        outputs.append(f"$ {command}\n{proc.stdout}")
        if proc.returncode != 0:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("\n\n".join(outputs), encoding="utf-8")
            return False, proc.stdout, command
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n\n".join(outputs), encoding="utf-8")
    return True, "\n\n".join(outputs), ""


def compact_error(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lower = line.lower()
        if "error:" in lower or "note:" in lower or "failed:" in lower or "undefined reference" in lower:
            lines.append(line)
    return "\n".join(lines[-200:]) if lines else "\n".join(text.splitlines()[-80:])


def packet_name(patch: dict[str, Any], suffix: str) -> str:
    seq = str(patch.get("seq", "x")).replace("/", "_")
    sha = str(patch.get("sha", "unknown"))[:12]
    return f"{seq}-{sha}-{suffix}.md"


def write_repair_packet(progress: Path, patch: dict[str, Any], phase: str, command: Any, output: str, gate: str) -> Path:
    path = progress / "packets" / packet_name(patch, phase)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(
        [
            f"# {phase.title()} Repair Packet",
            "",
            f"Patch: `{patch.get('sha', '')}`",
            f"Seq: `{patch.get('seq', '')}`",
            f"Title: {patch.get('title', patch.get('summary', ''))}",
            f"Gate: `{gate}`",
            f"Command: `{command}`",
            "",
            "## Files",
            "",
            "\n".join(f"- `{name}`" for name in patch.get("files", patch.get("touched_files", []))) or "- none recorded",
            "",
            "## Compact Output",
            "",
            "```text",
            compact_error(output),
            "```",
            "",
            "## Rules",
            "",
            "- Make the smallest safe edit.",
            "- Do not invent LLVM APIs; ground renamed APIs in the local LLVM source tree.",
            "- Preserve downstream MetaxGPU behavior unless the patch intent says it is obsolete.",
            "- Mark IR transforms, TableGen, debug info, ABI, backend lowering, runtime, and sanitizer edits for human review.",
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")
    return path


def write_conflict_packet(progress: Path, patch: dict[str, Any], cwd: Path) -> Path:
    path = progress / "packets" / packet_name(patch, "conflict")
    path.parent.mkdir(parents=True, exist_ok=True)
    conflicted = git(["diff", "--name-only", "--diff-filter=U"], cwd).stdout.splitlines()
    collector = Path(__file__).resolve().parents[2] / "git-conflict-context" / "scripts" / "collect_conflict_context.py"
    if collector.exists() and conflicted:
        proc = subprocess.run(
            [sys.executable, str(collector), *conflicted, "--output", str(path)],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode == 0:
            return path
    body = "\n".join(
        [
            "# Cherry Pick Conflict Packet",
            "",
            f"Patch: `{patch.get('sha', '')}`",
            f"Seq: `{patch.get('seq', '')}`",
            f"Title: {patch.get('title', patch.get('summary', ''))}",
            "",
            "## Conflicted Files",
            "",
            "\n".join(f"- `{name}`" for name in conflicted) or "- unavailable",
            "",
            "## Status",
            "",
            "```text",
            git(["status", "--short"], cwd).stdout,
            "```",
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")
    return path


def run_repair(kind: str, config: dict[str, Any], packet: Path, patch: dict[str, Any], cwd: Path) -> bool:
    repair = config.get(f"{kind}_repair", {})
    command = repair.get("command") or []
    if not command:
        return False
    env = dict(**__import__("os").environ)
    env["LLVM_UPGRADE_REPAIR_PACKET"] = str(packet)
    env["LLVM_UPGRADE_PATCH_SHA"] = str(patch.get("sha", ""))
    env["LLVM_UPGRADE_PATCH_SEQ"] = str(patch.get("seq", ""))
    proc = run_command(command, cwd, env=env)
    return proc.returncode == 0


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def has_unmerged_files(cwd: Path) -> bool:
    return bool(git(["diff", "--name-only", "--diff-filter=U"], cwd).stdout.strip())


def status_paths(cwd: Path, ignored_paths: list[Path]) -> list[str]:
    proc = git(["status", "--porcelain", "--untracked-files=all"], cwd)
    paths = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        name = line[3:]
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        if not is_ignored_status_path(cwd, name, ignored_paths):
            paths.append(name)
    return paths


def is_ignored_status_path(cwd: Path, name: str, ignored_paths: list[Path]) -> bool:
    candidate = (cwd / name).resolve()
    for ignored in ignored_paths:
        try:
            candidate.relative_to(ignored.resolve())
            return True
        except ValueError:
            pass
        if candidate == ignored.resolve():
            return True
    return False


def workspace_dirty(cwd: Path, ignored_paths: list[Path]) -> bool:
    return bool(status_paths(cwd, ignored_paths))


def ignored_paths_for(cwd: Path, paths: list[Path | None]) -> list[Path]:
    ignored = []
    for path in paths:
        if path is None:
            continue
        candidate = path if path.is_absolute() else cwd / path
        try:
            candidate.resolve().relative_to(cwd.resolve())
        except ValueError:
            continue
        ignored.append(candidate)
    return ignored


def amend_if_dirty(cwd: Path, ignored_paths: list[Path], config: dict[str, Any], progress: Path, agent: str, patch: dict[str, Any], gate: str) -> bool:
    paths = status_paths(cwd, ignored_paths)
    if not paths:
        return True
    if not config.get("auto_amend_after_repair", True):
        event(progress, agent, patch, "NEED_HUMAN", "repair changed files; auto amend disabled", gate=gate, files=paths)
        return False
    add = git(["add", "--", *paths], cwd)
    if add.returncode != 0:
        event(progress, agent, patch, "BLOCKED", f"failed to stage repair changes: {add.stderr}", gate=gate, files=paths)
        return False
    commit = git(["commit", "--amend", "--no-edit"], cwd)
    if commit.returncode != 0:
        event(progress, agent, patch, "BLOCKED", f"failed to amend repair changes: {commit.stderr}", gate=gate, files=paths)
        return False
    event(progress, agent, patch, "AMENDED", "repair changes amended into current patch", gate=gate, files=paths)
    return True


def run_build_or_test(
    kind: str,
    commands: list[Any],
    config: dict[str, Any],
    progress: Path,
    agent: str,
    patch: dict[str, Any],
    cwd: Path,
    gate: str,
) -> bool:
    if not commands:
        event(progress, agent, patch, f"{kind.upper()}_PASSED", f"no {kind} commands configured", gate=gate)
        return True
    repair = config.get(f"{kind}_repair", {})
    attempts = int(repair.get("max_attempts", 0))
    for attempt in range(attempts + 1):
        event(progress, agent, patch, f"{kind.upper()}ING", f"running {kind} gate attempt {attempt + 1}", gate=gate)
        ok, output, command = run_command_group(commands, cwd, progress / "logs" / f"{patch.get('seq')}-{patch.get('sha')}-{kind}.log")
        if ok:
            event(progress, agent, patch, f"{kind.upper()}_PASSED", f"{kind} gate passed", gate=gate)
            return True
        packet = write_repair_packet(progress, patch, kind, command, output, gate)
        event(progress, agent, patch, f"{kind.upper()}_FAILED", f"{kind} gate failed; packet: {packet}", gate=gate, packet=str(packet))
        if attempt >= attempts or not run_repair(kind, config, packet, patch, cwd):
            event(progress, agent, patch, "NEED_HUMAN", f"{kind} repair exhausted; packet: {packet}", gate=gate, packet=str(packet))
            return False
    return False


def cmd_init_config(args: argparse.Namespace) -> int:
    output = Path(args.output)
    output.write_text(json.dumps(DEFAULT_CONFIG, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


def cmd_init_manifest(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd)
    proc = git(["log", "--reverse", "--format=%H%x00%s", args.range], cwd)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        return proc.returncode
    rows = []
    for seq, line in enumerate(proc.stdout.splitlines(), 1):
        if not line.strip():
            continue
        sha, _, title = line.partition("\0")
        files = git(["show", "--name-only", "--format=", "--no-renames", sha], cwd).stdout.splitlines()
        rows.append({"seq": seq, "sha": sha, "title": title, "risk": "unknown", "files": [f for f in files if f.strip()]})
    write_jsonl(Path(args.output), rows)
    print(args.output)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config) if args.config else None)
    workers = int(args.workers or config.get("worker_count", 1))
    if workers != 1:
        print("multi-worker mode requires separate worktrees and ordered landing; set --workers 1 for this runner", file=sys.stderr)
        return 2
    progress = Path(args.progress)
    progress.mkdir(parents=True, exist_ok=True)
    manifest = sorted(read_jsonl(Path(args.manifest)), key=patch_sort_key)
    states = latest_states(progress)
    agent = args.agent
    processed = 0
    cwd = Path(args.cwd)
    ignored_paths = ignored_paths_for(cwd, [Path(args.manifest), Path(args.config) if args.config else None, progress])
    for patch in manifest:
        sha = str(patch.get("sha", "")).strip()
        if not sha:
            continue
        state = states.get(sha)
        if state in FINAL_STATES:
            continue
        if state in ATTENTION_STATES:
            print(f"stopping at attention state for {sha}: {state}", file=sys.stderr)
            return 1
        if args.limit and processed >= args.limit:
            break
        processed += 1
        code = process_patch(patch, config, progress, agent, cwd, args.dry_run, ignored_paths)
        if code != 0:
            render_dashboard(progress)
            return code
        render_dashboard(progress)
    heartbeat(progress, agent, {"sha": "", "seq": ""}, "IDLE", status="idle")
    render_dashboard(progress)
    return 0


def process_patch(
    patch: dict[str, Any],
    config: dict[str, Any],
    progress: Path,
    agent: str,
    cwd: Path,
    dry_run: bool,
    ignored_paths: list[Path],
) -> int:
    gate = select_gate(patch, config)
    event(progress, agent, patch, "CLAIMED", "claimed patch")
    event(progress, agent, patch, "GATE_SELECTED", f"selected {gate} gate", gate=gate)
    event(progress, agent, patch, "CHERRY_PICKING", "starting cherry-pick", gate=gate)
    if dry_run:
        event(progress, agent, patch, "CLEAN", "dry-run cherry-pick skipped", gate=gate)
    else:
        if workspace_dirty(cwd, ignored_paths):
            event(progress, agent, patch, "BLOCKED", "workspace is dirty before cherry-pick", gate=gate)
            return 1
        proc = git(["cherry-pick", "-x", str(patch["sha"])], cwd)
        if proc.returncode != 0:
            if has_unmerged_files(cwd):
                packet = write_conflict_packet(progress, patch, cwd)
                event(progress, agent, patch, "CONFLICT", f"cherry-pick conflict; packet: {packet}", gate=gate, packet=str(packet))
                event(progress, agent, patch, "NEED_HUMAN", f"resolve conflict then resume; packet: {packet}", gate=gate, packet=str(packet))
                return 1
            output = proc.stdout + proc.stderr
            if "previous cherry-pick is now empty" in output.lower() or "nothing to commit" in output.lower():
                git(["cherry-pick", "--skip"], cwd)
                event(progress, agent, patch, "EMPTY", "empty cherry-pick skipped", gate=gate)
                return 0
            packet = write_repair_packet(progress, patch, "cherry-pick", "git cherry-pick -x", output, gate)
            event(progress, agent, patch, "BLOCKED", f"cherry-pick failed; packet: {packet}", gate=gate, packet=str(packet))
            return 1
        event(progress, agent, patch, "CLEAN", "cherry-pick applied", gate=gate)
    build_commands, test_commands = gate_commands(gate, config)
    if not dry_run and not run_build_or_test("build", build_commands, config, progress, agent, patch, cwd, gate):
        return 1
    if dry_run:
        event(progress, agent, patch, "BUILD_PASSED", "dry-run build gate skipped", gate=gate)
    if not dry_run and not run_build_or_test("test", test_commands, config, progress, agent, patch, cwd, gate):
        return 1
    if dry_run:
        event(progress, agent, patch, "TEST_PASSED", "dry-run test gate skipped", gate=gate)
    if not dry_run and not amend_if_dirty(cwd, ignored_paths, config, progress, agent, patch, gate):
        return 1
    event(progress, agent, patch, "DONE", "patch completed", gate=gate)
    return 0


def render_dashboard(progress: Path) -> None:
    renderer = Path(__file__).resolve().parents[2] / "patch-progress-dashboard" / "scripts" / "render_dashboard.py"
    if renderer.exists():
        subprocess.run([sys.executable, str(renderer), str(progress)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_config = sub.add_parser("init-config")
    init_config.add_argument("--output", required=True)
    init_config.set_defaults(func=cmd_init_config)

    init_manifest = sub.add_parser("init-manifest")
    init_manifest.add_argument("--range", required=True)
    init_manifest.add_argument("--output", required=True)
    init_manifest.add_argument("--cwd", default=".")
    init_manifest.set_defaults(func=cmd_init_manifest)

    run = sub.add_parser("run")
    run.add_argument("--manifest", required=True)
    run.add_argument("--config")
    run.add_argument("--progress", default="progress")
    run.add_argument("--workers", type=int)
    run.add_argument("--agent", default="runner-001")
    run.add_argument("--cwd", default=".")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--limit", type=int)
    run.set_defaults(func=cmd_run)

    resume = sub.add_parser("resume")
    resume.add_argument("--manifest", required=True)
    resume.add_argument("--config")
    resume.add_argument("--progress", default="progress")
    resume.add_argument("--workers", type=int)
    resume.add_argument("--agent", default="runner-001")
    resume.add_argument("--cwd", default=".")
    resume.add_argument("--dry-run", action="store_true")
    resume.add_argument("--limit", type=int)
    resume.set_defaults(func=cmd_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
