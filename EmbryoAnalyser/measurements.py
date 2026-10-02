"""Protected Fiji morphology measurements and cell-mask export for TIFF/ROI pairs."""
from datetime import datetime
import math
from pathlib import Path
import shutil
import uuid

import numpy as np
import pandas as pd

from . import neighbours
from .fiji_worker import prepare_measurement_macro
from .preprocessing import MEASUREMENT_FEATURES, infer_label
from .segmentation import validate_roi_archive
from .workflow_io import DEFAULT_OUTPUT_ROOT, ensure_output_directory, safe_destination, sample_name, write_json


def matching_roi(image: Path) -> Path:
    """Never share a sole unmatched ZIP among several images in one folder."""
    archives = [p for p in image.parent.iterdir() if p.is_file() and p.suffix.lower() == ".zip"]
    named = [p for p in archives if p.stem.casefold() == (image.stem + "_rois").casefold()]
    if len(named) == 1:
        return named[0].resolve()
    images = [p for p in image.parent.iterdir() if p.is_file() and p.suffix.lower() in (".tif", ".tiff")]
    if not named and len(archives) == 1 and len(images) == 1:
        return archives[0].resolve()
    raise ValueError(f"Missing or ambiguous ROI ZIP for {image}; use <image_stem>_rois.zip.")


def measurement_workflow(inputs, output_dir=None, *, measure=True, export_masks=False,
                         fiji_path=None, python_executable=None, timeout=None) -> dict:
    """Measure raw morphology and/or export masks; classification cleans the CSVs.

    Each run has a unique output directory. CSVs remain raw measurements,
    including cells later excluded by the model's AR filter. The original
    macro's mask export excludes ROIs within two pixels of the image border.
    """
    if type(measure) is not bool or type(export_masks) is not bool or not (measure or export_masks):
        raise ValueError("Select measurements, masks, or both.")
    if timeout is not None:
        if isinstance(timeout, bool) or not math.isfinite(float(timeout)) or float(timeout) <= 0:
            raise ValueError("Fiji timeout must be a positive number of seconds.")
        timeout = float(timeout)
    output = safe_destination(output_dir or DEFAULT_OUTPUT_ROOT / "preprocessing")
    supplied = [inputs] if isinstance(inputs, (str, Path)) else list(inputs)
    for item in supplied:
        directory = Path(item).expanduser().resolve()
        if directory.is_dir() and (output == directory or directory in output.parents):
            raise ValueError("Choose an output directory outside the input directory.")
    images = neighbours.collect_images(supplied)
    pairs = [(image, matching_roi(image)) for image in images]
    for _, roi in pairs:
        validate_roi_archive(roi)
    executable = Path(python_executable or neighbours.DEFAULT_PYTHON).resolve(strict=True)
    fiji = Path(fiji_path or neighbours.DEFAULT_FIJI).resolve(strict=True)
    run_dir = ensure_output_directory(output / ("preprocessing_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]))
    csv_dir = ensure_output_directory(run_dir / "samples")
    samples = []
    for image, roi in pairs:
        label = infer_label(image)
        category = "input" if label is None else ("mutant" if label else "control")
        sample_id = sample_name(image)
        workspace = ensure_output_directory(csv_dir / category / sample_id)
        copies = ensure_output_directory(workspace / "input_copies")
        ensure_output_directory(workspace / "results")
        shutil.copy2(image, safe_destination(copies / "image.tif"))
        shutil.copy2(roi, safe_destination(copies / "image_rois.zip"))
        macro = safe_destination(workspace / "run_make_mask.ijm")
        macro.write_text(prepare_measurement_macro(workspace, measure, export_masks), encoding="utf-8")
        samples.append({"sample_id": sample_id, "input_image": str(image), "input_roi": str(roi),
                        "workspace": str(workspace), "macro": str(macro),
                        "measurement_csv": str(workspace / "results/image/measurement.csv"),
                        "masks_dir": str(workspace / "results/image/masks")})
    manifest = write_json(run_dir / "fiji_manifest.json", {
        "task": "measure", "measure": measure, "export_masks": export_masks,
        "fiji_path": str(fiji), "samples": samples,
    })
    worker = neighbours._run_worker(manifest, executable, timeout)
    for sample in samples:
        if measure:
            frame = pd.read_csv(sample["measurement_csv"])
            missing = set(MEASUREMENT_FEATURES) - set(frame.columns)
            if missing or frame.empty:
                raise ValueError(f"Invalid Fiji measurements for {sample['input_image']}: missing {sorted(missing)}")
            values = frame[list(MEASUREMENT_FEATURES)].apply(pd.to_numeric, errors="raise")
            if not np.isfinite(values.to_numpy()).all():
                raise ValueError("Fiji measurements contain non-finite values.")
            sample["measured_cells"] = len(frame)
        else:
            sample["measurement_csv"] = None
        sample["mask_files"] = sorted(str(p) for p in Path(sample["masks_dir"]).glob("mask_*.png")) if export_masks else []
        sample["n_masks"] = len(sample["mask_files"])
    report = {"run_dir": str(run_dir), "csv_dir": str(csv_dir) if measure else None,
              "measure": measure, "export_masks": export_masks, "samples": samples, "fiji": worker}
    report["report_json"] = str(write_json(run_dir / "preparation_report.json", report))
    return report
