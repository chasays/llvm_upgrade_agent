#!/usr/bin/env python3
"""Run alive-tv and classify the result for patch review."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def find_alive_tv(override=None):
    if override:
        return override
    env = os.environ.get("ALIVE_TV")
    if env:
        return env
    found = shutil.which("alive-tv")
    return found


def record_memory(memory_dir, classification, cmd, ir, output):
    if not memory_dir:
        return
    script = Path(__file__).resolve().parents[2] / "agent-memory" / "scripts" / "memory.py"
    if not script.exists():
        return
    confidence = "trusted" if classification == "ALIVE2_PASS" else "candidate"
    record = [
        sys.executable,
        str(script),
        "record",
        "--memory-dir",
        str(memory_dir),
        "--kind",
        "alive2-result",
        "--summary",
        f"alive-tv classified {', '.join(ir)} as {classification}.",
        "--source",
        " ".join(cmd),
        "--confidence",
        confidence,
        "--applies-to",
        classification,
    ]
    for item in ir:
        record.extend(["--file", item])
    for line in output.splitlines()[:20]:
        if line.strip():
            record.extend(["--evidence", line.strip()])
    subprocess.run(record, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ir", nargs="+", help="One or two IR files accepted by alive-tv")
    parser.add_argument("--alive-tv", help="Path to alive-tv. Defaults to ALIVE_TV or PATH lookup.")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--extra", action="append", default=[], help="Extra argument for alive-tv")
    parser.add_argument("--memory-dir", help="Optional agent-memory directory for alive2 verification results")
    args = parser.parse_args()

    alive = find_alive_tv(args.alive_tv)
    if not alive:
        print("error: alive-tv not found. Set ALIVE_TV or add alive-tv to PATH.", file=sys.stderr)
        return 2
    for item in args.ir:
        if not Path(item).exists():
            print(f"error: IR file not found: {item}", file=sys.stderr)
            return 2

    cmd = [alive] + args.extra + args.ir
    print("command:", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        classification = "TIMEOUT_REVIEW_BLOCKER"
        print(f"classification: {classification}")
        record_memory(args.memory_dir, classification, cmd, args.ir, "")
        return 124
    print(proc.stdout)
    lowered = proc.stdout.lower()
    if proc.returncode == 0 and ("incorrect" not in lowered or "0 incorrect" in lowered):
        classification = "ALIVE2_PASS"
    else:
        classification = "ALIVE2_REVIEW_BLOCKER"
    print(f"classification: {classification}")
    record_memory(args.memory_dir, classification, cmd, args.ir, proc.stdout)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
