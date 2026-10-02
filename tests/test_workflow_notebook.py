"""Execute the delivered notebook's analysis cells against real CSV inputs."""
import ast
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import nbformat


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "EmbryoAnalyser/run_workflow.ipynb"


class WorkflowNotebookTests(unittest.TestCase):
    def test_setup_finds_project_from_nested_directory_without_legacy_notebook(self):
        for name in ("run_workflow.ipynb", "staged_workflow.ipynb"):
            path = ROOT / "EmbryoAnalyser" / name
            notebook = nbformat.read(path, as_version=4)
            setup = next(cell for cell in notebook.cells
                         if cell.cell_type == "code" and "ROOT = next(" in cell.source)
            namespace = {"__name__": "__main__"}
            with self.subTest(notebook=name), patch.object(Path, "cwd", return_value=ROOT / "tests/fixtures"):
                with redirect_stdout(io.StringIO()):
                    exec(compile(setup.source, str(path), "exec"), namespace)
                self.assertEqual(namespace["ROOT"], ROOT)

    def test_staged_notebook_is_clean_and_tasks_start_only_when_selected(self):
        staged = ROOT / "EmbryoAnalyser/staged_workflow.ipynb"
        notebook = nbformat.read(staged, as_version=4)
        nbformat.validate(notebook)
        namespace = {"__name__": "__main__"}
        for cell in notebook.cells:
            if cell.cell_type == "code":
                ast.parse(cell.source)
                self.assertIsNone(cell.execution_count)
                self.assertEqual(cell.outputs, [])
                with redirect_stdout(io.StringIO()):
                    exec(compile(cell.source, str(staged), "exec"), namespace)
        for task in ("SEGMENTATION", "MEASUREMENT", "MASKS", "TRAINING", "CLASSIFICATION", "NEIGHBOURS", "DISTRIBUTION"):
            self.assertFalse(namespace["RUN_" + task])
        # Selecting segmentation performs only that task and provides a reusable
        # image directory for a later, separately selected neighbour task.
        from EmbryoAnalyser import workflow, neighbours
        report = {"samples": [{"input_image": "source", "n_rois": 2, "image_file": "image", "roi_file": "roi"}],
                  "image_dir": "output_images", "report_json": "report.json"}
        with patch.dict(namespace, {"RUN_SEGMENTATION": True, "display": lambda value: None}), \
                patch.object(workflow, "classify_workflow") as classify, \
                patch.object(neighbours, "run_neighbours") as count:
            fake_segment = unittest.mock.Mock(return_value=report)
            namespace["segmentation_workflow"] = fake_segment
            cell = next(c for c in notebook.cells if c.cell_type == "code" and "if RUN_SEGMENTATION:" in c.source)
            with redirect_stdout(io.StringIO()):
                exec(compile(cell.source, str(staged), "exec"), namespace)
            fake_segment.assert_called_once()
            self.assertEqual(namespace["NEIGHBOUR_INPUTS"], [Path("output_images")])
            self.assertEqual(namespace["PREPROCESS_IMAGE_INPUTS"], [Path("output_images")])
            classify.assert_not_called()
            count.assert_not_called()
        namespace.update(RUN_MEASUREMENT=True, RUN_MASKS=False, display=lambda value: None)
        fake_prepare = unittest.mock.Mock(return_value={"csv_dir": "measured_csvs", "run_dir": "prepared", "samples": []})
        namespace["measurement_workflow"] = fake_prepare
        cell = next(c for c in notebook.cells if c.cell_type == "code" and "if RUN_MEASUREMENT or RUN_MASKS:" in c.source)
        with redirect_stdout(io.StringIO()):
            exec(compile(cell.source, str(staged), "exec"), namespace)
        self.assertEqual(namespace["CSV_INPUTS"], [Path("measured_csvs")])
        self.assertEqual(namespace["TRAIN_INPUTS"], [Path("measured_csvs")])
        self.assertEqual(fake_prepare.call_args.kwargs["measure"], True)
        self.assertEqual(fake_prepare.call_args.kwargs["export_masks"], False)

    def test_notebook_schema_and_all_code_cells_compile(self):
        notebook = nbformat.read(NOTEBOOK, as_version=4)
        nbformat.validate(notebook)
        self.assertTrue(any("RUN_FIJI = True" in cell.source for cell in notebook.cells))
        for index, cell in enumerate(notebook.cells):
            if cell.cell_type == "code":
                with self.subTest(cell=index):
                    ast.parse(cell.source)
                    # A user may execute the notebook and keep their results.
                    self.assertTrue(cell.execution_count is None or isinstance(cell.execution_count, int))
                    self.assertIsInstance(cell.outputs, list)

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
                                         RUN_FIJI=False, display=captured.append)
            predictions = namespace["classified"]["predictions"]
            self.assertEqual(len(predictions), 10)
            self.assertIn("rf_prediction", predictions)
            self.assertIn("svm_prediction", predictions)
            report = json.loads((Path(temporary) / "classification/classification_report.json").read_text("utf-8"))
            self.assertEqual(report["predictions"], 10)
            from EmbryoAnalyser.workflow import DEFAULT_MODEL_FILE
            self.assertEqual(report["model_file"], str(DEFAULT_MODEL_FILE))
            self.assertFalse((Path(temporary) / "training").exists())
            samples = namespace["plotted"]["samples"]
            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0]["n_cells"], 114)
            self.assertTrue(Path(samples[0]["png"]).is_file())
            self.assertTrue(any(type(item).__name__ == "Image" for item in captured))


if __name__ == "__main__":
    unittest.main()
