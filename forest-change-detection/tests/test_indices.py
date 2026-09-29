"""Tests for the spectral indices."""

import numpy as np

from src.indices import BAND_INDEX, compute_all, false_color_composite, nbr, ndmi, ndvi
from src.synthetic_data import CLASS_MEANS


def _means(cls):
    m = CLASS_MEANS[cls]
    return {name: m[i] for name, i in BAND_INDEX.items()}


def test_index_ranges():
    rng = np.random.default_rng(0)
    nir = rng.uniform(0.01, 0.6, (40, 40))
    red = rng.uniform(0.01, 0.3, (40, 40))
    swir1 = rng.uniform(0.01, 0.4, (40, 40))
    swir2 = rng.uniform(0.01, 0.4, (40, 40))
    for arr in (ndvi(nir, red), nbr(nir, swir2), ndmi(nir, swir1)):
        assert arr.shape == (40, 40)
        assert np.all(arr >= -1.0) and np.all(arr <= 1.0)


def test_forest_ndvi_greater_than_pasture():
    f, p, w, b = _means(1), _means(2), _means(3), _means(4)
    assert ndvi(f["B08"], f["B04"]) > ndvi(p["B08"], p["B04"]) > ndvi(b["B08"], b["B04"])
    assert ndvi(w["B08"], w["B04"]) < 0          # water is negative
    assert nbr(f["B08"], f["B12"]) > nbr(p["B08"], p["B12"])
    assert ndmi(f["B08"], f["B11"]) > ndmi(p["B08"], p["B11"])


def test_zero_denominator_gives_nan():
    out = ndvi(np.array([[0.0, 0.5]]), np.array([[0.0, np.nan]]))
    assert np.isnan(out[0, 0]) and np.isnan(out[0, 1])


def test_compute_all_and_false_color():
    rng = np.random.default_rng(1)
    stack = rng.uniform(0.01, 0.5, (6, 30, 30)).astype(np.float32)
    idx = compute_all(stack)
    assert set(idx) == {"ndvi", "nbr", "ndmi"}
    rgb = false_color_composite(stack)
    assert rgb.shape == (30, 30, 3) and rgb.dtype == np.uint8
    assert rgb.min() == 0 and rgb.max() == 255   # 2-98 percentile stretch reaches both ends
