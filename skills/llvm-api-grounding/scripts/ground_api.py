#!/usr/bin/env python3
"""Search a local LLVM checkout for real API definitions and callers."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


DEFAULT_DIRS = ["llvm/include", "llvm/lib", "clang/include", "clang/lib", "mlir/include", "mlir/lib"]


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def candidate_roots(repo):
    roots = []
    for rel in DEFAULT_DIRS:
        path = repo / rel
        if path.exists():
            roots.append(rel)
    return roots or ["."]


def rg_search(repo, symbol, max_results):
    cmd = ["rg", "-n", "--fixed-strings", "--glob", "!.git", symbol]
    cmd.extend(candidate_roots(repo))
    proc = run(cmd, repo)
    lines = proc.stdout.splitlines()
    return lines[:max_results], proc.stderr.strip()


def fallback_search(repo, symbol, max_results):
    results = []
    for root in candidate_roots(repo):
        base = repo / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if len(results) >= max_results:
                return results, ""
            if path.suffix not in {".h", ".hpp", ".cpp", ".inc", ".td", ".def", ".ll"}:
                continue
            try:
                for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if symbol in line:
                        results.append(f"{path.relative_to(repo)}:{lineno}:{line}")
                        break
            except OSError:
                continue
    return results, ""


def context(repo, match_line, radius):
    parts = match_line.split(":", 2)
    if len(parts) < 3 or not parts[1].isdigit():
        return ""
    rel, lineno_s, _ = parts
    path = repo / rel
    lineno = int(lineno_s)
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    start = max(1, lineno - radius)
    end = min(len(lines), lineno + radius)
    rendered = []
    for idx in range(start, end + 1):
        marker = ">" if idx == lineno else " "
        rendered.append(f"{marker} {idx}: {lines[idx - 1]}")
    return "\n".join(rendered)


def record_memory(memory_dir, symbol, repo, matches):
    if not memory_dir or not matches:
        return
    script = Path(__file__).resolve().parents[2] / "agent-memory" / "scripts" / "memory.py"
    if not script.exists():
        return
    cmd = [
        sys.executable,
        str(script),
        "record",
        "--memory-dir",
        str(memory_dir),
        "--kind",
        "llvm-api-grounding",
        "--summary",
        f"Grounded LLVM API `{symbol}` with {len(matches)} local matches.",
        "--source",
        f"{repo}:{matches[0]}",
        "--confidence",
        "trusted",
        "--applies-to",
        "local-llvm-source",
        "--applies-to",
        symbol,
    ]
    for match in matches[:5]:
        cmd.extend(["--evidence", match])
    subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+", help="Symbols or literal API strings to ground")
    parser.add_argument("--repo", default=os.environ.get("LLVM_REPO", "."), help="LLVM project checkout")
    parser.add_argument("--max-results", type=int, default=30)
    parser.add_argument("--context", type=int, default=3)
    parser.add_argument("--memory-dir", help="Optional agent-memory directory for trusted grounding evidence")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"error: repo does not exist: {repo}", file=sys.stderr)
        return 2

    use_rg = shutil.which("rg") is not None
    print(f"# LLVM API Grounding\n\nRepository: `{repo}`\n")
    exit_code = 0
    for symbol in args.symbols:
        print(f"## `{symbol}`\n")
        matches, err = rg_search(repo, symbol, args.max_results) if use_rg else fallback_search(repo, symbol, args.max_results)
        if err:
            print(f"Search warning: `{err}`\n")
        if not matches:
            print("No literal matches found. Treat this API as ungrounded until another search proves it exists.\n")
            exit_code = 1
            continue
        record_memory(args.memory_dir, symbol, repo, matches)
        for match in matches:
            print(f"### {match.split(':', 2)[0]}\n")
            print("```text")
            snippet = context(repo, match, args.context)
            print(snippet or match)
            print("```\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
