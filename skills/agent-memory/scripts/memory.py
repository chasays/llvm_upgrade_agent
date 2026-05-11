#!/usr/bin/env python3
"""Local JSONL memory store for LLVM upgrade agents."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_MEMORY_DIR = "memories"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def memory_path(memory_dir: str | Path, confidence: str) -> Path:
    filename = "trusted.jsonl" if confidence == "trusted" else "candidates.jsonl"
    return Path(memory_dir) / filename


def stable_id(row: dict[str, Any]) -> str:
    payload = {
        "kind": row.get("kind", ""),
        "summary": row.get("summary", ""),
        "source": row.get("source", ""),
        "applies_to": row.get("applies_to", []),
        "evidence": row.get("evidence", []),
        "sha": row.get("sha", ""),
        "seq": row.get("seq", ""),
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:12]


def command_record(args: argparse.Namespace) -> None:
    row: dict[str, Any] = {
        "kind": args.kind,
        "summary": args.summary,
        "source": args.source or "",
        "applies_to": args.applies_to or [],
        "evidence": args.evidence or [],
        "files": args.file or [],
        "sha": args.sha or "",
        "seq": args.seq or "",
        "confidence": args.confidence,
        "created_at": now_iso(),
    }
    row["id"] = args.id or stable_id(row)
    append_jsonl(memory_path(args.memory_dir, args.confidence), row)
    print(json.dumps(row, ensure_ascii=False, sort_keys=True))


def command_promote(args: argparse.Namespace) -> None:
    candidates = read_jsonl(memory_path(args.memory_dir, "candidate"))
    matches = [row for row in candidates if str(row.get("id", "")) == args.id]
    if not matches:
        raise SystemExit(f"candidate not found: {args.id}")
    row = dict(matches[-1])
    row["confidence"] = "trusted"
    row["reviewer"] = args.reviewer
    row["promoted_at"] = now_iso()
    if args.evidence:
        evidence = list(row.get("evidence") or [])
        evidence.extend(args.evidence)
        row["evidence"] = evidence
    append_jsonl(memory_path(args.memory_dir, "trusted"), row)
    print(json.dumps(row, ensure_ascii=False, sort_keys=True))


def searchable_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ["id", "kind", "summary", "source", "confidence", "sha", "seq"]:
        parts.append(str(row.get(key, "")))
    for key in ["applies_to", "evidence", "files"]:
        parts.extend(str(item) for item in row.get(key) or [])
    return "\n".join(parts).lower()


def command_search(args: argparse.Namespace) -> None:
    rows = read_jsonl(memory_path(args.memory_dir, "trusted"))
    if args.include_candidates:
        rows.extend(read_jsonl(memory_path(args.memory_dir, "candidate")))
    terms = [term.lower() for term in args.query.split() if term.strip()]
    found = [row for row in rows if all(term in searchable_text(row) for term in terms)]
    print(json.dumps(found[: args.limit], ensure_ascii=False, sort_keys=True))


def command_summarize_session(args: argparse.Namespace) -> None:
    events = read_jsonl(Path(args.progress) / "events.jsonl")
    states = Counter(str(event.get("state", "")) for event in events if event.get("state"))
    shas = {str(event.get("sha", "")).strip() for event in events if str(event.get("sha", "")).strip()}
    attention = [
        event
        for event in events
        if str(event.get("state", "")) in {"CONFLICT", "NEED_HUMAN", "BLOCKED", "BUILD_FAILED", "TEST_FAILED"}
    ]
    summary = {
        "session_id": args.session_id,
        "created_at": now_iso(),
        "progress": str(Path(args.progress)),
        "event_count": len(events),
        "patch_count": len(shas),
        "states": dict(sorted(states.items())),
        "attention_count": len(attention),
        "latest_attention": attention[-5:],
    }
    output = Path(args.memory_dir) / "session-summaries" / f"{args.session_id}.json"
    write_json(output, summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def add_memory_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--memory-dir", default=DEFAULT_MEMORY_DIR, help="Memory directory")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="Record a candidate or trusted memory")
    add_memory_dir(record)
    record.add_argument("--id", help="Override generated memory id")
    record.add_argument("--kind", required=True)
    record.add_argument("--summary", required=True)
    record.add_argument("--source")
    record.add_argument("--applies-to", action="append", default=[])
    record.add_argument("--evidence", action="append", default=[])
    record.add_argument("--file", action="append", default=[])
    record.add_argument("--sha")
    record.add_argument("--seq")
    record.add_argument("--confidence", choices=["candidate", "trusted"], default="candidate")
    record.set_defaults(func=command_record)

    promote = sub.add_parser("promote", help="Promote a candidate memory to trusted")
    add_memory_dir(promote)
    promote.add_argument("--id", required=True)
    promote.add_argument("--reviewer", required=True)
    promote.add_argument("--evidence", action="append", default=[])
    promote.set_defaults(func=command_promote)

    search = sub.add_parser("search", help="Search trusted memories")
    add_memory_dir(search)
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--include-candidates", action="store_true")
    search.set_defaults(func=command_search)

    summarize = sub.add_parser("summarize-session", help="Summarize progress events into memory")
    add_memory_dir(summarize)
    summarize.add_argument("--progress", default="progress")
    summarize.add_argument("--session-id", required=True)
    summarize.set_defaults(func=command_summarize_session)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
