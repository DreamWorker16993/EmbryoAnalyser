# Fiji bridge environment

This directory contains the Windows-tested Python/Java bridge used by the embryo
neighbour-counting workflow. Optional MCP utilities are also retained. No MCP
server or global assistant configuration is required to run `workflow.py`.

## Existing environment

- Python 3.11.16 in the project-local `.venv`.
- PyImageJ 1.8.0, Fiji MCP server 0.2.0, and FastMCP 2.14.7.
- A local Fiji installation with its bundled Zulu Java 21.0.7.
- Three pinned Java bridge dependencies in `bridge-jars/`.
- In-memory Java preferences support in `java-support/`.

The existing `fiji_runtime.py` is loaded by an environment-specific `.pth` file.
It selects the local JVM, adds missing bridge JARs, isolates Java caches and user
preferences, and adjusts PATH only within the Python process. It does not change
the installed Fiji files or the user's/system PATH. Keep the runtime, bridge JARs,
compiled preference classes, and environments when cleaning temporary files.

`environment.py` and `fiji_runtime.py` contain local Fiji/JDK paths. Adjust these
paths when moving the repository to another machine. The current implementation
is Windows-specific and requires a GUI-capable Fiji process for the original
neighbour macro; a headless MCP server does not replace that worker.

## Setup on another Windows machine

Run the following from the repository root with Python 3.11 and an installed
Fiji/JDK. Adapt the paths in `environment.py` and `fiji_runtime.py` first.

```bat
python -m venv "fiji-agent\.venv"
"fiji-agent\.venv\Scripts\python.exe" -m pip install -r "fiji-agent\requirements.lock.txt"

set "FIJI_JDK=C:\path\to\Fiji\java\win64\your-jdk-folder"
"%FIJI_JDK%\bin\javac.exe" -d "fiji-agent\java-support" "fiji-agent\java-support\fijiagent\MemoryPreferencesFactory.java"

"fiji-agent\.venv\Scripts\python.exe" -c "from pathlib import Path; import sysconfig; root = Path('fiji-agent').resolve(); Path(sysconfig.get_path('purelib'), 'fiji_agent_runtime.pth').write_text(str(root) + '\nimport fiji_runtime\n', encoding='utf-8')"
"fiji-agent\.venv\Scripts\python.exe" -m pip check
"fiji-agent\.venv\Scripts\python.exe" "fiji-agent\test_pyimagej.py"
```

The `.pth` applies only to this project environment. The Java source is tracked;
compiled `.class` files are generated locally and ignored by Git. See the official
[PyImageJ installation guide](https://py.imagej.net/en/latest/Install.html) for
general platform requirements.

## Workflow use

From the repository root, use the analysis Python to launch the isolated worker:

```bat
"EmbryoAnalyser\.venv\Scripts\python.exe" "EmbryoAnalyser\workflow.py" neighbours --input "PATH_TO_IMAGES_WITH_ROIS" --output "outputs\neighbours" --fiji-path "C:\path\to\Fiji" --fiji-python "fiji-agent\.venv\Scripts\python.exe"
```

Each image and ROI ZIP is copied to a separate output workspace. Only the
directory-selection statement is changed in the macro's working copy. Fiji runs
with an interactive UI, processes the batch, and exits. The analysis code then
exports distributions. See the [main README](../README.md).

The same isolated worker also runs `measure` and `masks`, using the active
`EmbryoAnalyser/macros/make_mask.ijm`. Input copies, morphology CSVs, and cell
masks are written to separate per-image workspaces. For both exports:

```bat
"EmbryoAnalyser\.venv\Scripts\python.exe" "EmbryoAnalyser\workflow.py" measure --input "PATH_TO_IMAGES_WITH_ROIS" --export-masks --output "outputs\preprocessing"
```

Select alternate Fiji installations with the same `--fiji-path` and
`--fiji-python` options. The worker validates directory substitutions and task
switches before starting Java; the macro's measurement and mask algorithms
remain in the IJM file.

## Optional MCP utilities

`start_fiji_mcp.py` starts the JVM on the main thread before the original MCP
server, avoiding initialization from a request thread. Diagnostics go to stderr
to keep the JSON-RPC stdout stream valid. Its default mode is headless.

Run these checks from this directory using its `.venv/Scripts/python.exe`:

```bat
".venv\Scripts\python.exe" "test_pyimagej.py"
".venv\Scripts\python.exe" "test_mcp.py"
".venv\Scripts\python.exe" "test_codex.py"
```

`test_codex.py` previews configuration through process arguments by default.
`--saved` checks the installed configuration. `codex-fiji.snippet.toml` contains
the local candidate configuration. `install_codex_config.py` writes a backup and
appends the Fiji section to user configuration; obtain the user's approval before
running it. It is not part of the ordinary analysis workflow.

Test scripts regenerate their JSON results and logs. Old diagnostics can be
removed without deleting the test code or runtime dependencies. Java preferences
are not persisted between process restarts, and GUI-only plugins may not work in
headless mode.
