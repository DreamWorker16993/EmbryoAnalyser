"""Check English documentation, GitHub links, and the documented task interface."""
import ast
from pathlib import Path
import re
import unittest

import nbformat

from embryo_analyser.workflow import build_parser


ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r"[\u3400-\u9fff]")


class DocumentationTests(unittest.TestCase):
    def test_readme_identifies_classifier_targets_and_default_training_set(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("WT versus sdk null classification", readme)
        self.assertIn("0=control (WT)", readme)
        self.assertIn("1=mutant (sdk null)", readme)
        self.assertIn("14 gap43-mCherry embryos: 8 WT and 6 sdk null", readme)

    def test_project_markdown_is_english_and_has_valid_local_links(self):
        documents = [ROOT / "README.md", ROOT / "AGENTS.md",
                     ROOT / "embryo_analyser/WORKFLOW.md", ROOT / "fiji-agent/README.md"]
        for path in documents:
            with self.subTest(document=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertIsNone(HAN.search(content))
                self.assertFalse(re.search(r"C:[\\/]Users[\\/]", content),
                                 "Shared documentation must not require a personal user path")
                for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
                    if "://" in target or target.startswith("#"):
                        continue
                    self.assertTrue((path.parent / target.split("#", 1)[0]).exists(), target)

    def test_notebook_markdown_is_english_and_outputs_are_cleared(self):
        for path in (ROOT / "embryo_analyser").glob("*.ipynb"):
            with self.subTest(notebook=path.name):
                notebook = nbformat.read(path, as_version=4)
                nbformat.validate(notebook)
                for cell in notebook.cells:
                    if cell.cell_type == "markdown":
                        self.assertIsNone(HAN.search(cell.source))
                    elif cell.cell_type == "code":
                        self.assertIsNone(cell.execution_count)
                        self.assertEqual(cell.outputs, [])
                if path.name in ("run_workflow.ipynb", "staged_workflow.ipynb"):
                    for cell in notebook.cells:
                        if cell.cell_type == "code":
                            ast.parse(cell.source)
                            self.assertIsNone(HAN.search(cell.source))

    def test_readme_examples_match_the_actual_parser(self):
        parser = build_parser()
        examples = [
            ["measure", "--input", "images", "--export-masks", "--output", "out"],
            ["masks", "--input", "images", "--output", "out"],
            ["segment", "--input", "images", "--output", "out"],
            ["segment", "--input", "raw", "--z-projection", "max", "--output", "out"],
            ["neighbours", "--input", "images", "--output", "out", "--show"],
            ["train", "--input", "train", "--model", "both", "--output", "out"],
            ["classify", "--input", "csvs", "--model-file", "models.joblib", "--output", "out"],
            ["distribution", "--input", "counts", "--output", "out", "--show"],
        ]
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for arguments in examples:
            with self.subTest(command=arguments[0]):
                self.assertEqual(parser.parse_args(arguments).command, arguments[0])
                self.assertIn('workflow.py" ' + arguments[0], readme)

    def test_historical_report_and_presentation_are_removed(self):
        self.assertFalse((ROOT / "embryo_analyser/2026_EmbryoAnalyser_report.pdf").exists())
        self.assertFalse((ROOT / "embryo_analyser/final_presentation.pptx").exists())
        self.assertFalse((ROOT / "fiji-agent/README.zh-CN.md").exists())
        for path in ("embryo_analyser/macros/neighbour_counting_connect_centroid.ijm",
                     "fiji-agent/java-support/fijiagent/MemoryPreferencesFactory.java"):
            self.assertTrue((ROOT / path).is_file())

    def test_unused_sources_are_removed_and_active_interfaces_remain(self):
        obsolete = (
            "embryo_analyser/mask_to_dm.ipynb", "embryo_analyser/final_analyser.ipynb",
            "embryo_analyser/n_neighbour_distribution.ipynb", "embryo_analyser/helpers.py",
            "embryo_analyser/make_mask.ijm", "embryo_analyser/terminal_commands.txt",
            "fiji-agent/debug_java.py", "fiji-agent/test_bridge.py",
        )
        for path in obsolete:
            with self.subTest(path=path):
                self.assertFalse((ROOT / path).exists())
        self.assertEqual(
            {path.name for path in (ROOT / "embryo_analyser").glob("*.ipynb")},
            {"run_workflow.ipynb", "staged_workflow.ipynb"},
        )
        self.assertEqual(
            sorted(path.name for path in (ROOT / "embryo_analyser/macros").glob("*.ijm")),
            ["make_mask.ijm", "neighbour_counting_connect_centroid.ijm"],
        )


if __name__ == "__main__":
    unittest.main()
