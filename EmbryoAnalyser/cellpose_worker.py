"""Adapt the existing Cellpose batch command to protected copies and 2D ROI output."""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
import logging
from pathlib import Path
import shutil
import sys
import time
import traceback

try:
    from .workflow_io import safe_destination, write_json
    from .segmentation import validate_roi_archive
except ImportError:
    from workflow_io import safe_destination, write_json
    from segmentation import validate_roi_archive


def validate_manifest(specification: dict) -> None:
    run_dir = safe_destination(specification["run_dir"])
    image_dir = safe_destination(specification["image_dir"])
    if image_dir != run_dir / "images" or not specification.get("samples"):
        raise ValueError("Cellpose requires samples in a protected images directory.")
    if image_dir.exists() and any(image_dir.iterdir()):
        raise ValueError("Cellpose images directory must be empty before preparation.")
    safe_destination(run_dir / "cellpose.log")
    paths = set()
    for sample in specification["samples"]:
        label = sample["sample_id"]
        for key, expected in (("input_copy", run_dir / "input_copies" / (label + ".tif")),
                              ("image_file", image_dir / (label + ".tif")),
                              ("roi_file", image_dir / (label + "_rois.zip")),
                              ("seg_file", image_dir / (label + "_seg.npy"))):
            target = safe_destination(sample[key])
            if target != expected or target in paths:
                raise ValueError("Cellpose sample paths must be unique and inside their protected run directory.")
            paths.add(target)
            if key != "input_copy" and target.exists():
                raise FileExistsError(f"Refusing to overwrite an existing Cellpose output: {target}")
        copied = Path(sample["input_copy"])
        if not copied.is_file() or hashlib.sha256(copied.read_bytes()).hexdigest() != sample["source_sha256"]:
            raise ValueError("The copied input is missing or differs from its recorded hash.")


def image_layout(shape, axes, z_projection=None, z_plane=None) -> tuple:
    """Describe an explicit 2D conversion; do not guess a Z axis or drop channels."""
    shape, axes = list(shape), list(axes)
    if len(shape) != len(axes) or len(set(axes)) != len(axes):
        raise ValueError("Ambiguous TIFF axes; supply an explicitly labeled 2D image.")
    removals = []
    for index in range(len(shape) - 1, -1, -1):
        if axes[index] not in "YX" and shape[index] == 1:
            removals.append(index)
            shape.pop(index)
            axes.pop(index)
    z_index = axes.index("Z") if "Z" in axes else None
    if z_index is not None:
        if z_projection != "max" and z_plane is None:
            raise ValueError("Z-stack needs --z-projection max or --z-plane INDEX for the 2D ROI/Fiji workflow.")
        if z_plane is not None and not 0 <= z_plane < shape[z_index]:
            raise ValueError(f"Z plane {z_plane} is outside this stack (0 through {shape[z_index]-1}).")
        shape.pop(z_index)
        axes.pop(z_index)
    if axes not in (list("YX"), list("CYX"), list("YXC"), list("SYX"), list("YXS")):
        raise ValueError(f"Unsupported TIFF axes {''.join(axes)}; supply 2D YX or a labeled channel image.")
    channel = next((i for i, axis in enumerate(axes) if axis in "CS"), None)
    if channel is not None and shape[channel] > 3:
        raise ValueError("Cellpose uses at most three channels; choose channels explicitly before segmentation.")
    return removals, z_index, tuple(shape), "".join(axes)


def prepare_images(specification: dict) -> list[dict]:
    import numpy as np
    import tifffile
    planned = []
    # Check every image before loading the model or running any inference.
    for sample in specification["samples"]:
        with tifffile.TiffFile(sample["input_copy"]) as tiff:
            if len(tiff.series) != 1:
                raise ValueError("Multiple-series TIFFs require selecting an embryo series first.")
            series = tiff.series[0]
            shape, axes = tuple(series.shape), series.axes
        layout = image_layout(shape, axes, specification.get("z_projection"), specification.get("z_plane"))
        planned.append((sample, shape, axes, layout))
    prepared = []
    for sample, shape, axes, (removals, z_index, output_shape, output_axes) in planned:
        destination = safe_destination(sample["image_file"])
        if not removals and z_index is None:
            shutil.copy2(sample["input_copy"], destination)
            operation = "unchanged_2d"
        else:
            with tifffile.TiffFile(sample["input_copy"]) as tiff:
                pixels = tiff.series[0].asarray()
            for index in removals:
                pixels = np.take(pixels, 0, axis=index)
            if z_index is not None:
                # Preserve X/Y coordinates so the exported ROIs align with
                # the same prepared image later passed to the Fiji macro.
                pixels = (pixels.max(axis=z_index) if specification.get("z_projection") == "max"
                          else np.take(pixels, specification["z_plane"], axis=z_index))
            tifffile.imwrite(destination, pixels, metadata={"axes": output_axes},
                             photometric="rgb" if output_axes == "YXS" and output_shape[-1] == 3 else "minisblack")
            operation = ("max_z_projection" if z_index is not None and specification.get("z_projection") == "max"
                         else "z_plane" if z_index is not None else "remove_singleton_axes")
        prepared.append({**sample, "input_shape": list(shape), "input_axes": axes,
                         "output_shape": list(output_shape), "output_axes": output_axes,
                         "preparation": operation, "z_plane": specification.get("z_plane") if z_index is not None else None})
    return prepared


def main(manifest_path) -> int:
    manifest = safe_destination(manifest_path)
    result_path = safe_destination(manifest.parent / "cellpose_worker_result.json")
    started = time.monotonic()
    result = {"passed": False, "samples": []}
    try:
        specification = json.loads(manifest.read_text(encoding="utf-8"))
        if safe_destination(specification["run_dir"]) != manifest.parent:
            raise ValueError("The Cellpose manifest must be inside its run directory.")
        validate_manifest(specification)
        result["samples"] = prepare_images(specification)
        # Invoke the original CLI algorithm once for the whole staged directory.
        # --save_rois is the documented spelling of terminal_commands.txt's --save_roi.
        from cellpose import __main__ as cli, io, models
        # A caller's cache override must not let Cellpose create/download files
        # under dataset, even though the image outputs are already protected.
        safe_destination(models.MODEL_DIR)
        cli.get_arg_parser().parse_args(["--dir", specification["image_dir"], "--save_rois"])
        logger_setup = io.logger_setup
        io.logger_setup = lambda *args, **kwargs: logger_setup(cp_path=str(manifest.parent), logfile_name="cellpose.log")
        argv = ["cellpose", "--dir", specification["image_dir"], "--pretrained_model",
                specification["pretrained_model"], "--save_rois", "--verbose"]
        if specification.get("diameter") is not None:
            argv.extend(["--diameter", str(specification["diameter"])])
        if specification.get("use_gpu"):
            argv.append("--use_gpu")
        result.update(command=[sys.executable, "-m", *argv], cellpose_version=version("cellpose"))
        previous_argv = sys.argv
        try:
            sys.argv = argv
            cli.main()
        finally:
            sys.argv = previous_argv
            io.logger_setup = logger_setup
        for sample in result["samples"]:
            sample["n_rois"] = validate_roi_archive(safe_destination(sample["roi_file"]))
            if not safe_destination(sample["seg_file"]).is_file():
                raise RuntimeError(f"Cellpose did not save segmentation state: {sample['seg_file']}")
        result["passed"] = True
    except (Exception, SystemExit) as error:
        result["error"] = str(error)
        traceback.print_exc()
    finally:
        logging.shutdown()
        result["seconds"] = round(time.monotonic() - started, 3)
        write_json(result_path, result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
