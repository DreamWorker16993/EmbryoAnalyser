# Workflow details

See the [main README](../README.md) for installation, Anaconda Prompt commands,
Jupyter kernel registration, and the complete usage guide. This document records
input/output contracts, notebook choices, algorithm provenance, and limitations.

## Independent tasks

The command entry point is `workflow.py`. Its `segment`, `train`, `classify`,
`neighbours`, and `distribution` subcommands execute independently. Running
segmentation does not automatically train classifiers or launch Fiji.

```text
Single or batch measurement CSVs (one embryo per file)
  -> AR > 1.5 filtering -> correlated-feature removal -> 16-bin cell percentages
  -> RF / SVM training and saved state -> prediction CSV and JSON report

Single or batch TIFF images
  -> protected input copies -> optional explicit Z preparation -> Cellpose
  -> prepared images + ROI ZIPs -> protected Fiji workspaces
  -> original neighbour-counting macro -> counting CSV
  -> Python frequency/percentage table + PNG/PDF + batch summary
```

Segmentation produces ROI ZIPs for neighbour analysis. It does not create the
morphology measurement CSVs used by the classifiers.

## Notebook interfaces

- `staged_workflow.ipynb`: independent task cells and `RUN_...` switches, all
  initially disabled. Run the setup/configuration cells before selected tasks.
  Results default to `outputs/staged_notebook/`.
- `run_workflow.ipynb`: the earlier combined classification and existing-ROI
  workflow. `RUN_CLASSIFICATION` and `RUN_FIJI` select the two branches;
  `RETRAIN=False` reuses `MODEL_FILE`. Results default to `outputs/notebook/`.

Select the `Python (EmbryoAnalyser)` kernel backed by
`EmbryoAnalyser/.venv/Scripts/python.exe`. Launch notebooks from the repository
root or `EmbryoAnalyser/`. Input lists accept individual paths or recursive
folders. Notebook figures display through IPython and are also saved to disk.
Notebooks are stored without execution outputs for a compact Git checkout.

For staged segmentation, configure `SEGMENT_INPUTS`, `CELLPOSE_PYTHON`, and, if
needed, `Z_PROJECTION='max'` or zero-based `Z_PLANE`. Segmentation sets
`NEIGHBOUR_INPUTS` to its result directory in the current session. In a later
session, point `NEIGHBOUR_INPUTS` to that saved `images/` directory explicitly.
Other stages remain disabled until selected.

## Automatic Cellpose segmentation

`segment` copies `.tif`/`.tiff` inputs before inference and calls the original
Cellpose command-line algorithm once over the prepared directory. The model
remains `cpsam_v2`, following `terminal_commands.txt`. The full ROI flag is
`--save_rois`, as documented in the official
[Cellpose output reference](https://cellpose.readthedocs.io/en/latest/outputs.html).
The original command file is preserved.

Each run creates a unique folder containing `input_copies/`, prepared `images/`,
matching `*_rois.zip`, `*_seg.npy`, worker metadata, reports, and logs. The
**images directory** printed by the command is the input for a later neighbour
count. Repeated runs preserve earlier outputs. Exported mask/flow TIFFs are
excluded from segmentation input discovery.

The neighbour macro uses 2D ROIs. Two-dimensional TIFFs are unchanged. Z-stacks
require `--z-projection max` or `--z-plane INDEX`, not both. Maximum projection
operates separately on each channel and preserves X/Y coordinates. Multiple
series, multiple timepoints, ambiguous axes, and more than three channels require
explicit selection of the intended input before this workflow is run.

The existing local Cellpose Python is the default; override it with
`--cellpose-python` or `EMBRYO_CELLPOSE_PYTHON`. `--pretrained-model`, `--diameter`,
`--use-gpu`, and `--timeout` are optional. CPU and the original Cellpose diameter
setting are the defaults. A missing, empty, or invalid ROI ZIP causes an explicit
failure, with partial outputs and logs retained in that run's output directory.

## Fiji neighbour counting

Prefer `<image_stem>_rois.zip` beside every image. The existing matcher also
accepts a sole legacy ZIP, so explicit matching names should be used in folders
containing multiple images. Ambiguous ZIPs without a matching name are rejected.

The wrapper copies one TIFF and one ROI ZIP into each independent sample folder.
This satisfies the original macro's one-image/one-ZIP-per-folder assumption.
Counting runs in a separate GUI-capable Fiji process and exits on completion.
The macro's `close("*")` affects only that process. The working macro changes
only the directory prompt; the original macro is not rewritten.

Use `--fiji-path` and `--fiji-python` for alternate installations. The bridge
runtime must also select the appropriate JDK; see
[the Fiji setup guide](../fiji-agent/README.md). `--timeout` is a positive total
batch duration in seconds, with no fixed limit by default. `--show` displays the
saved PNG outside notebooks. Python figure export uses a non-GUI canvas and does
not require Tk.

## Output contracts

| Task | Files |
| --- | --- |
| Segmentation | Original copies, prepared `images/`, ROI ZIPs, `*_seg.npy`, segmentation JSON and logs |
| Training | `models.joblib`, `training_profiles.csv`, `training_report.json` |
| Classification | `predictions.csv`, `profiles.csv`, `classification_report.json` |
| Neighbours | Input copies, working macro, `slow_neighbour_counting.csv`, `neighbour_distribution.csv`, PNG/PDF, `neighbour_summary.csv`, report and logs |
| Existing-count plots | Per-input frequency CSV, PNG/PDF, `distribution_summary.csv` |

Prediction output has one row per source CSV, including its path, total and
retained cell counts, model predictions, and text labels. `0=control` and
`1=mutant`. True labels are inferred only from exact phenotype stems/directories
or `control-`/`mutant-` directory prefixes. Unlabeled files receive predictions,
but do not contribute to accuracy or macro F1. Reports also identify inputs that
were present in training. Saved preprocessing and scaling state is reused.

Directory input for `distribution` selects `slow_neighbour_counting.csv` files;
explicit files may have other names but must contain `n_neighbours`. Values must
be finite non-negative integers. Histogram bins extend beyond nine when needed,
and an empty counting table produces an empty distribution without division by
zero.

## Algorithm provenance

Original exploratory notebooks and IJM macros are retained. Code-cell numbers
below are zero-based.

- `preprocessing.py` copies and packages `final_analyser.ipynb` cells 2-3, 10,
  13-14, and 23-24. Angle correction is used for correlation only; binning uses
  original measurement values. The AR threshold is 1.5, the correlation
  threshold is 0.75, and each feature uses 16 bins.
- `classifiers.py` copies cells 28-41: Random Forest and LinearSVC parameters,
  feature importance, and refitting on features with at least 5% importance.
- `neighbours.py` preserves the percent histogram from
  `n_neighbour_distribution.ipynb`, with single-image export and extended bins.
- `segmentation.py` and `cellpose_worker.py` adapt the existing Cellpose batch
  command to input copies and explicit dimensional preparation.

Training and prediction are separate. Feature selection, bins, and the SVM
scaler are fitted only on the specified training CSVs. The original notebook's
globally fitted preprocessing and early scaling are not used to claim a new
Leave-One-Out validation score. Evaluate cross-strain performance through the
saved prediction reports rather than assuming accuracy has improved.

## Input errors and data protection

Missing measurement columns, non-finite values, no cells with `AR > 1.5`, or a
feature whose measurements all fall outside its training bins cause explicit
errors. Partially out-of-range measurements preserve the original `pd.cut`
behavior and are excluded from that feature's percentage denominator. Training
requires both phenotypes; the Python API supports explicit `labels=[0, 1, ...]`
for arbitrarily named training files.

Workflow destinations reject paths inside `dataset/`, including directory
aliases, junctions, Windows extended-path aliases, and multiply linked output
files. Tests use temporary folders. Existing scientific results under
`outputs/notebook/` are local artifacts excluded from Git; temporary validation
runs and obsolete diagnostics can be removed after checking their results.

## Validation

```bat
"EmbryoAnalyser\.venv\Scripts\python.exe" -m pip check
"EmbryoAnalyser\.venv\Scripts\python.exe" -B -m unittest discover -s tests -v
```

Run from the repository root. Regression tests cover the original algorithms,
CSV and image batch interfaces, saved model state, plot exports, independent
task selection, explicit Z preparation, and protected destinations. Local
fixture data is required for data-dependent tests. Real Cellpose image-crop
segmentation and subsequent Fiji counting have also been checked; these smoke
runs are distinct from mocked unit tests.
