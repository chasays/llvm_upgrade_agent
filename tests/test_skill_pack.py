import ast
from pathlib import Path
import subprocess
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
                ["python3", str(script), "init", "--ledger", str(ledger)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(ledger.is_file())


if __name__ == "__main__":
    unittest.main()
