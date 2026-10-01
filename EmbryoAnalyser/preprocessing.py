"""Reusable copies of the measurement processing in final_analyser.ipynb.

The source notebook is preserved. Cell numbers below use zero-based indexing.
Each CSV describes one embryo, and each CSV row describes one cell.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


MEASUREMENT_FEATURES = (
    "Area", "Perim.", "Major", "Minor", "Angle", "Circ.", "Feret",
    "FeretAngle", "MinFeret", "AR", "Round", "Solidity",
)
IGNORED_COLUMNS = (" ", "X", "Y", "FeretX", "FeretY")


@dataclass
class PreprocessingState:
    """Training feature selection and bin boundaries reused during prediction."""

    feature_columns: tuple[str, ...]
    removed_columns: tuple[str, ...]
    bin_edges: dict[str, np.ndarray]
    num_bins: int = 16
    ar_threshold: float = 1.5
    correlation_threshold: float = 0.75


def normalize_csv_paths(csv_paths: str | Path | Iterable[str | Path]) -> list[Path]:
    """Expand CSV directories while keeping one unique input per embryo."""

    if isinstance(csv_paths, (str, Path)):
        csv_paths = [csv_paths]
    result = []
    seen = set()
    for value in csv_paths:
        path = Path(value).expanduser().resolve()
        candidates = sorted(path.rglob("*.csv")) if path.is_dir() else [path]
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() != ".csv":
                raise ValueError(f"CSV input does not exist or is not a CSV file: {candidate}")
            if candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
    if not result:
        raise ValueError("At least one measurement CSV is required.")
    return result


def infer_label(path: str | Path) -> int | None:
    """Recognize explicit phenotype names, without guessing from substrings."""

    path = Path(path)
    stem = path.stem.lower()
    if stem in ("control", "mutant"):
        return int(stem == "mutant")
    for part in reversed(path.parent.parts):
        part = part.lower()
        if part == "control" or part.startswith("control-"):
            return 0
        if part == "mutant" or part.startswith("mutant-"):
            return 1
    return None


def _strain(path: Path) -> str:
    for strain in ("gap43-mCherry", "E-CadGFP"):
        if strain in str(path):
            return strain
    return "input"


def read_measurements(
    csv_paths: str | Path | Iterable[str | Path],
    *,
    ar_threshold: float = 1.5,
    required_features: Sequence[str] = MEASUREMENT_FEATURES,
    labels: Sequence[int] | None = None,
    require_labels: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Copy notebook cells 2–3 without writing to the input files.

    Prediction uses an internal placeholder label when no true label is known;
    the returned file information records that true label as missing.
    """

    paths = normalize_csv_paths(csv_paths)
    if labels is not None and len(labels) != len(paths):
        raise ValueError("Provide exactly one training label per CSV input.")
    frames, file_info = [], []
    for em, path in enumerate(paths):
        try:
            frame = pd.read_csv(path)
        except (pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
            raise ValueError(f"Cannot read measurement CSV {path}: {exc}") from exc
        total_cells = len(frame)
        required = tuple(dict.fromkeys((*required_features, "AR")))
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"Missing measurement columns in {path}: {', '.join(missing)}")
        try:
            frame["AR"] = pd.to_numeric(frame["AR"], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Non-numeric AR measurements in {path}") from exc
        frame = frame[frame["AR"] > ar_threshold].copy()
        if frame.empty:
            raise ValueError(f"No valid cells with AR > {ar_threshold} in {path}")
        for column in required:
            try:
                frame[column] = pd.to_numeric(frame[column], errors="raise")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Non-numeric {column} measurements in {path}") from exc
            if not np.isfinite(frame[column].to_numpy(dtype=float)).all():
                raise ValueError(f"Non-finite {column} measurements in {path}")
        label = labels[em] if labels is not None else infer_label(path)
        if label is not None and label not in (0, 1):
            raise ValueError(f"Training labels must be 0 (control) or 1 (mutant): {path}")
        if require_labels and label is None:
            raise ValueError(
                f"Missing training label for {path}; use control/mutant directories "
                "or pass explicit labels."
            )
        frame["EM"] = em
        frame["strain"] = _strain(path)
        # The placeholder supports the original grouped profile structure.
        # Unknown truth remains missing in file_info and is never a target.
        frame["label"] = 0 if label is None else int(label)
        # Retain only the measurement columns, preserving their source order.
        columns = [column for column in frame.columns if column in required_features]
        frames.append(frame[columns + ["EM", "strain", "label"]])
        file_info.append({
            "EM": em,
            "source_csv": str(path),
            "total_cells": total_cells,
            "retained_cells": len(frame),
            "true_label": label,
        })
    info = pd.DataFrame(file_info).set_index("EM")
    info["true_label"] = info["true_label"].astype("Int64")
    return pd.concat(frames).reset_index(drop=True), info


def _select_features(frame: pd.DataFrame, threshold: float) -> tuple[tuple[str, ...], tuple[str, ...]]:
    # Notebook cells 10 and 13: adjust periodic angles for correlation only.
    columns = frame.columns.drop(["EM", "strain", "label"])
    corrected = frame.copy()
    indices = list(frame[((frame["Angle"] > 150) & (frame["FeretAngle"] < 30)) |
                         ((frame["FeretAngle"] > 150) & (frame["Angle"] < 30))].index)
    for index in indices:
        if corrected.loc[index, "Angle"] > 150:
            corrected.loc[index, "Angle"] -= 180
        else:
            corrected.loc[index, "FeretAngle"] -= 180
    correlation = corrected[columns].corr(method="pearson")
    to_remove = set()
    for i in range(len(columns) - 1):
        for j in range(i + 1, len(columns)):
            if abs(correlation.iloc[i, j]) > threshold:
                to_remove.add(columns[j])
    selected = tuple(column for column in columns if column not in to_remove)
    removed = tuple(column for column in columns if column in to_remove)
    return selected, removed


def _make_profiles(frame: pd.DataFrame, state: PreprocessingState) -> pd.DataFrame:
    """Copy cell 24's per-feature pivot and percentage normalization."""

    temporary = frame.copy()
    profiles = []
    expected_embryos = set(temporary["EM"])
    for column in state.feature_columns:
        temporary[column + "_bins"] = pd.cut(
            x=temporary[column],
            bins=state.bin_edges[column],
            labels=[column + "_bin_" + str(i) for i in range(state.num_bins)],
        )
        profile = temporary.pivot_table(
            index=["EM", "strain", "label"],
            columns=column + "_bins",
            aggfunc="size",
            fill_value=0,
            observed=False,
        )
        profile = profile[profile.sum(axis=1) > 0].astype("float64")
        missing = expected_embryos - set(profile.index.get_level_values("EM"))
        if missing:
            raise ValueError(
                f"All retained {column} values are outside the training bin range "
                f"for embryo indices {sorted(missing)}."
            )
        for i in range(len(profile)):
            profile.iloc[i, :] = profile.iloc[i, :] / profile.iloc[i, :].sum() * 100
        profiles.append(profile)
    binned = pd.concat(profiles, axis=1)
    if binned.isna().any().any():
        raise ValueError("Measurement profiles contain missing bin percentages.")
    return binned


def fit_preprocessing(
    csv_paths: str | Path | Iterable[str | Path],
    *,
    labels: Sequence[int] | None = None,
    num_bins: int = 16,
    ar_threshold: float = 1.5,
    correlation_threshold: float = 0.75,
) -> tuple[PreprocessingState, pd.DataFrame, np.ndarray]:
    """Fit feature selection and bin edges from the supplied training CSVs only."""

    if not isinstance(num_bins, int) or num_bins < 1:
        raise ValueError("num_bins must be a positive integer.")
    if not 0 <= correlation_threshold <= 1:
        raise ValueError("correlation_threshold must be between 0 and 1.")
    frame, _ = read_measurements(csv_paths, ar_threshold=ar_threshold,
                                 labels=labels, require_labels=True)
    selected, removed = _select_features(frame, correlation_threshold)
    edges = {}
    # Fit bins on original measurements, as in notebook cells 14 and 24.
    for column in selected:
        _, edges[column] = pd.cut(frame[column], bins=num_bins, retbins=True)
    state = PreprocessingState(selected, removed, edges, num_bins,
                               ar_threshold, correlation_threshold)
    profiles = _make_profiles(frame, state)
    y = profiles.index.get_level_values("label").to_numpy(dtype=int)
    return state, profiles, y


def transform_files(
    state: PreprocessingState,
    csv_paths: str | Path | Iterable[str | Path],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reuse the training columns and bins for single or batch prediction."""

    frame, info = read_measurements(csv_paths, ar_threshold=state.ar_threshold,
                                    required_features=state.feature_columns)
    return _make_profiles(frame, state), info
