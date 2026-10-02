"""Independent, automatic Cellpose batch stage; original images stay read only."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import zipfile

try:
    from .workflow_io import (DEFAULT_OUTPUT_ROOT, PROJECT_ROOT, ensure_output_directory,
                              expand_inputs, safe_destination, sample_name, write_json)
except ImportError:
    from workflow_io import (DEFAULT_OUTPUT_ROOT, PROJECT_ROOT, ensure_output_directory,
                             expand_inputs, safe_destination, sample_name, write_json)


DEFAULT_CELLPOSE_PYTHON = Path(r"C:\Users\ethan\anaconda3\envs\cellpose_env\python.exe")
WORKER = Path(__file__).with_name("cellpose_worker.py")


def validate_roi_archive(path) -> int:
    """Reject missing/empty/corrupt archives before they can reach Fiji."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if not members or any(member.is_dir() or not member.filename.lower().endswith(".roi")
                                  for member in members):
                raise ValueError("ROI ZIP must contain ImageJ .roi files")
            for member in members:
                data = archive.read(member)
                if len(data) < 64 or data[:4] != b"Iout":
                    raise ValueError(f"Invalid ImageJ ROI: {member.filename}")
            return len(members)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        raise ValueError(f"Missing, empty, or invalid ROI ZIP: {path}: {error}") from error


def segmentation_workflow(inputs, output_dir=None, *, python_executable=None,
                          pretrained_model="cpsam_v2", z_projection=None, z_plane=None,
                          diameter=None, use_gpu=False, timeout=None) -> dict:
    """Copy TIFFs, run the original Cellpose CLI once, and return reusable ROIs.

    Directories are searched recursively. This stage does not train classifiers,
    start Fiji, or open a GUI. Z-stacks require an explicit maximum projection
    or zero-based plane, because the subsequent neighbour macro uses 2D ROIs.
    A new run directory prevents overwriting earlier segmentation results.
    """
    output = safe_destination(output_dir or DEFAULT_OUTPUT_ROOT / "segmentation")
    if z_projection not in (None, "max") or (z_projection is not None and z_plane is not None):
        raise ValueError("Choose z_projection='max' or z_plane, not both.")
    if z_plane is not None and (isinstance(z_plane, bool) or not isinstance(z_plane, int) or z_plane < 0):
        raise ValueError("z_plane must be a non-negative, zero-based integer.")
    for name, value in (("timeout", timeout), ("diameter", diameter)):
        if value is not None and (isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0):
            raise ValueError(f"{name} must be a positive finite number.")
    paths = expand_inputs(inputs, suffix=(".tif", ".tiff"))
    # Match Cellpose's exclusion of already exported mask/flow images.
    excluded = ("_cp_masks", "_masks", "_cp_output", "_flows", "_flows_0", "_flows_1", "_flows_2", "_cellprob")
    paths = [path for path in paths if not path.stem.lower().endswith(excluded)]
    if not paths:
        raise ValueError("No embryo TIFF inputs remain after excluding mask/flow outputs.")
    executable = Path(python_executable or os.environ.get("EMBRYO_CELLPOSE_PYTHON")
                      or DEFAULT_CELLPOSE_PYTHON).expanduser().resolve(strict=True)
    if not executable.is_file():
        raise ValueError("Cellpose Python must be an executable file.")
    run_dir = ensure_output_directory(output / ("segmentation_" + datetime.now().strftime("%Y%m%d_%H%M%S_")
                                               + uuid.uuid4().hex[:8]))
    image_dir = ensure_output_directory(run_dir / "images")
    copied_dir = ensure_output_directory(run_dir / "input_copies")
    samples = []
    for source in paths:
        label = sample_name(source)
        copied = safe_destination(copied_dir / (label + ".tif"))
        # Cellpose writes ROI ZIP and segmentation state beside its inputs.
        # Copying first protects source folders regardless of CLI savedir.
        shutil.copy2(source, copied)
        image = safe_destination(image_dir / (label + ".tif"))
        samples.append({"sample_id": label, "input_image": str(source),
                        "source_sha256": hashlib.sha256(copied.read_bytes()).hexdigest(),
                        "input_copy": str(copied), "image_file": str(image),
                        "roi_file": str(safe_destination(image.with_name(label + "_rois.zip"))),
                        "seg_file": str(safe_destination(image.with_name(label + "_seg.npy")))})
    manifest = write_json(run_dir / "cellpose_manifest.json", {
        "run_dir": str(run_dir), "image_dir": str(image_dir), "samples": samples,
        "pretrained_model": str(pretrained_model), "z_projection": z_projection,
        "z_plane": z_plane, "diameter": diameter, "use_gpu": bool(use_gpu),
    })
    log = safe_destination(run_dir / "cellpose_worker.log")
    result_file = safe_destination(run_dir / "cellpose_worker_result.json")
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    # Streaming to a file keeps large batches bounded and permits progress inspection.
    try:
        with log.open("w", encoding="utf-8") as stream:
            completed = subprocess.run([str(executable), "-u", str(WORKER), str(manifest)],
                                       cwd=str(PROJECT_ROOT), stdout=stream, stderr=subprocess.STDOUT,
                                       env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
                                       timeout=float(timeout) if timeout is not None else None, **kwargs)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Cellpose batch timed out after {timeout} seconds; see {log}.") from error
    result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.is_file() else {}
    if completed.returncode != 0 or not result.get("passed"):
        raise RuntimeError(f"Cellpose segmentation failed: {result.get('error', 'worker did not finish')}; see {log}.")
    returned = result.get("samples", [])
    if len(returned) != len(samples):
        raise RuntimeError(f"Cellpose returned an incomplete batch; see {log}.")
    for expected, actual in zip(samples, returned):
        if any(actual.get(key) != expected[key] for key in ("sample_id", "image_file", "roi_file", "seg_file")):
            raise RuntimeError("Cellpose returned outputs outside the expected sample paths.")
        if not Path(expected["seg_file"]).is_file():
            raise RuntimeError(f"Missing segmentation state: {expected['seg_file']}")
        actual["n_rois"] = validate_roi_archive(safe_destination(expected["roi_file"]))
    report = {**result, "run_dir": str(run_dir), "image_dir": str(image_dir),
              "manifest": str(manifest), "log": str(log), "result_path": str(result_file),
              "python_executable": str(executable), "command_documentation": "README.md#segment-images"}
    report["report_json"] = str(write_json(run_dir / "segmentation_report.json", report))
    return report
