# EmbryoAnalyser

A Windows-tested workflow for embryo image segmentation, measurement-based
classification, and cell-neighbour analysis. Each task can run independently
from an Anaconda Prompt or a Jupyter notebook.

## Features

- Automatically segment single or recursively collected TIFF images with
  Cellpose `cpsam_v2`, and export Fiji-compatible ROI ZIPs.
- Train and reuse Random Forest (RF), Support Vector Machine (SVM), or both
  classifiers from one measurement CSV per embryo.
- Run the existing centroid-connection neighbour-counting macro in an isolated
  Fiji process, then display and export neighbour-number distributions in Python.
- Replot existing counting CSVs without repeating segmentation or Fiji analysis.
- Protect `dataset/` from workflow writes. Input images are copied before tools
  generate files, and results are stored under `outputs/` by default.

```text
TIFF images -> Cellpose segmentation -> prepared images + ROI ZIPs
                                      -> Fiji neighbour counting -> tables + plots

Measurement CSVs -> cleaning + feature profiles -> RF / SVM -> predictions
```

Segmentation does not generate morphology measurement CSVs. Classification and
image analysis are separate branches; ROI ZIPs feed the neighbour-counting branch.

## Requirements

The existing setup has been tested on Windows with:

| Component | Environment / version | Required for |
| --- | --- | --- |
| Analysis Python | Python 3.11, `EmbryoAnalyser/.venv` | Classification, plots, notebooks, command entry point |
| Cellpose | Separate Python 3.10 environment, Cellpose 4.2.1.1 | Automatic segmentation |
| Fiji bridge | Python 3.11, `fiji-agent/.venv`, PyImageJ 1.8.0 | Neighbour counting |
| Fiji / Java | Local Fiji installation, tested with its bundled Java 21 | Neighbour counting |
| JupyterLab | May run in the existing conda `base` environment | Notebook interface |

A GPU is optional. Cellpose uses CPU unless `--use-gpu` is requested. The default
Fiji and Cellpose paths in the code reflect the original local Windows setup;
configure them for a different machine. Cross-platform Fiji operation has not
been validated for this repository.

## Installation

Skip environment creation if the project environments are already available.
Run commands below in **Anaconda Prompt**, from the repository root. Use a
Python 3.11 environment for the analysis and Fiji environments.

### Analysis environment

```bat
cd /d "C:\path\to\summer_project"
python -m venv "EmbryoAnalyser\.venv"
"EmbryoAnalyser\.venv\Scripts\python.exe" -m pip install -r "EmbryoAnalyser\requirements.lock.txt"
"EmbryoAnalyser\.venv\Scripts\python.exe" -m pip check
```

The lock file records the tested package versions. `requirements.txt` provides
the supported dependency ranges. Cellpose and PyImageJ remain in separate
environments to avoid mixing their dependency stacks.

### Cellpose environment

Reuse an existing Cellpose environment, or create one:

```bat
conda create -n cellpose_env python=3.10 -y
conda run -n cellpose_env python -m pip install "cellpose==4.2.1.1"
```

Pass its Python executable using `--cellpose-python`, or set
`EMBRYO_CELLPOSE_PYTHON` in the current prompt:

```bat
set "EMBRYO_CELLPOSE_PYTHON=C:\path\to\cellpose_env\python.exe"
```

Cellpose caches pretrained model weights in the user's `.cellpose/models`
directory and may download them on first use. See the official
[Cellpose installation documentation](https://cellpose.readthedocs.io/en/latest/installation.html).
Do not place model caches inside `dataset/`.

### Fiji environment

Install Fiji with a compatible JDK, then follow
[the Fiji bridge setup guide](fiji-agent/README.md). Keep its bridge JARs and
compiled Java support in place; they are runtime dependencies. Configure the
local Fiji/JDK paths before running a newly created bridge environment.

## Quick start: JupyterLab

Register the analysis environment once, using its own Python:

```bat
"EmbryoAnalyser\.venv\Scripts\python.exe" -m ipykernel install --user --name embryo-analyser --display-name "Python (EmbryoAnalyser)"
```

Launch JupyterLab from an environment where it is installed, such as `base`:

```bat
conda activate base
jupyter lab
```

The Jupyter server and notebook kernel may use different environments. Select
**Python (EmbryoAnalyser)** in the notebook's kernel menu. Confirm with:

```python
import sys
print(sys.executable)
```

The path should end in `EmbryoAnalyser\.venv\Scripts\python.exe`. This follows
the [IPython kernel registration instructions](https://ipython.readthedocs.io/en/stable/install/kernel_install.html).

Open [staged_workflow.ipynb](EmbryoAnalyser/staged_workflow.ipynb):

1. Run the environment and input-configuration cells.
2. Set input paths and enable only the required `RUN_...` switches.
3. Run the selected task cells. All task switches are initially `False`.
4. Review displayed tables and plots, or open the saved files under
   `outputs/staged_notebook/`.

| Switch | Task |
| --- | --- |
| `RUN_SEGMENTATION` | Automatic Cellpose segmentation and ROI export |
| `RUN_TRAINING` | Train and save RF / SVM classifiers |
| `RUN_CLASSIFICATION` | Predict measurement CSVs using a saved model |
| `RUN_NEIGHBOURS` | Run Fiji counting and display distributions |
| `RUN_DISTRIBUTION` | Plot existing counting CSVs only |

Segmentation sets `NEIGHBOUR_INPUTS` to its generated `images/` directory for the
current session, but does not start counting. In a later session, set
`NEIGHBOUR_INPUTS` to the saved directory explicitly. The older
[run_workflow.ipynb](EmbryoAnalyser/run_workflow.ipynb) remains available for the
combined classification and existing-ROI workflow.

## Quick start: independent terminal tasks

Activate the analysis environment from the repository root:

```bat
call "EmbryoAnalyser\.venv\Scripts\activate.bat"
python "EmbryoAnalyser\workflow.py" --help
```

### Segment images

```bat
python "EmbryoAnalyser\workflow.py" segment --input "dataset\fixed_EM\processed\del15" --output "outputs\segmentation"
```

For raw Z-stacks, explicitly select a per-channel maximum-intensity Z projection:

```bat
python "EmbryoAnalyser\workflow.py" segment --input "dataset\fixed_EM\raw" --z-projection max --output "outputs\segmentation"
```

Alternatively, use `--z-plane 0` to select a zero-based plane. Do not combine the
two options. Two-dimensional images remain unchanged. The current workflow
supports labeled 2D grayscale or up-to-three-channel TIFFs. Multiple timepoints,
ambiguous axes, and multiple TIFF series require selecting the intended data
first. Z-stacks without an explicit plane/projection are rejected.

The command prints the generated **images directory**. Keep that path for the
next task. Optional settings include `--cellpose-python`, `--pretrained-model`,
`--diameter`, `--use-gpu`, and a whole-batch `--timeout` in seconds. The default
model is `cpsam_v2`. Repeated runs create separate output directories.

### Count neighbours

Replace `PATH_TO_SEGMENTED_IMAGES` with the directory printed by segmentation:

```bat
python "EmbryoAnalyser\workflow.py" neighbours --input "PATH_TO_SEGMENTED_IMAGES" --output "outputs\neighbours" --show
```

Existing TIFFs with matching ROI ZIPs can also be supplied directly. Prefer
`<image_stem>_rois.zip` beside each image. A single legacy ZIP is also accepted
by the current matcher; use explicit matching names for folders containing
multiple images.

Fiji opens in its own process and exits after counting. The macro's window-close
operations affect that process. Use `--fiji-path` and `--fiji-python` for alternate
installations; the bridge must also use the correct JDK. `--show` displays the
saved plot. The default whole-batch time limit is unlimited.

### Train classifiers

```bat
python "EmbryoAnalyser\workflow.py" train --input "dataset\raw_dataset\gap43-mCherry\train" --model both --output "outputs\training"
```

Use `--model rf` or `--model svm` to train only one classifier. Training inputs
must include both control and mutant embryos. The default training directory is
`dataset/raw_dataset/gap43-mCherry/train`; its test directory is not included.

### Classify measurement CSVs

```bat
python "EmbryoAnalyser\workflow.py" classify --input "dataset\raw_dataset\E-CadGFP" --model-file "outputs\training\models.joblib" --output "outputs\classification"
```

One CSV is one embryo; rows are individual cells. Training CSVs require ImageJ
columns `Area`, `Perim.`, `Major`, `Minor`, `Angle`, `Circ.`, `Feret`,
`FeretAngle`, `MinFeret`, `AR`, `Round`, and `Solidity`. Prediction requires the
saved model's feature columns plus `AR`.

Labels are `0=control` and `1=mutant`, recognized from exact CSV stems or directory
names, or `control-` / `mutant-` directory prefixes. Prediction does not require
known labels. Report metrics use only recognizable true labels. For arbitrarily
named training files, the Python `train_models` API accepts explicit labels.

### Plot existing counts

```bat
python "EmbryoAnalyser\workflow.py" distribution --input "dataset\fixed_EM\processed\del15" --output "outputs\distributions" --show
```

Directory input selects `slow_neighbour_counting.csv` files. Explicit counting
CSV input must contain a non-negative integer `n_neighbours` column.

All tasks accept one file, multiple paths following `--input`, or a recursive
directory. Quote paths containing spaces. `segment` and `neighbours` expect
TIFFs; `train`, `classify`, and `distribution` expect their corresponding CSVs.

## Outputs

| Task | Main files |
| --- | --- |
| Segmentation | Input copies, prepared `images/`, `*_rois.zip`, `*_seg.npy`, `segmentation_report.json`, logs |
| Training | `models.joblib`, `training_profiles.csv`, `training_report.json` |
| Classification | `predictions.csv`, `profiles.csv`, `classification_report.json` |
| Neighbour counting | Per-cell CSV, frequency CSV, PNG/PDF plots, `neighbour_summary.csv`, JSON report, Fiji logs |
| Existing-count plots | Per-input frequency CSV and PNG/PDF, `distribution_summary.csv` |

The model bundle contains training feature selection, bin edges, selected model
columns, and the fitted SVM scaler. Prediction reuses these values.

## Repository layout

```text
EmbryoAnalyser/        Workflow modules, notebooks, original IJM macros, dependencies
fiji-agent/           Local PyImageJ bridge, Java support, optional MCP utilities
tests/                Workflow regression and integration tests
dataset/              Local input data; never modified and excluded from Git
outputs/              Local results; excluded from Git
AGENTS.md             Contribution and dataset-protection rules
```

Historical reports and presentation slides are not runtime dependencies and have
been removed. Original exploratory notebooks, macros, and helpers are retained
as reference. Use the protected workflow entry points for normal analysis;
legacy standalone code should be run on input copies when it writes files.

## Validation

From the repository root:

```bat
"EmbryoAnalyser\.venv\Scripts\python.exe" -m pip check
"EmbryoAnalyser\.venv\Scripts\python.exe" -B -m unittest discover -s tests -v
```

Tests cover notebook algorithm regression, single/batch classification,
segmentation staging and explicit Z preparation, ROI validation, task selection,
distribution exports, and dataset write protection. Data-dependent tests require
the local `dataset/` fixtures, which are not distributed through GitHub. Most
segmentation tests mock inference; separate smoke validation has run real
Cellpose on image crops and passed its ROI output through Fiji. Tests requiring
the local Cellpose runtime are skipped if that runtime is unavailable.

The original classification parameters are preserved: `AR > 1.5`, correlation
threshold `0.75`, 16 bins, and at least 5% feature importance for reduced models.
The workflow does not claim a new cross-validation accuracy estimate or improved
biological classification performance. See [WORKFLOW.md](EmbryoAnalyser/WORKFLOW.md)
for implementation provenance and troubleshooting.

## Contributing and GitHub use

Follow [AGENTS.md](AGENTS.md): add/update relevant tests, validate before delivery,
commit each completed change, preserve existing algorithms where practical, and
never modify `dataset/`. Keep environments, caches, model weights, local results,
and notebook checkpoints out of Git. Stored notebooks should have execution
outputs cleared before committing.

Before uploading, review `git status` and the staged diff. Dataset files and local
environments are intentionally not bundled, and this README uses relative links
so it renders on GitHub. No project license has been selected; third-party
dependencies retain their respective licenses.
