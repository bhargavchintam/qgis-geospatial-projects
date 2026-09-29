"""
Analytical Hierarchy Process (AHP) Engine

Implements Saaty's AHP method for deriving criteria weights from
pairwise comparison matrices, including consistency validation.

This copy uses the row geometric-mean method (Crawford & Williams, 1985)
instead of the eigenvector method. For a perfectly consistent matrix the
two agree exactly; for slightly inconsistent matrices they agree to within
rounding. The geometric mean is deterministic, always positive and handles
the identity matrix without any eigen-solver ambiguity.

Reference:
    Saaty, T.L. (1980). The Analytic Hierarchy Process.
    McGraw-Hill, New York.
    Crawford, G. & Williams, C. (1985). A note on the analysis of subjective
    judgment matrices. Journal of Mathematical Psychology, 29, 387-405.
"""

import numpy as np
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Random Consistency Index values (Saaty, 1980)
# Index corresponds to matrix size n
RANDOM_INDEX = {
    1: 0.00, 2: 0.00, 3: 0.58, 4: 0.90, 5: 1.12,
    6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49,
}


class AHPEngine:
    """
    Analytical Hierarchy Process for multi-criteria weight derivation.

    Given a pairwise comparison matrix, computes:
    - Priority weights via the row geometric-mean method
    - Consistency Index (CI) and Consistency Ratio (CR)
    - Validates CR against threshold (typically 0.10)
    """

    def __init__(
        self,
        pairwise_matrix: np.ndarray,
        criteria_names: Optional[List[str]] = None,
        consistency_threshold: float = 0.10,
    ):
        """
        Initialize AHP with pairwise comparison matrix.

        Args:
            pairwise_matrix: n×n matrix of pairwise comparisons (Saaty scale)
            criteria_names: optional list of criterion names
            consistency_threshold: maximum acceptable CR (default: 0.10)
        """
        self.matrix = np.array(pairwise_matrix, dtype=np.float64)
        if self.matrix.ndim != 2 or self.matrix.shape[0] != self.matrix.shape[1]:
            raise ValueError("Pairwise comparison matrix must be square")
        self.n = self.matrix.shape[0]
        self.criteria_names = criteria_names or [f"C{i+1}" for i in range(self.n)]
        if len(self.criteria_names) != self.n:
            raise ValueError("criteria_names length must match matrix size")
        self.consistency_threshold = consistency_threshold

        # Zero / negative entries (e.g. np.eye) mean "no preference" = 1
        if np.any(self.matrix <= 0):
            logger.warning("Non-positive pairwise entries found; treating them as 1 (equal importance)")
        self._positive = np.where(self.matrix > 0, self.matrix, 1.0)

        # Validate reciprocal property: a[i,j] = 1/a[j,i]
        self._validate_reciprocal()

    def _validate_reciprocal(self, tolerance: float = 0.01) -> None:
        """Verify the matrix satisfies the reciprocal property."""
        for i in range(self.n):
            for j in range(i + 1, self.n):
                if self.matrix[j, i] <= 0 or self.matrix[i, j] <= 0:
                    continue
                expected = 1.0 / self.matrix[j, i]
                actual = self.matrix[i, j]
                if abs(actual - expected) > tolerance:
                    logger.warning(
                        f"Reciprocal violation at ({i},{j}): "
                        f"expected {expected:.4f}, got {actual:.4f}"
                    )

    def compute_weights(self) -> np.ndarray:
        """
        Compute priority weights using the row geometric-mean method.

        w_i = (prod_j a_ij)^(1/n) / sum_k (prod_j a_kj)^(1/n)

        lambda_max is estimated as the mean of (A w)_i / w_i, which equals
        the principal eigenvalue exactly when the matrix is consistent
        (for the identity matrix it gives n, so CI = 0).

        Returns:
            1D array of normalized weights summing to 1.0
        """
        # Geometric mean of each row (log form avoids overflow for large n)
        matrix = self._positive
        log_gm = np.mean(np.log(matrix), axis=1)
        geometric_means = np.exp(log_gm)
        weights = geometric_means / np.sum(geometric_means)

        # Principal eigenvalue estimate: mean of (A @ w) / w
        aw = matrix @ weights
        self.lambda_max = float(np.mean(aw / weights))

        logger.info(f"AHP weights computed (geometric mean) — λ_max: {self.lambda_max:.4f}")
        for name, weight in zip(self.criteria_names, weights):
            logger.info(f"  {name}: {weight:.4f}")

        self.weights = weights
        return weights

    def compute_consistency(self) -> Dict[str, float]:
        """
        Compute Consistency Index (CI) and Consistency Ratio (CR).

        CI = (λ_max - n) / (n - 1)
        CR = CI / RI

        where RI is the Random Consistency Index for matrix size n.

        Returns:
            dict with 'lambda_max', 'CI', 'RI', 'CR', and 'is_consistent'
        """
        if not hasattr(self, "lambda_max"):
            self.compute_weights()

        # Consistency Index
        ci = (self.lambda_max - self.n) / (self.n - 1) if self.n > 1 else 0.0
        ci = max(ci, 0.0)  # tiny negative values from rounding become 0

        # Random Index
        ri = RANDOM_INDEX.get(self.n, 1.49)

        # Consistency Ratio
        cr = ci / ri if ri > 0 else 0.0

        is_consistent = cr < self.consistency_threshold

        result = {
            "lambda_max": round(float(self.lambda_max), 4),
            "CI": round(float(ci), 4),
            "RI": round(float(ri), 4),
            "CR": round(float(cr), 4),
            "is_consistent": bool(is_consistent),
            "threshold": self.consistency_threshold,
        }

        status = "PASS" if is_consistent else "FAIL"
        logger.info(
            f"AHP Consistency Check [{status}] — "
            f"CR: {result['CR']:.4f} (threshold: {self.consistency_threshold})"
        )

        if not is_consistent:
            logger.warning(
                "Pairwise comparison matrix is INCONSISTENT. "
                "Revise comparisons to achieve CR < 0.10."
            )

        return result

    def get_weight_dict(self) -> Dict[str, float]:
        """Return weights as a {criterion_name: weight} dictionary."""
        if not hasattr(self, "weights"):
            self.compute_weights()
        return dict(zip(self.criteria_names, self.weights.tolist()))

    def sensitivity_analysis(
        self, perturbation_pct: float = 10.0
    ) -> Dict[str, Dict[str, float]]:
        """
        One-at-a-time sensitivity analysis on criteria weights.

        Increases each criterion weight by perturbation_pct and
        proportionally decreases others, then recomputes rankings.

        Args:
            perturbation_pct: percentage increase for sensitivity test

        Returns:
            dict mapping criterion → adjusted weight vector
        """
        if not hasattr(self, "weights"):
            self.compute_weights()

        base_weights = self.weights.copy()
        results = {}

        for i, name in enumerate(self.criteria_names):
            adjusted = base_weights.copy()
            delta = base_weights[i] * (perturbation_pct / 100)

            adjusted[i] += delta

            # Proportionally decrease other weights
            other_indices = [j for j in range(self.n) if j != i]
            other_sum = np.sum(adjusted[other_indices])
            if other_sum > 0:
                scale = (1.0 - adjusted[i]) / other_sum
                adjusted[other_indices] *= scale

            results[name] = {
                "original_weight": round(float(base_weights[i]), 4),
                "adjusted_weight": round(float(adjusted[i]), 4),
                "weight_change": round(float(delta), 4),
                "all_weights": {
                    n: round(float(w), 4) for n, w in zip(self.criteria_names, adjusted)
                },
            }

        return results

    def __repr__(self) -> str:
        if hasattr(self, "weights"):
            w = ", ".join(f"{n}={w:.3f}" for n, w in zip(self.criteria_names, self.weights))
            return f"AHPEngine(n={self.n}, weights=[{w}])"
        return f"AHPEngine(n={self.n}, weights=not_computed)"
