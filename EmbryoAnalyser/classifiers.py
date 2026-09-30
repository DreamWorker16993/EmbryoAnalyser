"""Train and reuse the final reduced RF/SVM classifiers from the notebook."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

from .preprocessing import (
    PreprocessingState, fit_preprocessing, normalize_csv_paths, transform_files,
)


@dataclass
class ModelBundle:
    """All fitted state needed to classify a new embryo without its label."""

    preprocessing: PreprocessingState
    models: dict[str, object]
    selected_columns: dict[str, tuple[str, ...]]
    scaler: StandardScaler | None = None
    importances: dict[str, pd.Series] = field(default_factory=dict)
    training_profiles: pd.DataFrame | None = None
    training_labels: np.ndarray | None = None
    training_info: pd.DataFrame | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    format_version: int = 1


def train_models(
    csv_paths: str | Path | Iterable[str | Path],
    model: str = "both",
    *,
    labels: Sequence[int] | None = None,
    num_bins: int = 16,
    ar_threshold: float = 1.5,
    correlation_threshold: float = 0.75,
    importance_threshold: float = 5.0,
    seed: int = 114514,
) -> ModelBundle:
    """Copy notebook cells 28–41, training only on the supplied CSV files.

    The notebook's classifier parameters and >=5% importance selection are
    retained. No cross-validation score is reported: the original globally
    fitted preprocessing would leak information into its LeaveOneOut folds.
    """

    model = model.lower()
    if model not in {"rf", "svm", "both"}:
        raise ValueError("model must be 'rf', 'svm', or 'both'.")
    if not 0 <= importance_threshold <= 100:
        raise ValueError("importance_threshold must be between 0 and 100.")
    paths = normalize_csv_paths(csv_paths)
    state, profiles, y = fit_preprocessing(
        paths, labels=labels, num_bins=num_bins, ar_threshold=ar_threshold,
        correlation_threshold=correlation_threshold,
    )
    if set(y) != {0, 1}:
        raise ValueError("Training requires embryos from both control (0) and mutant (1).")
    _, training_info = transform_files(state, paths)
    if labels is not None:
        training_info["true_label"] = pd.array(labels, dtype="Int64")
    bundle = ModelBundle(
        state, {}, {}, training_profiles=profiles, training_labels=y,
        training_info=training_info,
        metadata={"training_files": [str(path) for path in paths],
                  "training_embryos": len(profiles), "seed": seed,
                  "importance_threshold": importance_threshold,
                  "label_names": {0: "control", 1: "mutant"},
                  "validation": "No cross-validation accuracy is estimated."},
    )
    if model in {"rf", "both"}:
        # Cells 28, 30–34: original model, then refit on important columns.
        rf = RandomForestClassifier(
            n_estimators=100, max_depth=2, max_features=0.3,
            min_samples_leaf=2, random_state=seed,
        )
        rf.fit(profiles, y)
        importance = pd.Series(rf.feature_importances_ * 100, index=profiles.columns)
        columns = tuple(importance.index[importance >= importance_threshold])
        if not columns:
            raise ValueError("RF has no features meeting the importance threshold.")
        rf.fit(profiles[list(columns)], y)
        bundle.models["rf"] = rf
        bundle.selected_columns["rf"] = columns
        bundle.importances["rf"] = importance
    if model in {"svm", "both"}:
        # Cells 36–41: scaler fitted on all bins, then retain selected columns.
        bundle.scaler = StandardScaler()
        scaled = pd.DataFrame(bundle.scaler.fit_transform(profiles),
                              index=profiles.index, columns=profiles.columns)
        svm = LinearSVC(penalty="l2", C=1, dual="auto", random_state=0)
        svm.fit(scaled, y)
        normal_vec = svm.coef_[0]
        norm = np.sqrt(sum(value ** 2 for value in normal_vec))
        if norm == 0 or not np.isfinite(norm):
            raise ValueError("SVM coefficients cannot define meaningful feature importance.")
        normal_vec = normal_vec / norm
        importance = pd.Series([100 * value ** 2 for value in normal_vec],
                               index=profiles.columns)
        columns = tuple(importance.index[importance >= importance_threshold])
        if not columns:
            raise ValueError("SVM has no features meeting the importance threshold.")
        svm.fit(scaled[list(columns)], y)
        bundle.models["svm"] = svm
        bundle.selected_columns["svm"] = columns
        bundle.importances["svm"] = importance
    return bundle


def predict_files(
    bundle: ModelBundle,
    csv_paths: str | Path | Iterable[str | Path],
) -> pd.DataFrame:
    """Return one result per CSV, reusing all fitted model and bin state."""

    profiles, info = transform_files(bundle.preprocessing, csv_paths)
    embryo_ids = profiles.index.get_level_values("EM")
    result = info.loc[embryo_ids].reset_index(drop=True)
    for name, classifier in bundle.models.items():
        features = profiles
        if name == "svm":
            if bundle.scaler is None:
                raise ValueError("Saved SVM model has no fitted scaler.")
            features = pd.DataFrame(bundle.scaler.transform(profiles),
                                    index=profiles.index, columns=profiles.columns)
        predictions = classifier.predict(features[list(bundle.selected_columns[name])])
        result[name + "_prediction"] = predictions.astype(int)
        result[name + "_label"] = ["mutant" if prediction else "control"
                                   for prediction in predictions]
    return result


def save_bundle(bundle: ModelBundle, path: str | Path) -> Path:
    """Save fitted state to an approved output destination outside dataset."""

    from .workflow_io import ensure_output_directory, safe_destination

    destination = safe_destination(path)
    ensure_output_directory(destination.parent)
    joblib.dump(bundle, destination)
    return destination


def load_bundle(path: str | Path) -> ModelBundle:
    """Load a model bundle previously created by this workflow."""

    bundle = joblib.load(Path(path))
    if not isinstance(bundle, ModelBundle) or bundle.format_version != 1:
        raise ValueError("The file is not a supported embryo classifier model bundle.")
    return bundle
