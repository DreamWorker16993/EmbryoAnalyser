"""Run the existing Fiji neighbour macro on copies and export Python distributions.

The counting algorithm remains in neighbour_counting_connect_centroid.ijm.
Only its interactive input-directory prompt is replaced in each working copy.
The histogram follows n_neighbour_distribution.ipynb, cells 0--3.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from datetime import datetime

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import seaborn as sns

try:
    from .workflow_io import ensure_output_directory, safe_destination
except ImportError:
    from workflow_io import ensure_output_directory, safe_destination


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
MACRO = HERE / "neighbour_counting_connect_centroid.ijm"
DEFAULT_FIJI = Path(r"C:\Users\ethan\Desktop\Fiji")
DEFAULT_PYTHON = PROJECT / "fiji-agent" / ".venv" / "Scripts" / "python.exe"
_PROMPT = 'getDirectory("Choose the Master Directory containing subfolders:")'


def collect_images(inputs) -> list[Path]:
    """Resolve TIFF files from a single path, many paths, or recursive directories."""
    paths = [inputs] if isinstance(inputs, (str, os.PathLike)) else list(inputs)
    images = []
    for supplied in paths:
        path = Path(supplied).expanduser().resolve(strict=True)
        if path.is_dir():
            candidates = sorted(
                (p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in {".tif", ".tiff"}),
                key=lambda p: str(p).casefold(),
            )
        elif path.suffix.lower() in {".tif", ".tiff"}:
            candidates = [path]
        else:
            raise ValueError(f"Expected a TIFF image or directory: {path}")
        images.extend(candidate.resolve() for candidate in candidates)
    images = list(dict.fromkeys(images))
    if not images:
        raise ValueError("No TIFF images were found in the supplied input paths.")
    return images


def find_roi(image: Path) -> Path:
    """Prefer the corresponding <image>_rois.zip; otherwise require one ZIP."""
    candidates = sorted(p for p in image.parent.iterdir() if p.is_file() and p.suffix.lower() == ".zip")
    matching = [p for p in candidates if p.stem.casefold() == (image.stem + "_rois").casefold()]
    if len(matching) == 1:
        return matching[0].resolve()
    if len(candidates) == 1:
        return candidates[0].resolve()
    if not candidates:
        raise FileNotFoundError(f"The image has no corresponding ROI ZIP: {image}")
    raise ValueError(f"Multiple ROI ZIP files were found for {image}; use <image>_rois.zip.")


def prepare_macro(workspace: Path, source: str | None = None) -> str:
    """Change only the directory prompt; leave the original macro on disk intact."""
    source = MACRO.read_text(encoding="utf-8") if source is None else source
    if source.count(_PROMPT) != 1:
        raise ValueError("The original macro's directory prompt was changed; review its working-copy adapter.")
    # Forward slashes are accepted by Fiji and avoid IJM backslash escaping.
    directory = Path(workspace).resolve().as_posix().rstrip("/") + "/"
    return source.replace(_PROMPT, json.dumps(directory, ensure_ascii=False), 1)


def neighbour_distribution(csv_path) -> pd.DataFrame:
    """Return a complete integer frequency/percentage table for one Fiji CSV."""
    csv_path = Path(csv_path)
    counts = pd.read_csv(csv_path)
    if "n_neighbours" not in counts.columns:
        raise ValueError(f"Missing n_neighbours column: {csv_path}")
    values = pd.to_numeric(counts["n_neighbours"], errors="raise")
    if values.isna().any() or not np.isfinite(values).all() or (values < 0).any() or (values % 1 != 0).any():
        raise ValueError(f"Neighbour counts must be finite non-negative integers: {csv_path}")
    frequencies = values.astype(int).value_counts().reindex(range(max(9, int(values.max()) if len(values) else 9) + 1), fill_value=0)
    result = pd.DataFrame({"n_neighbours": frequencies.index, "count": frequencies.values})
    result["percent"] = result["count"] * 100.0 / len(values) if len(values) else 0.0
    return result


def plot_neighbour_distribution(csv_path, output_dir, sample_name=None, show=False) -> dict:
    """Export the notebook's percent histogram, its frequency CSV, and figure."""
    output_dir = ensure_output_directory(output_dir)
    csv_path = Path(csv_path).resolve(strict=True)
    distribution_csv = safe_destination(output_dir / "neighbour_distribution.csv")
    png = safe_destination(output_dir / "neighbour_distribution.png")
    pdf = safe_destination(output_dir / "neighbour_distribution.pdf")
    if distribution_csv == csv_path or (distribution_csv.exists() and os.path.samefile(csv_path, distribution_csv)):
        raise ValueError("The distribution output would overwrite its input CSV; choose another output directory.")
    distribution = neighbour_distribution(csv_path)
    frame = pd.read_csv(csv_path)
    title = sample_name or csv_path.parent.name
    # Use a standalone figure: the bundled Python's optional Tk installation
    # is not required, and notebook callers keep their existing backend.
    figure = Figure(figsize=(6, 4))
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    # Original notebook bins are -0.5 through 9.5. Extend when required so
    # counts above nine are included rather than silently falling outside.
    bins = np.arange(-0.5, distribution["n_neighbours"].max() + 1.5, 1)
    if len(frame):
        sns.histplot(data=frame, x="n_neighbours", bins=bins, stat="percent", ax=axis)
    axis.set_title(title)
    axis.set_xlabel("Number of neighbours")
    axis.set_ylabel("Percent of cells")
    axis.set_xticks(distribution["n_neighbours"])
    figure.tight_layout()
    distribution.to_csv(distribution_csv, index=False)
    figure.savefig(png, dpi=180)
    figure.savefig(pdf)
    if show:
        from IPython import get_ipython
        if get_ipython() is not None:
            # Display the saved image even when a notebook has not enabled
            # Matplotlib's inline Figure formatter.
            from IPython.display import Image, display
            display(Image(filename=str(png)))
        else:
            import webbrowser
            webbrowser.open(Path(png).as_uri())
    return {"distribution_csv": str(distribution_csv), "png": str(png), "pdf": str(pdf), "figure": figure,
            "n_cells": int(distribution["count"].sum()),
            "mean_neighbours": float((distribution["n_neighbours"] * distribution["count"]).sum() / distribution["count"].sum()) if distribution["count"].sum() else None}


def _sample_id(image: Path, index: int) -> str:
    label = re.sub(r"[^\w.-]+", "_", image.parent.name + "_" + image.stem).strip("._")[:72]
    digest = hashlib.sha256(str(image).encode("utf-8")).hexdigest()[:8]
    return f"{index:03d}_{label}_{digest}"


def _run_worker(manifest: Path, python_executable: Path, timeout: float | None) -> dict:
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    log = safe_destination(manifest.parent / "fiji_worker.log")
    try:
        # subprocess.run kills and waits for the worker on timeout. Its JVM is
        # embedded in that same process, so no detached Fiji is left behind.
        completed = subprocess.run(
            [str(python_executable), str(HERE / "fiji_worker.py"), str(manifest)],
            cwd=str(PROJECT), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, **kwargs,
        )
    except subprocess.TimeoutExpired as error:
        def decode(value):
            return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")
        log.write_text(decode(error.stdout) + "\n" + decode(error.stderr) + f"\nFiji worker timed out after {timeout} seconds.\n", encoding="utf-8")
        raise RuntimeError(f"Fiji neighbour counting timed out after {timeout} seconds; see {log}.") from error
    log.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    result_path = manifest.parent / "fiji_worker_result.json"
    if completed.returncode != 0 or not result_path.is_file():
        raise RuntimeError(f"Fiji neighbour counting failed; see {log}.\n{completed.stderr[-2000:]}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not result.get("passed"):
        raise RuntimeError(f"Fiji neighbour counting failed: {result.get('error')}; see {log}.")
    return result


def run_neighbours(inputs, output_dir, fiji_path=None, show=False, timeout=None, python_executable=None) -> dict:
    """Copy TIFF/ROI inputs, count in isolated Fiji, and export per-image plots.

    Inputs may be an image, a directory searched recursively, or a sequence of
    either. Existing ROI ZIP files are required. The report contains the copied
    images, counting CSVs, frequency CSVs, PNG/PDF paths, and Python figures.
    All generated files are placed in a new run folder under output_dir.
    By default there is no fixed time limit. An explicit timeout is the
    positive total number of seconds allowed for the entire Fiji batch.
    """
    images = collect_images(inputs)
    if timeout is None:
        budget = None
    else:
        try:
            budget = float(timeout)
        except (TypeError, ValueError) as error:
            raise ValueError("Fiji timeout must be a positive number of seconds.") from error
        if isinstance(timeout, bool) or not np.isfinite(budget) or budget <= 0:
            raise ValueError("Fiji timeout must be a positive number of seconds.")
    pairs = [(image, find_roi(image)) for image in images]
    fiji_path = Path(fiji_path or DEFAULT_FIJI).expanduser().resolve(strict=True)
    executable = Path(python_executable or DEFAULT_PYTHON).expanduser().resolve(strict=True)
    output_dir = ensure_output_directory(output_dir)
    run_dir = ensure_output_directory(output_dir / ("neighbours_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]))
    source = MACRO.read_text(encoding="utf-8")
    samples = []
    for index, (image, roi) in enumerate(pairs, 1):
        sample_id = _sample_id(image, index)
        workspace = ensure_output_directory(run_dir / "samples" / sample_id)
        # Canonical filenames let the untouched macro process .tiff inputs too.
        image_copy = safe_destination(workspace / "image.tif")
        roi_copy = safe_destination(workspace / "image_rois.zip")
        shutil.copy2(image, image_copy)
        shutil.copy2(roi, roi_copy)
        macro_path = safe_destination(workspace / "run_neighbour_counting.ijm")
        macro_path.write_text(prepare_macro(workspace, source), encoding="utf-8")
        samples.append({"sample_id": sample_id, "input_image": str(image), "roi_file": str(roi),
                        "workspace": str(workspace), "macro": str(macro_path),
                        "counts_csv": str(safe_destination(workspace / "slow_neighbour_counting.csv"))})
    manifest = safe_destination(run_dir / "fiji_manifest.json")
    manifest.write_text(json.dumps({"fiji_path": str(fiji_path), "samples": samples,
                                   "macro_source": str(MACRO), "macro_sha256": hashlib.sha256(MACRO.read_bytes()).hexdigest()}, indent=2, ensure_ascii=False), encoding="utf-8")
    worker = _run_worker(manifest, executable, budget)
    for sample in samples:
        sample.update(plot_neighbour_distribution(sample["counts_csv"], sample["workspace"],
                                                 sample_name=Path(sample["input_image"]).parent.name, show=show))
    summary = safe_destination(run_dir / "neighbour_summary.csv")
    pd.DataFrame([{key: sample[key] for key in ("sample_id", "input_image", "n_cells", "mean_neighbours", "counts_csv", "distribution_csv", "png", "pdf")} for sample in samples]).to_csv(summary, index=False)
    report = {"run_dir": str(run_dir), "samples": samples, "summary_csv": str(summary),
              "run_manifest": str(manifest), "fiji": worker}
    report_path = safe_destination(run_dir / "neighbour_report.json")
    serializable = {**report, "samples": [{k: v for k, v in sample.items() if k != "figure"} for sample in samples]}
    report_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    report["report_json"] = str(report_path)
    return report
