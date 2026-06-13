"""validators.py -- Shared input-validation helpers for the billing pipeline.

Used by rules.py, peer_stats.py, codemix.py, temporal.py, and anomaly_model.py
to reject or coerce bad inputs before processing, so every module fails loudly
rather than crashing with a cryptic KeyError or producing a silent miscount.

POLICY (document here so every module can reference it):

  - Empty DataFrame (0 rows)          : return empty result with correct schema
  - Missing required column            : raise ValueError("Missing columns: ...")
  - NaN in provider_id / fee_code / specialty: drop rows, emit WARNING
  - Malformed service_date             : coerce with pd.to_datetime(errors='coerce'),
                                         drop NaT rows, emit WARNING
  - Negative / zero service_minutes    : keep rows (rule logic handles edge cases),
                                         emit WARNING if any are present
  - Negative amount_billed             : keep rows, emit WARNING
  - Wrong dtype in numeric columns     : coerce with pd.to_numeric(errors='coerce'),
                                         emit WARNING
"""

import logging
import warnings

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _warn(msg: str) -> None:
    """Emit both a logging.warning and a Python UserWarning (visible in tests)."""
    logger.warning(msg)
    warnings.warn(msg, UserWarning, stacklevel=3)


def validate_claims_df(
    df: pd.DataFrame,
    required_cols: list,
    caller: str = "",
) -> pd.DataFrame:
    """Validate and coerce a claims DataFrame.

    Args:
        df:            Input DataFrame.
        required_cols: Columns that must exist (KeyError-free guarantee).
        caller:        Name of the calling module/function for log messages.

    Returns:
        Cleaned copy of df (rows may be dropped; dtypes may be coerced).

    Raises:
        ValueError: if any required_cols are missing from df.
        TypeError:  if df is not a pandas DataFrame.
    """
    tag = f"[{caller}] " if caller else ""

    # ── Type check ────────────────────────────────────────────────────────────
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"{tag}Expected a pandas DataFrame, got {type(df).__name__!r}")

    # ── Missing columns ───────────────────────────────────────────────────────
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"{tag}Missing columns: {missing}")

    # ── Empty DataFrame ───────────────────────────────────────────────────────
    if df.empty:
        return df.copy()

    df = df.copy()

    # ── Coerce numeric columns ─────────────────────────────────────────────────
    for col in ("service_minutes", "amount_billed"):
        if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
            before = len(df)
            df[col] = pd.to_numeric(df[col], errors="coerce")
            n_bad = df[col].isna().sum()
            if n_bad:
                _warn(
                    f"{tag}Column '{col}': {n_bad} non-numeric value(s) coerced to NaN"
                )

    # ── Warn on negative / zero service_minutes ───────────────────────────────
    if "service_minutes" in df.columns:
        n_neg = (df["service_minutes"].dropna() <= 0).sum()
        if n_neg:
            _warn(
                f"{tag}Column 'service_minutes': {n_neg} row(s) with value <= 0. "
                "These rows are kept; detection logic will handle them."
            )

    # ── Warn on negative amount_billed ────────────────────────────────────────
    if "amount_billed" in df.columns:
        n_neg = (df["amount_billed"].dropna() < 0).sum()
        if n_neg:
            _warn(
                f"{tag}Column 'amount_billed': {n_neg} row(s) with negative value. "
                "These rows are kept."
            )

    # ── Coerce service_date ───────────────────────────────────────────────────
    if "service_date" in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df["service_date"]):
            df["service_date"] = pd.to_datetime(df["service_date"], errors="coerce")
        n_nat = df["service_date"].isna().sum()
        if n_nat:
            _warn(
                f"{tag}Column 'service_date': {n_nat} unparseable/NaT value(s) dropped."
            )
            df = df.dropna(subset=["service_date"])

    # ── Drop rows with NaN in key categorical columns ─────────────────────────
    for col in ("provider_id", "fee_code", "specialty"):
        if col not in df.columns:
            continue
        # Treat both NaN and empty string as missing
        is_empty = df[col].isna()
        if df[col].dtype == object:
            is_empty = is_empty | (df[col].astype(str).str.strip() == "")
        n_bad = is_empty.sum()
        if n_bad:
            _warn(
                f"{tag}Column '{col}': {n_bad} row(s) with null/empty value dropped."
            )
            df = df[~is_empty]

    return df
