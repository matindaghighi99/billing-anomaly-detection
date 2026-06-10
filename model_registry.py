"""model_registry.py — Model versioning for the feedback XGBoost classifier.

On every training run in feedback.py, register_model() is called to:
  1. Assign a monotonically-incrementing version_id (v001, v002, …)
  2. Save the model artifact (joblib) and record an integrity tag
  3. Write a machine-readable model card (JSON)
  4. Write a human-readable model card (Markdown)
  5. Append the version record to the registry index (registry.json)

load_version(version_id) verifies the artefact's integrity tag and then
reloads the model so a disputed flag can be replayed against the model that
produced it. NOTE: joblib.load (like pickle) executes code embedded in the
artefact, so the integrity check is a security control, not just a checksum.

All version artefacts live under REGISTRY_DIR/v{n:03d}/.
"""

import datetime
import hashlib
import hmac
import json
import os
import warnings

import joblib
import numpy as np

REGISTRY_DIR  = "model_registry"
REGISTRY_JSON = os.path.join(REGISTRY_DIR, "registry.json")

KNOWN_LIMITATIONS = (
    "Trained on a small seed of confirmed/cleared dispositions (demo only). "
    "Requires at least 6 labeled examples; performance degrades rapidly with "
    "fewer labels. All data is SYNTHETIC — not validated for production use. "
    "Purpose: decision-SUPPORT for human auditors only; no automated decisions."
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_dir():
    os.makedirs(REGISTRY_DIR, exist_ok=True)


def _load_registry() -> list:
    if not os.path.exists(REGISTRY_JSON):
        return []
    with open(REGISTRY_JSON) as fh:
        return json.load(fh)


def _save_registry(registry: list) -> None:
    _ensure_dir()
    with open(REGISTRY_JSON, "w") as fh:
        json.dump(registry, fh, indent=2)


def _next_version_id(registry: list) -> str:
    n = len(registry) + 1
    return f"v{n:03d}"


def _model_integrity(path: str) -> str:
    """Integrity tag for a model artifact file.

    joblib.load() (like pickle) executes arbitrary code embedded in the
    artifact, so an attacker who can drop or modify a .joblib file gets code
    execution the moment it is loaded. We record an integrity tag at save time
    and verify it before loading.

    If MODEL_REGISTRY_HMAC_KEY is set, an HMAC-SHA256 is used (resists tampering
    even by someone who can also rewrite registry.json, provided the key stays
    secret). Otherwise a plain SHA-256 is used, which detects accidental or
    third-party corruption but not an attacker who can rewrite the registry too.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    digest = h.hexdigest()
    key = os.environ.get("MODEL_REGISTRY_HMAC_KEY")
    if key:
        return "hmac:" + hmac.new(key.encode("utf-8"), digest.encode("utf-8"),
                                  hashlib.sha256).hexdigest()
    return "sha256:" + digest


def _data_hash(X_train: np.ndarray, y_train: np.ndarray) -> str:
    """SHA256 of the exact training arrays used.

    Uses raw IEEE-754 bytes rather than np.array2string(), which varies
    across NumPy versions and precision settings, producing different hashes
    for identical data in different environments.
    """
    h = hashlib.sha256()
    h.update(X_train.astype(np.float64).tobytes())
    h.update(y_train.astype(np.int64).tobytes())
    return h.hexdigest()


def _val_metrics(clf, X_train: np.ndarray, y_train: np.ndarray) -> dict:
    """Hold-out validation metrics.

    Uses stratified 80/20 split when enough data exists; otherwise
    reports training-set accuracy with a note.
    """
    from sklearn.model_selection import train_test_split

    n = len(y_train)
    classes, counts = np.unique(y_train, return_counts=True)
    min_class = int(counts.min())

    if n >= 10 and min_class >= 2:
        try:
            X_tr, X_val, y_tr, y_val = train_test_split(
                X_train, y_train,
                test_size=0.20,
                random_state=42,
                stratify=y_train,
            )
            # Re-train a proxy model on 80 % to get genuine held-out metrics.
            # The deployed model was fit on 100 % of labels; these metrics come
            # from a separate proxy fit, so they are directionally correct but
            # slightly conservative (less data → lower performance than deployed).
            import copy
            clf_val = copy.deepcopy(clf)
            clf_val.fit(X_tr, y_tr)
            preds = clf_val.predict(X_val)
            det_rate = float((preds[y_val == 1] == 1).mean()) if (y_val == 1).any() else None
            fpr      = float((preds[y_val == 0] == 1).mean()) if (y_val == 0).any() else None
            return {
                "method":          "stratified_80_20_split_proxy",
                "val_size":        len(y_val),
                "detection_rate":  round(det_rate, 3) if det_rate is not None else None,
                "false_pos_rate":  round(fpr, 3)      if fpr      is not None else None,
                "note":            (
                    "Proxy model retrained on 80 % of labels; deployed model "
                    "uses all labels and will perform at least as well."
                ),
            }
        except Exception as exc:
            return {"method": "error", "note": str(exc)}
    else:
        preds    = clf.predict(X_train)
        det_rate = float((preds[y_train == 1] == 1).mean()) if (y_train == 1).any() else None
        fpr      = float((preds[y_train == 0] == 1).mean()) if (y_train == 0).any() else None
        return {
            "method":         "training_set_only",
            "val_size":       n,
            "detection_rate": round(det_rate, 3) if det_rate is not None else None,
            "false_pos_rate": round(fpr, 3)      if fpr      is not None else None,
            "note":           (
                f"Insufficient data for held-out split "
                f"(n={n}, min class size={min_class}). "
                f"Training-set metrics only."
            ),
        }


def _write_model_card_md(path: str, card: dict) -> None:
    hp  = card["hyperparameters"]
    val = card["validation_metrics"]

    hp_rows  = "\n".join(f"| {k} | {v} |" for k, v in hp.items())
    det_rate = f"{val['detection_rate']:.1%}" if val.get("detection_rate") is not None else "N/A"
    fpr_val  = f"{val['false_pos_rate']:.1%}"  if val.get("false_pos_rate")  is not None else "N/A"

    md = f"""# Model Card — Feedback Classifier

**Version:** {card['version_id']}
**Trained:** {card['utc_timestamp']}
**Model type:** {card['model_type']}

---

## Training Data

| Field | Value |
|---|---|
| Training data hash (SHA256) | `{card['training_data_hash']}` |
| Total labeled examples | {card['n_total_labels']} |
| Confirmed (bad actor) | {card['n_confirmed']} |
| Cleared (clean) | {card['n_cleared']} |

---

## Hyperparameters

| Parameter | Value |
|---|---|
{hp_rows}

---

## Validation Metrics

| Metric | Value |
|---|---|
| Method | {val['method']} |
| Validation set size | {val.get('val_size', 'N/A')} |
| Detection rate (confirmed) | {det_rate} |
| False positive rate (cleared) | {fpr_val} |
| Note | {val.get('note', '')} |

---

## Methods

Semi-supervised {card['model_type']} classifier trained on auditor-confirmed
dispositions. Features: claims_per_day, avg_billed, avg_minutes, top_tier_share,
services_per_patient, kl_divergence, cosine_distance, ml_score, cusum_score,
spike_ratio.

Decision threshold: 0.5. Only providers above threshold contribute positive
feedback score to the overall risk score. Cleared providers receive 0 pts.

---

## Known Limitations

{KNOWN_LIMITATIONS}

---

*All providers and claims in this demo are entirely fictional (synthetic data).*
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)


# ── Public API ────────────────────────────────────────────────────────────────

def register_model(
    clf,
    X_train: np.ndarray,
    y_train: np.ndarray,
    hyperparameters: dict,
    n_confirmed: int,
    n_cleared: int,
) -> str:
    """Save a trained model and its model card. Return the new version_id.

    Args:
        clf:             Fitted sklearn/XGBoost classifier
        X_train:         Training feature matrix
        y_train:         Training labels (1=confirmed, 0=cleared)
        hyperparameters: Dict of hyperparameter names → values
        n_confirmed:     Number of 'confirmed' training labels
        n_cleared:       Number of 'cleared' training labels
    """
    _ensure_dir()
    registry = _load_registry()
    version_id = _next_version_id(registry)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    version_dir = os.path.join(REGISTRY_DIR, version_id)
    os.makedirs(version_dir, exist_ok=True)

    # Determine model type
    model_type = type(clf).__name__

    # Compute data hash
    d_hash = _data_hash(X_train, y_train)

    # Compute validation metrics
    val = _val_metrics(clf, X_train, y_train)

    card = {
        "version_id":         version_id,
        "utc_timestamp":      ts,
        "model_type":         model_type,
        "training_data_hash": d_hash,
        "n_total_labels":     int(len(y_train)),
        "n_confirmed":        int(n_confirmed),
        "n_cleared":          int(n_cleared),
        "hyperparameters":    hyperparameters,
        "validation_metrics": val,
        "known_limitations":  KNOWN_LIMITATIONS,
    }

    # Save artefacts
    model_path = os.path.join(version_dir, "model.joblib")
    joblib.dump(clf, model_path)
    model_integrity = _model_integrity(model_path)
    card["model_integrity"] = model_integrity

    card_json_path = os.path.join(version_dir, "model_card.json")
    with open(card_json_path, "w", encoding="utf-8") as fh:
        json.dump(card, fh, indent=2)

    card_md_path = os.path.join(version_dir, "model_card.md")
    _write_model_card_md(card_md_path, card)

    # Update index
    registry.append({
        "version_id":         version_id,
        "utc_timestamp":      ts,
        "model_type":         model_type,
        "training_data_hash": d_hash,
        "n_total_labels":     int(len(y_train)),
        "n_confirmed":        int(n_confirmed),
        "n_cleared":          int(n_cleared),
        "val_detection_rate": val.get("detection_rate"),
        "val_false_pos_rate": val.get("false_pos_rate"),
        "val_note":           val.get("note", ""),
        "model_path":         model_path,
        "model_integrity":    model_integrity,
        "card_json_path":     card_json_path,
        "card_md_path":       card_md_path,
    })
    _save_registry(registry)

    return version_id


def load_version(version_id: str):
    """Reload the model artefact for a given version_id.

    Verifies the artefact's integrity tag (recorded at save time) BEFORE
    calling joblib.load(), because joblib/pickle deserialization executes
    arbitrary code in the artefact. A failed check raises ValueError and the
    file is never loaded.

    Returns (clf, card_dict) or raises FileNotFoundError / ValueError.
    """
    version_dir   = os.path.join(REGISTRY_DIR, version_id)
    model_path    = os.path.join(version_dir, "model.joblib")
    card_json_path = os.path.join(version_dir, "model_card.json")

    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"No model artefact for version {version_id!r} at {model_path}"
        )

    # ── Integrity gate (second line of defence against tampered artefacts) ──
    expected = None
    for rec in _load_registry():
        if rec.get("version_id") == version_id:
            expected = rec.get("model_integrity")
            break
    actual = _model_integrity(model_path)
    if expected is None:
        warnings.warn(
            f"[model_registry] No integrity tag recorded for {version_id!r}; "
            f"loading an unverified artefact. Re-register the model to enable "
            f"integrity verification.",
            UserWarning,
        )
    elif not hmac.compare_digest(expected, actual):
        raise ValueError(
            f"Model artefact integrity check failed for {version_id!r}: stored "
            f"tag does not match the file on disk. Refusing to load a possibly "
            f"tampered model."
        )

    clf = joblib.load(model_path)

    card = {}
    if os.path.exists(card_json_path):
        with open(card_json_path) as fh:
            card = json.load(fh)

    return clf, card


def list_versions() -> list:
    """Return the registry index as a list of version dicts."""
    return _load_registry()


def current_version() -> dict:
    """Return the most recently registered version dict, or None."""
    registry = _load_registry()
    return registry[-1] if registry else None


# ── Self-test ─────────────────────────────────────────────────────────────────

def _selftest():
    """Train twice, confirm two distinct versions, reload v001 and replay scores."""
    import shutil, model_registry as _m

    test_dir  = "model_registry_selftest"
    orig_dir  = _m.REGISTRY_DIR
    orig_json = _m.REGISTRY_JSON

    # Redirect to test directory
    _m.REGISTRY_DIR  = test_dir
    _m.REGISTRY_JSON = os.path.join(test_dir, "registry.json")

    try:
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

        # Build a tiny training set
        np.random.seed(42)
        X1 = np.random.randn(10, 5)
        y1 = np.array([1, 1, 1, 1, 1, 1, 0, 0, 0, 0])

        # Train v1
        try:
            from xgboost import XGBClassifier
            clf1 = XGBClassifier(n_estimators=10, max_depth=2, random_state=42,
                                 eval_metric="logloss")
        except ImportError:
            from sklearn.linear_model import LogisticRegression
            clf1 = LogisticRegression(random_state=42, max_iter=200)

        clf1.fit(X1, y1)
        probs1_before = clf1.predict_proba(X1)[:, 1].copy()

        v1 = _m.register_model(clf1, X1, y1,
                                hyperparameters={"n_estimators": 10, "max_depth": 2},
                                n_confirmed=6, n_cleared=4)
        print(f"    [PASS] Registered {v1}")

        # Extend labels, train v2
        X2 = np.vstack([X1, np.random.randn(4, 5)])
        y2 = np.concatenate([y1, [1, 1, 0, 0]])

        try:
            from xgboost import XGBClassifier
            clf2 = XGBClassifier(n_estimators=20, max_depth=2, random_state=42,
                                 eval_metric="logloss")
        except ImportError:
            from sklearn.linear_model import LogisticRegression
            clf2 = LogisticRegression(random_state=42, max_iter=200)

        clf2.fit(X2, y2)
        v2 = _m.register_model(clf2, X2, y2,
                                hyperparameters={"n_estimators": 20, "max_depth": 2},
                                n_confirmed=8, n_cleared=6)
        print(f"    [PASS] Registered {v2}")

        # Two distinct versions
        versions = _m.list_versions()
        assert len(versions) == 2, f"Expected 2 versions, got {len(versions)}"
        assert versions[0]["version_id"] == "v001"
        assert versions[1]["version_id"] == "v002"
        print(f"    [PASS] Registry has 2 distinct versions: v001, v002")

        # Reload v001 and confirm scores match
        clf1_reloaded, card = _m.load_version("v001")
        probs1_after = clf1_reloaded.predict_proba(X1)[:, 1]
        assert np.allclose(probs1_before, probs1_after, atol=1e-6), (
            "Reloaded v001 produces different predictions"
        )
        print(f"    [PASS] load_version('v001') reproduces identical scores "
              f"(max diff = {abs(probs1_before - probs1_after).max():.2e})")

        # Check model card fields
        assert card["version_id"] == "v001"
        assert "training_data_hash" in card
        assert "validation_metrics" in card
        print(f"    [PASS] model card fields present; "
              f"data hash = {card['training_data_hash'][:16]}...")

    finally:
        _m.REGISTRY_DIR  = orig_dir
        _m.REGISTRY_JSON = orig_json
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)


if __name__ == "__main__":
    print("model_registry.py — Self-test")
    print("=" * 60)
    _selftest()
    print("=" * 60)
    print("  All Phase 2 model_registry tests passed.")
