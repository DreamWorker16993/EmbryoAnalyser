"""Protected image-to-CSV/mask staging and raw-CSV preprocessing integration."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import pandas as pd

from EmbryoAnalyser import measurements, fiji_worker, workflow
from EmbryoAnalyser.workflow_io import DATASET_ROOT


REFERENCE = DATASET_ROOT / "fixed_EM/processed/del15/s9_1/measurement.csv"


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def pair(self, folder="inputs", name="embryo.tif"):
        image = self.root / folder / name
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"original TIFF")
        roi = image.with_name(image.stem + "_rois.zip")
        with zipfile.ZipFile(roi, "w") as archive:
            archive.writestr("cell.roi", b"Iout" + bytes(60))
        return image, roi

    def fake_worker(self, manifest, executable, timeout):
        specification = json.loads(Path(manifest).read_text(encoding="utf-8"))
        fiji_worker.validate_manifest(specification)
        for sample in specification["samples"]:
            self.assertEqual((Path(sample["workspace"]) / "input_copies/image.tif").read_bytes(), b"original TIFF")
            directory = Path(sample["measurement_csv"]).parent
            directory.mkdir(parents=True)
            if specification["measure"]:
                shutil.copy2(REFERENCE, sample["measurement_csv"])
            if specification["export_masks"]:
                masks = Path(sample["masks_dir"])
                masks.mkdir()
                (masks / "mask_0.png").write_bytes(b"mask")
        return {"passed": True}

    def run_images(self, inputs, **kwargs):
        with patch.object(measurements.neighbours, "_run_worker", side_effect=self.fake_worker):
            return measurements.measurement_workflow(inputs, self.root / "out", fiji_path=self.root,
                                                     python_executable=__file__, **kwargs)

    def test_multiple_same_named_and_co_located_images_keep_corresponding_rois(self):
        first, roi = self.pair("inputs/control", "same.tif")
        second, _ = self.pair("inputs/mutant", "same.tiff")
        third, _ = self.pair("inputs/control", "other.tif")
        hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (first, roi, second, third)}
        report = self.run_images(first.parent.parent, export_masks=True)
        self.assertEqual(len(report["samples"]), 3)
        self.assertEqual(len({s["workspace"] for s in report["samples"]}), 3)
        self.assertEqual(len(list(Path(report["csv_dir"]).rglob("*.csv"))), 3)
        for sample in report["samples"]:
            self.assertTrue(Path(sample["measurement_csv"]).is_file())
            self.assertEqual(sample["n_masks"], 1)
        self.assertEqual(hashes, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in hashes})

    def test_measurements_and_masks_can_run_independently_and_repeat_safely(self):
        image, _ = self.pair()
        measured = self.run_images(image)
        masks = self.run_images(image, measure=False, export_masks=True)
        repeated = self.run_images(image)
        self.assertEqual(measured["samples"][0]["n_masks"], 0)
        self.assertIsNone(masks["csv_dir"])
        self.assertIsNone(masks["samples"][0]["measurement_csv"])
        self.assertFalse(list(Path(masks["run_dir"]).rglob("*.csv")))
        self.assertNotEqual(measured["run_dir"], repeated["run_dir"])

    def test_missing_or_unmatched_roi_is_rejected_before_fiji(self):
        first, roi = self.pair()
        roi.rename(roi.with_name("legacy.zip"))
        self.assertEqual(measurements.matching_roi(first).name, "legacy.zip")
        second, _ = self.pair(name="other.tif")
        with patch.object(measurements.neighbours, "_run_worker") as worker:
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                measurements.measurement_workflow(first.parent, self.root / "out")
            worker.assert_not_called()

    def test_dataset_and_input_output_paths_are_rejected_before_writes(self):
        image, _ = self.pair()
        for destination in (DATASET_ROOT / "forbidden_measurements", image.parent / "out"):
            with self.subTest(destination=destination), patch.object(measurements.neighbours, "_run_worker") as worker:
                with self.assertRaises(ValueError):
                    measurements.measurement_workflow(image.parent, destination)
                worker.assert_not_called()
                self.assertFalse(destination.exists())

    def test_direct_worker_rejects_output_escape_and_macro_changes(self):
        image, _ = self.pair()
        report = self.run_images(image)
        specification = json.loads((Path(report["run_dir"]) / "fiji_manifest.json").read_text(encoding="utf-8"))
        sample = specification["samples"][0]
        sample["measurement_csv"] = str(DATASET_ROOT / "forbidden.csv")
        with self.assertRaisesRegex(ValueError, "dataset"):
            fiji_worker.validate_manifest(specification)
        sample["measurement_csv"] = str(Path(sample["workspace"]) / "results/image/measurement.csv")
        Path(sample["measurement_csv"]).unlink()
        Path(sample["measurement_csv"]).parent.rmdir()
        macro = Path(sample["macro"])
        macro.write_text(macro.read_text(encoding="utf-8").replace("thres = 2", "thres = 3"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "algorithm"):
            fiji_worker.validate_manifest(specification)

    def test_cli_measure_and_masks_select_independent_tasks(self):
        for command, extra, measure, masks in (
                ("measure", [], True, False), ("measure", ["--export-masks"], True, True),
                ("masks", [], False, True)):
            with self.subTest(command=command, extra=extra), \
                    patch.object(measurements, "measurement_workflow", return_value={"samples": [], "run_dir": "out", "csv_dir": None}) as prepared:
                workflow.main([command, "--input", "images", "--output", "out", *extra])
                self.assertEqual(prepared.call_args.kwargs["measure"], measure)
                self.assertEqual(prepared.call_args.kwargs["export_masks"], masks)

    def test_measured_raw_csvs_are_automatically_cleaned_and_classified(self):
        image, _ = self.pair()
        prepared = self.run_images(image)
        source = Path(prepared["samples"][0]["measurement_csv"])
        original = source.read_bytes()
        raw = pd.read_csv(source)
        classified = workflow.classify_workflow(prepared["csv_dir"], output_dir=self.root / "classification")
        prediction = classified["predictions"].iloc[0]
        self.assertEqual(prediction.total_cells, len(raw))
        self.assertEqual(prediction.retained_cells, int(raw.AR.gt(1.5).sum()))
        self.assertEqual(source.read_bytes(), original)
        self.assertIn("rf_prediction", classified["predictions"])
        self.assertIn("svm_prediction", classified["predictions"])


if __name__ == "__main__":
    unittest.main()
