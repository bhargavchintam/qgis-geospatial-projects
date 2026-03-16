"""
Unit tests for the LST Processor module.
"""

import numpy as np
import pytest
import tempfile
import rasterio
from pathlib import Path
from rasterio.transform import from_bounds


# ─── Test Fixtures ────────────────────────────────────────────────


def create_test_raster(data, filepath, crs="EPSG:32612"):
    """Helper: write a numpy array as a GeoTIFF test fixture."""
    height, width = data.shape
    transform = from_bounds(0, 0, width * 30, height * 30, width, height)

    profile = {
        "driver": "GTiff",
        "dtype": data.dtype,
        "width": width,
        "height": height,
        "count": 1,
        "crs": crs,
        "transform": transform,
        "nodata": -9999,
    }

    with rasterio.open(filepath, "w", **profile) as dst:
        dst.write(data, 1)


@pytest.fixture
def sample_bands(tmp_path):
    """Create sample Landsat band rasters for testing."""
    np.random.seed(42)
    size = (100, 100)

    # Thermal band (simulated DN values for Collection 2 L2SP)
    thermal = np.random.uniform(28000, 32000, size).astype(np.float64)
    thermal_path = tmp_path / "B10.TIF"
    create_test_raster(thermal, str(thermal_path))

    # Red band (reflectance values)
    red = np.random.uniform(0.05, 0.30, size).astype(np.float64)
    red_path = tmp_path / "B4.TIF"
    create_test_raster(red, str(red_path))

    # NIR band (higher reflectance for vegetation)
    nir = np.random.uniform(0.10, 0.60, size).astype(np.float64)
    nir_path = tmp_path / "B5.TIF"
    create_test_raster(nir, str(nir_path))

    return {
        "thermal": str(thermal_path),
        "red": str(red_path),
        "nir": str(nir_path),
    }


# ─── NDVI Tests ───────────────────────────────────────────────────


class TestNDVI:
    """Tests for NDVI computation."""

    def test_ndvi_range(self):
        """NDVI values should be in [-1, 1]."""
        from src.lst_processor import LSTProcessor

        processor = LSTProcessor.__new__(LSTProcessor)
        processor.ndvi_cfg = {"soil_threshold": 0.2, "vegetation_threshold": 0.5}

        red = np.array([[0.1, 0.3, 0.5], [0.2, 0.4, 0.0]])
        nir = np.array([[0.4, 0.3, 0.1], [0.6, 0.2, 0.0]])

        ndvi = processor._compute_ndvi(red, nir)

        assert np.all(ndvi[~np.isnan(ndvi)] >= -1.0)
        assert np.all(ndvi[~np.isnan(ndvi)] <= 1.0)

    def test_ndvi_vegetation(self):
        """Dense vegetation should have high NDVI."""
        from src.lst_processor import LSTProcessor

        processor = LSTProcessor.__new__(LSTProcessor)

        red = np.array([[0.05]])
        nir = np.array([[0.50]])

        ndvi = processor._compute_ndvi(red, nir)
        assert ndvi[0, 0] > 0.7

    def test_ndvi_bare_soil(self):
        """Bare soil should have low positive NDVI."""
        from src.lst_processor import LSTProcessor

        processor = LSTProcessor.__new__(LSTProcessor)

        red = np.array([[0.25]])
        nir = np.array([[0.30]])

        ndvi = processor._compute_ndvi(red, nir)
        assert 0 < ndvi[0, 0] < 0.2

    def test_ndvi_water(self):
        """Water should have negative NDVI."""
        from src.lst_processor import LSTProcessor

        processor = LSTProcessor.__new__(LSTProcessor)

        red = np.array([[0.10]])
        nir = np.array([[0.05]])

        ndvi = processor._compute_ndvi(red, nir)
        assert ndvi[0, 0] < 0

    def test_ndvi_division_by_zero(self):
        """Zero denominator should produce NaN, not crash."""
        from src.lst_processor import LSTProcessor

        processor = LSTProcessor.__new__(LSTProcessor)

        red = np.array([[0.0]])
        nir = np.array([[0.0]])

        ndvi = processor._compute_ndvi(red, nir)
        assert np.isnan(ndvi[0, 0])


# ─── Emissivity Tests ────────────────────────────────────────────


class TestEmissivity:
    """Tests for land surface emissivity computation."""

    def test_emissivity_bare_soil(self):
        """Bare soil (low NDVI) should have soil emissivity."""
        from src.lst_processor import LSTProcessor

        processor = LSTProcessor.__new__(LSTProcessor)
        processor.ndvi_cfg = {"soil_threshold": 0.2, "vegetation_threshold": 0.5}
        processor.emissivity_cfg = {
            "soil": 0.966,
            "vegetation": 0.973,
            "offset": 0.986,
            "slope": 0.004,
        }

        ndvi = np.array([[0.1]])
        pv = np.array([[0.0]])

        emissivity = processor._compute_emissivity(ndvi, pv)
        assert np.isclose(emissivity[0, 0], 0.966)

    def test_emissivity_dense_vegetation(self):
        """Dense vegetation should have vegetation emissivity."""
        from src.lst_processor import LSTProcessor

        processor = LSTProcessor.__new__(LSTProcessor)
        processor.ndvi_cfg = {"soil_threshold": 0.2, "vegetation_threshold": 0.5}
        processor.emissivity_cfg = {
            "soil": 0.966,
            "vegetation": 0.973,
            "offset": 0.986,
            "slope": 0.004,
        }

        ndvi = np.array([[0.8]])
        pv = np.array([[1.0]])

        emissivity = processor._compute_emissivity(ndvi, pv)
        assert np.isclose(emissivity[0, 0], 0.973)

    def test_emissivity_range(self):
        """All emissivity values should be in physical range [0.9, 1.0]."""
        from src.lst_processor import LSTProcessor

        processor = LSTProcessor.__new__(LSTProcessor)
        processor.ndvi_cfg = {"soil_threshold": 0.2, "vegetation_threshold": 0.5}
        processor.emissivity_cfg = {
            "soil": 0.966,
            "vegetation": 0.973,
            "offset": 0.986,
            "slope": 0.004,
        }

        ndvi = np.random.uniform(-0.5, 0.9, (50, 50))
        pv = np.clip((ndvi - 0.2) / 0.3, 0, 1) ** 2

        emissivity = processor._compute_emissivity(ndvi, pv)
        valid = emissivity[~np.isnan(emissivity)]

        assert np.all(valid >= 0.9)
        assert np.all(valid <= 1.0)


# ─── LST Computation Tests ───────────────────────────────────────


class TestLSTComputation:
    """Tests for the final LST calculation."""

    def test_lst_physical_range(self):
        """LST should be within physically plausible range."""
        from src.lst_processor import LSTProcessor

        processor = LSTProcessor.__new__(LSTProcessor)
        processor.wavelength = 10.895e-6
        processor.RHO = 1.438e-2

        bt = np.array([[310.0, 320.0], [300.0, 330.0]])  # Kelvin
        emissivity = np.array([[0.97, 0.96], [0.98, 0.95]])

        lst = processor._compute_lst(bt, emissivity)
        lst_celsius = lst - 273.15

        # Plausible surface temps: -50°C to 80°C
        assert np.all(lst_celsius > -50)
        assert np.all(lst_celsius < 80)

    def test_lst_increases_with_bt(self):
        """Higher brightness temperature should yield higher LST."""
        from src.lst_processor import LSTProcessor

        processor = LSTProcessor.__new__(LSTProcessor)
        processor.wavelength = 10.895e-6
        processor.RHO = 1.438e-2

        bt_low = np.array([[300.0]])
        bt_high = np.array([[320.0]])
        emissivity = np.array([[0.97]])

        lst_low = processor._compute_lst(bt_low, emissivity)
        lst_high = processor._compute_lst(bt_high, emissivity)

        assert lst_high[0, 0] > lst_low[0, 0]


# ─── Integration Test ────────────────────────────────────────────


class TestPipelineIntegration:
    """End-to-end pipeline integration test."""

    def test_anomaly_computation(self):
        """LST anomaly should center around zero for uniform data."""
        from src.lst_processor import LSTProcessor

        processor = LSTProcessor.__new__(LSTProcessor)

        lst = np.random.normal(40.0, 5.0, (100, 100))
        anomaly = processor.compute_lst_anomaly(lst)

        # Mean anomaly should be ~0
        assert abs(np.nanmean(anomaly)) < 0.5
