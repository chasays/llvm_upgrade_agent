import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

EXPECTED_SKILLS = {
    "llvm-api-grounding",
    "git-conflict-context",
    "update-test-checks",
    "alive2-verify",
    "lit-failure-triage",
    "downstream-patch-ledger",
    "tablegen-expand",
    "patch-progress-dashboard",
    "cherry-pick-runner",
}


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---", 4)
    data = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().strip('"')
    return data


class SkillPackTest(unittest.TestCase):
    def test_expected_skills_exist_with_valid_frontmatter(self):
        self.assertTrue(SKILLS.is_dir())
        names = {p.name for p in SKILLS.iterdir() if p.is_dir()}
        self.assertLessEqual(EXPECTED_SKILLS, names)

        for name in EXPECTED_SKILLS:
            skill = SKILLS / name / "SKILL.md"
            self.assertTrue(skill.is_file(), str(skill))
            meta = frontmatter(skill)
            self.assertEqual(meta["name"], name)
            self.assertTrue(meta["description"].startswith("Use when"))
            self.assertLess(len(meta["description"]), 700)

    def test_every_skill_has_at_least_one_python_script_that_compiles(self):
        for name in EXPECTED_SKILLS:
            scripts = sorted((SKILLS / name / "scripts").glob("*.py"))
            self.assertTrue(scripts, f"{name} has no helper scripts")
            for script in scripts:
                ast.parse(script.read_text(encoding="utf-8"), filename=str(script))

    def test_skills_do_not_contain_template_placeholders(self):
        for name in EXPECTED_SKILLS:
            for path in [SKILLS / name / "SKILL.md", SKILLS / name / "agents" / "openai.yaml"]:
                self.assertTrue(path.is_file(), str(path))
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("TODO", text)
                self.assertNotIn("[TODO", text)

    def test_board_and_agent_entrypoints_exist(self):
        self.assertTrue((ROOT / "BOARD.md").is_file())
        self.assertTrue((ROOT / "AGENTS.md").is_file())
        self.assertTrue((ROOT / "docs" / "mvp-skill-pack.md").is_file())

    def test_ledger_accepts_ledger_argument_after_subcommand(self):
        script = SKILLS / "downstream-patch-ledger" / "scripts" / "ledger.py"
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "patches.jsonl"
            proc = subprocess.run(
                [sys.executable, str(script), "init", "--ledger", str(ledger)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(ledger.is_file())

    def test_dashboard_renders_progress_outputs(self):
        script = SKILLS / "patch-progress-dashboard" / "scripts" / "render_dashboard.py"
        with tempfile.TemporaryDirectory() as tmp:
            progress = Path(tmp) / "progress"
            (progress / "agents").mkdir(parents=True)
            (progress / "packets").mkdir()
            (progress / "events.jsonl").write_text(
                "\n".join(
                    [
                        '{"ts":"2026-05-07T12:00:00+08:00","agent":"agent-001","sha":"aaa111","seq":1,"state":"CLAIMED","files":["llvm/lib/Target/MetaxGPU/A.cpp"],"message":"claimed"}',
                        '{"ts":"2026-05-07T12:01:00+08:00","agent":"agent-001","sha":"aaa111","seq":1,"state":"CLEAN","files":["llvm/lib/Target/MetaxGPU/A.cpp"],"message":"clean cherry-pick"}',
                        '{"ts":"2026-05-07T12:02:00+08:00","agent":"agent-002","sha":"bbb222","seq":2,"state":"NEED_HUMAN","files":["llvm/lib/CodeGen/B.cpp"],"message":"semantic conflict"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (progress / "agents" / "agent-001.json").write_text(
                '{"agent":"agent-001","status":"idle","current_sha":"aaa111","current_seq":1,"state":"CLEAN","updated_at":"2026-05-07T12:01:00+08:00"}',
                encoding="utf-8",
            )
            (progress / "agents" / "agent-002.json").write_text(
                '{"agent":"agent-002","status":"waiting","current_sha":"bbb222","current_seq":2,"state":"NEED_HUMAN","updated_at":"2026-05-07T12:02:00+08:00"}',
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(script), str(progress)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            dashboard = (progress / "DASHBOARD.md").read_text(encoding="utf-8")
            html = (progress / "dashboard.html").read_text(encoding="utf-8")
            summary = json.loads((progress / "api" / "summary.json").read_text(encoding="utf-8"))
            self.assertIn("Total patches: 2", dashboard)
            self.assertIn("Need human: 1", dashboard)
            self.assertIn("bbb222", html)
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["states"]["CLEAN"], 1)
            self.assertEqual(summary["states"]["NEED_HUMAN"], 1)

    def test_cherry_pick_runner_writes_default_hybrid_config(self):
        script = SKILLS / "cherry-pick-runner" / "scripts" / "cherry_pick_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "runner-config.json"
            proc = subprocess.run(
                [sys.executable, str(script), "init-config", "--output", str(config)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(data["worker_count"], 1)
            self.assertEqual(data["gate_strategy"], "hybrid")
            self.assertGreater(data["full_gate_interval"], 0)
            self.assertTrue(data["auto_amend_after_repair"])
            self.assertEqual(data["build_repair"]["max_attempts"], 3)
            self.assertEqual(data["test_repair"]["max_attempts"], 2)

    def test_cherry_pick_runner_dry_run_records_hybrid_gate_events(self):
        script = SKILLS / "cherry-pick-runner" / "scripts" / "cherry_pick_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "patches.jsonl"
            config = root / "runner-config.json"
            progress = root / "progress"
            manifest.write_text(
                "\n".join(
                    [
                        '{"seq":1,"sha":"aaa111","title":"normal patch","risk":"low","files":["llvm/lib/Target/MetaxGPU/A.cpp"]}',
                        '{"seq":2,"sha":"bbb222","title":"tablegen patch","risk":"low","files":["llvm/lib/Target/MetaxGPU/B.td"]}',
                        '{"seq":3,"sha":"ccc333","title":"third patch","risk":"low","files":["llvm/lib/Target/MetaxGPU/C.cpp"]}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            config.write_text(
                json.dumps(
                    {
                        "worker_count": 1,
                        "gate_strategy": "hybrid",
                        "full_gate_interval": 3,
                        "quick_build_commands": [],
                        "quick_test_commands": [],
                        "full_build_commands": [],
                        "full_test_commands": [],
                        "high_risk_patterns": [".td"],
                        "build_repair": {"max_attempts": 3, "command": []},
                        "test_repair": {"max_attempts": 2, "command": []},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "run",
                    "--manifest",
                    str(manifest),
                    "--config",
                    str(config),
                    "--progress",
                    str(progress),
                    "--dry-run",
                    "--limit",
                    "3",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            events = [
                json.loads(line)
                for line in (progress / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            gates = {
                event["sha"]: event["gate"]
                for event in events
                if event.get("state") == "GATE_SELECTED"
            }
            self.assertEqual(gates["aaa111"], "quick")
            self.assertEqual(gates["bbb222"], "heavy")
            self.assertEqual(gates["ccc333"], "full")

    def test_cherry_pick_runner_accepts_bom_encoded_manifest(self):
        script = SKILLS / "cherry-pick-runner" / "scripts" / "cherry_pick_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "patches.jsonl"
            progress = root / "progress"
            manifest.write_text(
                '{"seq":1,"sha":"aaa111","title":"bom patch","risk":"low","files":["llvm/lib/Target/MetaxGPU/A.cpp"]}\n',
                encoding="utf-8-sig",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "run",
                    "--manifest",
                    str(manifest),
                    "--progress",
                    str(progress),
                    "--dry-run",
                    "--limit",
                    "1",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            events = [
                json.loads(line)
                for line in (progress / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(events[-1]["state"], "DONE")


if __name__ == "__main__":
    unittest.main()
