#!/usr/bin/env python3
"""Run the portable skill-pack checks with only Python stdlib."""

from pathlib import Path
import runpy
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    test_file = root / "tests" / "test_skill_pack.py"
    sys.path.insert(0, str(root))
    runpy.run_path(str(test_file), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
