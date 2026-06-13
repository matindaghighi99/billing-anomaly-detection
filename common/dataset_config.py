"""dataset_config.py — single source of truth for pipeline file paths.

Selects the active dataset via the DATASET environment variable so the original
demo set and the expanded MOH set coexist without colliding:

    DATASET unset / "demo"  →  claims.csv        + standard output names
    DATASET=large           →  claims_large.csv  + *_large output names

All pipeline inputs/outputs live under PIPELINE_DATA_DIR (default "data/") so
the repository root stays uncluttered. Override with the PIPELINE_DATA_DIR
environment variable (e.g. point it at a mounted volume). CLAIMS_FILE overrides
the input path explicitly if ever needed.

Usage in a module:
    from dataset_config import CLAIMS_FILE, out
    INPUT_CSV  = CLAIMS_FILE
    OUTPUT_CSV = out("rules_flags.csv")
"""

import os

_DATASET = os.environ.get("DATASET", "demo").strip().lower()
_LARGE = _DATASET == "large"
_SUFFIX = "_large" if _LARGE else ""

# Directory holding generated pipeline artefacts (CSV/JSON). Created on demand.
DATA_DIR = os.environ.get("PIPELINE_DATA_DIR", "data")
# Directory holding generated human-readable reports (Markdown). Created on demand.
REPORTS_DIR = os.environ.get("REPORTS_DIR", "reports")


def data_path(name: str) -> str:
    """Resolve a filename under DATA_DIR, creating the directory if needed."""
    if DATA_DIR and DATA_DIR not in (".", ""):
        os.makedirs(DATA_DIR, exist_ok=True)
        return os.path.join(DATA_DIR, name)
    return name


def report_path(name: str) -> str:
    """Resolve a report filename under REPORTS_DIR, creating it if needed."""
    if REPORTS_DIR and REPORTS_DIR not in (".", ""):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        return os.path.join(REPORTS_DIR, name)
    return name


CLAIMS_FILE = os.environ.get(
    "CLAIMS_FILE", data_path("claims_large.csv" if _LARGE else "claims.csv")
)


def out(name: str) -> str:
    """Map a base output filename to the active dataset's variant under DATA_DIR."""
    if _SUFFIX:
        base, ext = os.path.splitext(name)
        name = f"{base}{_SUFFIX}{ext}"
    return data_path(name)


def is_large() -> bool:
    return _LARGE

