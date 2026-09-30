"""Execute the delivered notebook's analysis cells against real CSV inputs."""
import ast
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import nbformat


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "EmbryoAnalyser/run_workflow.ipynb"


class WorkflowNotebookTests(unittest.TestCase):
    def test_notebook_schema_and_all_code_cells_compile(self):
        notebook = nbformat.read(NOTEBOOK, as_version=4)
        nbformat.validate(notebook)
        self.assertTrue(any("RUN_FIJI = True" in cell.source for cell in notebook.cells))
        for index, cell in enumerate(notebook.cells):
            if cell.cell_type == "code":
                with self.subTest(cell=index):
                    ast.parse(cell.source)
                    self.assertIsNone(cell.execution_count)
                    self.assertEqual(cell.outputs, [])

    def test_notebook_classification_and_existing_distribution_cells_execute(self):
        notebook = nbformat.read(NOTEBOOK, as_version=4)
        with tempfile.TemporaryDirectory(prefix="embryo-notebook-test-") as temporary:
            namespace = {"__name__": "__main__"}
            captured = []
            with redirect_stdout(io.StringIO()):
                for cell in notebook.cells:
                    if cell.cell_type != "code":
                        continue
                    source = cell.source
                    if "PLOT_EXISTING_COUNTS = False" in source:
                        source = source.replace("PLOT_EXISTING_COUNTS = False",
                                                "PLOT_EXISTING_COUNTS = True", 1)
                    exec(compile(source, str(NOTEBOOK), "exec"), namespace)
                    if "RUN_FIJI = True" in source:
                        output = Path(temporary)
                        namespace.update(OUTPUT=output,
                                         MODEL_FILE=output / "training/models.joblib",
                                         RUN_FIJI=False, display=captured.append)
            predictions = namespace["classified"]["predictions"]
            self.assertEqual(len(predictions), 10)
            self.assertIn("rf_prediction", predictions)
            self.assertIn("svm_prediction", predictions)
            report = json.loads((Path(temporary) / "classification/classification_report.json").read_text("utf-8"))
            self.assertEqual(report["predictions"], 10)
            samples = namespace["plotted"]["samples"]
            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0]["n_cells"], 114)
            self.assertTrue(Path(samples[0]["png"]).is_file())
            self.assertTrue(any(type(item).__name__ == "Image" for item in captured))


if __name__ == "__main__":
    unittest.main()
