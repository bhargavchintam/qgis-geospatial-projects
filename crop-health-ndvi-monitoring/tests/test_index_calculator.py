"""
Unit tests for the Vegetation Index Calculator.
"""

import numpy as np
import pytest
from src.index_calculator import IndexCalculator


@pytest.fixture
def calculator():
    return IndexCalculator()


@pytest.fixture
def sample_bands():
    """Synthetic reflectance bands for testing."""
    np.random.seed(42)
    size = (50, 50)
    return {
        "nir": np.random.uniform(0.2, 0.6, size),
        "red": np.random.uniform(0.02, 0.15, size),
        "blue": np.random.uniform(0.01, 0.10, size),
        "green": np.random.uniform(0.03, 0.12, size),
        "red_edge": np.random.uniform(0.05, 0.30, size),
    }


class TestNDVI:
    """Tests for NDVI computation."""

    def test_ndvi_range(self, calculator, sample_bands):
        ndvi = calculator.ndvi(sample_bands["nir"], sample_bands["red"])
        assert np.all(ndvi[~np.isnan(ndvi)] >= -1.0)
        assert np.all(ndvi[~np.isnan(ndvi)] <= 1.0)

    def test_ndvi_healthy_vegetation(self, calculator):
        nir = np.array([[0.50]])
        red = np.array([[0.05]])
        ndvi = calculator.ndvi(nir, red)
        assert ndvi[0, 0] > 0.7  # Healthy vegetation

    def test_ndvi_bare_soil(self, calculator):
        nir = np.array([[0.15]])
        red = np.array([[0.12]])
        ndvi = calculator.ndvi(nir, red)
        assert 0 < ndvi[0, 0] < 0.2

    def test_ndvi_water(self, calculator):
        nir = np.array([[0.02]])
        red = np.array([[0.08]])
        ndvi = calculator.ndvi(nir, red)
        assert ndvi[0, 0] < 0

    def test_ndvi_nan_propagation(self, calculator):
        nir = np.array([[np.nan, 0.5]])
        red = np.array([[0.1, np.nan]])
        ndvi = calculator.ndvi(nir, red)
        assert np.isnan(ndvi[0, 0])
        assert np.isnan(ndvi[0, 1])

    def test_ndvi_zero_division(self, calculator):
        nir = np.array([[0.0]])
        red = np.array([[0.0]])
        ndvi = calculator.ndvi(nir, red)
        assert np.isnan(ndvi[0, 0])


class TestEVI:
    """Tests for EVI computation."""

    def test_evi_range(self, calculator, sample_bands):
        evi = calculator.evi(
            sample_bands["nir"], sample_bands["red"], sample_bands["blue"]
        )
        assert np.all(evi[~np.isnan(evi)] >= -1.0)
        assert np.all(evi[~np.isnan(evi)] <= 1.0)

    def test_evi_healthy_vegetation(self, calculator):
        nir = np.array([[0.50]])
        red = np.array([[0.05]])
        blue = np.array([[0.03]])
        evi = calculator.evi(nir, red, blue)
        assert evi[0, 0] > 0.3

    def test_evi_less_saturated_than_ndvi(self, calculator):
        """EVI should be less saturated than NDVI in high-biomass areas."""
        nir = np.array([[0.80]])
        red = np.array([[0.03]])
        blue = np.array([[0.02]])

        ndvi = calculator.ndvi(nir, red)
        evi = calculator.evi(nir, red, blue)

        # Both should be high, but NDVI closer to 1.0
        assert ndvi[0, 0] > evi[0, 0]


class TestSAVI:
    """Tests for SAVI computation."""

    def test_savi_range(self, calculator, sample_bands):
        savi = calculator.savi(sample_bands["nir"], sample_bands["red"])
        assert np.all(savi[~np.isnan(savi)] >= -1.0)
        assert np.all(savi[~np.isnan(savi)] <= 1.0)

    def test_savi_converges_to_ndvi(self, calculator):
        """With L=0, SAVI should equal NDVI."""
        nir = np.array([[0.45]])
        red = np.array([[0.10]])

        ndvi = calculator.ndvi(nir, red)
        savi = calculator.savi(nir, red, L=0.0)

        np.testing.assert_almost_equal(savi[0, 0], ndvi[0, 0], decimal=4)


class TestNDRE:
    """Tests for NDRE computation."""

    def test_ndre_range(self, calculator, sample_bands):
        ndre = calculator.ndre(sample_bands["nir"], sample_bands["red_edge"])
        assert np.all(ndre[~np.isnan(ndre)] >= -1.0)
        assert np.all(ndre[~np.isnan(ndre)] <= 1.0)

    def test_ndre_sensitive_to_chlorophyll(self, calculator):
        """Higher chlorophyll (more red-edge absorption) → higher NDRE."""
        nir = np.array([[0.50]])
        red_edge_low_chl = np.array([[0.35]])  # Less absorption
        red_edge_high_chl = np.array([[0.15]])  # More absorption

        ndre_low = calculator.ndre(nir, red_edge_low_chl)
        ndre_high = calculator.ndre(nir, red_edge_high_chl)

        assert ndre_high[0, 0] > ndre_low[0, 0]


class TestNDWI:
    """Tests for NDWI computation."""

    def test_ndwi_water_positive(self, calculator):
        """Water bodies should have positive NDWI."""
        green = np.array([[0.10]])
        nir = np.array([[0.02]])
        ndwi = calculator.ndwi(green, nir)
        assert ndwi[0, 0] > 0

    def test_ndwi_vegetation_negative(self, calculator):
        """Vegetation should have negative NDWI."""
        green = np.array([[0.08]])
        nir = np.array([[0.45]])
        ndwi = calculator.ndwi(green, nir)
        assert ndwi[0, 0] < 0


class TestComputeAll:
    """Tests for batch index computation."""

    def test_compute_all_indices(self, calculator, sample_bands):
        scene = {
            "nir": sample_bands["nir"],
            "red": sample_bands["red"],
            "blue": sample_bands["blue"],
            "green": sample_bands["green"],
            "red_edge1": sample_bands["red_edge"],
        }
        results = calculator.compute_all(scene)
        assert "ndvi" in results
        assert "evi" in results
        assert "savi" in results
        assert "ndre" in results
        assert "ndwi" in results

    def test_compute_subset(self, calculator, sample_bands):
        scene = {"nir": sample_bands["nir"], "red": sample_bands["red"]}
        results = calculator.compute_all(scene, indices=["ndvi", "savi"])
        assert "ndvi" in results
        assert "savi" in results
        assert "evi" not in results  # Missing blue band


class TestAnomalyDetector:
    """Basic tests for anomaly detection."""

    def test_z_score_detects_low_values(self):
        from src.anomaly_detector import AnomalyDetector
        import tempfile
        import yaml

        config = {
            "anomaly": {
                "method": "z_score",
                "z_score_threshold": -1.5,
                "min_cluster_ha": 0.01,
            },
            "classification": {"health_classes": {}},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config, f)
            config_path = f.name

        detector = AnomalyDetector(config_path)

        # Create data with a clearly anomalous region
        data = np.random.normal(0.7, 0.05, (100, 100))
        data[40:50, 40:50] = 0.2  # Low-NDVI anomaly

        anomaly_mask, stats = detector.detect(data, method="z_score")

        # Should detect the anomalous block
        assert np.sum(anomaly_mask[40:50, 40:50]) > 50  # Most of the block
        assert stats["anomalous_percent"] < 20  # Not too many false positives
