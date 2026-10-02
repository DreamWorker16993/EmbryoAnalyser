"""Isolated GUI-capable Fiji worker for the original neighbour-counting macro."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import traceback

try:
    from .workflow_io import safe_destination
except ImportError:
    from workflow_io import safe_destination


def prepare_measurement_macro(workspace: Path, measure: bool, masks: bool) -> str:
    """Adapt only directory prompts and task switches in the active mask macro."""
    source = (Path(__file__).parent / "macros/make_mask.ijm").read_text(encoding="utf-8")
    changes = {
        'getDirectory("Choose the Master Directory containing subfolders:")':
            json.dumps((workspace / "input_copies").as_posix() + "/"),
        'getDirectory("Choose the output directory:")':
            json.dumps((workspace / "results").as_posix() + "/"),
        "measureCells = true;": "measureCells = " + str(measure).lower() + ";",
        "exportMasks = true;": "exportMasks = " + str(masks).lower() + ";",
    }
    for original, replacement in changes.items():
        if source.count(original) != 1:
            raise ValueError("The measurement macro adapter needs review.")
        source = source.replace(original, replacement, 1)
    return source


def validate_measurements(specification: dict) -> None:
    measure, masks = specification.get("measure"), specification.get("export_masks")
    if type(measure) is not bool or type(masks) is not bool or not (measure or masks):
        raise ValueError("Select measurements, masks, or both.")
    if not specification.get("samples"):
        raise ValueError("The Fiji manifest contains no samples.")
    for sample in specification["samples"]:
        workspace = safe_destination(sample["workspace"])
        if safe_destination(sample["macro"]) != workspace / "run_make_mask.ijm":
            raise ValueError("Measurement macro must be in its protected workspace.")
        expected_csv = workspace / "results/image/measurement.csv"
        expected_masks = workspace / "results/image/masks"
        if safe_destination(sample["measurement_csv"]) != expected_csv or safe_destination(sample["masks_dir"]) != expected_masks:
            raise ValueError("Measurement outputs must be in their protected workspace.")
        if expected_csv.parent.exists():
            raise FileExistsError("Refusing to overwrite previous measurement or mask results.")
        for filename in ("image.tif", "image_rois.zip"):
            if not safe_destination(workspace / "input_copies" / filename).is_file():
                raise FileNotFoundError("Missing copied measurement input: " + filename)
        if Path(sample["macro"]).read_text(encoding="utf-8") != prepare_measurement_macro(workspace, measure, masks):
            raise ValueError("The measurement working macro changes its algorithm.")


def validate_manifest(specification: dict) -> None:
    """Validate all output paths and exact macro copies before starting Java."""
    task = specification.get("task", "neighbours")
    if task == "measure":
        validate_measurements(specification)
        return
    if task != "neighbours":
        raise ValueError("Unknown Fiji task.")
    original = (Path(__file__).parent / "macros" / "neighbour_counting_connect_centroid.ijm").read_text(encoding="utf-8")
    prompt = 'getDirectory("Choose the Master Directory containing subfolders:")'
    if original.count(prompt) != 1:
        raise ValueError("The original macro directory prompt needs review.")
    if not specification.get("samples"):
        raise ValueError("The Fiji manifest contains no samples.")
    for sample in specification["samples"]:
        workspace = safe_destination(sample["workspace"])
        counts = safe_destination(sample["counts_csv"])
        macro = safe_destination(sample["macro"])
        if counts != workspace / "slow_neighbour_counting.csv" or macro != workspace / "run_neighbour_counting.ijm":
            raise ValueError("Fiji output and macro paths must be inside their protected workspace.")
        for filename in ("image.tif", "image_rois.zip"):
            if not safe_destination(workspace / filename).is_file():
                raise FileNotFoundError(f"Missing copied Fiji input: {workspace / filename}")
        directory = workspace.as_posix().rstrip("/") + "/"
        expected = original.replace(prompt, json.dumps(directory, ensure_ascii=False), 1)
        if macro.read_text(encoding="utf-8") != expected:
            raise ValueError("The Fiji working macro must change only the original directory prompt.")


def main(manifest_path: str) -> int:
    manifest = Path(manifest_path).resolve(strict=True)
    result_path = safe_destination(manifest.parent / "fiji_worker_result.json")
    started = time.monotonic()
    ij = None
    result = {"passed": False, "samples": []}
    try:
        specification = json.loads(manifest.read_text(encoding="utf-8"))
        validate_manifest(specification)
        # The project Fiji environment's existing .pth supplies Java and bridge
        # libraries. This process is separate from the headless MCP instance.
        import imagej
        import scyjava

        ij = imagej.init(specification["fiji_path"], mode="interactive")
        if ij.ui().isHeadless():
            raise RuntimeError("This macro requires a GUI-capable Fiji process.")
        ij.ui().showUI()
        result.update({"imagej_version": str(ij.getVersion()), "headless": False})
        for sample in specification["samples"]:
            measurement_task = specification.get("task") == "measure"
            key = "measurement_csv" if measurement_task else "counts_csv"
            counts = safe_destination(sample[key])
            if counts.exists():
                raise FileExistsError(f"Refusing to overwrite a previous counting result: {counts}")
            code = Path(sample["macro"]).read_text(encoding="utf-8")
            ij.IJ.runMacro(code)
            log = ij.IJ.getLog()
            if log is None or "--- ALL SUBFOLDERS FULLY PROCESSED ---" not in str(log):
                raise RuntimeError("Fiji macro did not reach its completion message.")
            csv_required = not measurement_task or specification["measure"]
            if csv_required and not counts.is_file():
                raise RuntimeError(f"The Fiji macro did not produce its counting CSV: {counts}")
            if measurement_task and specification["export_masks"] and not Path(sample["masks_dir"]).is_dir():
                raise RuntimeError("The Fiji macro did not produce its masks directory.")
            result["samples"].append({"sample_id": sample["sample_id"], key: str(counts)})
            # Clear the log to ensure the next completion message is new.
            ij.IJ.log("\\Clear")
        result["passed"] = True
        return_code = 0
    except Exception as error:
        result["error"] = str(error)
        traceback.print_exc(file=sys.stderr)
        return_code = 1
    finally:
        result["seconds"] = round(time.monotonic() - started, 3)
        result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        if ij is not None:
            # Fiji's AWT event thread survives context.dispose(); exit this
            # isolated worker explicitly after its report has been saved.
            ij.dispose()
            scyjava.jimport("java.lang.System").exit(0 if result["passed"] else 1)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
