"""Runtime and notebook checks that require no private experimental inputs."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import nbformat
import pandas as pd

from EmbryoAnalyser import workflow
from fixture_support import synthetic_measurements, write_measurements


ROOT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def test_custom_training_and_prediction_work_with_generated_user_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frame = synthetic_measurements()
            for phenotype, selected in (("control", frame.iloc[[1] * 6]), ("mutant", frame.iloc[[12] * 7])):
                folder = root / "own_inputs" / phenotype
                folder.mkdir(parents=True)
                for number in range(3):
                    selected.to_csv(folder / f"embryo_{number}.csv", index=False)
            trained = workflow.train_workflow(root / "own_inputs", root / "training")
            self.assertEqual(trained["report"]["training_embryos"], 6)
            held_out = root / "new_embryo.csv"
            frame.iloc[[12] * 7].to_csv(held_out, index=False)
            result = workflow.classify_workflow(held_out, trained["model_file"], root / "classified")
            self.assertEqual(result["predictions"].rf_prediction.tolist(), [1])
            self.assertEqual(result["predictions"].svm_prediction.tolist(), [1])

    def test_default_prediction_reads_only_user_csvs_and_never_trains(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_measurements(root / "own_inputs/embryo.csv")
            original_reader = pd.read_csv
            def read_user_file(path, *args, **kwargs):
                self.assertEqual(Path(path).resolve(), source.resolve())
                return original_reader(path, *args, **kwargs)
            with patch("EmbryoAnalyser.preprocessing.pd.read_csv", side_effect=read_user_file), \
                    patch("EmbryoAnalyser.classifiers.train_models", side_effect=AssertionError("Unexpected training")):
                result = workflow.classify_workflow(source, output_dir=root / "results")
            self.assertEqual(len(result["predictions"]), 1)
            self.assertEqual(result["report"]["also_in_training"], [])

    def test_training_requires_user_inputs_before_fitting_or_creating_outputs(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch("EmbryoAnalyser.classifiers.train_models") as train:
            output = Path(temporary) / "results"
            with self.assertRaisesRegex(ValueError, "Provide training CSV"):
                workflow.train_workflow(output_dir=output)
            train.assert_not_called()
            self.assertFalse(output.exists())
        with redirect_stdout(io.StringIO()), patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit):
                workflow.build_parser().parse_args(["train"])

    def test_both_notebooks_start_without_input_files_or_enabled_tasks(self):
        for name in ("run_workflow.ipynb", "staged_workflow.ipynb"):
            path = ROOT / "EmbryoAnalyser" / name
            namespace = {"__name__": "__main__"}
            with self.subTest(notebook=name), redirect_stdout(io.StringIO()):
                for cell in nbformat.read(path, as_version=4).cells:
                    if cell.cell_type == "code":
                        exec(compile(cell.source, str(path), "exec"), namespace)
                for key, value in namespace.items():
                    if key.startswith("RUN_"):
                        self.assertFalse(value)
                    if key.endswith("INPUTS") or key == "EXISTING_COUNTS":
                        self.assertEqual(value, [])


if __name__ == "__main__":
    unittest.main()
