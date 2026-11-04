"""Check the distributed skill and demo, beyond the CLI's mechanical checks."""

import csv
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_generated_instructions_match_skill_source(self):
        source = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        _, metadata, body = source.split("---", 2)
        description = next(line.removeprefix("description:").strip()
                           for line in metadata.splitlines() if line.startswith("description:"))
        title, body = body.lstrip().split("\n", 1)
        expected = f"{title}\n\n> {description}\n\n{body.lstrip().rstrip()}\n"
        for name in ("AGENTS.md", "CLAUDE.md"):
            with self.subTest(name=name):
                self.assertEqual((ROOT / name).read_text(encoding="utf-8"), expected)

    def test_local_document_links_resolve(self):
        docs = list(ROOT.glob("*.md")) + list((ROOT / "references").glob("*.md"))
        for doc in docs:
            for link in re.findall(r"\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
                if "://" in link or link.startswith("#"):
                    continue
                with self.subTest(document=doc.name, target=link):
                    self.assertTrue((doc.parent / link.split("#")[0]).is_file())

    def test_demo_reference_amounts_recompute_from_inputs(self):
        demo = ROOT / "examples/demo"
        oracle = json.loads((demo / "private/oracle.json").read_text(encoding="utf-8"))
        with (demo / "inputs/payments.csv").open(encoding="utf-8", newline="") as stream:
            payments = list(csv.DictReader(stream))
        total = Decimal(0)
        with (demo / "inputs/invoices.csv").open(encoding="utf-8", newline="") as stream:
            for invoice in csv.DictReader(stream):
                identifier = invoice["invoice_id"]
                eligible = Decimal(invoice["amount"]) if invoice["accepted"] == "true" else Decimal(0)
                paid = sum((Decimal(p["amount"]) for p in payments if p["invoice_id"] == identifier), Decimal(0))
                remaining = max(eligible - paid, Decimal(0))
                for key, value in (("eligible", eligible), ("paid", paid), ("remaining", remaining)):
                    self.assertEqual(value, Decimal(str(oracle[identifier][key])))
                total += remaining
                for locator in oracle["evidence"][identifier]:
                    match = re.match(r"([^:]+):(\d+)(?:-(\d+))?", locator)
                    self.assertIsNotNone(match)
                    lines = (demo / match[1]).read_text(encoding="utf-8").splitlines()
                    first, last = int(match[2]), int(match[3] or match[2])
                    self.assertTrue(1 <= first <= last <= len(lines))
        self.assertEqual(total, Decimal(str(oracle["remaining_total"])))

    def test_solver_prompt_contains_declared_deliverable_paths(self):
        demo = ROOT / "examples/demo"
        task = json.loads((demo / "task.json").read_text(encoding="utf-8"))
        prompt = (demo / task["prompt_path"]).read_text(encoding="utf-8")
        for deliverable in task["deliverables"]:
            self.assertIn(deliverable["path"], prompt)

    def test_demo_total_is_graded_in_the_requested_memo(self):
        demo = ROOT / "examples/demo"
        task = json.loads((demo / "task.json").read_text(encoding="utf-8"))
        outputs = {item["id"]: item["path"] for item in task["deliverables"]}
        total_check = next(item for item in task["criteria"] if item["id"] == "C04")
        self.assertEqual(outputs[total_check["deliverable_id"]], "output/memo.md")

    def install_script(self, root):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        scripts = re.findall(r"```bash\n(.*?)```", readme, re.DOTALL)
        script = next(script for script in scripts if 'skill_source=' in script)
        return script.replace("${HOME}", str(root))

    def test_repeated_documented_install_does_not_nest_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "shared-ai-skills/office-task-bench-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("existing skill", encoding="utf-8")
            target = root / ".codex/skills/office-task-bench-skill"
            target.parent.mkdir(parents=True)
            target.symlink_to(source, target_is_directory=True)
            result = subprocess.run(["bash", "-c", self.install_script(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual([p.name for p in source.iterdir()], ["SKILL.md"])
            self.assertEqual(target.resolve(), source.resolve())

    def test_documented_install_preserves_existing_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / ".codex/skills/office-task-bench-skill"
            target.parent.mkdir(parents=True)
            target.write_text("user-owned file", encoding="utf-8")
            result = subprocess.run(["bash", "-c", self.install_script(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "user-owned file")
            self.assertFalse((root / "shared-ai-skills/office-task-bench-skill").exists())


if __name__ == "__main__":
    unittest.main()
