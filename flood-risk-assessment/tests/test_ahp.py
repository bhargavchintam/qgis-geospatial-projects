"""
Unit tests for the AHP Engine.
"""

import numpy as np
import pytest
from src.ahp import AHPEngine, RANDOM_INDEX


class TestAHPWeights:
    """Tests for AHP weight computation."""

    def test_weights_sum_to_one(self):
        """Priority weights must sum to 1.0."""
        matrix = [
            [1, 3, 5],
            [1/3, 1, 2],
            [1/5, 1/2, 1],
        ]
        ahp = AHPEngine(matrix, criteria_names=["A", "B", "C"])
        weights = ahp.compute_weights()
        assert np.isclose(np.sum(weights), 1.0, atol=1e-6)

    def test_weights_all_positive(self):
        """All weights must be positive."""
        matrix = [
            [1, 2, 4],
            [1/2, 1, 2],
            [1/4, 1/2, 1],
        ]
        ahp = AHPEngine(matrix)
        weights = ahp.compute_weights()
        assert np.all(weights > 0)

    def test_identity_matrix_equal_weights(self):
        """Identity matrix should produce equal weights."""
        n = 4
        matrix = np.eye(n)
        ahp = AHPEngine(matrix)
        weights = ahp.compute_weights()
        expected = np.ones(n) / n
        np.testing.assert_array_almost_equal(weights, expected, decimal=4)

    def test_dominant_criterion(self):
        """A strongly preferred criterion should have the highest weight."""
        matrix = [
            [1, 9, 9],
            [1/9, 1, 1],
            [1/9, 1, 1],
        ]
        ahp = AHPEngine(matrix, criteria_names=["A", "B", "C"])
        weights = ahp.compute_weights()
        assert weights[0] > weights[1]
        assert weights[0] > weights[2]
        assert weights[0] > 0.7


class TestAHPConsistency:
    """Tests for AHP consistency validation."""

    def test_consistent_matrix(self):
        """A perfectly consistent matrix should have CR = 0."""
        # Perfectly consistent 3×3 matrix
        matrix = [
            [1, 2, 4],
            [1/2, 1, 2],
            [1/4, 1/2, 1],
        ]
        ahp = AHPEngine(matrix)
        ahp.compute_weights()
        consistency = ahp.compute_consistency()
        assert consistency["CR"] < 0.01
        assert consistency["is_consistent"] is True

    def test_inconsistent_matrix(self):
        """An inconsistent matrix should have CR > threshold."""
        # Highly inconsistent matrix
        matrix = [
            [1, 9, 1/9],
            [1/9, 1, 9],
            [9, 1/9, 1],
        ]
        ahp = AHPEngine(matrix, consistency_threshold=0.10)
        ahp.compute_weights()
        consistency = ahp.compute_consistency()
        assert consistency["CR"] > 0.10
        assert consistency["is_consistent"] is False

    def test_2x2_always_consistent(self):
        """2×2 matrices are always perfectly consistent."""
        matrix = [[1, 5], [1/5, 1]]
        ahp = AHPEngine(matrix)
        ahp.compute_weights()
        consistency = ahp.compute_consistency()
        assert consistency["CR"] == 0.0
        assert consistency["is_consistent"] is True

    def test_random_index_lookup(self):
        """Random index table should have values for n=1 through 10."""
        for n in range(1, 11):
            assert n in RANDOM_INDEX


class TestAHPSensitivity:
    """Tests for sensitivity analysis."""

    def test_sensitivity_preserves_sum(self):
        """Adjusted weights should still sum to 1.0."""
        matrix = [
            [1, 3, 5],
            [1/3, 1, 2],
            [1/5, 1/2, 1],
        ]
        ahp = AHPEngine(matrix, criteria_names=["A", "B", "C"])
        ahp.compute_weights()

        results = ahp.sensitivity_analysis(perturbation_pct=10)

        for criterion, data in results.items():
            adjusted_weights = list(data["all_weights"].values())
            assert np.isclose(sum(adjusted_weights), 1.0, atol=1e-4)

    def test_sensitivity_increases_target(self):
        """Perturbed criterion should have higher weight than original."""
        matrix = [
            [1, 2, 3],
            [1/2, 1, 2],
            [1/3, 1/2, 1],
        ]
        ahp = AHPEngine(matrix, criteria_names=["A", "B", "C"])
        ahp.compute_weights()

        results = ahp.sensitivity_analysis(perturbation_pct=20)

        for criterion, data in results.items():
            assert data["adjusted_weight"] > data["original_weight"]


class TestAHPValidation:
    """Tests for input validation."""

    def test_non_square_matrix_raises(self):
        """Non-square matrix should raise ValueError."""
        matrix = [[1, 2, 3], [1/2, 1, 2]]
        with pytest.raises(ValueError, match="square"):
            AHPEngine(matrix)

    def test_repr(self):
        """Test string representation."""
        matrix = [[1, 2], [0.5, 1]]
        ahp = AHPEngine(matrix, criteria_names=["X", "Y"])
        assert "n=2" in repr(ahp)

        ahp.compute_weights()
        assert "X=" in repr(ahp)
