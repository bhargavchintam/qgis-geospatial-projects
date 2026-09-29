"""Tests for the accuracy assessment."""

import numpy as np

from src.accuracy import (accuracy_summary, confusion_matrix, kappa, overall_accuracy,
                          producers_users_accuracy)


def test_perfect_prediction():
    ref = np.array([1, 1, 2, 2, 3, 3, 4, 5])
    cm = confusion_matrix(ref, ref, labels=[1, 2, 3, 4, 5])
    assert overall_accuracy(cm) == 1.0
    assert kappa(cm) == 1.0
    pu = producers_users_accuracy(cm, [1, 2, 3, 4, 5])
    assert np.allclose(pu["producers_accuracy"], 1.0) and np.allclose(pu["users_accuracy"], 1.0)


def test_known_matrix_values():
    ref = np.array([1, 1, 1, 1, 2, 2, 2, 2])
    pred = np.array([1, 1, 1, 2, 2, 2, 1, 1])
    cm = confusion_matrix(ref, pred, labels=[1, 2])
    assert cm.tolist() == [[3, 1], [2, 2]]
    assert abs(overall_accuracy(cm) - 5 / 8) < 1e-12
    # p_o = 0.625, p_e = (4*5 + 4*3) / 64 = 0.5 -> kappa = 0.25
    assert abs(kappa(cm) - 0.25) < 1e-12
    pu = producers_users_accuracy(cm, [1, 2], {1: "Forest", 2: "Pasture"})
    assert list(pu["name"]) == ["Forest", "Pasture"]
    assert abs(pu.loc[0, "producers_accuracy"] - 0.75) < 1e-12
    assert abs(pu.loc[0, "users_accuracy"] - 0.6) < 1e-12


def test_summary_dict():
    s = accuracy_summary([1, 2, 2], [1, 2, 1], labels=[1, 2], class_names={1: "A", 2: "B"})
    assert s["n_samples"] == 3 and s["class_names"] == ["A", "B"]
    assert abs(s["overall_accuracy"] - 2 / 3) < 1e-12
    assert s["per_class"].shape[0] == 2
