#!/usr/bin/env python3
"""Expand LLVM TableGen records with llvm-tblgen --print-records."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def find_tblgen(build):
    if build:
        candidate = Path(build) / "bin" / "llvm-tblgen"
        if candidate.exists():
            return str(candidate)
    return shutil.which("llvm-tblgen")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("td_file")
    parser.add_argument("--llvm-source", required=True)
    parser.add_argument("--llvm-build")
    parser.add_argument("-I", "--include", action="append", default=[])
    parser.add_argument("--grep", help="Print only lines containing this literal text")
    parser.add_argument("--output")
    args = parser.parse_args()

    tblgen = find_tblgen(args.llvm_build)
    if not tblgen:
        print("error: llvm-tblgen not found. Pass --llvm-build or add llvm-tblgen to PATH.", file=sys.stderr)
        return 2
    src = Path(args.llvm_source)
    td = Path(args.td_file)
    includes = [td.parent, src / "llvm" / "include"] + [Path(p) for p in args.include]
    cmd = [tblgen, "--print-records"] + [item for inc in includes for item in ("-I", str(inc))] + [str(td)]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        return proc.returncode
    output = proc.stdout
    if args.grep:
        output = "\n".join(line for line in output.splitlines() if args.grep in line) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(args.output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
