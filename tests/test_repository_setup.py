from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositorySetupTests(unittest.TestCase):
    def test_agents_file_contains_required_rules(self) -> None:
        instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

        required_rules = (
            "Create a corresponding Git commit after completing each change.",
            "Add or update relevant tests after each change.",
            "Obtain the user's approval before making large-scale changes.",
            "Never modify any content inside the `dataset` directory.",
        )
        for rule in required_rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, instructions)

    def test_large_local_artifacts_are_ignored(self) -> None:
        ignore_rules = {
            line.strip()
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertIn("dataset/", ignore_rules)
        self.assertIn("fiji-agent/runtime/", ignore_rules)
        self.assertIn("fiji-agent/cache/", ignore_rules)
        self.assertIn("**/.venv/", ignore_rules)
        self.assertIn("*.class", ignore_rules)
        self.assertIn("**/.ipynb_checkpoints/", ignore_rules)
        self.assertIn(".virtual_documents/", ignore_rules)
        self.assertIn("anaconda_projects/", ignore_rules)


if __name__ == "__main__":
    unittest.main()
