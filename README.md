# EmbryoAnalyser

A Windows-tested workflow for embryo image segmentation, measurement-based
classification, and cell-neighbour analysis. Each task can run independently
from an Anaconda Prompt or a Jupyter notebook.

## Features

- Automatically segment single or recursively collected TIFF images with
  Cellpose `cpsam_v2`, and export Fiji-compatible ROI ZIPs.
- Measure every image's cell ROIs in Fiji and export one raw morphology CSV per
  embryo; optionally save individual cell masks using `macros/make_mask.ijm`.
- Train and reuse Random Forest (RF), Support Vector Machine (SVM), or both
  classifiers from one measurement CSV per embryo.
- Run the existing centroid-connection neighbour-counting macro in an isolated
  Fiji process, then display and export neighbour-number distributions in Python.
- Replot existing counting CSVs without repeating segmentation or Fiji analysis.
- Protect `dataset/` from workflow writes. Input images are copied before tools
  generate files, and results are stored under `outputs/` by default.

```text
TIFF images -> Cellpose segmentation -> prepared images + ROI ZIPs
                                      -> Fiji measurements -> raw CSVs
                                         -> automatic CSV preprocessing -> RF / SVM
                                      -> optional individual cell-mask PNGs
                                      -> Fiji neighbour counting -> tables + plots
```

The image-to-classification workflow is segmentation, image preparation
(measurements plus optional masks), and classification. Users with existing
ROIs can start at measurement; users with raw measurement CSVs can classify
directly. Training and classification always preprocess raw CSVs automatically.

## Requirements

The existing setup has been tested on Windows with:

| Component | Environment / version | Required for |
| --- | --- | --- |
| Analysis Python | Python 3.11, `EmbryoAnalyser/.venv` | Classification, plots, notebooks, command entry point |
| Cellpose | Separate Python 3.10 environment, Cellpose 4.2.1.1 | Automatic segmentation |
| Fiji bridge | Python 3.11, `fiji-agent/.venv`, PyImageJ 1.8.0 | Measurements, masks, neighbour counting |
| Fiji / Java | Local Fiji installation, tested with its bundled Java 21 | Measurements, masks, neighbour counting |
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
| `RUN_MEASUREMENT` | Fiji morphology measurement and raw CSV export |
| `RUN_MASKS` | Export individual cell-mask PNGs |
| `RUN_TRAINING` | Train and save RF / SVM classifiers |
| `RUN_CLASSIFICATION` | Predict CSVs using the bundled gap43 model or a custom model |
| `RUN_NEIGHBOURS` | Run Fiji counting and display distributions |
| `RUN_DISTRIBUTION` | Plot existing counting CSVs only |

Segmentation sets `NEIGHBOUR_INPUTS` to its generated `images/` directory for the
current session, but does not start counting. In a later session, set
`NEIGHBOUR_INPUTS` to the saved directory explicitly. The older
[run_workflow.ipynb](EmbryoAnalyser/run_workflow.ipynb) remains available for the
combined classification and existing-ROI workflow.

For classification, enable `RUN_CLASSIFICATION` and leave `RUN_TRAINING=False`.
`MODEL_FILE` already points to the bundled RF/SVM model trained on all 14 gap43
embryos. Training is optional; enabling it replaces `MODEL_FILE` with the newly
saved custom model for that notebook session. The combined notebook defaults
to `RETRAIN=False` and also loads the bundled model.

For the full image workflow, enable `RUN_SEGMENTATION`, `RUN_MEASUREMENT`, and
`RUN_CLASSIFICATION`. Run the task cells in their displayed order. Segmentation
sets `PREPROCESS_IMAGE_INPUTS` to its images directory; measurement sets
`CSV_INPUTS` and `TRAIN_INPUTS` to its raw CSV directory. Enable `RUN_MASKS` to
save masks during the same Fiji run. With existing ROIs, set
`PREPROCESS_IMAGE_INPUTS` directly and skip segmentation. The output base is
`OUTPUT / 'preprocessing'`; change `OUTPUT` to choose another destination.

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

### Measure images and export masks

Supply the images directory printed by segmentation, or a directory of existing
TIFF images and matching `<image_stem>_rois.zip` files:

```bat
python "EmbryoAnalyser\workflow.py" measure --input "PATH_TO_IMAGES_WITH_ROIS" --output "outputs\preprocessing" --export-masks
```

Omit `--export-masks` to produce only measurements. To export only masks:

```bat
python "EmbryoAnalyser\workflow.py" masks --input "PATH_TO_IMAGES_WITH_ROIS" --output "outputs\masks"
```

Both tasks accept individual TIFFs, a recursive directory, or multiple paths.
Several images may share a folder, provided every image has its own named ROI
ZIP. A legacy ZIP name is accepted only when the folder has one TIFF and one
ZIP. Missing, empty, corrupt, or ambiguous ROI inputs are rejected. Choose an
output base outside `dataset` and outside the input directory. Without
`--output`, results go to `outputs/preprocessing/`. Each run creates a unique
`preprocessing_DATE_TIME_ID` directory containing:

```text
samples/control|mutant|input/SAMPLE_ID/
  input_copies/image.tif + image_rois.zip
  results/image/measurement.csv
  results/image/masks/mask_0.png, mask_1.png, ...
  run_make_mask.ijm
```

Only selected tasks produce their corresponding files. Sample IDs distinguish
same-named images in different directories. Recognized control/mutant input
directories are preserved as output label categories for later training.
`measurement.csv` contains all ROI measurements using the original ImageJ
options (`area centroid perimeter fit shape feret's`, three decimal places).
Masks follow the original macro: one full-image-size binary PNG per eligible
ROI, black cell on white background, named using its zero-based ROI index.
ROIs whose bounding boxes are within two pixels of the border are skipped for
mask export; their measurements remain in the CSV.

The command prints a **raw CSV directory** ending in `samples`. Classify it
using the bundled gap43 model:

```bat
python "EmbryoAnalyser\workflow.py" classify --input "PATH_TO_RAW_CSV_DIRECTORY" --output "outputs\classification"
```

Training and prediction clean these raw CSVs automatically: validate measurement
columns, remove irrelevant columns, filter `AR > 1.5`, and build percentage
feature profiles. Training fits correlation-based feature selection, 16-bin
boundaries, important-feature selection, and SVM scaling. Prediction reuses the
saved model's fitted state. Do not pass exported `profiles.csv` as raw input.

The active macro is `EmbryoAnalyser/macros/make_mask.ijm`. It can also be opened
directly in Fiji; select the input and a fresh output directory in its prompts.
Its `measureCells` and `exportMasks` switches choose the tasks. CLI/notebook use
provides protected input copies and stronger checks for dataset aliases and
output collisions. The obsolete root-level macro and `final_analyser.ipynb`
are absent.

For a separate ShapeEmbedLite analysis, copy eligible PNG masks into your own
training/test directories and keep all cells from each embryo in the same
split. The historical command notes used:

```bat
python ShapeEmbedLite.py --train-test-dataset run_1 TRAIN_MASK_DIR TEST_MASK_DIR
```

That script and its dependencies are external to this workflow. Check its
installed version's input requirements and options, including whether masks
need cropping or resizing. This workflow exports the masks and does not launch
ShapeEmbedLite.

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
python "EmbryoAnalyser\workflow.py" train --input "dataset\raw_dataset\gap43-mCherry" --model both --output "outputs\training"
```

Use `--model rf` or `--model svm` to train only one classifier. Training inputs
must include both control and mutant embryos. The default training directory is
`dataset/raw_dataset/gap43-mCherry`, including both historical `train` and `test`
subdirectories (14 embryos). Custom training saves a separate model under the
chosen output directory. It does not replace the bundled default model.

### Classify measurement CSVs

```bat
python "EmbryoAnalyser\workflow.py" classify --input "dataset\raw_dataset\E-CadGFP" --output "outputs\classification"
```

Omitting `--model-file` loads `EmbryoAnalyser/models/gap43_default.joblib`, which
contains RF, SVM, and preprocessing state fitted on all 14 gap43-mCherry embryos
(8 controls and 6 mutants). It is included in Git and works without access to
the training dataset or a training step. Supply
`--model-file "outputs\training\models.joblib"` to use a custom saved model;
an invalid explicit path causes an error rather than silently choosing another
model. The bundled model records its training sources, hashes, and package
versions. Use the pinned analysis dependencies in `requirements.lock.txt` when
loading it; scikit-learn model files require compatible package versions.

All 14 gap43 embryos, including the historical `test` folder, are in the final
default model's training set. Predictions on those same embryos are training
predictions, not independent test results; `also_in_training` identifies these
inputs in classification reports. Separate leave-one-embryo-out validation uses
14 folds: train on 13 embryos and predict the remaining one. Each fold refits
correlation-based feature removal, bin edges, the SVM scaler, importance-based
feature selection, and both classifiers using only its 13 training embryos.
Accuracy, macro F1, and confusion matrices are calculated from the 14 held-out
predictions. This validation was run in memory; its results and fold models were
not saved. The shipped default model is the final fit on all 14 embryos.

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
| Measurements | Per-image raw `measurement.csv`, input copies, preparation report, Fiji logs |
| Masks | Per-cell `mask_INDEX.png` under each sample's `masks/`, preparation report |
| Training | `models.joblib`, `training_profiles.csv`, `training_report.json` |
| Classification | `predictions.csv`, `profiles.csv`, `classification_report.json` |
| Neighbour counting | Per-cell CSV, frequency CSV, PNG/PDF plots, `neighbour_summary.csv`, JSON report, Fiji logs |
| Existing-count plots | Per-input frequency CSV and PNG/PDF, `distribution_summary.csv` |

The model bundle contains training feature selection, bin edges, selected model
columns, and the fitted SVM scaler. Prediction reuses these values.

## Repository layout

```text
EmbryoAnalyser/        Workflow modules, two user notebooks, dependencies
  macros/             Active measurement/mask and neighbour-counting macros
  models/             Bundled RF/SVM model trained on all 14 gap43 embryos
fiji-agent/           Local PyImageJ bridge, Java support, optional MCP utilities
tests/                Workflow regression and integration tests
  fixtures/           Original preprocessing cells used only as a regression oracle
dataset/              Local input data; never modified and excluded from Git
outputs/              Local results; excluded from Git
AGENTS.md             Contribution and dataset-protection rules
```

Historical reports, slides, exploratory notebooks, unused mask helpers/macros,
command notes, and duplicate debug launchers have been removed. Their originals
remain available in Git commit `63909ae`. The active IJMs are retained under
`EmbryoAnalyser/macros/`: `make_mask.ijm` produces morphology CSVs/masks and
`neighbour_counting_connect_centroid.ijm` counts neighbours.
`tests/fixtures/legacy_preprocessing.json` retains only the original processing
cells needed for independent algorithm regression. Workflow modules stay at
their existing import paths so saved model bundles remain compatible.

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
Leave-one-embryo-out validation on gap43 does not establish performance on a
different strain or imaging protocol. See [WORKFLOW.md](EmbryoAnalyser/WORKFLOW.md)
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
