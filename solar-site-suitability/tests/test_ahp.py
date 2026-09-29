"""Tests for the AHP engine (row geometric-mean method)."""

import numpy as np
import pytest

from src.ahp import RANDOM_INDEX, AHPEngine


def test_weights_sum_to_one_and_positive():
    matrix = [[1, 3, 5], [1 / 3, 1, 2], [1 / 5, 1 / 2, 1]]
    ahp = AHPEngine(matrix, criteria_names=["A", "B", "C"])
    w = ahp.compute_weights()
    assert np.isclose(w.sum(), 1.0, atol=1e-9)
    assert np.all(w > 0)
    assert w[0] > w[1] > w[2]


def test_identity_matrix_gives_equal_weights_and_zero_cr():
    n = 5
    ahp = AHPEngine(np.eye(n))
    w = ahp.compute_weights()
    np.testing.assert_allclose(w, np.ones(n) / n, atol=1e-12)
    cons = ahp.compute_consistency()
    assert cons["lambda_max"] == pytest.approx(n, abs=1e-9)
    assert cons["CR"] == 0.0
    assert cons["is_consistent"] is True


def test_consistent_matrix_matches_eigenvector_exactly():
    # A = w_i / w_j for w = (0.5, 0.3, 0.2) is perfectly consistent
    w_true = np.array([0.5, 0.3, 0.2])
    matrix = w_true[:, None] / w_true[None, :]
    ahp = AHPEngine(matrix)
    np.testing.assert_allclose(ahp.compute_weights(), w_true, atol=1e-12)
    cons = ahp.compute_consistency()
    assert cons["CI"] == pytest.approx(0.0, abs=1e-9)
    assert cons["lambda_max"] == pytest.approx(3.0, abs=1e-9)


def test_inconsistent_matrix_is_flagged():
    matrix = [[1, 9, 1 / 9], [1 / 9, 1, 9], [9, 1 / 9, 1]]
    ahp = AHPEngine(matrix, consistency_threshold=0.10)
    ahp.compute_weights()
    cons = ahp.compute_consistency()
    assert cons["CR"] > 0.10
    assert cons["is_consistent"] is False


def test_project_matrix_is_consistent():
    from src.utils import load_config
    from tests.conftest import PROJECT_DIR
    cfg = load_config(PROJECT_DIR / "config.yaml")["ahp"]
    ahp = AHPEngine(cfg["pairwise_matrix"], criteria_names=cfg["criteria_names"])
    w = ahp.get_weight_dict()
    cons = ahp.compute_consistency()
    assert cons["CR"] < 0.10
    assert max(w, key=w.get) == "ghi"
    assert np.isclose(sum(w.values()), 1.0)


def test_sensitivity_preserves_sum_and_raises_target():
    matrix = [[1, 2, 3], [1 / 2, 1, 2], [1 / 3, 1 / 2, 1]]
    ahp = AHPEngine(matrix, criteria_names=["A", "B", "C"])
    ahp.compute_weights()
    for name, data in ahp.sensitivity_analysis(20).items():
        assert np.isclose(sum(data["all_weights"].values()), 1.0, atol=1e-4)
        assert data["adjusted_weight"] > data["original_weight"]


def test_non_square_raises_and_random_index_table():
    with pytest.raises(ValueError, match="square"):
        AHPEngine([[1, 2, 3], [1 / 2, 1, 2]])
    for n in range(1, 11):
        assert n in RANDOM_INDEX
