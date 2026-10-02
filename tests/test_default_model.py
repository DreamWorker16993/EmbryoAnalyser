"""Verify the bundled gap43 model and classification without a training step."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from embryo_analyser.classifiers import load_bundle, predict_files, train_models
from embryo_analyser.workflow import DEFAULT_MODEL_FILE, build_parser, classify_workflow
from fixture_support import write_measurements


ROOT = Path(__file__).resolve().parents[1]
GAP43 = ROOT / "dataset/raw_dataset/gap43-mCherry"


class DefaultModelTests(unittest.TestCase):
    @unittest.skipUnless(GAP43.is_dir(), "Optional local training provenance fixtures")
    def test_bundled_model_matches_all_14_training_sources_and_fresh_fit(self):
        paths = sorted(GAP43.rglob("*.csv"))
        bundled = load_bundle(DEFAULT_MODEL_FILE)
        self.assertEqual(len(paths), 14)
        self.assertEqual(bundled.metadata["training_embryos"], 14)
        self.assertEqual(set(bundled.models), {"rf", "svm"})
        self.assertEqual(list(np.bincount(bundled.training_labels)), [8, 6])
        self.assertEqual(
            bundled.metadata["sources"],
            [{"path": path.relative_to(ROOT).as_posix(),
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths],
        )
        self.assertEqual(bundled.training_info["source_csv"].tolist(),
                         [path.relative_to(ROOT).as_posix() for path in paths])
        fresh = train_models(paths)
        pd.testing.assert_frame_equal(bundled.training_profiles, fresh.training_profiles)
        for name in ("rf", "svm"):
            self.assertEqual(bundled.selected_columns[name], fresh.selected_columns[name])
        test_inputs = ROOT / "dataset/raw_dataset/E-CadGFP"
        pd.testing.assert_frame_equal(predict_files(bundled, test_inputs),
                                      predict_files(fresh, test_inputs))

    @unittest.skipUnless(GAP43.is_dir(), "Optional local training overlap fixtures")
    def test_default_classification_loads_without_training_and_detects_overlap(self):
        source = next(GAP43.rglob("*.csv"))
        model_hash = hashlib.sha256(DEFAULT_MODEL_FILE.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temporary, \
                patch("embryo_analyser.classifiers.train_models", side_effect=AssertionError("Unexpected training")):
            result = classify_workflow(source, output_dir=temporary)
            self.assertEqual(result["report"]["model_file"], str(DEFAULT_MODEL_FILE))
            self.assertEqual(result["report"]["also_in_training"], [str(source.resolve())])
            self.assertEqual(set(result["report"]["models"]), {"rf", "svm"})
        self.assertEqual(hashlib.sha256(DEFAULT_MODEL_FILE.read_bytes()).hexdigest(), model_hash)

    def test_explicit_missing_model_is_rejected_without_default_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaises(FileNotFoundError):
                classify_workflow(write_measurements(directory / "input.csv"), directory / "missing.joblib",
                                  directory / "results")
            self.assertFalse((directory / "results/predictions.csv").exists())

    def test_cli_uses_default_model_from_another_working_directory(self):
        arguments = build_parser().parse_args(["classify", "--input", "input.csv"])
        self.assertIsNone(arguments.model_file)
        with tempfile.TemporaryDirectory() as temporary:
            command = [sys.executable, "-B", str(ROOT / "embryo_analyser/workflow.py"),
                       "classify", "--input", str(write_measurements(Path(temporary) / "input.csv")),
                       "--output", str(Path(temporary) / "results")]
            completed = subprocess.run(command, cwd=temporary, capture_output=True,
                                       text=True, encoding="utf-8", timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("rf_prediction", completed.stdout)
            self.assertIn("svm_prediction", completed.stdout)


if __name__ == "__main__":
    unittest.main()
