"""dataset_config.py — single source of truth for pipeline file paths.

Selects the active dataset via the DATASET environment variable so the original
demo set and the expanded MOH set coexist without colliding:

    DATASET unset / "demo"  →  claims.csv        + standard output names
    DATASET=large           →  claims_large.csv  + *_large output names

CLAIMS_FILE overrides the input path explicitly if ever needed. Defaults keep
existing behaviour (and the test suite / validate.py) unchanged.

Usage in a module:
    from dataset_config import CLAIMS_FILE, out
    INPUT_CSV  = CLAIMS_FILE
    OUTPUT_CSV = out("rules_flags.csv")
"""

import os

_DATASET = os.environ.get("DATASET", "demo").strip().lower()
_LARGE = _DATASET == "large"
_SUFFIX = "_large" if _LARGE else ""

CLAIMS_FILE = os.environ.get(
    "CLAIMS_FILE", "claims_large.csv" if _LARGE else "claims.csv"
)


def out(name: str) -> str:
    """Map a base output filename to the active dataset's variant."""
    if not _SUFFIX:
        return name
    base, ext = os.path.splitext(name)
    return f"{base}{_SUFFIX}{ext}"


def is_large() -> bool:
    return _LARGE
