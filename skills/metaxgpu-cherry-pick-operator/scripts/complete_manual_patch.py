#!/usr/bin/env python3
"""Mark the latest manually resolved attention patch as DONE."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ATTENTION_STATES = {"CONFLICT", "NEED_HUMAN", "BLOCKED", "BUILD_FAILED", "TEST_FAILED"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"{path} does not exist")
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def latest_attention(events: list[dict[str, Any]], sha: str | None) -> dict[str, Any]:
    for event in reversed(events):
        event_sha = str(event.get("sha", "")).strip()
        state = str(event.get("state", "")).strip()
        if sha and event_sha != sha:
            continue
        if state in ATTENTION_STATES:
            return event
    if sha:
        raise SystemExit(f"no attention event found for {sha}")
    raise SystemExit("no attention event found")


def write_heartbeat(progress: Path, agent: str, patch: dict[str, Any]) -> None:
    agents = progress / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    data = {
        "agent": agent,
        "status": "idle",
        "current_sha": patch.get("sha", ""),
        "current_seq": patch.get("seq", ""),
        "state": "DONE",
        "updated_at": utc_now(),
    }
    (agents / f"{agent}.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_dashboard(progress: Path) -> None:
    renderer = Path(__file__).resolve().parents[2] / "patch-progress-dashboard" / "scripts" / "render_dashboard.py"
    if not renderer.exists():
        return
    proc = subprocess.run([sys.executable, str(renderer), str(progress)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--progress", default="../output/progress-master", help="Progress directory containing events.jsonl")
    parser.add_argument("--sha", help="Specific original patch sha to mark done. Defaults to latest attention event.")
    parser.add_argument("--agent", default="claude-001")
    parser.add_argument("--message", default="manual conflict resolution completed")
    args = parser.parse_args()

    progress = Path(args.progress)
    events_path = progress / "events.jsonl"
    events = read_jsonl(events_path)
    patch = latest_attention(events, args.sha)
    files = patch.get("files", [])
    if isinstance(files, str):
        files = [files]
    row = {
        "ts": utc_now(),
        "agent": args.agent,
        "seq": patch.get("seq", ""),
        "sha": patch.get("sha", ""),
        "title": patch.get("title", ""),
        "state": "DONE",
        "files": files,
        "message": args.message,
        "resolved_from": patch.get("state", ""),
    }
    append_jsonl(events_path, row)
    write_heartbeat(progress, args.agent, row)
    render_dashboard(progress)
    print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
