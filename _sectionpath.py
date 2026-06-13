"""_sectionpath.py — make the section folders importable as flat modules.

The codebase is organised into section folders (common/, detection/,
data_pipeline/, dashboard/, auth/, audit/, ops/, testing/) but the modules
still import each other by bare name (``import scoring``, ``from dataset_config
import out``). Every module name is unique, so putting each section folder on
``sys.path`` preserves the exact pre-reorganisation import namespace with no
changes to import statements.

``activate()`` is idempotent and is called from:
  * conftest.py            (pytest test runs)
  * the entry points       (dashboard/app.py, data_pipeline/run_pipeline.py)
  * the harnesses          (testing/fuzz_test.py, testing/stress_test.py)

Containers/CI may instead set PYTHONPATH (see entrypoint.sh / Dockerfile);
calling activate() as well is harmless.
"""

import os
import sys

# Code-bearing section folders. Data files, SQL, and generated artefacts stay
# at the repo root and are read/written relative to the working directory.
SECTIONS = (
    "common", "detection", "data_pipeline", "dashboard",
    "auth", "audit", "ops", "testing",
)

ROOT = os.path.dirname(os.path.abspath(__file__))


def activate(root: str = ROOT) -> None:
    """Prepend each section folder (and the root) to sys.path, once."""
    for name in (".",) + SECTIONS:
        path = os.path.abspath(os.path.join(root, name))
        if path not in sys.path:
            sys.path.insert(0, path)


if __name__ != "__main__":
    activate()
