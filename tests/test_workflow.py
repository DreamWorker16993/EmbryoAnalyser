"""Regression checks for the added workflow; dataset inputs are read only."""
from __future__ import annotations

import csv
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
ANALYSER = ROOT / "EmbryoAnalyser"
DATASET = ROOT / "dataset"
sys.path.insert(0, str(ANALYSER))

from workflow_io import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT,
    ensure_output_directory,
    expand_inputs,
    safe_destination,
    sample_name,
    write_json,
)


class WorkflowOutputSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="embryo-workflow-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()

    def test_default_output_is_outside_dataset(self) -> None:
        self.assertEqual(DEFAULT_OUTPUT_ROOT, ROOT / "outputs")
        self.assertNotIn(DATASET, safe_destination(DEFAULT_OUTPUT_ROOT).parents)

    def test_creates_output_directory_outside_dataset(self) -> None:
        requested = self.directory / "new" / "output"
        result = ensure_output_directory(requested)
        self.assertEqual(result, requested.resolve())
        self.assertTrue(result.is_dir())

    def test_rejects_dataset_before_creating_any_directory_or_file(self) -> None:
        forbidden = DATASET / ("workflow_forbidden_" + uuid.uuid4().hex)
        self.assertFalse(forbidden.exists())
        for requested in (DATASET, forbidden, forbidden / "deeper" / "results.csv"):
            with self.subTest(path=str(requested)):
                with self.assertRaisesRegex(ValueError, "dataset"):
                    safe_destination(requested)
                with self.assertRaisesRegex(ValueError, "dataset"):
                    ensure_output_directory(requested)
                with self.assertRaisesRegex(ValueError, "dataset"):
                    write_json(requested, {"test": True})
        self.assertFalse(forbidden.exists())

    def test_rejects_link_into_dataset(self) -> None:
        link = self.directory / "dataset_alias"
        if os.name == "nt":
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(DATASET)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        else:
            link.symlink_to(DATASET, target_is_directory=True)
        # Remove only the link before TemporaryDirectory's recursive cleanup.
        self.addCleanup(lambda: link.rmdir() if os.name == "nt" else link.unlink())
        forbidden = link / ("workflow_forbidden_" + uuid.uuid4().hex) / "output"
        with self.assertRaisesRegex(ValueError, "dataset"):
            ensure_output_directory(forbidden)
        with self.assertRaisesRegex(ValueError, "dataset"):
            write_json(forbidden / "report.json", {})
        self.assertFalse(forbidden.exists())

    @unittest.skipUnless(os.name == "nt", "Windows extended paths")
    def test_rejects_extended_windows_dataset_path_before_creation(self) -> None:
        forbidden = DATASET / ("workflow_forbidden_" + uuid.uuid4().hex)
        extended = "\\\\?\\" + str(forbidden)
        self.assertFalse(forbidden.exists())
        with self.assertRaisesRegex(ValueError, "dataset"):
            safe_destination(extended)
        with self.assertRaisesRegex(ValueError, "dataset"):
            ensure_output_directory(extended)
        with self.assertRaisesRegex(ValueError, "dataset"):
            write_json(extended + "\\report.json", {})
        self.assertFalse(forbidden.exists())

    @unittest.skipUnless(os.name == "nt", "Windows extended junction paths")
    def test_rejects_extended_windows_junction_into_dataset(self) -> None:
        link = self.directory / "extended_dataset_alias"
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(DATASET)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.addCleanup(link.rmdir)
        forbidden = link / ("workflow_forbidden_" + uuid.uuid4().hex) / "output"
        extended = "\\\\?\\" + str(forbidden)
        with self.assertRaisesRegex(ValueError, "dataset"):
            safe_destination(extended)
        with self.assertRaisesRegex(ValueError, "dataset"):
            ensure_output_directory(extended)
        self.assertFalse(forbidden.exists())

    def test_writes_json_with_unicode_and_rejects_nonfinite_values(self) -> None:
        destination = self.directory / "results" / "summary.json"
        result = write_json(destination, {"sample": "胚胎", "count": 4})
        self.assertEqual(result, destination.resolve())
        self.assertEqual(json.loads(result.read_text(encoding="utf-8")),
                         {"sample": "胚胎", "count": 4})
        with self.assertRaises(ValueError):
            write_json(self.directory / "nan.json", {"value": float("nan")})

    def test_rejects_existing_hardlinked_output_without_changing_original(self) -> None:
        original = self.directory / "original.json"
        original.write_text('{"preserve":true}\n', encoding="utf-8")
        linked_output = self.directory / "linked_output.json"
        os.link(original, linked_output)
        self.assertTrue(original.samefile(linked_output))
        before = original.read_bytes()
        with self.assertRaisesRegex(ValueError, "hard|link"):
            safe_destination(linked_output)
        with self.assertRaisesRegex(ValueError, "hard|link"):
            write_json(linked_output, {"overwrite": True})
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(linked_output.read_bytes(), before)


class WorkflowInputDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="embryo-input-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()

    def make_file(self, relative: str) -> Path:
        path = self.directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test", encoding="utf-8")
        return path

    def test_single_batch_and_recursive_directory_are_deterministic(self) -> None:
        first = self.make_file("a/measurement.csv")
        second = self.make_file("b/measurement.CSV")
        self.make_file("b/unrelated.txt")
        expected = sorted([first, second], key=lambda path: str(path).casefold())
        self.assertEqual(expand_inputs(first), [first])
        self.assertEqual(expand_inputs([second, first, first]), expected)
        self.assertEqual(expand_inputs(self.directory), expected)

    def test_image_suffix_tuple_is_case_insensitive(self) -> None:
        first = self.make_file("first.TIF")
        second = self.make_file("nested/second.png")
        self.make_file("nested/rois.zip")
        self.assertEqual(expand_inputs(self.directory, suffix=(".tif", ".png")),
                         [first, second])

    def test_rejects_missing_wrong_extension_and_empty_inputs(self) -> None:
        wrong = self.make_file("image.tif")
        for supplied in (wrong, self.directory, []):
            with self.subTest(input=str(supplied)):
                with self.assertRaises(ValueError):
                    expand_inputs(supplied)
        with self.assertRaises(FileNotFoundError):
            expand_inputs(self.directory / "missing.csv")

    def test_same_named_samples_have_stable_distinct_output_names(self) -> None:
        first = self.make_file("a/measurement.csv")
        second = self.make_file("b/measurement.csv")
        self.assertEqual(sample_name(first), sample_name(first))
        self.assertNotEqual(sample_name(first), sample_name(second))
        self.assertRegex(sample_name(first), r"^[A-Za-z0-9._-]+_[0-9a-f]{10}$")


class WorkflowClassificationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="embryo-cli-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name).resolve()
        cls.training_inputs = DATASET / "raw_dataset" / "gap43-mCherry" / "train"
        cls.testing_inputs = DATASET / "raw_dataset" / "E-CadGFP"
        cls.training_csvs = expand_inputs(cls.training_inputs)
        cls.testing_csvs = expand_inputs(cls.testing_inputs)
        cls.single_csv = cls.testing_csvs[0]
        cls.original_hashes = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in cls.training_csvs + cls.testing_csvs + [
                ANALYSER / "final_analyser.ipynb",
                ANALYSER / "neighbour_counting_connect_centroid.ijm",
            ]
        }
        cls.addClassCleanup(cls.assert_original_inputs_unchanged)
        cls.training_output = cls.directory / "train-both"
        cls.run_cli("train", "--input", cls.training_inputs,
                    "--output", cls.training_output, "--model", "both")

    @classmethod
    def assert_original_inputs_unchanged(cls) -> None:
        for path, expected in cls.original_hashes.items():
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise AssertionError(f"Workflow changed a protected source: {path}")

    @classmethod
    def run_cli(cls, *arguments, success: bool = True) -> subprocess.CompletedProcess:
        environment = dict(os.environ, MPLBACKEND="Agg", PYTHONUTF8="1")
        completed = subprocess.run(
            [sys.executable, str(ANALYSER / "workflow.py"),
             *(str(argument) for argument in arguments)],
            cwd=ROOT, env=environment, capture_output=True, text=True,
            encoding="utf-8", check=False, timeout=180,
        )
        if success and completed.returncode != 0:
            raise AssertionError(completed.stdout + completed.stderr)
        if not success and completed.returncode == 0:
            raise AssertionError("Expected CLI to reject the requested operation")
        return completed

    def read_table(self, path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def assert_predictions(self, output: Path, expected_sources: list[Path]) -> None:
        predictions = self.read_table(output / "predictions.csv")
        profiles = self.read_table(output / "profiles.csv")
        self.assertEqual(len(predictions), len(expected_sources))
        self.assertEqual(len(profiles), len(expected_sources))
        self.assertEqual(
            {Path(row["source_csv"]).resolve() for row in predictions},
            {path.resolve() for path in expected_sources},
        )
        for row in predictions:
            self.assertGreater(int(row["total_cells"]), 0)
            self.assertGreater(int(row["retained_cells"]), 0)
            self.assertLessEqual(int(row["retained_cells"]), int(row["total_cells"]))
            for model in ("rf", "svm"):
                self.assertIn(int(row[f"{model}_prediction"]), (0, 1))
                self.assertIn(row[f"{model}_label"], ("control", "mutant"))
        report = json.loads((output / "classification_report.json").read_text("utf-8"))
        self.assertEqual(set(report["models"]), {"rf", "svm"})

    def test_train_real_batch_saves_both_models_and_profiles(self) -> None:
        import joblib

        model_file = self.training_output / "models.joblib"
        self.assertTrue(model_file.is_file())
        bundle = joblib.load(model_file)
        self.assertEqual(set(bundle.models), {"rf", "svm"})
        profiles = self.read_table(self.training_output / "training_profiles.csv")
        self.assertEqual(len(profiles), len(self.training_csvs))
        report = json.loads((self.training_output / "training_report.json").read_text("utf-8"))
        self.assertEqual(set(report["models"]), {"rf", "svm"})

    def test_classify_single_real_csv_with_both_models(self) -> None:
        output = self.directory / "classify-single"
        self.run_cli("classify", "--input", self.single_csv,
                     "--model-file", self.training_output / "models.joblib",
                     "--output", output)
        self.assert_predictions(output, [self.single_csv])

    def test_classify_real_recursive_batch_with_both_models(self) -> None:
        output = self.directory / "classify-directory"
        self.run_cli("classify", "--input", self.testing_inputs,
                     "--model-file", self.training_output / "models.joblib",
                     "--output", output)
        self.assert_predictions(output, self.testing_csvs)

    def test_classify_explicit_batch_retains_same_named_sources(self) -> None:
        output = self.directory / "classify-explicit"
        inputs = self.testing_csvs[:2]
        self.assertEqual(inputs[0].name, inputs[1].name)
        self.run_cli("classify", "--input", *inputs,
                     "--model-file", self.training_output / "models.joblib",
                     "--output", output)
        self.assert_predictions(output, inputs)

    def test_selects_rf_or_svm_training_models(self) -> None:
        import joblib

        for selected in ("rf", "svm"):
            with self.subTest(model=selected):
                output = self.directory / f"train-{selected}"
                self.run_cli("train", "--input", self.training_inputs,
                             "--output", output, "--model", selected)
                self.assertEqual(set(joblib.load(output / "models.joblib").models),
                                 {selected})

    def test_cli_rejects_dataset_output_before_writing(self) -> None:
        forbidden = DATASET / ("workflow_forbidden_" + uuid.uuid4().hex)
        self.assertFalse(forbidden.exists())
        for command in ("train", "classify", "distribution", "neighbours"):
            with self.subTest(command=command):
                if command == "neighbours":
                    source = next((DATASET / "fixed_EM" / "processed").rglob("*.tif"))
                elif command == "distribution":
                    source = next((DATASET / "fixed_EM" / "processed").rglob("neighbours.csv"))
                else:
                    source = self.single_csv
                arguments = [command, "--input", source, "--output", forbidden]
                if command == "classify":
                    arguments.extend(["--model-file", self.training_output / "models.joblib"])
                completed = self.run_cli(*arguments, success=False)
                self.assertIn("dataset", completed.stdout + completed.stderr)
                self.assertFalse(forbidden.exists())

    def test_classify_rejects_overwriting_its_loaded_model(self) -> None:
        spellings = ("ordinary", "extended") if os.name == "nt" else ("ordinary",)
        for spelling in spellings:
            with self.subTest(spelling=spelling):
                output = self.directory / f"model-collision-{spelling}"
                output.mkdir()
                model_file = output / "predictions.csv"
                shutil.copy2(self.training_output / "models.joblib", model_file)
                before = model_file.read_bytes()
                requested_model = ("\\\\?\\" + str(model_file)
                                   if spelling == "extended" else model_file)
                completed = self.run_cli(
                    "classify", "--input", self.single_csv,
                    "--model-file", requested_model, "--output", output, success=False,
                )
                self.assertIn("overwrite", completed.stdout + completed.stderr)
                self.assertEqual(model_file.read_bytes(), before)
                self.assertFalse((output / "profiles.csv").exists())
                self.assertFalse((output / "classification_report.json").exists())


class WorkflowDistributionIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="embryo-distribution-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.sources = [
            DATASET / "fixed_EM" / "processed" / "del15" / "s9_1" / "slow_neighbour_counting.csv",
            DATASET / "fixed_EM" / "processed" / "del15" / "s7_2" / "slow_neighbour_counting.csv",
        ]
        self.original_hashes = {source: hashlib.sha256(source.read_bytes()).hexdigest()
                                for source in self.sources}
        self.addCleanup(self.assert_sources_unchanged)

    def assert_sources_unchanged(self) -> None:
        for source, expected in self.original_hashes.items():
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), expected)

    def assert_distribution_matches_source(self, output: Path, source: Path) -> None:
        with source.open(encoding="utf-8-sig", newline="") as stream:
            expected = Counter(int(row["n_neighbours"]) for row in csv.DictReader(stream))
        table = output / sample_name(source) / "neighbour_distribution.csv"
        with table.open(encoding="utf-8-sig", newline="") as stream:
            distribution = list(csv.DictReader(stream))
        actual = {int(row["n_neighbours"]): int(row["count"]) for row in distribution}
        self.assertEqual(actual, {number: expected[number]
                                  for number in range(max(9, max(expected)) + 1)})
        self.assertEqual(sum(actual.values()), sum(expected.values()))
        self.assertAlmostEqual(sum(float(row["percent"]) for row in distribution), 100.0)
        for extension in ("png", "pdf"):
            artifact = table.with_suffix("." + extension)
            self.assertTrue(artifact.is_file())
            self.assertGreater(artifact.stat().st_size, 100)

    def test_existing_neighbour_csv_single_exports_matching_frequency_and_plots(self) -> None:
        output = self.directory / "single"
        WorkflowClassificationIntegrationTests.run_cli(
            "distribution", "--input", self.sources[0], "--output", output,
        )
        self.assert_distribution_matches_source(output, self.sources[0])

    def test_existing_neighbour_csv_batch_keeps_each_samples_distribution(self) -> None:
        output = self.directory / "batch"
        WorkflowClassificationIntegrationTests.run_cli(
            "distribution", "--input", *self.sources, "--output", output,
        )
        self.assertEqual(len(list(output.rglob("neighbour_distribution.csv"))), 2)
        for source in self.sources:
            with self.subTest(source=str(source)):
                self.assert_distribution_matches_source(output, source)


if __name__ == "__main__":
    unittest.main()
