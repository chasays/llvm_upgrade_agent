#!/usr/bin/env python3
"""Create a compact three-way git conflict work packet."""

import argparse
from pathlib import Path
import subprocess
import sys


def git(args):
    return subprocess.run(["git"] + args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def must_git_root():
    proc = git(["rev-parse", "--show-toplevel"])
    if proc.returncode != 0:
        print("error: not inside a git repository", file=sys.stderr)
        return None
    return Path(proc.stdout.strip())


def git_text(args):
    proc = git(args)
    return proc.stdout if proc.returncode == 0 else f"[unavailable: {' '.join(args)}]\n{proc.stderr}"


def stage(path, number):
    return git_text(["show", f":{number}:{path}"])


def truncate(text, max_bytes):
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= max_bytes:
        return text
    return raw[:max_bytes].decode("utf-8", errors="replace") + "\n\n[truncated]\n"


def section(title, body, max_bytes):
    return f"## {title}\n\n```text\n{truncate(body, max_bytes)}```\n\n"


def build_packet(paths, max_bytes):
    root = must_git_root()
    if root is None:
        return 2, ""
    out = [f"# Git Conflict Context\n\nRepository: `{root}`\n\n"]
    out.append("## Status\n\n```text\n")
    out.append(git_text(["status", "--short"]))
    out.append("```\n\n")
    for path in paths:
        out.append(f"# File: `{path}`\n\n")
        worktree = Path(path)
        if worktree.exists():
            out.append(section("Worktree With Conflict Markers", worktree.read_text(encoding="utf-8", errors="replace"), max_bytes))
        out.append(section("Base (:1)", stage(path, 1), max_bytes))
        out.append(section("Ours (:2)", stage(path, 2), max_bytes))
        out.append(section("Theirs (:3)", stage(path, 3), max_bytes))
        out.append(section("Recent History", git_text(["log", "--oneline", "-n", "8", "--", path]), max_bytes))
    return 0, "".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--output", help="Write markdown packet to this file")
    parser.add_argument("--max-bytes", type=int, default=30000)
    args = parser.parse_args()
    code, packet = build_packet(args.paths, args.max_bytes)
    if args.output:
        Path(args.output).write_text(packet, encoding="utf-8")
        print(args.output)
    else:
        print(packet)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

