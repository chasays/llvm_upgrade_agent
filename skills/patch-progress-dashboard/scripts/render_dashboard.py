#!/usr/bin/env python3
"""Render an offline dashboard from LLVM patch cherry-pick progress files."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path


FINAL_STATES = {"CLEAN", "EMPTY", "CONFLICT_FIXED", "BUILD_PASSED", "TEST_PASSED", "DONE"}
ATTENTION_STATES = {"NEED_HUMAN", "BLOCKED", "BUILD_FAILED", "TEST_FAILED"}
DEFAULT_STATE = "PENDING"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
    return rows


def read_agents(path: Path) -> list[dict]:
    agents_dir = path / "agents"
    if not agents_dir.exists():
        return []
    agents = []
    for agent_file in sorted(agents_dir.glob("*.json")):
        try:
            row = json.loads(agent_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{agent_file}: invalid JSON: {exc}") from exc
        row.setdefault("agent", agent_file.stem)
        agents.append(row)
    return agents


def latest_patch_rows(events: list[dict]) -> list[dict]:
    by_sha: dict[str, dict] = {}
    for event in events:
        sha = str(event.get("sha", "")).strip()
        if not sha:
            continue
        current = by_sha.get(sha, {})
        files = event.get("files") or current.get("files") or []
        if isinstance(files, str):
            files = [files]
        by_sha[sha] = {
            "seq": event.get("seq", current.get("seq", "")),
            "sha": sha,
            "title": event.get("title", current.get("title", "")),
            "state": event.get("state", DEFAULT_STATE),
            "agent": event.get("agent", current.get("agent", "")),
            "updated_at": event.get("ts", event.get("updated_at", current.get("updated_at", ""))),
            "message": event.get("message", current.get("message", "")),
            "files": files,
        }
    return sorted(by_sha.values(), key=patch_sort_key)


def patch_sort_key(row: dict):
    seq = row.get("seq")
    try:
        return (0, int(seq), row.get("sha", ""))
    except (TypeError, ValueError):
        return (1, str(seq), row.get("sha", ""))


def summarize(patches: list[dict], agents: list[dict]) -> dict:
    states = Counter(row.get("state", DEFAULT_STATE) for row in patches)
    done = sum(states[state] for state in FINAL_STATES)
    attention = sum(states[state] for state in ATTENTION_STATES)
    return {
        "generated_at": utc_now(),
        "total": len(patches),
        "done": done,
        "remaining": max(len(patches) - done, 0),
        "attention": attention,
        "active_agents": len(agents),
        "states": dict(sorted(states.items())),
    }


def hotspot_counts(patches: list[dict]) -> dict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)
    for patch in patches:
        if patch.get("state") not in ATTENTION_STATES and patch.get("state") != "CONFLICT":
            continue
        for file_name in patch.get("files", []):
            parts = Path(str(file_name)).parts
            key = "/".join(parts[:3]) if len(parts) >= 3 else str(file_name)
            counts[key] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell.replace("\n", " ") for cell in row) + " |")
    return "\n".join(lines)


def render_markdown(summary: dict, patches: list[dict], agents: list[dict], hotspots: dict[str, int]) -> str:
    state_lines = "\n".join(f"- {state}: {count}" for state, count in summary["states"].items()) or "- none: 0"
    agent_rows = [
        [
            str(agent.get("agent", "")),
            str(agent.get("status", "")),
            str(agent.get("current_sha", "")),
            str(agent.get("state", "")),
            str(agent.get("updated_at", "")),
        ]
        for agent in agents
    ]
    patch_rows = [
        [
            str(patch.get("seq", "")),
            str(patch.get("sha", "")),
            str(patch.get("state", "")),
            str(patch.get("agent", "")),
            str(patch.get("message", "")),
        ]
        for patch in patches
    ]
    attention_rows = [
        [
            str(patch.get("seq", "")),
            str(patch.get("sha", "")),
            str(patch.get("state", "")),
            str(patch.get("message", "")),
        ]
        for patch in patches
        if patch.get("state") in ATTENTION_STATES
    ]
    hotspot_lines = "\n".join(f"- {path}: {count}" for path, count in hotspots.items()) or "- none: 0"
    return "\n".join(
        [
            "# LLVM Patch Progress Dashboard",
            "",
            f"Generated: {summary['generated_at']}",
            "",
            f"Total patches: {summary['total']}",
            f"Done: {summary['done']}",
            f"Remaining: {summary['remaining']}",
            f"Need human: {summary['states'].get('NEED_HUMAN', 0)}",
            f"Blocked: {summary['states'].get('BLOCKED', 0)}",
            f"Active agents: {summary['active_agents']}",
            "",
            "## States",
            "",
            state_lines,
            "",
            "## Agents",
            "",
            markdown_table(["agent", "status", "sha", "state", "updated_at"], agent_rows) if agent_rows else "No agent heartbeats found.",
            "",
            "## Attention Queue",
            "",
            markdown_table(["seq", "sha", "state", "message"], attention_rows) if attention_rows else "No patches need attention.",
            "",
            "## Failure Hotspots",
            "",
            hotspot_lines,
            "",
            "## Patches",
            "",
            markdown_table(["seq", "sha", "state", "agent", "message"], patch_rows) if patch_rows else "No patch events found.",
            "",
        ]
    )


def render_html(summary: dict, patches: list[dict], agents: list[dict], hotspots: dict[str, int]) -> str:
    state_cards = "".join(
        f"<div class='metric'><span>{escape(state)}</span><strong>{count}</strong></div>"
        for state, count in summary["states"].items()
    )
    agent_rows = "".join(
        "<tr>"
        f"<td>{escape(str(agent.get('agent', '')))}</td>"
        f"<td>{escape(str(agent.get('status', '')))}</td>"
        f"<td>{escape(str(agent.get('current_sha', '')))}</td>"
        f"<td>{escape(str(agent.get('state', '')))}</td>"
        f"<td>{escape(str(agent.get('updated_at', '')))}</td>"
        "</tr>"
        for agent in agents
    )
    patch_rows = "".join(
        "<tr>"
        f"<td>{escape(str(patch.get('seq', '')))}</td>"
        f"<td>{escape(str(patch.get('sha', '')))}</td>"
        f"<td>{escape(str(patch.get('state', '')))}</td>"
        f"<td>{escape(str(patch.get('agent', '')))}</td>"
        f"<td>{escape(', '.join(str(file_name) for file_name in patch.get('files', [])))}</td>"
        f"<td>{escape(str(patch.get('message', '')))}</td>"
        "</tr>"
        for patch in patches
    )
    hotspot_items = "".join(f"<li>{escape(path)} <strong>{count}</strong></li>" for path, count in hotspots.items())
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>LLVM Patch Progress Dashboard</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; color: #17202a; background: #f6f8fa; }}
    header {{ padding: 20px 28px; background: #ffffff; border-bottom: 1px solid #d8dee4; }}
    main {{ padding: 20px 28px; }}
    h1 {{ font-size: 24px; margin: 0 0 8px; }}
    h2 {{ font-size: 18px; margin: 24px 0 10px; }}
    .muted {{ color: #59636e; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }}
    .metric {{ background: #ffffff; border: 1px solid #d8dee4; border-radius: 6px; padding: 12px; }}
    .metric span {{ display: block; color: #59636e; font-size: 12px; }}
    .metric strong {{ display: block; font-size: 24px; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #d8dee4; }}
    th, td {{ text-align: left; border-bottom: 1px solid #d8dee4; padding: 8px 10px; font-size: 13px; vertical-align: top; }}
    th {{ background: #eef2f5; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ font-family: Consolas, monospace; }}
  </style>
</head>
<body>
  <header>
    <h1>LLVM Patch Progress Dashboard</h1>
    <div class="muted">Generated {escape(summary['generated_at'])}. Auto-refreshes every 30 seconds.</div>
  </header>
  <main>
    <section class="grid">
      <div class="metric"><span>Total patches</span><strong>{summary['total']}</strong></div>
      <div class="metric"><span>Done</span><strong>{summary['done']}</strong></div>
      <div class="metric"><span>Remaining</span><strong>{summary['remaining']}</strong></div>
      <div class="metric"><span>Need human</span><strong>{summary['states'].get('NEED_HUMAN', 0)}</strong></div>
      <div class="metric"><span>Blocked</span><strong>{summary['states'].get('BLOCKED', 0)}</strong></div>
      <div class="metric"><span>Active agents</span><strong>{summary['active_agents']}</strong></div>
    </section>
    <h2>States</h2>
    <section class="grid">{state_cards}</section>
    <h2>Agents</h2>
    <table><thead><tr><th>Agent</th><th>Status</th><th>SHA</th><th>State</th><th>Updated</th></tr></thead><tbody>{agent_rows}</tbody></table>
    <h2>Failure Hotspots</h2>
    <ul>{hotspot_items or '<li>none <strong>0</strong></li>'}</ul>
    <h2>Patches</h2>
    <table><thead><tr><th>Seq</th><th>SHA</th><th>State</th><th>Agent</th><th>Files</th><th>Message</th></tr></thead><tbody>{patch_rows}</tbody></table>
  </main>
</body>
</html>
"""


def render(progress_dir: Path) -> dict:
    events = read_jsonl(progress_dir / "events.jsonl")
    agents = read_agents(progress_dir)
    patches = latest_patch_rows(events)
    summary = summarize(patches, agents)
    hotspots = hotspot_counts(patches)
    write_json(progress_dir / "api" / "summary.json", summary)
    write_json(progress_dir / "api" / "patches.json", patches)
    write_json(progress_dir / "api" / "agents.json", agents)
    (progress_dir / "DASHBOARD.md").write_text(render_markdown(summary, patches, agents, hotspots), encoding="utf-8")
    (progress_dir / "dashboard.html").write_text(render_html(summary, patches, agents, hotspots), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("progress_dir", nargs="?", default="progress", help="Progress directory containing events.jsonl and agents/")
    args = parser.parse_args()
    progress_dir = Path(args.progress_dir)
    progress_dir.mkdir(parents=True, exist_ok=True)
    summary = render(progress_dir)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
