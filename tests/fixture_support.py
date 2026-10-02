"""Generate small test inputs without copying private experimental files."""
from pathlib import Path

import numpy as np
import pandas as pd

from EmbryoAnalyser.classifiers import load_bundle
from EmbryoAnalyser.preprocessing import MEASUREMENT_FEATURES
from EmbryoAnalyser.workflow import DEFAULT_MODEL_FILE


def synthetic_measurements():
    """Use bin centres as artificial measurements accepted by the bundled model."""
    state = load_bundle(DEFAULT_MODEL_FILE).preprocessing
    frame = pd.DataFrame({column: np.full(state.num_bins, 2.0)
                          for column in MEASUREMENT_FEATURES})
    for column, edges in state.bin_edges.items():
        frame[column] = (edges[:-1] + edges[1:]) / 2
    rejected = frame.iloc[[0]].copy()
    rejected["AR"] = 1.0
    return pd.concat([frame, rejected], ignore_index=True)


def write_measurements(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    synthetic_measurements().to_csv(path, index=False)
    return path


def write_neighbour_counts(path, values=(2, 3, 3, 4, 5)):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"n_neighbours": values}).to_csv(path, index=False)
    return path
