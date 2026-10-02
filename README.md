# EmbryoAnalyser

A Windows-tested workflow for embryo segmentation, morphology-based
**WT versus sdk null classification**, and cell-neighbour analysis. Random
Forest (RF) and SVM predict one phenotype per embryo from cell measurements.
Output labels are `0=control (WT)` and `1=mutant (sdk null)`.

```text
TIFF images -> Cellpose -> images + ROI ZIPs -> Fiji measurements
            -> automatic raw CSV preprocessing -> RF / SVM predictions
                         + optional cell masks and neighbour distributions
```

Tasks run independently. Start with measurement if ROIs already exist, or
classify directly if you have raw measurement CSVs. Inputs stay unchanged;
outputs default to `outputs/`. The workflow rejects writes inside `dataset/`.

## Setup

Run these commands in **Anaconda Prompt**, from the repository root. Skip
creation/install steps for environments that are already configured.

```bat
cd /d "C:\path\to\summer_project"
python -m venv "EmbryoAnalyser\.venv"
"EmbryoAnalyser\.venv\Scripts\python.exe" -m pip install -r "EmbryoAnalyser\requirements.lock.txt"
call "EmbryoAnalyser\.venv\Scripts\activate.bat"
```

Use Python 3.11 for analysis. Cellpose runs in a separate environment:

```bat
conda create -n cellpose_env python=3.10 -y
conda run -n cellpose_env python -m pip install "cellpose==4.2.1.1"
set "EMBRYO_CELLPOSE_PYTHON=C:\path\to\cellpose_env\python.exe"
```

For Fiji installation and the separate PyImageJ environment, follow the
[Fiji setup guide](fiji-agent/README.md). Configure local paths with
`--fiji-path`, `--fiji-python`, and `--cellpose-python` where needed.

## JupyterLab

Register the analysis kernel once, then launch JupyterLab from an environment
where it is installed:

```bat
"EmbryoAnalyser\.venv\Scripts\python.exe" -m ipykernel install --user --name embryo-analyser --display-name "Python (EmbryoAnalyser)"
conda activate base
jupyter lab
```

Open [staged_workflow.ipynb](EmbryoAnalyser/staged_workflow.ipynb), select
**Python (EmbryoAnalyser)**, and run setup/configuration cells. Set input paths
and `OUTPUT`, enable the required tasks, then run their cells in order.

- Full image workflow: `RUN_SEGMENTATION`, `RUN_MEASUREMENT`, `RUN_CLASSIFICATION`.
- Optional tasks: `RUN_MASKS`, `RUN_TRAINING`, `RUN_NEIGHBOURS`, `RUN_DISTRIBUTION`.

All switches start disabled. Segmentation supplies images to measurement;
measurement supplies raw CSVs to classification. Training is optional: the
notebook already selects the bundled gap43 RF/SVM model.

## Terminal tasks

Activate `EmbryoAnalyser/.venv` before running these commands. Replace capitalized
paths with your files/directories. Inputs may be one file, several paths after
`--input`, or a recursive directory; each task accepts `--output`.

### Segment images

```bat
python "EmbryoAnalyser\workflow.py" segment --input "RAW_IMAGES" --output "outputs\segmentation"
```

The default Cellpose model is `cpsam_v2`. For Z-stacks, add `--z-projection max`
or `--z-plane 0`. Use the printed **images directory** in the next step.

### Measure images and export masks

```bat
python "EmbryoAnalyser\workflow.py" measure --input "IMAGES_WITH_ROIS" --output "outputs\preprocessing" --export-masks
python "EmbryoAnalyser\workflow.py" masks --input "IMAGES_WITH_ROIS" --output "outputs\masks"
```

Use matching `<image_stem>_rois.zip` beside each TIFF. Omit `--export-masks` for
CSV measurements only; `masks` exports masks only. Results use a new run folder
with per-image `measurement.csv` and `masks/mask_INDEX.png`. Masks are full-frame,
black cells on white background; ROIs within two pixels of the border are
excluded from mask export. Choose an output directory outside the input tree.
The active macro is [make_mask.ijm](EmbryoAnalyser/macros/make_mask.ijm).

### Classify measurement CSVs

```bat
python "EmbryoAnalyser\workflow.py" classify --input "RAW_CSV_DIRECTORY" --output "outputs\classification"
```

Use the **raw CSV directory** printed by measurement, or your existing CSVs.
One CSV represents one embryo. Raw CSV preprocessing runs automatically before
training/prediction: `AR > 1.5` filtering and percentage feature profiles.
Prediction reuses the saved model's feature selection, bins, and SVM scaler.
Do not supply already binned `profiles.csv` as raw input.

The default [model](EmbryoAnalyser/models/gap43_default.joblib) contains RF/SVM
trained on all **14 gap43-mCherry embryos: 8 WT and 6 sdk null**, including the
historical `train` and `test` folders. No training step is required. Add
`--model-file "outputs\training\models.joblib"` to select a custom model.
Predictions on those 14 embryos are training predictions; reports identify
training overlap. Performance on other strains requires separate evaluation.

### Train a custom model

```bat
python "EmbryoAnalyser\workflow.py" train --input "LABELED_CSV_DIRECTORY" --model both --output "outputs\training"
```

Use `--model rf`, `svm`, or `both`. Training requires both phenotypes, named
`control`/`mutant` or using `control-`/`mutant-` directory prefixes. Omitted input
uses all gap43 embryos. Custom models do not replace the bundled default.

### Neighbour distributions

```bat
python "EmbryoAnalyser\workflow.py" neighbours --input "IMAGES_WITH_ROIS" --output "outputs\neighbours" --show
python "EmbryoAnalyser\workflow.py" distribution --input "COUNTING_CSV_DIRECTORY" --output "outputs\distributions" --show
```

`neighbours` runs Fiji counting and Python plotting. `distribution` plots
existing `slow_neighbour_counting.csv` files without rerunning Fiji.

## Outputs and optional ShapeEmbedLite

Main outputs are raw measurement CSVs, cell-mask PNGs, `models.joblib`,
`predictions.csv`, JSON reports, and neighbour frequency tables/PNG/PDF plots.
Generated results and local environments are excluded from Git; the bundled
classifier model is included.

To use masks separately with ShapeEmbedLite, prepare its training/test folders,
keeping all cells from each embryo in the same split. Historical project notes
used the following external command; check your installation's requirements:

```bat
python ShapeEmbedLite.py --train-test-dataset run_1 TRAIN_MASK_DIR TEST_MASK_DIR
```

ShapeEmbedLite is not bundled or launched by this workflow.

## Validation and contributing

```bat
"EmbryoAnalyser\.venv\Scripts\python.exe" -B -m unittest discover -s tests -v
```

Data-dependent tests require the local `dataset/` fixtures. See
[WORKFLOW.md](EmbryoAnalyser/WORKFLOW.md) for input contracts, algorithm provenance,
and validation details. Follow [AGENTS.md](AGENTS.md): preserve dataset contents,
validate changes, and create corresponding commits.
