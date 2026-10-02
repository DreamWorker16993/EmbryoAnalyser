"""Input safety, original macro preservation, and neighbour export regression tests."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import pandas as pd

from EmbryoAnalyser import neighbours
from EmbryoAnalyser import fiji_worker
from EmbryoAnalyser.workflow_io import DATASET_ROOT


class NeighbourTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def image(self, directory="input", name="test.tif"):
        directory = self.root / directory
        directory.mkdir(parents=True, exist_ok=True)
        image = directory / name
        image.write_bytes(b"source image")
        roi = directory / (image.stem + "_rois.zip")
        roi.write_bytes(b"source ROIs")
        return image, roi

    def test_single_directory_batch_and_duplicates(self):
        first, _ = self.image("genotype/s7_1", "one.TIF")
        second, _ = self.image("genotype/s7_2", "two.tiff")
        self.assertEqual(neighbours.collect_images(first), [first.resolve()])
        self.assertEqual(neighbours.collect_images([first, self.root / "genotype", second]),
                         [first.resolve(), second.resolve()])

    def test_missing_ambiguous_and_named_rois(self):
        image, roi = self.image()
        (image.parent / "other.zip").write_bytes(b"other")
        self.assertEqual(neighbours.find_roi(image), roi.resolve())
        roi.rename(image.parent / "one.zip")
        with self.assertRaisesRegex(ValueError, "Multiple ROI"):
            neighbours.find_roi(image)
        for path in image.parent.glob("*.zip"):
            path.unlink()
        with self.assertRaisesRegex(FileNotFoundError, "no corresponding ROI"):
            neighbours.find_roi(image)

    def test_macro_copy_changes_only_directory_prompt(self):
        original = neighbours.MACRO.read_bytes()
        source = original.decode("utf-8")
        workspace = self.root / "space in path"
        copied = neighbours.prepare_macro(workspace, source)
        new_expression = json.dumps(workspace.resolve().as_posix() + "/", ensure_ascii=False)
        self.assertEqual(copied.replace(new_expression, neighbours._PROMPT), source)
        self.assertEqual(neighbours.MACRO.read_bytes(), original)
        with self.assertRaisesRegex(ValueError, "directory prompt"):
            neighbours.prepare_macro(workspace, "unexpected source")

    def test_real_distribution_regression_and_exports(self):
        source = DATASET_ROOT / "fixed_EM/processed/del15/s9_1/slow_neighbour_counting.csv"
        distribution = neighbours.neighbour_distribution(source).set_index("n_neighbours")
        self.assertEqual(distribution.loc[range(2, 9), "count"].tolist(), [4, 11, 25, 33, 28, 12, 1])
        self.assertEqual(distribution["count"].sum(), 114)
        self.assertAlmostEqual(distribution["percent"].sum(), 100)
        exported = neighbours.plot_neighbour_distribution(source, self.root / "plots")
        for key in ("distribution_csv", "png", "pdf"):
            self.assertGreater(Path(exported[key]).stat().st_size, 0)
        self.assertEqual(exported["n_cells"], 114)

    def test_export_does_not_require_tk_gui_backend(self):
        source = DATASET_ROOT / "fixed_EM/processed/del15/s9_1/slow_neighbour_counting.csv"
        command = [sys.executable, "-c", "from EmbryoAnalyser.neighbours import plot_neighbour_distribution; import sys; plot_neighbour_distribution(sys.argv[1], sys.argv[2])", str(source), str(self.root / "portable")]
        environment = {**os.environ, "MPLBACKEND": "TkAgg"}
        completed = subprocess.run(command, cwd=str(neighbours.PROJECT), capture_output=True,
                                   text=True, env=environment, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((self.root / "portable/neighbour_distribution.png").is_file())

    def test_empty_csv_and_neighbours_above_nine(self):
        source = self.root / "counts.csv"
        pd.DataFrame({"n_neighbours": [0, 10, 12, 12]}).to_csv(source, index=False)
        table = neighbours.neighbour_distribution(source).set_index("n_neighbours")
        self.assertEqual(table.loc[12, "count"], 2)
        self.assertEqual(table.loc[12, "percent"], 50)
        pd.DataFrame(columns=["n_neighbours"]).to_csv(source, index=False)
        result = neighbours.plot_neighbour_distribution(source, self.root / "empty")
        self.assertEqual(result["n_cells"], 0)
        self.assertIsNone(result["mean_neighbours"])

    def test_invalid_neighbour_values_are_rejected(self):
        source = self.root / "invalid.csv"
        for value in (-1, 2.5, float("nan"), float("inf"), "bad"):
            with self.subTest(value=value):
                pd.DataFrame({"n_neighbours": [value]}).to_csv(source, index=False)
                with self.assertRaises(ValueError):
                    neighbours.neighbour_distribution(source)

    def test_plot_output_cannot_overwrite_input_csv(self):
        source = self.root / "neighbour_distribution.csv"
        original = b"n_neighbours\n3\n"
        source.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "overwrite its input"):
            neighbours.plot_neighbour_distribution(source, self.root)
        self.assertEqual(source.read_bytes(), original)

    @unittest.skipUnless(os.name == "nt", "Windows extended-path aliases")
    def test_extended_path_alias_cannot_overwrite_input_csv(self):
        source = self.root / "neighbour_distribution.csv"
        original = b"n_neighbours\n3\n"
        source.write_bytes(original)
        extended_source = Path("\\\\?\\" + str(source.resolve()))
        extended_output = Path("\\\\?\\" + str(self.root.resolve()))
        self.assertTrue(os.path.samefile(extended_source, source))
        for input_csv, output_dir in ((extended_source, self.root), (source, extended_output)):
            with self.subTest(input_csv=input_csv, output_dir=output_dir):
                with self.assertRaisesRegex(ValueError, "overwrite its input"):
                    neighbours.plot_neighbour_distribution(input_csv, output_dir)
                self.assertEqual(source.read_bytes(), original)

    def test_show_opens_png_only_when_explicitly_requested_outside_notebook(self):
        source = self.root / "counts.csv"
        source.write_text("n_neighbours\n3\n", encoding="utf-8")
        with patch("IPython.get_ipython", return_value=None), patch("webbrowser.open") as open_image:
            neighbours.plot_neighbour_distribution(source, self.root / "silent")
            open_image.assert_not_called()
            result = neighbours.plot_neighbour_distribution(source, self.root / "visible", show=True)
            open_image.assert_called_once_with(Path(result["png"]).as_uri())

    def test_timeout_must_be_positive_and_finite(self):
        image, _ = self.image()
        for timeout in (0, -1, float("nan"), float("inf"), True, "bad"):
            with self.subTest(timeout=timeout), patch.object(neighbours, "_run_worker") as worker:
                with self.assertRaisesRegex(ValueError, "positive number"):
                    neighbours.run_neighbours(image, self.root / "outputs", timeout=timeout)
                worker.assert_not_called()

    def test_worker_timeout_preserves_stdout_and_stderr(self):
        manifest = self.root / "fiji_manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        timeout = subprocess.TimeoutExpired("Fiji", 1, output=b"partial stdout", stderr=b"partial stderr")
        with patch.object(neighbours.subprocess, "run", side_effect=timeout):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                neighbours._run_worker(manifest, Path(__file__), timeout=1)
        log = (self.root / "fiji_worker.log").read_text(encoding="utf-8")
        self.assertIn("partial stdout", log)
        self.assertIn("partial stderr", log)

    def test_dataset_output_rejected_before_worker(self):
        image, _ = self.image()
        with patch.object(neighbours, "_run_worker") as worker:
            with self.assertRaisesRegex(ValueError, "dataset"):
                neighbours.run_neighbours(image, DATASET_ROOT / "forbidden", fiji_path=self.root,
                                          python_executable=__file__)
            worker.assert_not_called()

    def test_direct_worker_rejects_dataset_paths_without_starting_java(self):
        manifest = {"samples": [{"workspace": str(DATASET_ROOT / "forbidden"),
                                  "counts_csv": str(DATASET_ROOT / "forbidden/slow_neighbour_counting.csv"),
                                  "macro": str(DATASET_ROOT / "forbidden/run_neighbour_counting.ijm")}]}
        with self.assertRaisesRegex(ValueError, "dataset"):
            fiji_worker.validate_manifest(manifest)

    def test_relocated_macro_is_accepted_by_worker_without_algorithm_changes(self):
        image, roi = self.image()
        workspace = self.root / "valid_workspace"
        workspace.mkdir()
        shutil.copy2(image, workspace / "image.tif")
        shutil.copy2(roi, workspace / "image_rois.zip")
        macro = workspace / "run_neighbour_counting.ijm"
        macro.write_text(neighbours.prepare_macro(workspace), encoding="utf-8")
        manifest = {"samples": [{"workspace": str(workspace),
                                  "counts_csv": str(workspace / "slow_neighbour_counting.csv"),
                                  "macro": str(macro)}]}
        fiji_worker.validate_manifest(manifest)

    def test_direct_worker_rejects_modified_algorithm_before_starting_java(self):
        workspace = self.root / "copied_inputs"
        workspace.mkdir()
        (workspace / "image.tif").write_bytes(b"image")
        (workspace / "image_rois.zip").write_bytes(b"rois")
        macro = workspace / "run_neighbour_counting.ijm"
        macro.write_text(neighbours.prepare_macro(workspace).replace("enlarge=30", "enlarge=50"), encoding="utf-8")
        manifest = {"samples": [{"workspace": str(workspace), "macro": str(macro),
                                  "counts_csv": str(workspace / "slow_neighbour_counting.csv")}]}
        with self.assertRaisesRegex(ValueError, "directory prompt"):
            fiji_worker.validate_manifest(manifest)

    def test_batch_is_staged_independently_and_source_unchanged(self):
        first, first_roi = self.image("one/s7_1", "Composite.tif")
        second, _ = self.image("two/s7_1", "Composite.tif")
        expected = DATASET_ROOT / "fixed_EM/processed/del15/s9_1/slow_neighbour_counting.csv"
        def mock_worker(manifest_path, python_executable, timeout):
            self.assertIsNone(timeout)
            specification = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(specification["samples"]), 2)
            for sample in specification["samples"]:
                workspace = Path(sample["workspace"])
                self.assertEqual((workspace / "image.tif").read_bytes(), b"source image")
                self.assertEqual((workspace / "image_rois.zip").read_bytes(), b"source ROIs")
                shutil.copyfile(expected, sample["counts_csv"])
            return {"passed": True, "headless": False}
        with patch.object(neighbours, "_run_worker", side_effect=mock_worker):
            report = neighbours.run_neighbours([first, second], self.root / "outputs", fiji_path=self.root,
                                              python_executable=__file__)
        self.assertEqual(first.read_bytes(), b"source image")
        self.assertEqual(first_roi.read_bytes(), b"source ROIs")
        self.assertEqual(len(set(sample["workspace"] for sample in report["samples"])), 2)
        self.assertTrue(Path(report["summary_csv"]).is_file())
        self.assertTrue(Path(report["report_json"]).is_file())


if __name__ == "__main__":
    unittest.main()
