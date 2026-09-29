"""
Accuracy assessment for the land-cover classification.

All metrics are computed from an error (confusion) matrix whose rows are the
reference classes and whose columns are the predicted classes.

    Overall accuracy  OA = sum(diagonal) / N
    Kappa             k  = (p_o - p_e) / (1 - p_e)
                      p_o = OA,  p_e = sum_i (row_i * col_i) / N^2
    Producer's acc.   PA_i = cm[i, i] / row_i     (1 - omission error)
    User's acc.       UA_i = cm[i, i] / col_i     (1 - commission error)
"""

import numpy as np
import pandas as pd


def confusion_matrix(ref, pred, labels) -> np.ndarray:
    """Error matrix with rows = reference, cols = predicted, ordered by ``labels``."""
    ref = np.asarray(ref).ravel()
    pred = np.asarray(pred).ravel()
    if ref.shape != pred.shape:
        raise ValueError("ref and pred must have the same length")
    labels = list(labels)
    lookup = {lab: i for i, lab in enumerate(labels)}
    cm = np.zeros((len(labels), len(labels)), dtype=np.int64)
    for r, p in zip(ref, pred):
        if r in lookup and p in lookup:
            cm[lookup[r], lookup[p]] += 1
    return cm


def overall_accuracy(cm: np.ndarray) -> float:
    cm = np.asarray(cm, dtype=np.float64)
    n = cm.sum()
    return float(np.trace(cm) / n) if n > 0 else float("nan")


def kappa(cm: np.ndarray) -> float:
    """Cohen's kappa from the error matrix."""
    cm = np.asarray(cm, dtype=np.float64)
    n = cm.sum()
    if n == 0:
        return float("nan")
    p_o = np.trace(cm) / n
    p_e = float((cm.sum(axis=1) * cm.sum(axis=0)).sum() / (n * n))
    if abs(1.0 - p_e) < 1e-12:
        return 1.0 if p_o >= 1.0 - 1e-12 else 0.0
    return float((p_o - p_e) / (1.0 - p_e))


def producers_users_accuracy(cm: np.ndarray, labels, class_names=None) -> pd.DataFrame:
    """Per-class producer's and user's accuracy as a DataFrame."""
    cm = np.asarray(cm, dtype=np.float64)
    labels = list(labels)
    row_tot = cm.sum(axis=1)
    col_tot = cm.sum(axis=0)
    diag = np.diag(cm)
    with np.errstate(divide="ignore", invalid="ignore"):
        pa = np.where(row_tot > 0, diag / row_tot, np.nan)
        ua = np.where(col_tot > 0, diag / col_tot, np.nan)
    names = [class_names.get(l, str(l)) if class_names else str(l) for l in labels]
    return pd.DataFrame({
        "class": labels,
        "name": names,
        "n_reference": row_tot.astype(int),
        "n_predicted": col_tot.astype(int),
        "producers_accuracy": pa,
        "users_accuracy": ua,
    })


def accuracy_summary(ref, pred, labels, class_names=None) -> dict:
    """
    Full assessment from held-out samples.

    Returns dict with ``confusion_matrix`` (ndarray), ``labels``,
    ``overall_accuracy``, ``kappa``, ``per_class`` (DataFrame) and ``n_samples``.
    """
    cm = confusion_matrix(ref, pred, labels)
    return {
        "confusion_matrix": cm,
        "labels": list(labels),
        "class_names": [class_names.get(l, str(l)) if class_names else str(l) for l in labels],
        "overall_accuracy": overall_accuracy(cm),
        "kappa": kappa(cm),
        "per_class": producers_users_accuracy(cm, labels, class_names),
        "n_samples": int(cm.sum()),
    }
