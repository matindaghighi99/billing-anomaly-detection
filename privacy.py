"""privacy.py — Calibrated Laplace noise for displayed SHAP explanations.

PURPOSE
-------
Show WHY the model flagged a provider without making the raw feature values
trivially reconstructable from the displayed explanation.

Laplace mechanism: noise ~ Laplace(0, sensitivity / epsilon)
  - sensitivity: L1 sensitivity, set to the 95th percentile of |SHAP values|
    across all features and providers in the current dataset (auto-computed
    or user-supplied).
  - epsilon:  privacy parameter; larger = less noise.  Default: 1.0.

HONESTY REQUIREMENT (mandatory)
--------------------------------
This module deliberately labels its output as:
  "Explanation values include calibrated privacy noise (epsilon shown)."
  "This is a demo-grade privacy measure, NOT a formal differential-privacy
   guarantee across all queries. Formal DP requires a managed privacy budget."

Do not represent this as full differential-privacy compliance anywhere in
code, documentation, or UI.

FALLBACK BEHAVIOUR
------------------
  • If diffprivlib is installed it is used for the Laplace draw.
  • If diffprivlib is not installed, numpy.random.default_rng().laplace() is
    used directly — a clean manual implementation of the same mechanism.
  • If shap is not installed the caller is expected to skip SHAP entirely;
    this module does not import shap.

TEST
----
  python privacy.py  →  runs _selftest() which verifies:
    1. Noised values stay within ±5×(sensitivity/epsilon) of the true values.
    2. Top-feature rank is preserved for clear-cut cases (gap ≥ 10× noise scale).
"""

import numpy as np
import pandas as pd
from typing import Optional

DEFAULT_EPSILON     = 1.0
PRIVACY_DISCLAIMER  = (
    "Explanation values include calibrated Laplace privacy noise "
    "(epsilon shown). This is a demo-grade privacy measure, NOT a formal "
    "differential-privacy guarantee across all queries. Formal DP requires "
    "a managed privacy budget."
)


# ── Core noise mechanism ──────────────────────────────────────────────────────

def _laplace_noise(
    size: int,
    sensitivity: float,
    epsilon: float,
    seed: Optional[int] = None,
) -> np.ndarray:
    """Draw Laplace(0, sensitivity/epsilon) noise using diffprivlib or numpy."""
    scale = sensitivity / epsilon

    try:
        from diffprivlib.mechanisms import Laplace as DPLaplace
        # diffprivlib Laplace draws one value at a time; vectorise manually
        mech  = DPLaplace(epsilon=epsilon, sensitivity=sensitivity)
        noise = np.array([mech.randomise(0.0) for _ in range(size)])
    except ImportError:
        rng   = np.random.default_rng(seed)
        noise = rng.laplace(loc=0.0, scale=scale, size=size)

    return noise


def _auto_sensitivity(shap_matrix: np.ndarray) -> float:
    """95th percentile of |SHAP values| across all entries.

    This is a reasonable heuristic for a demo: the noise will be
    proportional to the typical magnitude of contributions, not the
    extreme outlier values.
    """
    abs_vals = np.abs(shap_matrix[np.isfinite(shap_matrix)])
    if len(abs_vals) == 0:
        return 1.0
    return float(np.percentile(abs_vals, 95))


# ── Public API ────────────────────────────────────────────────────────────────

def add_display_noise(
    values: np.ndarray,
    sensitivity: Optional[float] = None,
    epsilon: float = DEFAULT_EPSILON,
    seed: Optional[int] = None,
) -> np.ndarray:
    """Add calibrated Laplace noise to a 1-D array of SHAP values.

    Args:
        values:      True SHAP contribution values (1-D numpy array).
        sensitivity: L1 sensitivity. If None, auto-computed from values.
        epsilon:     Privacy budget parameter. Larger = less noise.
        seed:        Optional RNG seed for reproducibility in tests.

    Returns:
        Array of the same shape with Laplace noise added.

    Note: This is a DEMO-GRADE privacy measure only.
    """
    if sensitivity is None:
        sensitivity = max(float(np.percentile(np.abs(values[np.isfinite(values)]), 95)),
                         1e-6)
    noise = _laplace_noise(len(values), sensitivity=sensitivity, epsilon=epsilon,
                           seed=seed)
    return values + noise


def apply_display_noise_to_df(
    shap_df: pd.DataFrame,
    epsilon: float = DEFAULT_EPSILON,
    seed: Optional[int] = None,
) -> pd.DataFrame:
    """Apply noise to every numeric column of a SHAP value DataFrame.

    The input DataFrame has one row per provider and one column per feature
    (as written by explain.build_shap_explanations → shap_values.csv).

    A column 'epsilon' is appended so downstream display can show the value.
    The original values are NOT modified — this returns a noisy copy.

    Note: This is a DEMO-GRADE privacy measure only.
    """
    numeric_cols = shap_df.select_dtypes(include=[np.number]).columns.tolist()
    if "provider_id" in shap_df.columns:
        numeric_cols = [c for c in numeric_cols if c != "provider_id"]

    noisy = shap_df.copy()
    if not numeric_cols:
        noisy["epsilon"] = epsilon
        return noisy

    # Compute global sensitivity from the entire matrix
    matrix       = shap_df[numeric_cols].values.astype(float)
    sensitivity  = _auto_sensitivity(matrix)

    rng = np.random.default_rng(seed)
    for col in numeric_cols:
        vals  = shap_df[col].values.astype(float)
        noise = _laplace_noise(len(vals), sensitivity=sensitivity,
                               epsilon=epsilon, seed=int(rng.integers(1 << 31)))
        noisy[col] = vals + noise

    noisy["epsilon"]     = epsilon
    noisy["sensitivity"] = round(sensitivity, 6)
    return noisy


def noise_top_vals(
    top_vals: np.ndarray,
    sensitivity: float,
    epsilon: float = DEFAULT_EPSILON,
    seed: Optional[int] = None,
) -> np.ndarray:
    """Add noise to the small array of top-N SHAP values used in the dashboard.

    Returns the noised array.  Note: DEMO-GRADE privacy measure only.
    """
    noise = _laplace_noise(len(top_vals), sensitivity=sensitivity,
                           epsilon=epsilon, seed=seed)
    return top_vals + noise


# ── Self-test ─────────────────────────────────────────────────────────────────

def _selftest():
    """Verify noise bounds and top-feature ordering preservation."""

    # ── Case 1: bounding check ────────────────────────────────────────────────
    # Use auto-computed sensitivity; just verify noise stays within 5x bound.
    true_vals   = np.array([0.800, 0.050, 0.020, 0.010, 0.005])
    epsilon     = 1.0
    sensitivity = _auto_sensitivity(true_vals.reshape(1, -1))
    noise_scale = sensitivity / epsilon
    bound       = 5 * noise_scale   # very conservative Laplace tail bound

    noised = add_display_noise(true_vals.copy(), sensitivity=sensitivity,
                               epsilon=epsilon, seed=0)
    max_delta = float(np.abs(noised - true_vals).max())
    assert max_delta <= bound, (
        f"Noise {max_delta:.4f} exceeds 5x bound {bound:.4f}"
    )
    print(f"    [PASS] Noise bounded: max |delta| = {max_delta:.4f} "
          f"<= 5*(s/e) = {bound:.4f}")

    # ── Case 2: ordering preservation for clear-cut case ─────────────────────
    # Use a controlled (tiny) sensitivity so noise << gap, guaranteeing ordering.
    # This simulates a real case where the top feature contribution is >> noise.
    ctrl_vals       = np.array([1.000, 0.100, 0.050, 0.010, 0.005])
    ctrl_sensitivity = 0.005   # noise scale = 0.005; gap rank-1/rank-2 = 0.9
    ctrl_epsilon     = 1.0

    noised_ctrl  = add_display_noise(ctrl_vals.copy(),
                                     sensitivity=ctrl_sensitivity,
                                     epsilon=ctrl_epsilon, seed=42)
    top_true  = int(np.argmax(ctrl_vals))
    top_noisy = int(np.argmax(noised_ctrl))
    assert top_true == top_noisy, (
        f"Top feature changed: true={top_true}, noisy={top_noisy}"
    )
    print(f"    [PASS] Top-feature rank preserved for clear-cut case "
          f"(feature {top_true}, noise_scale={ctrl_sensitivity/ctrl_epsilon:.4f})")

    # ── Case 3: DataFrame API ─────────────────────────────────────────────────
    fake_df = pd.DataFrame({
        "provider_id": ["P1", "P2", "P3"],
        "feat_a":      [0.6, 0.1, 0.0],
        "feat_b":      [0.0, 0.5, 0.2],
        "feat_c":      [0.1, 0.1, 0.3],
    })
    noisy_df = apply_display_noise_to_df(fake_df, epsilon=1.0, seed=42)
    assert "epsilon" in noisy_df.columns
    assert "sensitivity" in noisy_df.columns
    assert (noisy_df["epsilon"] == 1.0).all()
    assert list(noisy_df["provider_id"]) == ["P1", "P2", "P3"]
    print("    [PASS] apply_display_noise_to_df: epsilon column present, "
          "provider_id unchanged")

    # ── Info: which Laplace backend is in use ─────────────────────────────────
    try:
        import diffprivlib
        print("    [INFO] diffprivlib is installed — used for noise draws")
    except ImportError:
        print("    [INFO] diffprivlib not installed — using numpy fallback (OK)")


if __name__ == "__main__":
    print("privacy.py — Self-test")
    print("=" * 60)
    _selftest()
    print("=" * 60)
    print("  All Phase 3 privacy tests passed.")
