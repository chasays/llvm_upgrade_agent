#!/usr/bin/env python3
"""Small JSONL ledger for LLVM downstream patch upgrade state."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


DEFAULT_LEDGER = "DOWNSTREAM_PATCHES.jsonl"


def now():
    return datetime.now(timezone.utc).isoformat()


def read_rows(path):
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_rows(path, rows):
    Path(path).write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + ("\n" if rows else ""), encoding="utf-8")


def git_commit_info(sha):
    proc = subprocess.run(["git", "show", "--name-only", "--format=%H%n%s", "--no-renames", sha], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return sha, "", []
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    commit = lines[0] if lines else sha
    summary = lines[1] if len(lines) > 1 else ""
    files = lines[2:] if len(lines) > 2 else []
    return commit, summary, files


def cmd_init(args):
    path = Path(args.ledger)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    print(path)
    return 0


def cmd_add(args):
    rows = read_rows(args.ledger)
    patch_id = args.patch_id or args.sha
    sha, git_summary, files = git_commit_info(args.sha) if args.sha else ("", "", [])
    row = {
        "patch_id": patch_id,
        "sha": sha or args.sha,
        "summary": args.summary or git_summary,
        "status": args.status,
        "risk": args.risk,
        "touched_files": args.file or files,
        "notes": [args.note] if args.note else [],
        "updated_at": now(),
    }
    rows = [r for r in rows if r.get("patch_id") != patch_id]
    rows.append(row)
    write_rows(args.ledger, rows)
    print(json.dumps(row, indent=2, sort_keys=True))
    return 0


def cmd_update(args):
    rows = read_rows(args.ledger)
    found = False
    for row in rows:
        if row.get("patch_id") == args.patch_id:
            found = True
            if args.status:
                row["status"] = args.status
            if args.risk:
                row["risk"] = args.risk
            if args.note:
                row.setdefault("notes", []).append(args.note)
            row["updated_at"] = now()
    if not found:
        raise SystemExit(f"patch not found: {args.patch_id}")
    write_rows(args.ledger, rows)
    return 0


def cmd_list(args):
    rows = read_rows(args.ledger)
    for row in rows:
        print(f"{row.get('patch_id','-')}\t{row.get('status','-')}\t{row.get('risk','-')}\t{row.get('summary','')}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(func=cmd_init)
    add = sub.add_parser("add")
    add.add_argument("--patch-id")
    add.add_argument("--sha", required=True)
    add.add_argument("--summary")
    add.add_argument("--status", default="new")
    add.add_argument("--risk", default="unknown")
    add.add_argument("--file", action="append")
    add.add_argument("--note")
    add.set_defaults(func=cmd_add)
    upd = sub.add_parser("update")
    upd.add_argument("--patch-id", required=True)
    upd.add_argument("--status")
    upd.add_argument("--risk")
    upd.add_argument("--note")
    upd.set_defaults(func=cmd_update)
    sub.add_parser("list").set_defaults(func=cmd_list)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

