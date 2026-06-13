# env.sh — local-development path setup.
#
# The code is organised into section folders (common/, detection/, …) but the
# modules import each other by bare name. The main entry points (the dashboard,
# the pipeline runner, the test suite, and the fuzz/stress harnesses) bootstrap
# this automatically. Source this file only if you want to run an individual
# phase script directly, e.g.:
#
#     source env.sh
#     python detection/rules.py
#
# Run scripts from the repository root so the working-directory-relative data
# files (claims.csv, *.db, schema.sql, …) resolve.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export PYTHONPATH="$ROOT:$ROOT/common:$ROOT/detection:$ROOT/data_pipeline:$ROOT/dashboard:$ROOT/auth:$ROOT/audit:$ROOT/ops:$ROOT/testing${PYTHONPATH:+:$PYTHONPATH}"
