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


def validate_manifest(specification: dict) -> None:
    """Validate all output paths and exact macro copies before starting Java."""
    original = (Path(__file__).parent / "neighbour_counting_connect_centroid.ijm").read_text(encoding="utf-8")
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
            counts = safe_destination(sample["counts_csv"])
            if counts.exists():
                raise FileExistsError(f"Refusing to overwrite a previous counting result: {counts}")
            code = Path(sample["macro"]).read_text(encoding="utf-8")
            ij.IJ.runMacro(code)
            log = ij.IJ.getLog()
            if log is None or "--- ALL SUBFOLDERS FULLY PROCESSED ---" not in str(log):
                raise RuntimeError("Fiji macro did not reach its completion message.")
            if not counts.is_file():
                raise RuntimeError(f"The Fiji macro did not produce its counting CSV: {counts}")
            result["samples"].append({"sample_id": sample["sample_id"], "counts_csv": str(counts)})
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
