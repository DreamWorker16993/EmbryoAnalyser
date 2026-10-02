"""Shared input discovery and output protection for the embryo workflow."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Reserved write-protection path; this directory need not exist at runtime.
DATASET_ROOT = PROJECT_ROOT / "dataset"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs"


def _inside(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def _comparison_path(path: Path) -> Path:
    value = str(path)
    if os.name == "nt":
        if value.casefold().startswith("\\\\?\\unc\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\") and re.match(r"[A-Za-z]:[\\/]", value[4:]):
            value = value[4:]
        elif value.startswith("\\\\.\\"):
            raise ValueError("Device namespace paths cannot be used for workflow outputs")
    return Path(value)


def safe_destination(path: str | Path) -> Path:
    """Reject both direct paths and existing links into the protected dataset.

    Check before creating anything: even a missing descendant of a directory
    junction is resolved by pathlib and cannot bypass this protection.
    """
    requested = Path(path).expanduser().absolute()
    resolved = requested.resolve()
    if _inside(_comparison_path(requested), _comparison_path(DATASET_ROOT.absolute())) or _inside(
        _comparison_path(resolved), _comparison_path(DATASET_ROOT.resolve())
    ):
        raise ValueError(f"Outputs cannot be written inside dataset: {path}")
    # Volume/share aliases and Windows extended paths can name the same folder
    # without equal strings. Compare existing ancestry by filesystem identity.
    for ancestor in (resolved, *resolved.parents):
        try:
            if os.path.samefile(ancestor, DATASET_ROOT):
                raise ValueError(f"Outputs cannot be written inside dataset: {path}")
        except OSError:
            continue
    # A hard link outside dataset can still truncate a protected input. Refuse
    # any multiply linked output file rather than scanning the dataset inodes.
    if resolved.is_file() and resolved.stat().st_nlink > 1:
        raise ValueError(f"Refusing to overwrite a multiply linked output file: {path}")
    return resolved


def ensure_output_directory(path: str | Path) -> Path:
    destination = safe_destination(path)
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def expand_inputs(inputs, suffix: str | tuple[str, ...] = ".csv") -> list[Path]:
    """Expand explicit files or recursive directories in a deterministic order."""
    if isinstance(inputs, (str, Path)):
        inputs = [inputs]
    endings = (suffix,) if isinstance(suffix, str) else suffix
    endings = tuple(ending.lower() for ending in endings)
    paths = set()
    for supplied in inputs:
        path = Path(supplied).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Input does not exist: {supplied}")
        if path.is_dir():
            found = [item for item in path.rglob("*") if item.is_file()
                     and item.suffix.lower() in endings]
            if not found:
                raise ValueError(f"No {', '.join(endings)} inputs found in {path}")
            paths.update(item.resolve() for item in found)
        elif path.suffix.lower() in endings:
            paths.add(path)
        else:
            raise ValueError(f"Expected {', '.join(endings)} input: {path}")
    if not paths:
        raise ValueError("At least one input file is required")
    return sorted(paths, key=lambda item: str(item).casefold())


def sample_name(path: str | Path) -> str:
    """Give identically named files in different folders distinct output names."""
    source = Path(path).resolve()
    label = re.sub(r"[^A-Za-z0-9._-]+", "_", source.parent.name + "_" + source.stem)
    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:10]
    return f"{label[:70].strip('._') or 'sample'}_{digest}"


def write_json(path: str | Path, payload) -> Path:
    destination = safe_destination(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return destination
