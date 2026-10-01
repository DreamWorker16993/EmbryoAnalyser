"""Protected batch segmentation, explicit Z handling, and independent task checks."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from EmbryoAnalyser import segmentation, cellpose_worker, workflow, neighbours
from EmbryoAnalyser.workflow_io import DATASET_ROOT


class SegmentationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def image(self, folder="input", name="embryo.tif"):
        path = self.root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"original image")
        return path

    def archive(self, path, data=b"Iout" + bytes(60)):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("1.roi", data)

    def fake_batch(self, command, **kwargs):
        self.assertEqual(command[1:3], ["-u", str(segmentation.WORKER)])
        spec = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        cellpose_worker.validate_manifest(spec)
        for sample in spec["samples"]:
            shutil.copy2(sample["input_copy"], sample["image_file"])
            Path(sample["seg_file"]).write_bytes(b"saved masks")
            self.archive(sample["roi_file"])
        Path(spec["run_dir"], "cellpose_worker_result.json").write_text(
            json.dumps({"passed": True, "samples": spec["samples"]}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    def run_batch(self, inputs, **kwargs):
        with patch.object(segmentation.subprocess, "run", side_effect=self.fake_batch):
            return segmentation.segmentation_workflow(inputs, self.root / "out", python_executable=sys.executable, **kwargs)

    def test_recursive_batch_same_names_deduplicates_and_preserves_sources(self):
        first = self.image("input/one")
        second = self.image("input/two")
        before = [p.read_bytes() for p in (first, second)]
        report = self.run_batch([self.root / "input", first])
        self.assertEqual(len(report["samples"]), 2)
        self.assertEqual(len({s["image_file"] for s in report["samples"]}), 2)
        self.assertEqual([p.read_bytes() for p in (first, second)], before)
        self.assertFalse(any((self.root / "input").rglob("*.zip")))
        self.assertTrue(Path(report["report_json"]).is_file())
        self.assertTrue(all(s["n_rois"] == 1 for s in report["samples"]))
        self.assertEqual(neighbours.collect_images(report["image_dir"]),
                         sorted([Path(s["image_file"]) for s in report["samples"]], key=lambda p: str(p).casefold()))
        for sample in report["samples"]:
            self.assertEqual(neighbours.find_roi(Path(sample["image_file"])), Path(sample["roi_file"]))

    def test_repeated_single_segmentation_has_separate_outputs(self):
        image = self.image()
        first, second = self.run_batch(image), self.run_batch(image)
        self.assertNotEqual(first["run_dir"], second["run_dir"])
        self.assertTrue(Path(first["samples"][0]["roi_file"]).is_file())

    def test_excludes_cellpose_generated_mask_images(self):
        image = self.image()
        self.image(name="embryo_cp_masks.tif")
        self.image(name="embryo_flows.tif")
        report = self.run_batch(self.root / "input")
        self.assertEqual([s["input_image"] for s in report["samples"]], [str(image)])

    def test_dataset_rejected_before_copy_or_cellpose(self):
        image = self.image()
        with patch.object(segmentation.shutil, "copy2") as copy, patch.object(segmentation.subprocess, "run") as worker:
            with self.assertRaisesRegex(ValueError, "dataset"):
                segmentation.segmentation_workflow(image, DATASET_ROOT / "forbidden")
            copy.assert_not_called()
            worker.assert_not_called()

    def test_invalid_options_do_not_start_worker(self):
        for options in ({"z_projection": "mean"}, {"z_projection": "max", "z_plane": 0},
                        {"z_plane": -1}, {"z_plane": True}, {"timeout": 0},
                        {"timeout": float("inf")}, {"diameter": -1}):
            with self.subTest(options=options), patch.object(segmentation.subprocess, "run") as worker:
                with self.assertRaises(ValueError):
                    segmentation.segmentation_workflow(self.image(), self.root / "out", **options)
                worker.assert_not_called()

    def test_empty_corrupt_and_non_imagej_rois_are_rejected(self):
        roi = self.root / "bad.zip"
        for contents in (None, b"Not an ImageJ ROI", b"Iout"):
            with self.subTest(contents=contents):
                if contents is None:
                    with zipfile.ZipFile(roi, "w"):
                        pass
                else:
                    self.archive(roi, contents)
                with self.assertRaisesRegex(ValueError, "invalid ROI"):
                    segmentation.validate_roi_archive(roi)
        roi.write_bytes(b"not a zip")
        with self.assertRaises(ValueError):
            segmentation.validate_roi_archive(roi)

    def test_worker_failure_and_timeout_are_errors_with_logs(self):
        image = self.image()
        for outcome in (subprocess.CompletedProcess([], 1), subprocess.TimeoutExpired([], 1)):
            options = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
            with self.subTest(outcome=outcome), patch.object(segmentation.subprocess, "run", **options):
                with self.assertRaisesRegex(RuntimeError, "see .*cellpose_worker.log"):
                    segmentation.segmentation_workflow(image, self.root / "out", python_executable=sys.executable, timeout=1)

    def test_direct_worker_rejects_dataset_without_importing_cellpose(self):
        with self.assertRaisesRegex(ValueError, "dataset"):
            cellpose_worker.validate_manifest({"run_dir": str(DATASET_ROOT), "image_dir": str(DATASET_ROOT / "images")})

    def test_z_axis_conversion_is_explicit_and_checks_plane_range(self):
        with self.assertRaisesRegex(ValueError, "--z-projection"):
            cellpose_worker.image_layout((9, 3, 100, 120), "ZCYX")
        self.assertEqual(cellpose_worker.image_layout((9, 3, 100, 120), "ZCYX", "max"),
                         ([], 0, (3, 100, 120), "CYX"))
        self.assertEqual(cellpose_worker.image_layout((3, 9, 100, 120), "CZYX", z_plane=8)[1], 1)
        with self.assertRaisesRegex(ValueError, "outside"):
            cellpose_worker.image_layout((9, 3, 100, 120), "ZCYX", z_plane=9)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            cellpose_worker.image_layout((9, 100, 120), "QYX")
        with self.assertRaisesRegex(ValueError, "three channels"):
            cellpose_worker.image_layout((5, 100, 120), "CYX")

    def test_cli_segment_is_independent_and_forwards_settings(self):
        with patch.object(segmentation, "segmentation_workflow", return_value={"samples": [1], "image_dir": "images", "report_json": "report"}) as segment, \
                patch.object(workflow, "classify_workflow") as classify, patch.object(neighbours, "run_neighbours") as count:
            self.assertEqual(workflow.main(["segment", "--input", "a", "b", "--output", "out", "--z-projection", "max", "--diameter", "30", "--use-gpu"]), 0)
            self.assertEqual(segment.call_args.args, (["a", "b"], "out"))
            self.assertEqual(segment.call_args.kwargs["z_projection"], "max")
            self.assertTrue(segment.call_args.kwargs["use_gpu"])
            classify.assert_not_called()
            count.assert_not_called()

    @unittest.skipUnless(segmentation.DEFAULT_CELLPOSE_PYTHON.is_file(), "Cellpose runtime not installed")
    def test_real_tiff_projection_and_plane_do_not_modify_sources(self):
        code = '''
import hashlib
from pathlib import Path
import numpy as np
import tifffile
from EmbryoAnalyser.cellpose_worker import prepare_images
import sys
root=Path(sys.argv[1]); image=root/'stack.tif'
pixels=np.arange(3*2*12*14,dtype=np.uint16).reshape(3,2,12,14)
tifffile.imwrite(image,pixels,metadata={'axes':'ZCYX'},photometric='minisblack')
before=hashlib.sha256(image.read_bytes()).hexdigest()
for option in ({'z_projection':'max'}, {'z_plane':1}):
    target=root/('maximum.tif' if 'z_projection' in option else 'plane.tif')
    sample={'input_copy':str(image),'image_file':str(target)}
    result=prepare_images({'samples':[sample],**option})
    expected=pixels.max(axis=0) if 'z_projection' in option else pixels[1]
    np.testing.assert_array_equal(tifffile.imread(target),expected)
assert hashlib.sha256(image.read_bytes()).hexdigest()==before
'''
        result = subprocess.run([str(segmentation.DEFAULT_CELLPOSE_PYTHON), "-B", "-c", code, str(self.root)],
                                capture_output=True, text=True, cwd=segmentation.PROJECT_ROOT, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
