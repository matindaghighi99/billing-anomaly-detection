"""tests/test_rules_boundary.py
Edge and boundary tests for rules.py

Covers:
  - impossible_day threshold (> 1440 means 1440 is NOT a violation)
  - duplicate billing key logic
  - unbundling detection
  - empty / single-row degenerate inputs
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest

from rules import check_impossible_days, check_duplicates, check_unbundling, run_rules

# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_row(**kwargs):
    """Return a one-row dict with all required columns, overridable via kwargs."""
    defaults = {
        "claim_id":       "C001",
        "provider_id":    "PRV001",
        "provider_name":  "Dr. Test",
        "patient_id":     "PAT001",
        "fee_code":       "99213",
        "service_date":   pd.Timestamp("2024-01-15"),
        "service_minutes": 15,
        "amount_billed":  85.00,
        "specialty":      "Family Medicine",
        "clinic_id":      "CLN01",
    }
    defaults.update(kwargs)
    return defaults


def _make_df(*rows):
    return pd.DataFrame(rows)


# ── Rule 1: impossible day ─────────────────────────────────────────────────────

def test_impossible_day_at_1439():
    """1439 minutes on one day: BELOW the threshold, must NOT be flagged.

    Rule uses > 1440 (strict greater-than), so 1439 is clean.
    """
    df = _make_df(
        _base_row(service_minutes=700),
        _base_row(claim_id="C002", service_minutes=739),
    )
    result = check_impossible_days(df)
    assert result.empty, (
        "1439 total service-minutes should NOT trigger impossible_day "
        "(threshold is > 1440, not >= 1440)"
    )


def test_impossible_day_at_1440():
    """1440 minutes = exactly 24 hours: must NOT be flagged.

    INTENTIONAL DESIGN: The rule uses `> 1440` (strictly greater than).
    1440 minutes is precisely 24 hours -- physically possible if a provider
    worked the full day with no breaks -- so it is NOT treated as impossible.
    A value of 1440 is the boundary but NOT a violation.
    """
    df = _make_df(
        _base_row(service_minutes=720),
        _base_row(claim_id="C002", service_minutes=720),
    )
    result = check_impossible_days(df)
    assert result.empty, (
        "1440 total service-minutes should NOT trigger impossible_day "
        "(1440 == 24 h exactly; rule is STRICTLY > 1440)"
    )


def test_impossible_day_at_1441():
    """1441 minutes: one minute over 24 hours -- MUST be flagged."""
    df = _make_df(
        _base_row(service_minutes=720),
        _base_row(claim_id="C002", service_minutes=721),
    )
    result = check_impossible_days(df)
    assert not result.empty, (
        "1441 total service-minutes MUST trigger impossible_day "
        "(strictly > 1440)"
    )
    assert result.iloc[0]["rule"] == "impossible_day"


def test_impossible_day_exactly_zero():
    """0 service-minutes: should not be flagged as impossible."""
    df = _make_df(_base_row(service_minutes=0))
    result = check_impossible_days(df)
    assert result.empty, "0 service-minutes must NOT be flagged as impossible_day"


# ── Rule 2: duplicate billing ─────────────────────────────────────────────────

def test_duplicate_same_claim_id_same_day():
    """Two rows with same provider + patient + fee_code + service_date should flag."""
    df = _make_df(
        _base_row(claim_id="C001", patient_id="PAT001",
                  fee_code="99213", service_date=pd.Timestamp("2024-01-15")),
        _base_row(claim_id="C002", patient_id="PAT001",
                  fee_code="99213", service_date=pd.Timestamp("2024-01-15")),
    )
    result = check_duplicates(df)
    assert not result.empty, (
        "Same provider + patient + fee_code + date (different claim_ids) "
        "MUST trigger duplicate_billing"
    )
    assert result.iloc[0]["rule"] == "duplicate_billing"


def test_duplicate_same_code_same_day_different_claim_ids():
    """Same provider + fee_code + date but different patient_ids:
    duplicate rule keys on patient_id too, so this should NOT flag.
    """
    df = _make_df(
        _base_row(claim_id="C001", patient_id="PAT001",
                  fee_code="99213", service_date=pd.Timestamp("2024-01-15")),
        _base_row(claim_id="C002", patient_id="PAT002",
                  fee_code="99213", service_date=pd.Timestamp("2024-01-15")),
    )
    result = check_duplicates(df)
    assert result.empty, (
        "Same provider + fee_code + date but DIFFERENT patient_ids should NOT "
        "be flagged -- duplicate key includes patient_id"
    )


def test_duplicate_different_day():
    """Same provider + patient + fee_code but different dates: must NOT flag."""
    df = _make_df(
        _base_row(claim_id="C001", patient_id="PAT001",
                  fee_code="99213", service_date=pd.Timestamp("2024-01-15")),
        _base_row(claim_id="C002", patient_id="PAT001",
                  fee_code="99213", service_date=pd.Timestamp("2024-01-16")),
    )
    result = check_duplicates(df)
    assert result.empty, (
        "Same provider/patient/code but DIFFERENT service dates "
        "must NOT trigger duplicate_billing"
    )


# ── Rule 3: unbundling ─────────────────────────────────────────────────────────

def test_unbundling_present():
    """Provider bills both 93005 and 93010 to same patient same date: should flag."""
    df = _make_df(
        _base_row(claim_id="C001", patient_id="PAT001",
                  fee_code="93005", service_date=pd.Timestamp("2024-01-15"),
                  amount_billed=35.00),
        _base_row(claim_id="C002", patient_id="PAT001",
                  fee_code="93010", service_date=pd.Timestamp("2024-01-15"),
                  amount_billed=45.00),
    )
    result = check_unbundling(df)
    assert not result.empty, (
        "Billing component codes 93005+93010 for same patient+date "
        "MUST trigger unbundling flag"
    )
    assert result.iloc[0]["rule"] == "unbundling"


def test_unbundling_absent():
    """Provider bills only 93005 (one component, not both): must NOT flag."""
    df = _make_df(
        _base_row(claim_id="C001", fee_code="93005", amount_billed=35.00),
        _base_row(claim_id="C002", fee_code="99213", amount_billed=85.00),
    )
    result = check_unbundling(df)
    assert result.empty, (
        "Billing only ONE component code (93005) must NOT trigger unbundling"
    )


# ── Degenerate inputs ─────────────────────────────────────────────────────────

def test_empty_df():
    """run_rules on empty DataFrame must return empty result, not crash.

    Regression guard from fuzz session: previously crashed with KeyError on
    empty input before validator was added.
    """
    df = pd.DataFrame(columns=[
        "claim_id", "provider_id", "provider_name", "patient_id",
        "fee_code", "service_date", "service_minutes", "amount_billed",
        "specialty", "clinic_id",
    ])
    result = run_rules(df)
    assert isinstance(result, pd.DataFrame), "run_rules must return a DataFrame on empty input"
    assert result.empty, "run_rules on empty input must return an empty DataFrame"


def test_single_row():
    """One claim with no violations should produce an empty flags DataFrame."""
    df = _make_df(_base_row())
    result = run_rules(df)
    assert isinstance(result, pd.DataFrame), "run_rules must return DataFrame on single-row input"
    assert result.empty, "A single clean claim must produce no flags"
