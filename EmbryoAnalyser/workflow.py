"""Unified command and notebook entry points for embryo analysis."""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import os
from pathlib import Path
import sys

if __package__ in (None, ""):
    # Use the same qualified module names in notebooks and saved model bundles.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from EmbryoAnalyser.workflow_io import (
    DEFAULT_OUTPUT_ROOT, PROJECT_ROOT, ensure_output_directory,
    expand_inputs, safe_destination, sample_name, write_json,
)


def _versions() -> dict:
    return {name: version(name) for name in
            ("numpy", "pandas", "scikit-learn", "matplotlib", "seaborn", "joblib")}


def _sources(paths) -> list[dict]:
    return [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in paths]


def _csv(frame, destination, *, index=False, inputs=()) -> Path:
    target = safe_destination(destination)
    if _matches_input(target, inputs):
        raise ValueError(f"An output would overwrite an input CSV: {target}")
    frame.to_csv(target, index=index, encoding="utf-8-sig")
    return target


def _matches_input(destination: Path, inputs) -> bool:
    for source in inputs:
        source = Path(source).resolve()
        if destination == source:
            return True
        try:
            if os.path.samefile(destination, source):
                return True
        except OSError:
            continue
    return False


def _protect_inputs(output: Path, filenames, inputs) -> None:
    for filename in filenames:
        destination = safe_destination(output / filename)
        if _matches_input(destination, inputs):
            raise ValueError(f"An output would overwrite an input or saved model: {destination}")


def train_workflow(inputs=None, output_dir=None, model="both") -> dict:
    """Train RF, SVM, or both, then export their complete reusable state."""
    from EmbryoAnalyser.classifiers import train_models, save_bundle

    inputs = inputs or PROJECT_ROOT / "dataset/raw_dataset/gap43-mCherry/train"
    paths = expand_inputs(inputs)
    output = ensure_output_directory(output_dir or DEFAULT_OUTPUT_ROOT / "training")
    _protect_inputs(output, ("models.joblib", "training_profiles.csv", "training_report.json"), paths)
    bundle = train_models(paths, model=model)
    model_file = safe_destination(output / "models.joblib")
    if model_file in paths:
        raise ValueError("The model output would overwrite an input file")
    save_bundle(bundle, model_file)
    profiles_csv = _csv(bundle.training_profiles, output / "training_profiles.csv",
                        index=True, inputs=paths)
    state = bundle.preprocessing
    report = {
        "model_file": str(model_file), "profiles_csv": str(profiles_csv),
        "models": list(bundle.models), "training_embryos": len(bundle.training_profiles),
        "sources": _sources(paths), "feature_columns": list(state.feature_columns),
        "removed_columns": list(state.removed_columns), "num_bins": state.num_bins,
        "ar_threshold": state.ar_threshold,
        "correlation_threshold": state.correlation_threshold,
        "selected_columns": {name: list(columns)
                             for name, columns in bundle.selected_columns.items()},
        "bin_edges": {name: edges.tolist() for name, edges in state.bin_edges.items()},
        "class_mapping": {"0": "control", "1": "mutant"},
        "package_versions": _versions(),
        "source_notebook": "EmbryoAnalyser/final_analyser.ipynb",
    }
    report_path = write_json(output / "training_report.json", report)
    return {"bundle": bundle, "model_file": model_file,
            "profiles_csv": profiles_csv, "report_path": report_path, "report": report}


def classify_workflow(inputs, model_file, output_dir=None) -> dict:
    """Classify one embryo per CSV and compute metrics only for known labels."""
    from EmbryoAnalyser.classifiers import load_bundle, predict_files
    from EmbryoAnalyser.preprocessing import transform_files
    from sklearn.metrics import accuracy_score, f1_score

    paths = expand_inputs(inputs)
    output = ensure_output_directory(output_dir or DEFAULT_OUTPUT_ROOT / "classification")
    _protect_inputs(output, ("predictions.csv", "profiles.csv", "classification_report.json"),
                    [*paths, model_file])
    bundle = load_bundle(model_file)
    predictions = predict_files(bundle, paths)
    profiles, _ = transform_files(bundle.preprocessing, paths)
    predictions_csv = _csv(predictions, output / "predictions.csv", inputs=paths)
    profiles_csv = _csv(profiles, output / "profiles.csv", index=True, inputs=paths)
    known = predictions["true_label"].notna()
    metrics = {}
    if known.any():
        truth = predictions.loc[known, "true_label"].astype(int)
        for name in bundle.models:
            predicted = predictions.loc[known, name + "_prediction"]
            metrics[name] = {
                "accuracy": float(accuracy_score(truth, predicted)),
                "macro_f1": float(f1_score(truth, predicted, labels=[0, 1],
                                           average="macro", zero_division=0)),
            }
    training_sources = set()
    if bundle.training_profiles is not None and hasattr(bundle, "training_info"):
        if bundle.training_info is not None:
            training_sources = set(bundle.training_info["source_csv"])
    report = {
        "model_file": str(Path(model_file).resolve()), "models": list(bundle.models),
        "predictions": len(predictions), "labeled_count": int(known.sum()),
        "metrics": metrics, "sources": _sources(paths),
        "also_in_training": [str(path) for path in paths if str(path) in training_sources],
        "predictions_csv": str(predictions_csv), "profiles_csv": str(profiles_csv),
        "class_mapping": {"0": "control", "1": "mutant"},
        "package_versions": _versions(),
    }
    report_path = write_json(output / "classification_report.json", report)
    return {"predictions": predictions, "profiles": profiles,
            "predictions_csv": predictions_csv, "profiles_csv": profiles_csv,
            "report_path": report_path, "report": report}


def distribution_workflow(inputs, output_dir=None, show=False) -> dict:
    """Plot existing Fiji counting CSVs without rerunning image analysis."""
    from EmbryoAnalyser.neighbours import plot_neighbour_distribution

    supplied = [inputs] if isinstance(inputs, (str, Path)) else inputs
    paths = []
    for value in supplied:
        path = Path(value).resolve()
        discovered = expand_inputs(path)
        if path.is_dir():
            discovered = [item for item in discovered if item.name == "slow_neighbour_counting.csv"]
            if not discovered:
                raise ValueError(f"No slow_neighbour_counting.csv files found in {path}")
        paths.extend(discovered)
    output = ensure_output_directory(output_dir or DEFAULT_OUTPUT_ROOT / "distributions")
    samples = []
    for path in dict.fromkeys(paths):
        directory = ensure_output_directory(output / sample_name(path))
        sample = plot_neighbour_distribution(path, directory,
                                             sample_name=path.parent.name, show=show)
        samples.append({"input_csv": str(path), **sample})
    import pandas as pd
    summary_csv = _csv(pd.DataFrame([
        {key: value for key, value in sample.items() if key != "figure"}
        for sample in samples
    ]), output / "distribution_summary.csv", inputs=paths)
    return {"samples": samples, "output_dir": output, "summary_csv": summary_csv}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Embryo CSV classification and Fiji neighbour analysis")
    commands = parser.add_subparsers(dest="command", required=True)
    segment = commands.add_parser("segment", help="Automatically segment TIFFs with Cellpose and save Fiji ROIs")
    segment.add_argument("--input", nargs="+", required=True, help="TIFF files or recursive directories")
    segment.add_argument("--output", default=None)
    segment.add_argument("--cellpose-python", default=None)
    segment.add_argument("--pretrained-model", default="cpsam_v2")
    dimensional = segment.add_mutually_exclusive_group()
    dimensional.add_argument("--z-projection", choices=("max",), default=None)
    dimensional.add_argument("--z-plane", type=int, default=None, help="Zero-based Z plane for 2D ROI export")
    segment.add_argument("--diameter", type=float, default=None)
    segment.add_argument("--use-gpu", action="store_true")
    segment.add_argument("--timeout", type=float, default=None, help="Optional whole-batch seconds")
    train = commands.add_parser("train", help="Train and save RF/SVM from labeled measurement CSVs")
    train.add_argument("--input", nargs="+", default=None,
                       help="CSV files or directories; default: gap43-mCherry/train")
    train.add_argument("--output", default=None)
    train.add_argument("--model", choices=("rf", "svm", "both"), default="both")
    classify = commands.add_parser("classify", help="Predict a single or batch of measurement CSVs")
    classify.add_argument("--input", nargs="+", required=True)
    classify.add_argument("--model-file", required=True)
    classify.add_argument("--output", default=None)
    neighbours = commands.add_parser("neighbours", help="Run Fiji on TIFF + ROI copies and plot distributions")
    neighbours.add_argument("--input", nargs="+", required=True)
    neighbours.add_argument("--output", default=None)
    neighbours.add_argument("--fiji-path", default=None)
    neighbours.add_argument("--fiji-python", default=None)
    neighbours.add_argument("--timeout", type=float, default=None,
                            help="Optional whole-batch seconds; default: no time limit")
    neighbours.add_argument("--show", action="store_true")
    distribution = commands.add_parser("distribution", help="Plot existing neighbour counting CSVs")
    distribution.add_argument("--input", nargs="+", required=True)
    distribution.add_argument("--output", default=None)
    distribution.add_argument("--show", action="store_true")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "segment":
            from EmbryoAnalyser.segmentation import segmentation_workflow
            result = segmentation_workflow(args.input, args.output, python_executable=args.cellpose_python,
                                           pretrained_model=args.pretrained_model, z_projection=args.z_projection,
                                           z_plane=args.z_plane, diameter=args.diameter,
                                           use_gpu=args.use_gpu, timeout=args.timeout)
            print(f"Segmented {len(result['samples'])} images. Use this directory for neighbours: {result['image_dir']}")
            print(f"Report: {result['report_json']}")
        elif args.command == "train":
            result = train_workflow(args.input, args.output, args.model)
            print(f"Saved {', '.join(result['report']['models'])}: {result['model_file']}")
        elif args.command == "classify":
            result = classify_workflow(args.input, args.model_file, args.output)
            print(result["predictions"].to_string(index=False))
            print(f"Results: {result['predictions_csv']}")
        elif args.command == "neighbours":
            from EmbryoAnalyser.neighbours import run_neighbours
            result = run_neighbours(args.input, args.output or DEFAULT_OUTPUT_ROOT / "neighbours",
                                    fiji_path=args.fiji_path, show=args.show,
                                    timeout=args.timeout, python_executable=args.fiji_python)
            print(f"Completed {len(result['samples'])} images: {result['summary_csv']}")
        else:
            result = distribution_workflow(args.input, args.output, args.show)
            print(f"Exported {len(result['samples'])} distributions: {result['output_dir']}")
    except (ValueError, FileNotFoundError, RuntimeError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
