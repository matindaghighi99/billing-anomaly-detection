"""conftest.py — ensure section folders are importable during pytest runs.

Tests import first-party modules by bare name (``from rules import ...``);
this puts the section folders on sys.path before collection. See
_sectionpath.py for the rationale.
"""

import _sectionpath

_sectionpath.activate()
