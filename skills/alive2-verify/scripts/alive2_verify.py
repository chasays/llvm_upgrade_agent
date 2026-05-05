#!/usr/bin/env python3
"""Run alive-tv and classify the result for patch review."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def find_alive_tv():
    env = os.environ.get("ALIVE_TV")
    if env:
        return env
    found = shutil.which("alive-tv")
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ir", nargs="+", help="One or two IR files accepted by alive-tv")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--extra", action="append", default=[], help="Extra argument for alive-tv")
    args = parser.parse_args()

    alive = find_alive_tv()
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
        print("classification: TIMEOUT_REVIEW_BLOCKER")
        return 124
    print(proc.stdout)
    lowered = proc.stdout.lower()
    if proc.returncode == 0 and ("incorrect" not in lowered or "0 incorrect" in lowered):
        print("classification: ALIVE2_PASS")
    else:
        print("classification: ALIVE2_REVIEW_BLOCKER")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())

